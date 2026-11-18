// SPDX-License-Identifier: GPL-3.0-only
// IoT Current Scope. Created by Wenderson Oliveira and project contributors.
// ESP32-WROOM-32, ESP-IDF 5.4.x. See LICENSE and THIRD_PARTY.md at repository root.

#include <inttypes.h>
#include <math.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"
#include "driver/uart.h"
#include "esp_err.h"
#include "esp_random.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "scope_core.h"

#define FIRMWARE_VERSION "1.0.0"
#define UART_PORT UART_NUM_0
#define STOPPED BIT0
#define WIRE_SIZE 1400
#define I2C_TIMEOUT_MS 3
#define I2C_CLOCK_HZ 400000
#define CALIBRATION_READINGS 16
#define CALIBRATION_MAGIC 0x53435031

enum {
    INA219_CONFIG_REGISTER = 0,
    INA219_SHUNT_REGISTER = 1,
    INA219_BUS_REGISTER = 2,
    INA219_CALIBRATION_REGISTER = 5,
};

enum {
    SAMPLE_NEAR_LIMIT = 1u,
    SAMPLE_LATE = 2u,
    SAMPLE_ZERO_NOT_CALIBRATED = 4u,
};

typedef struct {
    char text[WIRE_SIZE];
} wire_t;

// This layout is persisted as cal_v1. Keep it stable for existing boards.
typedef struct {
    uint32_t magic;
    float zero[4];
    float gain[4];
    uint32_t valid;
} calibration_t;

static i2c_master_bus_handle_t bus;
static i2c_master_dev_handle_t sensor;
static QueueHandle_t tx_queue;
static EventGroupHandle_t events;
static SemaphoreHandle_t acquisition_mutex;

// Only the acquisition task reads the INA219 while running. The command task
// waits for acquisition_mutex on STOP before changing configuration/calibration.
static atomic_bool run_requested = false;
static atomic_uint errors = 0;
static atomic_uint skipped = 0;
static atomic_uint queue_drops = 0;
static atomic_uint late = 0;
static atomic_uint max_late_us = 0;

static scope_plan_t plan;
static uint16_t requested_average = 0;  // Zero means automatic averaging.
static uint8_t pga = 3;                // +/-320 mV at startup.
static int address = -1;
static uint8_t ack[112];
static uint8_t candidates[16];
static unsigned ack_count = 0;
static unsigned candidate_count = 0;
static calibration_t cal;
static uint32_t session = 0;
static int64_t epoch_us = 0;

/* Protocol output is serialized by one task. A sample never blocks waiting for
 * a full queue; its missing sequence number tells the PC that data was lost.
 * Command replies may wait up to one second for queue space.
 */
static bool wire_payload(const char *payload, TickType_t wait) {
    wire_t message;
    size_t length = strlen(payload);
    if (length + 7 > sizeof(message.text)) {
        return false;
    }

    uint16_t crc = scope_crc((const uint8_t *)payload, length);
    snprintf(message.text, sizeof(message.text), "%s*%04X\n", payload, crc);
    return xQueueSend(tx_queue, &message, wait) == pdTRUE;
}

static void reply(const char *format, ...) {
    char payload[WIRE_SIZE - 8];
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(payload, sizeof(payload), format, arguments);
    va_end(arguments);

    wire_payload(payload, pdMS_TO_TICKS(1000));
}

static void error_reply(const char *message) {
    reply("@{\"type\":\"error\",\"message\":\"%s\"}", message);
}

static esp_err_t read_reg(uint8_t reg, uint16_t *value) {
    if (sensor == NULL) {
        return ESP_ERR_NOT_FOUND;
    }

    // INA219 registers are 16-bit words, transferred most significant byte first.
    uint8_t bytes[2];
    esp_err_t result = i2c_master_transmit_receive(
        sensor, &reg, 1, bytes, sizeof(bytes), I2C_TIMEOUT_MS);
    if (result == ESP_OK) {
        *value = ((uint16_t)bytes[0] << 8) | bytes[1];
    }
    return result;
}

static esp_err_t write_reg(uint8_t reg, uint16_t value) {
    if (sensor == NULL) {
        return ESP_ERR_NOT_FOUND;
    }

    uint8_t bytes[] = {reg, (uint8_t)(value >> 8), (uint8_t)value};
    return i2c_master_transmit(sensor, bytes, sizeof(bytes), I2C_TIMEOUT_MS);
}

static void detach_sensor(void) {
    if (sensor != NULL) {
        i2c_master_bus_rm_device(sensor);
        sensor = NULL;
    }
    address = -1;
}

static bool attach(int new_address) {
    detach_sensor();
    i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = new_address,
        .scl_speed_hz = I2C_CLOCK_HZ,
    };
    if (i2c_master_bus_add_device(bus, &config, &sensor) != ESP_OK) {
        return false;
    }

    uint16_t config_register;
    uint16_t calibration_register;
    bool readable = read_reg(INA219_CONFIG_REGISTER, &config_register) == ESP_OK
        && read_reg(INA219_CALIBRATION_REGISTER, &calibration_register) == ESP_OK;
    if (!readable || (config_register & 0x4000u) != 0) {
        detach_sensor();
        return false;
    }

    // INA219 has no chip-ID register. Readability and reserved bit 14 are only
    // plausibility checks: another device at this address may still pass.
    address = new_address;
    return true;
}

static void scan(void) {
    detach_sensor();
    ack_count = 0;
    candidate_count = 0;

    for (int probe_address = 8; probe_address < 0x78; ++probe_address) {
        if (i2c_master_probe(bus, probe_address, I2C_TIMEOUT_MS) != ESP_OK) {
            continue;
        }

        ack[ack_count++] = (uint8_t)probe_address;
        bool ina219_address = probe_address >= 0x40 && probe_address <= 0x4f;
        if (ina219_address && attach(probe_address)) {
            candidates[candidate_count++] = (uint8_t)probe_address;
        }
    }

    if (candidate_count > 0) {
        attach(candidates[0]);
    } else {
        detach_sensor();
    }
}

static void persist_cal(void) {
    nvs_handle_t handle;
    if (nvs_open("scope", NVS_READWRITE, &handle) != ESP_OK) {
        error_reply("NVS_OPEN_FAILED");
        return;
    }

    esp_err_t result = nvs_set_blob(handle, "cal_v1", &cal, sizeof(cal));
    if (result == ESP_OK) {
        result = nvs_commit(handle);
    }
    nvs_close(handle);
    if (result != ESP_OK) {
        error_reply("NVS_SAVE_FAILED");
    }
}

static void metadata(const char *type) {
    char ack_list[480] = "";
    char candidate_list[80] = "";
    size_t used = 0;
    for (unsigned index = 0; index < ack_count; ++index) {
        used += (size_t)snprintf(ack_list + used, sizeof(ack_list) - used,
            "%s%u", index == 0 ? "" : ",", ack[index]);
    }
    used = 0;
    for (unsigned index = 0; index < candidate_count; ++index) {
        used += (size_t)snprintf(candidate_list + used, sizeof(candidate_list) - used,
            "%s%u", index == 0 ? "" : ",", candidates[index]);
    }

    // START metadata enters the output queue before the first sample.
    // The acquisition task is enabled immediately after this call returns.
    bool running = atomic_load(&run_requested) || strcmp(type, "started") == 0;
    reply("@{\"type\":\"%s\",\"protocol\":1,\"firmware\":\"" FIRMWARE_VERSION "\",\"state\":\"%s\","
          "\"baud\":%d,\"address\":%d,\"ack\":[%s],\"candidates\":[%s],\"pga\":%u,"
          "\"rate_hz\":%u,\"period_us\":%u,\"avg_requested\":%u,\"averages\":%u,"
          "\"window_us\":%u,\"zero_raw\":%.6f,\"gain\":%.8f,\"calibrated\":%s,"
          "\"session\":%" PRIu32 ",\"epoch_us\":%" PRId64 "}",
          type, running ? "RUNNING" : "STOPPED", SCOPE_BAUD, address,
          ack_list, candidate_list, pga, plan.rate_hz, plan.period_us,
          requested_average, plan.averages, plan.conversion_typ_us,
          (double)cal.zero[pga], (double)cal.gain[pga],
          (cal.valid & (1u << pga)) != 0 ? "true" : "false", session, epoch_us);
}

/* Trigger exactly one shunt conversion window. Register 2 is read only to
 * check CNVR; bus voltage itself is unused. The signed shunt register has
 * a 10 uV/count scale regardless of the PGA selected by the user.
 */
static bool read_conversion(scope_plan_t conversion_plan, int16_t *raw,
                            int64_t *timestamp, bool cancellable) {
    uint16_t config = scope_config(pga, conversion_plan.adc_bits);
    if (write_reg(INA219_CONFIG_REGISTER, config) != ESP_OK) {
        return false;
    }

    int64_t started = esp_timer_get_time();
    int64_t first_check = started + conversion_plan.conversion_typ_us;
    while (esp_timer_get_time() < first_check) {
        if (cancellable && !atomic_load(&run_requested)) {
            return false;
        }
        int64_t remaining = first_check - esp_timer_get_time();
        if (remaining > 2000) {
            vTaskDelay(pdMS_TO_TICKS(1));
        } else {
            esp_rom_delay_us(30);
        }
    }

    // Poll ready instead of reporting an old register value as a new sample.
    int64_t deadline = started + conversion_plan.conversion_max_us + 300;
    do {
        uint16_t bus_value;
        if (read_reg(INA219_BUS_REGISTER, &bus_value) != ESP_OK) {
            return false;
        }
        if ((bus_value & 2u) != 0) {
            uint16_t value;
            if (read_reg(INA219_SHUNT_REGISTER, &value) != ESP_OK) {
                return false;
            }
            // End of the I2C read, not the center of the ADC integration window.
            *timestamp = esp_timer_get_time();
            *raw = (int16_t)value;
            return true;
        }
        esp_rom_delay_us(20);
    } while (esp_timer_get_time() < deadline);

    return false;
}

static void tx_task(void *argument) {
    (void)argument;
    wire_t message;
    while (true) {
        if (xQueueReceive(tx_queue, &message, portMAX_DELAY) == pdTRUE) {
            uart_write_bytes(UART_PORT, message.text, strlen(message.text));
        }
    }
}

static void send_sync(uint32_t sequence, int64_t timestamp) {
    char payload[320];
    snprintf(payload, sizeof(payload),
        "@{\"type\":\"sync\",\"session\":%" PRIu32 ",\"seq\":%" PRIu32
        ",\"t_us\":%" PRId64 ",\"i2c_errors\":%u,\"skipped\":%u,"
        "\"tx_drops\":%u,\"late\":%u,\"max_late_us\":%u}",
        session, sequence, timestamp, atomic_load(&errors), atomic_load(&skipped),
        atomic_load(&queue_drops), atomic_load(&late), atomic_load(&max_late_us));
    wire_payload(payload, 0);
}

static void send_sample(uint32_t sequence, int64_t timestamp, int16_t raw,
                        uint32_t lateness_us) {
    unsigned flags = 0;
    int full_scale_counts = 4000 * (1 << pga);
    if (abs((int)raw) >= full_scale_counts - 1) {
        flags |= SAMPLE_NEAR_LIMIT;
    }
    if (lateness_us > 50) {
        flags |= SAMPLE_LATE;
    }
    if ((cal.valid & (1u << pga)) == 0) {
        flags |= SAMPLE_ZERO_NOT_CALIBRATED;
    }

    char payload[64];
    snprintf(payload, sizeof(payload), "D,%" PRIu32 ",%" PRIu32 ",%d,%02X",
        sequence, (uint32_t)timestamp, (int)raw, flags);
    if (!wire_payload(payload, 0)) {
        atomic_fetch_add(&queue_drops, 1);
    }
}

static void acquisition_task(void *argument) {
    (void)argument;
    while (true) {
        if (!atomic_load(&run_requested)) {
            xEventGroupSetBits(events, STOPPED);
            vTaskDelay(pdMS_TO_TICKS(1));
            continue;
        }

        xSemaphoreTake(acquisition_mutex, portMAX_DELAY);
        if (!atomic_load(&run_requested)) {
            xSemaphoreGive(acquisition_mutex);
            continue;
        }
        xEventGroupClearBits(events, STOPPED);

        uint32_t sequence = 0;
        int64_t due = epoch_us;
        int64_t next_sync = epoch_us + 1000000;
        while (atomic_load(&run_requested)) {
            int64_t now = esp_timer_get_time();
            if (now < due) {
                int64_t remaining = due - now;
                if (remaining > 2000) {
                    vTaskDelay(pdMS_TO_TICKS(1));
                } else {
                    esp_rom_delay_us(20);
                }
                continue;
            }

            // Preserve the original time grid. Skip expired slots instead of
            // firing conversions back-to-back to catch up.
            uint64_t missed_periods = (uint64_t)(now - due) / plan.period_us;
            if (missed_periods > 0) {
                sequence += (uint32_t)missed_periods;
                due += (int64_t)missed_periods * plan.period_us;
                atomic_fetch_add(&skipped, (unsigned)missed_periods);
            }

            uint32_t lateness_us = (uint32_t)(esp_timer_get_time() - due);
            if (lateness_us > 50) {
                atomic_fetch_add(&late, 1);
            }
            if (lateness_us > atomic_load(&max_late_us)) {
                atomic_store(&max_late_us, lateness_us);
            }

            int16_t raw;
            int64_t timestamp;
            if (read_conversion(plan, &raw, &timestamp, true)) {
                send_sample(sequence, timestamp, raw, lateness_us);
                if (timestamp >= next_sync) {
                    send_sync(sequence, timestamp);
                    next_sync = timestamp + 1000000;
                }
            } else if (atomic_load(&run_requested)) {
                atomic_fetch_add(&errors, 1);
            }

            // Every scheduled slot consumes a sequence number, including errors.
            ++sequence;
            due += plan.period_us;
        }

        uint16_t power_down_config = scope_config(pga, plan.adc_bits) & ~7u;
        write_reg(INA219_CONFIG_REGISTER, power_down_config);
        xEventGroupSetBits(events, STOPPED);
        xSemaphoreGive(acquisition_mutex);
    }
}

static void calibrate(bool gain_calibration, double expected_uv) {
    if (sensor == NULL) {
        error_reply("NO_SENSOR");
        return;
    }

    // Calibration uses 16 independent, internally averaged readings to obtain
    // the mean and observed spread for the current PGA range.
    scope_plan_t calibration_plan;
    scope_plan(1, 128, &calibration_plan);
    double sum = 0;
    double sum_of_squares = 0;
    for (int reading = 0; reading < CALIBRATION_READINGS; ++reading) {
        int16_t raw;
        int64_t timestamp;
        if (!read_conversion(calibration_plan, &raw, &timestamp, false)) {
            error_reply("CAL_I2C_FAILED");
            return;
        }
        sum += raw;
        sum_of_squares += (double)raw * raw;
    }
    double mean = sum / CALIBRATION_READINGS;

    if (gain_calibration) {
        double full_scale_uv = 40000.0 * (1 << pga);
        bool reference_near_limit = fabs(expected_uv) >= full_scale_uv * 0.9;
        bool reading_near_limit = fabs(mean) * 10 >= full_scale_uv * 0.95;
        if (reference_near_limit || reading_near_limit) {
            error_reply("CAL_REFERENCE_NEAR_FULL_SCALE");
            return;
        }

        double measured_uv = (mean - cal.zero[pga]) * 10.0;
        double factor = expected_uv / measured_uv;
        if (fabs(measured_uv) < 200 || !isfinite(factor) || factor < 0.5 || factor > 1.5) {
            error_reply("CAL_GAIN_INVALID_USE_LARGER_REFERENCE");
            return;
        }
        cal.gain[pga] = (float)factor;
    } else {
        if (fabs(mean) > 100) {
            error_reply("CAL_ZERO_TOO_LARGE_REMOVE_LOAD");
            return;
        }
        cal.zero[pga] = (float)mean;
        cal.valid |= 1u << pga;
    }

    persist_cal();
    double variance = sum_of_squares / CALIBRATION_READINGS - mean * mean;
    double standard_deviation = sqrt(fmax(0, variance));
    reply("@{\"type\":\"calibration\",\"kind\":\"%s\",\"mean_raw\":%.6f,\"std_raw\":%.6f}",
        gain_calibration ? "gain" : "zero", mean, standard_deviation);
    metadata("config");
}

static void start_acquisition(void) {
    if (atomic_load(&run_requested)) {
        error_reply("ALREADY_RUNNING");
        return;
    }
    if (sensor == NULL) {
        error_reply("NO_SENSOR");
        return;
    }

    session = esp_random();
    epoch_us = esp_timer_get_time() + 10000;
    atomic_store(&errors, 0);
    atomic_store(&skipped, 0);
    atomic_store(&queue_drops, 0);
    atomic_store(&late, 0);
    atomic_store(&max_late_us, 0);
    xEventGroupClearBits(events, STOPPED);
    metadata("started");
    atomic_store(&run_requested, true);
}

/* Commands run in wire order. sscanf's trailing %c detects an extra argument
 * rather than silently accepting it. Configuration/calibration requires STOP.
 */
static void command(char *line) {
    unsigned value;
    char extra;

    if (strcmp(line, "HELLO") == 0 || strcmp(line, "STATUS") == 0) {
        metadata("status");
        return;
    }
    if (strcmp(line, "STOP") == 0) {
        atomic_store(&run_requested, false);
        // The mutex is the STOP acknowledgement: configuration cannot race
        // an in-flight I2C conversion/read.
        xSemaphoreTake(acquisition_mutex, portMAX_DELAY);
        xSemaphoreGive(acquisition_mutex);
        metadata("stopped");
        return;
    }
    if (strcmp(line, "START") == 0) {
        start_acquisition();
        return;
    }
    if (atomic_load(&run_requested)) {
        error_reply("STOP_REQUIRED");
        return;
    }
    if (strcmp(line, "SCAN") == 0) {
        scan();
        metadata("config");
        return;
    }
    if (sscanf(line, "SET PGA %u %c", &value, &extra) == 1) {
        if (value > 3) {
            error_reply("PGA_RANGE_0_TO_3");
            return;
        }
        pga = (uint8_t)value;
        metadata("config");
        return;
    }
    if (sscanf(line, "SET RATE %u %c", &value, &extra) == 1) {
        scope_plan_t new_plan;
        if (!scope_plan(value, requested_average, &new_plan)) {
            error_reply("RATE_OR_AVERAGE_INVALID");
            return;
        }
        plan = new_plan;
        metadata("config");
        return;
    }
    if (strcmp(line, "SET AVG AUTO") == 0) {
        requested_average = 0;
        scope_plan(plan.rate_hz, 0, &plan);
        metadata("config");
        return;
    }
    if (sscanf(line, "SET AVG %u %c", &value, &extra) == 1) {
        scope_plan_t new_plan;
        if (value == 0 || value > 128 || !scope_plan(plan.rate_hz, value, &new_plan)) {
            error_reply("AVERAGE_DOES_NOT_FIT_PERIOD");
            return;
        }
        requested_average = (uint16_t)value;
        plan = new_plan;
        metadata("config");
        return;
    }
    if (sscanf(line, "SET ADDR %x %c", &value, &extra) == 1) {
        if (value < 0x40 || value > 0x4f) {
            error_reply("ADDRESS_RANGE_40_TO_4F");
            return;
        }
        if (!attach(value)) {
            error_reply("SENSOR_NOT_FOUND");
            return;
        }
        metadata("config");
        return;
    }
    if (strcmp(line, "CAL ZERO") == 0) {
        calibrate(false, 0);
        return;
    }

    double expected_uv;
    if (sscanf(line, "CAL GAIN %lf %c", &expected_uv, &extra) == 1 && isfinite(expected_uv)) {
        if ((cal.valid & (1u << pga)) == 0) {
            error_reply("CAL_ZERO_FIRST");
            return;
        }
        calibrate(true, expected_uv);
        return;
    }
    if (strcmp(line, "CAL RESET") == 0) {
        cal.zero[pga] = 0;
        cal.gain[pga] = 1;
        cal.valid &= ~(1u << pga);
        persist_cal();
        metadata("config");
        return;
    }
    error_reply("UNKNOWN_COMMAND");
}

static void load_calibration(void) {
    cal.magic = CALIBRATION_MAGIC;
    for (int range = 0; range < 4; ++range) {
        cal.gain[range] = 1;
    }

    nvs_handle_t handle;
    if (nvs_open("scope", NVS_READONLY, &handle) != ESP_OK) {
        return;  // A new board has no saved calibration yet.
    }

    calibration_t saved;
    size_t saved_size = sizeof(saved);
    esp_err_t result = nvs_get_blob(handle, "cal_v1", &saved, &saved_size);
    bool valid = result == ESP_OK && saved_size == sizeof(saved)
        && saved.magic == cal.magic;
    if (valid) {
        for (int range = 0; range < 4; ++range) {
            if (!isfinite(saved.zero[range]) || !isfinite(saved.gain[range])
                    || saved.gain[range] < 0.5 || saved.gain[range] > 1.5) {
                valid = false;
            }
        }
        if (valid) {
            cal = saved;
        }
    }
    nvs_close(handle);
}

static void initialize_uart(void) {
    uart_config_t config = {
        .baud_rate = SCOPE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &config));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT, 1, 3, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT, 2048, 4096, 0, NULL, 0));
}

static void initialize_i2c(void) {
    i2c_master_bus_config_t config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = CONFIG_SCOPE_SDA_GPIO,
        .scl_io_num = CONFIG_SCOPE_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&config, &bus));
    scan();
}

static void read_commands(void) {
    char line[128];
    size_t used = 0;
    bool overflow = false;

    while (true) {
        uint8_t character;
        if (uart_read_bytes(UART_PORT, &character, 1, pdMS_TO_TICKS(100)) != 1) {
            continue;
        }
        if (character == '\r') {
            continue;
        }
        if (character == '\n') {
            if (overflow) {
                error_reply("COMMAND_TOO_LONG");
            } else if (used > 0) {
                line[used] = '\0';
                command(line);
            }
            used = 0;
            overflow = false;
        } else if (character >= 32 && character < 127) {
            if (used < sizeof(line) - 1) {
                line[used++] = (char)character;
            } else {
                overflow = true;
            }
        }
    }
}

void app_main(void) {
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(result);

    load_calibration();
    scope_plan(1000, 0, &plan);
    initialize_uart();

    tx_queue = xQueueCreate(32, sizeof(wire_t));
    events = xEventGroupCreate();
    acquisition_mutex = xSemaphoreCreateMutex();
    if (tx_queue == NULL || events == NULL || acquisition_mutex == NULL) {
        abort();
    }
    xEventGroupSetBits(events, STOPPED);

    // Core 0 drains serial output. Core 1 schedules and reads the sensor.
    // This command loop remains in the ESP-IDF main task.
    if (xTaskCreatePinnedToCore(tx_task, "scope_tx", 4096, NULL, 10, NULL, 0) != pdPASS) {
        abort();
    }
    initialize_i2c();
    if (xTaskCreatePinnedToCore(acquisition_task, "scope_acq", 6144, NULL, 20, NULL, 1) != pdPASS) {
        abort();
    }

    metadata("boot");
    read_commands();
}

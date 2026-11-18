// SPDX-License-Identifier: GPL-3.0-only
#include "scope_core.h"

bool scope_plan(uint32_t hz, uint16_t requested_average, scope_plan_t *out) {
    static const uint16_t average_counts[] = {1, 2, 4, 8, 16, 32, 64, 128};
    static const uint32_t typical_times_us[] = {
        532, 1060, 2130, 4260, 8510, 17020, 34050, 68100
    };
    const size_t mode_count = sizeof(average_counts) / sizeof(average_counts[0]);

    if (out == NULL || hz < 1 || hz > SCOPE_MAX_HZ) {
        return false;
    }

    // Round to the nearest whole microsecond; the accepted period is reported to the PC.
    uint32_t period_us = (1000000u + hz / 2u) / hz;
    int selected_mode = -1;

    for (size_t mode = 0; mode < mode_count; ++mode) {
        // 586 us is the specified maximum for one 12-bit conversion.
        // Multiplication is a conservative planning rule, not an additional TI guarantee.
        uint32_t conversion_budget_us = 586u * average_counts[mode];
        bool fits_period = conversion_budget_us + SCOPE_GUARD_US <= period_us;
        bool matches_request = requested_average == 0
            || requested_average == average_counts[mode];

        if (fits_period && matches_request) {
            // Counts are ascending, so the last accepted mode gives the largest average.
            selected_mode = (int)mode;
        }
    }

    if (selected_mode < 0) {
        return false;
    }

    // SADC=3 means one 12-bit reading. SADC=9..15 means 2..128 readings.
    uint16_t adc_field = selected_mode == 0 ? 3 : (uint16_t)(8 + selected_mode);
    *out = (scope_plan_t){
        .rate_hz = hz,
        .period_us = period_us,
        .averages = average_counts[selected_mode],
        .adc_bits = adc_field,
        .conversion_typ_us = typical_times_us[selected_mode],
        .conversion_max_us = 586u * average_counts[selected_mode],
    };
    return true;
}

uint16_t scope_config(uint8_t pga, uint16_t adc_bits) {
    // Bus-voltage conversion is disabled. Its range/resolution fields stay at zero.
    uint16_t pga_field = (uint16_t)((pga & 3u) << 11);
    uint16_t shunt_adc_field = (uint16_t)((adc_bits & 15u) << 3);
    uint16_t shunt_triggered_mode = 1u;
    return (uint16_t)(pga_field | shunt_adc_field | shunt_triggered_mode);
}

uint16_t scope_crc(const uint8_t *data, size_t length) {
    uint16_t crc = 0xffff;

    for (size_t byte = 0; byte < length; ++byte) {
        crc ^= (uint16_t)data[byte] << 8;

        for (int bit = 0; bit < 8; ++bit) {
            bool high_bit_set = (crc & 0x8000u) != 0;
            crc = (uint16_t)(crc << 1);
            if (high_bit_set) {
                crc ^= 0x1021u;
            }
        }
    }

    return crc;
}

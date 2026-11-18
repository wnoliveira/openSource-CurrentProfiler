// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SCOPE_BAUD 460800
#define SCOPE_MAX_HZ 1000
#define SCOPE_GUARD_US 350

/* A complete timing decision, shared by configuration and acquisition.
 * adc_bits is the INA219 SADC register field, not the ADC resolution.
 * Every supported mode uses 12-bit conversions; larger fields select averaging.
 */
typedef struct {
    uint32_t rate_hz;
    uint32_t period_us;
    uint16_t averages;
    uint16_t adc_bits;
    uint32_t conversion_typ_us;
    uint32_t conversion_max_us;
} scope_plan_t;

/* requested_average == 0 selects the largest average that fits the period.
 * A nonzero value requests exactly that many internal conversions.
 */
bool scope_plan(uint32_t hz, uint16_t requested_average, scope_plan_t *out);

/* Build a shunt-only, single-shot INA219 configuration register. */
uint16_t scope_config(uint8_t pga, uint16_t adc_bits);

/* CRC-16/CCITT-FALSE: polynomial 0x1021, initial value 0xffff, no reflection. */
uint16_t scope_crc(const uint8_t *data, size_t length);

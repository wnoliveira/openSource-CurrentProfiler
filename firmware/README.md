# IoT Current Scope firmware

**Status: In development · Version: 1.0.0 · Protocol: 1**

Created by Wenderson Oliveira. Source and issue tracker:
[wnoliveira/openSource-CurrentProfiler](https://github.com/wnoliveira/openSource-CurrentProfiler).

This is the ESP-IDF firmware for an ESP32 DevKit with an ESP-WROOM-32 module
and an INA219 current sensor. The ESP32 schedules shunt-voltage measurements;
the desktop application converts them to current, draws the trace and records
CSV files. Bus voltage, power and accumulated energy are not measured here.

The reference build uses **ESP-IDF 5.4.2**, target `esp32`, 4 MB flash and a
240 MHz CPU. The supplied prebuilt images are historical build artifacts; rebuild
the current source before testing changes. No physical-board test is claimed
for this revision.

## Wiring and first build

| ESP32 DevKit | INA219 |
|---|---|
| 3V3 | VCC / VS |
| GND | GND |
| GPIO21 | SDA |
| GPIO22 | SCL |

Power the INA219 module at 3.3 V so its I²C pull-ups do not drive the ESP32 pins
at 5 V. Use suitable external pull-ups; account for resistors already fitted on
the module. Keep wiring short. The load current passes through IN+ to IN−;
the logger's own power supply should be outside that measured current path.
The [project README](../README.md) explains shunt replacement, wiring and
measurement limits in more detail.

Open this directory in an ESP-IDF terminal, then run:

```powershell
idf.py set-target esp32
idf.py build
idf.py -p COM5 flash
```

Replace `COM5` with the board's port. The USB connection uses the board's
CP2102 USB-to-UART bridge, not native USB. GPIO1/TX and GPIO3/RX are reserved
for UART0. Close serial monitors before opening the desktop application.
To change SDA/SCL, use `idf.py menuconfig` → **IoT Current Scope** and rebuild.

At startup the device scans the bus and remains stopped. The initial settings
are PGA ±320 mV, 1,000 Hz and automatic averaging. Only calibration survives
a restart; the selected address, rate and PGA return to their startup defaults.

## How a measurement is made

The I²C bus runs at **400 kHz**, with a 3 ms timeout for each driver operation.
The scan probes non-reserved addresses from `0x08` through `0x77`. A device
between `0x40` and `0x4F` becomes a candidate if its configuration and calibration
registers can be read and the configuration's reserved bit is clear. The first
candidate is selected. The INA219 has no chip identification register, so this
is a plausibility check; it does not prove that the responding device is an INA219.

Each scheduled sample follows the same steps:

1. Write the INA219 configuration register to trigger a **shunt-only** conversion.
2. Wait until the typical conversion time has elapsed. Longer waits yield to
   FreeRTOS; the final short waits use microsecond delays.
3. Read the conversion-ready bit, CNVR, in the bus-voltage register. The bus
   voltage value is unused. Continue polling until ready or until the timing
   budget plus 300 µs has elapsed. An I²C operation can itself extend that time.
4. Read the signed shunt-voltage register and timestamp the end of that I²C read.
5. Queue the raw reading, timestamp, sequence number and flags for UART output.

An unsuccessful conversion consumes a sequence number and increments the I²C/
conversion error counter; the firmware does not resend an old reading as a new
sample. If scheduling falls behind, expired periods are skipped. It does not
perform a burst of conversions to catch up. A delay above 50 µs sets the sample's
late flag. A raw value within one register count of nominal full scale sets the
near-limit flag. These indicators describe the acquisition; they do not replace
checking the circuit against a reference instrument.

## Rate, averaging and timing

Rates from 1 to 1,000 whole Hz are accepted. The period is rounded to the nearest
whole microsecond using `(1000000 + rate / 2) / rate` with integer arithmetic.
The accepted period is included in device metadata. For example, 333 Hz gives
3,003 µs rather than an exact fractional-microsecond period.

All supported modes use 12-bit shunt conversions. Averaging combines 1, 2, 4,
8, 16, 32, 64 or 128 conversions inside the INA219. Automatic mode picks the
largest count that fits `586 µs × count + 350 µs <= period`. The 350 µs is a
scheduling/communication allowance. Multiplying the single-conversion maximum
by the count is a conservative planning rule, not an extra timing guarantee
from TI. Conversion-ready checking remains necessary.

| Requested rate | Rounded period | Automatic average | Typical ADC window |
|---:|---:|---:|---:|
| 1,000 Hz | 1,000 µs | 1 | 532 µs |
| 500 Hz | 2,000 µs | 2 | 1,060 µs |
| 250 Hz | 4,000 µs | 4 | 2,130 µs |
| 100 Hz | 10,000 µs | 16 | 8,510 µs |
| 50 Hz | 20,000 µs | 32 | 17,020 µs |
| 10 Hz | 100,000 µs | 128 | 68,100 µs |
| 1 Hz | 1,000,000 µs | 128 | 68,100 µs |

More averaging can reduce random noise but smooths short events. Conversion
windows are separated by unobserved time, especially at low rates. The resulting
samples do not guarantee an unbiased average of a pulsed IoT load. Reducing the
rate below the point that already permits 128 conversions cannot increase the
internal average further.

## Raw values, PGA and calibration

The transmitted quantity is the **raw shunt-voltage register**, before correction.
Its scale remains **10 µV per count** for every PGA setting. The desktop applies:

```text
current_A = (raw - zero_raw) × 10e-6 × gain / shunt_ohm
```

| PGA index | Nominal shunt range | Nominal current with a 1 Ω shunt |
|---:|---:|---:|
| 0 | ±40 mV | ±40 mA |
| 1 | ±80 mV | ±80 mA |
| 2 | ±160 mV | ±160 mA |
| 3 | ±320 mV | ±320 mA |

Do not multiply the raw voltage by an extra PGA gain. The PGA chooses the input
range, while the shunt resistance determines the current conversion. Register
scale is not a statement of effective resolution or measurement accuracy.

Calibration requires STOP and stores separate offset/gain values for each PGA
in NVS namespace `scope`, blob `cal_v1`. Both operations collect 16 readings,
each with 128-conversion internal averaging, taking roughly 1.1–1.2 seconds
before communication and scheduling overhead. The reply reports the mean and
population standard deviation of those raw readings.

- **Zero:** remove the load while keeping the INA219 powered and allow the
  circuit to settle. The mean becomes the offset. An offset above 100 counts
  in magnitude is rejected to avoid zeroing a substantial applied load.
- **Gain:** first calibrate zero, then apply a stable known current and enter
  the measured shunt resistance in the desktop application. The desktop sends
  the expected shunt voltage in µV. The firmware computes
  `gain = expected_uV / ((mean_raw - zero_raw) × 10)`.
- Gain calibration rejects measured signals below 200 µV in magnitude, factors
  outside 0.5–1.5, expected voltage at or above 90% of nominal full scale, and
  observed mean voltage at or above 95% of full scale.
- **Reset:** restores zero=0 and gain=1 for the selected PGA and clears its
  zero-calibrated flag. Recheck calibration after changing shunt, sensor,
  wiring or temperature. One gain point does not validate the full range.

## Serial protocol and task ownership

UART0 uses **460,800 baud, 8 data bits, no parity, one stop bit**, with no hardware
flow control. One 8N1 byte consumes ten serial bits, giving a nominal capacity
of 46,080 bytes/s. ASCII lines make sessions easy to inspect, and CRC-16/
CCITT-FALSE detects damaged payloads. A sample has the form
`D,sequence,timestamp_us,raw,flags*CRC` followed by a newline. JSON event lines
begin with `@`. See [PROTOCOL.md](../docs/PROTOCOL.md) for commands and framing.

There are three task roles. The main task receives commands; acquisition runs
on core 1; a task on core 0 drains a 32-message transmit queue. Samples do not
wait when that queue is full: a drop counter and sequence gaps expose the loss.
A synchronization event is queued about once per second with a full 64-bit
timestamp and diagnostic counters. Individual samples carry the low 32 bits;
the desktop handles rollover. The timestamp is a read-completion time, not the
center of the ADC window or a UTC timestamp.

STOP clears the run request and waits for the acquisition mutex before
acknowledging. This keeps configuration changes from racing sensor reads.
START creates a new session, resets counters and queues session metadata before
enabling sampling. `HELLO`, `STATUS` and `STOP` remain available while running;
sensor configuration and calibration require the stopped state.

## Reading and checking the source

| File | Responsibility |
|---|---|
| `main/main.c` | Hardware access, task scheduling, commands, calibration and NVS |
| `main/scope_core.c` | Timing plan, configuration register fields and CRC |
| `main/scope_core.h` | Shared plan structure and public helper declarations |
| `main/Kconfig.projbuild` | Configurable I²C pins |
| `sdkconfig.defaults` | Reference target, CPU, flash and FreeRTOS defaults |

The host tests compare the C planner with Python for all 1,000 rates when GCC
is available. A host check does not compile the ESP-IDF drivers or verify real
timing. The current source also completed a full build with the locally
installed **ESP-IDF 6.1.0 / Xtensa GCC 15.2.0** on November 18, 2026. Its output
is in `build/review-idf61`; the application image is 190,896 bytes. This was a
compatibility build, without flashing a board. The 5.4.2 reference was not
rebuilt in that environment.

Build with ESP-IDF and test on the board: scan/address selection,
START/STOP, each PGA, zero/gain persistence, sustained 1 kHz capture and deliberate
disconnects. Use a reference load/instrument to assess offset, noise, shunt
heating, burden voltage and short-pulse response. Record the flashed build and
all acquisition settings with the measurement.

Project source follows the repository's [GPL-3.0 license](../LICENSE).
ESP-IDF retains Apache-2.0 and its component licenses; see
[THIRD_PARTY.md](../THIRD_PARTY.md) before distributing firmware binaries.

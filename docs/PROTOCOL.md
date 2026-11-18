# Serial protocol 1

This is the protocol implemented by firmware 1.0.0 and the IoT Current Scope desktop application. It carries a single raw shunt-voltage channel. Display language does not change commands, packet fields, CSV column names or protocol error codes.

## Connection and framing

UART0 uses **460800 baud, 8N1, without RTS/CTS**. The ESP32 DevKit's USB-to-UART bridge exposes this link to the computer. Boot-ROM output can appear at another speed before the application starts; the desktop waits for a valid protocol-1 metadata packet.

PC-to-ESP32 commands are printable ASCII, terminated by LF (`\n`). CR is ignored. The command buffer accepts at most 127 printable characters before LF. Commands are not echoed and do not carry a CRC. An overlong command is discarded and produces `COMMAND_TOO_LONG`.

Every firmware response has this form:

```text
payload*CCCC\n
```

`CCCC` is four hexadecimal digits of CRC-16/CCITT-FALSE: polynomial 0x1021, initial value 0xFFFF, no reflection, final XOR 0. The checksum covers the ASCII payload bytes only, excluding `*`, checksum and LF. The test vector `123456789` gives `29B1`; Python can calculate it with `binascii.crc_hqx(payload, 0xffff)`.

The receiver assembles fragmented serial reads into complete lines, validates framing and CRC, and only then processes the payload. Boot noise and malformed messages are rejected. No sample acknowledgement or retransmission is implemented.

## Sample packets

```text
D,<seq>,<t_us32>,<raw>,<flags_hex>*<CRC>\n
```

| Field | Meaning |
|---|---|
| `seq` | Unsigned 32-bit decimal slot counter. Starts at zero for START and wraps at 2³². Advances across failed or skipped acquisition slots. |
| `t_us32` | Low 32 bits of `esp_timer_get_time()` in decimal microseconds, captured after the shunt-register I²C read. |
| `raw` | Signed 16-bit decimal value of INA219 register 0x01, before project calibration. |
| `flags_hex` | Two hexadecimal digits; flag meanings below. |
| `CRC` | Four hexadecimal checksum digits. |

| Flag | Meaning |
|---:|---|
| `0x01` | Raw value is at or near the nominal PGA limit. This is a range check, not an uncertainty estimate. |
| `0x02` | Acquisition started more than 50 µs after the scheduled deadline. |
| `0x04` | No measured zero offset is saved for the selected PGA. |

A maximum-width sample line has 39 bytes. With ten wire bits per byte in 8N1, it takes about 846 µs at 460800 baud. One thousand such samples per second consume 390 kbit/s, before periodic metadata. This is why the link is faster than 230400 baud and stays at one fixed speed for every sample rate. The CP2102 and its driver must support that rate.

## Metadata packets

A metadata payload begins with `@`, followed by compact JSON:

```text
@{"type":"config",...}*<CRC>\n
```

Event types are `boot`, `status`, `config`, `started`, `stopped`, `sync`, `calibration` and `error`.

The main configuration events contain:

| Field group | Contents |
|---|---|
| Identity | `type`, `protocol`, `firmware`, `state`, `baud`. |
| Sensor | `address`, responding-address list `ack`, plausible INA219 `candidates`, `pga`. |
| Timing | `rate_hz`, rounded `period_us`, requested `avg_requested`, accepted `averages`, typical conversion `window_us`. |
| Calibration | `zero_raw`, `gain`, `calibrated` for the active PGA. |
| Session | Random `session` identifier and 64-bit ESP32 `epoch_us`. |

`avg_requested` is zero for automatic averaging. `address` is −1 when no sensor is selected. `calibrated` records a completed zero procedure; it does not claim a complete metrological calibration.

The firmware queues `started` before enabling sample acquisition, so it defines the session for the packets that follow. STOP waits for acquisition to leave its I²C section, and `stopped` is queued after the data already waiting for transmission.

A `sync` packet is attempted about once per second of successful acquisition. It contains the full timestamp `t_us`, session, sequence and the device counters:

| Counter | Meaning |
|---|---|
| `i2c_errors` | Failed conversion/read slots. |
| `skipped` | Entire scheduled periods skipped after execution fell behind. |
| `tx_drops` | Samples that did not fit in the transmit queue. |
| `late` | Slots whose start was over 50 µs late. |
| `max_late_us` | Largest observed start delay in the session. |

These counters help explain missing data. They must not be added to the PC's missing-sequence total, because the same failure can appear in both. Sync packets themselves can be lost; there is no acknowledgement.

## Commands

| Command | Allowed state | Effect |
|---|---|---|
| `HELLO` or `STATUS` | Either | Return `status` metadata. |
| `START` | Stopped | Open a new session and begin periodic conversions. |
| `STOP` | Either | Stop acquisition and return `stopped` metadata after queued samples. |
| `SCAN` | Stopped | Probe 0x08–0x77, test candidates at 0x40–0x4F and select the first plausible one. |
| `SET ADDR 40` | Stopped | Select a hexadecimal sensor address; the `0x` prefix is optional. |
| `SET PGA 0` | Stopped | Select range: 0 = ±40 mV, 1 = ±80 mV, 2 = ±160 mV, 3 = ±320 mV. |
| `SET RATE 1000` | Stopped | Request an integer 1–1000 Hz; return the accepted rounded period. |
| `SET AVG AUTO` | Stopped | Choose the largest averaging count that fits the period. |
| `SET AVG 16` | Stopped | Use 1, 2, 4, 8, 16, 32, 64 or 128 if it fits. |
| `CAL ZERO` | Stopped | Measure and persist the current range's zero offset; roughly 1.2 s. |
| `CAL GAIN 10000` | Stopped | Calibrate using a known 10000 µV drop across the shunt. Requires zero first. |
| `CAL RESET` | Stopped | Set zero to 0, gain to 1 and clear the current range's zero-calibrated mark. |

To change rate from an incompatible manual average, send `SET AVG AUTO`, then `SET RATE ...`, then the desired `SET AVG ...`. Wait for the `config` responses. The desktop follows this order when applying a configuration. Sensor configuration during acquisition returns `STOP_REQUIRED`.

Errors use a JSON `error` event with a stable `message` code. Most rejected commands leave accepted settings unchanged. A failed attempt to attach another sensor removes the previous selection: choose a valid address or scan again. Only calibration commands write NVS.

The INA219 has no identity register. Address acknowledgement and plausible register values cannot establish which device is connected. Avoid unrelated devices at candidate addresses during first tests.

## Scheduling and time interpretation

Slots follow `epoch_us + slot × period_us`. The epoch is scheduled 10 ms ahead when START is accepted. A conversion is explicitly triggered once per slot in shunt-only mode. The firmware waits for its planned typical duration, checks CNVR in register 0x02 and reads register 0x01 only when ready. It does not convert bus voltage. A timeout or I²C error loses the slot without inventing a sample.

The planning condition is `586 × averages + 350 <= period_us`, in microseconds. Typical conversion windows, the planning reserve and their limitations are explained in the [main README](../README.md#rate-and-averaging).

The sample timestamp identifies the end of the read, after the integration window. It does not represent an instantaneous aperture or exact window center. The desktop unwraps 32-bit timestamps relative to the session epoch. Its modular comparison rejects duplicate or backward sequence numbers and ambiguous backward time jumps; less than 2³¹ µs, about 35.8 minutes, may elapse between accepted timestamps. A normal active connection times out much sooner.

Estimated UTC is assigned by the desktop using the computer clock when it receives START acknowledgement. Device intervals are preserved rather than replaced with USB arrival times. Characterize the conversion and read delay on the bench if phase alignment with another instrument is needed.

## Connection lifecycle

The receive worker tries HELLO every 0.5 s until valid metadata arrives and gives up after about 6 s. During an active session it closes a link with no received bytes for 4 s. Data is passed to the interface in batches around every 20 ms; diagnostics update around every 250 ms. These are host update intervals, not acquisition periods.

The ESP32 uses separate acquisition and transmission tasks with a 32-message queue. Without CTS, transmission cannot determine whether a downstream USB connection was unplugged. The application attempts STOP on normal closure, but a physical disconnect does not guarantee the firmware stops. Reconnect, check its state, stop it if needed, and start a new session before continuing the recording.

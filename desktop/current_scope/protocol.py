"""Encode serial frames and interpret measurements without a Qt dependency.

The ESP32 sends the signed INA219 shunt register rather than a calculated
current. Keeping framing, timestamp tracking and conversion here lets the GUI,
CSV recorder and tests share the same measurement rules.
"""

import binascii
from dataclasses import dataclass
import json
import math


BAUD = 460800
MASK32 = (1 << 32) - 1
HALF_COUNTER_RANGE = 1 << 31
SHUNT_VOLTS_PER_COUNT = 10e-6
AVERAGE_OPTIONS = (1, 2, 4, 8, 16, 32, 64, 128)
CONVERSION_BUDGET_US = 586
COMMUNICATION_MARGIN_US = 350


@dataclass(frozen=True)
class Data:
    """A validated packet, with the original wrapping device counters."""

    seq: int
    us32: int
    raw: int
    flags: int


@dataclass(frozen=True)
class Sample:
    """An accepted measurement with a timestamp extended beyond 32 bits."""

    sequence: int
    device_us: int
    raw: int
    flags: int


def encode(payload: str) -> bytes:
    """Append CRC-16/CCITT-FALSE and a newline to an ASCII payload."""
    data = payload.encode("ascii")
    checksum = binascii.crc_hqx(data, 0xFFFF)
    trailer = f"*{checksum:04X}\n".encode("ascii")
    return data + trailer


def decode(line: bytes) -> Data | dict:
    """Validate a complete line before exposing its data or JSON event.

    Invalid or incomplete frames raise ValueError (or a decoding subclass).
    The caller counts these errors and waits for the next newline.
    """
    data, checksum = line.rstrip(b"\r\n").rsplit(b"*", 1)
    expected_checksum = binascii.crc_hqx(data, 0xFFFF)
    if len(checksum) != 4 or int(checksum, 16) != expected_checksum:
        raise ValueError("Incorrect CRC")

    payload = data.decode("ascii")
    if payload.startswith("@"):
        event = json.loads(payload[1:])
        if not isinstance(event, dict) or "type" not in event:
            raise ValueError("Invalid metadata")
        return event

    fields = payload.split(",")
    if len(fields) != 5 or fields[0] != "D":
        raise ValueError("Unknown packet")

    sequence = int(fields[1])
    timestamp_us = int(fields[2])
    raw_shunt = int(fields[3])
    flags = int(fields[4], 16)
    fields_in_range = (
        0 <= sequence <= MASK32
        and 0 <= timestamp_us <= MASK32
        and -32768 <= raw_shunt <= 32767
        and 0 <= flags <= 255
    )
    if not fields_in_range:
        raise ValueError("Packet field out of range")
    return Data(sequence, timestamp_us, raw_shunt, flags)


class Tracker:
    """Reject stale packets, count losses and extend device timestamps.

    Modular subtraction handles a normal 32-bit rollover. A difference of half
    the counter range or more is ambiguous, so it is treated as out of order.
    START resets the tracker using the full device epoch from its JSON event.
    """

    def __init__(self):
        self.reset()

    def reset(self, epoch_us=0):
        self.last_seq = None
        self.last_us = int(epoch_us)
        self.lost = 0
        self.received = 0
        self.bad_crc = 0
        self.out_of_order = 0

    def accept(self, packet: Data) -> Sample | None:
        """Return an ordered sample, or None for a duplicate/stale packet."""
        if self.last_seq is None:
            # Sequence numbers start at zero for each START session. If the
            # first received packet is later, earlier packets were lost.
            missing_before = packet.seq
        else:
            sequence_step = (packet.seq - self.last_seq) & MASK32
            if sequence_step == 0 or sequence_step >= HALF_COUNTER_RANGE:
                self.out_of_order += 1
                return None
            missing_before = sequence_step - 1

        previous_timestamp32 = self.last_us & MASK32
        elapsed_us = (packet.us32 - previous_timestamp32) & MASK32
        if elapsed_us >= HALF_COUNTER_RANGE:
            self.out_of_order += 1
            return None

        self.lost += missing_before
        self.last_us += elapsed_us
        self.last_seq = packet.seq
        self.received += 1
        return Sample(packet.seq, self.last_us, packet.raw, packet.flags)


def current_amp(raw, shunt_ohm, zero_raw=0.0, gain=1.0):
    """Convert the signed shunt register to amperes using session calibration.

    The register scale is 10 microvolts/count at every PGA setting. Applying
    the PGA multiplier again would incorrectly scale the reported current.
    """
    if not math.isfinite(shunt_ohm) or shunt_ohm <= 0:
        raise ValueError("The shunt resistance must be greater than zero")

    corrected_counts = raw - zero_raw
    shunt_voltage = corrected_counts * SHUNT_VOLTS_PER_COUNT * gain
    return shunt_voltage / shunt_ohm


def planning(rate_hz, requested=0):
    """Choose the acquisition period and the largest averaging count that fits.

    requested=0 means automatic averaging. The 586 us conversion budget and
    350 us margin mirror scope_plan() in the firmware; they are a scheduling
    allowance, not an additional ADC accuracy specification.
    """
    if not 1 <= rate_hz <= 1000:
        raise ValueError("The sample rate must be between 1 and 1000 Hz")

    # Match the firmware's integer rounding instead of Python's round-to-even.
    period_us = (1_000_000 + rate_hz // 2) // rate_hz
    selected_average = None
    for average_count in AVERAGE_OPTIONS:
        if requested and average_count != requested:
            continue
        required_us = average_count * CONVERSION_BUDGET_US + COMMUNICATION_MARGIN_US
        if required_us <= period_us:
            selected_average = average_count

    if selected_average is None:
        raise ValueError("The averaging window does not fit the selected period")
    return period_us, selected_average

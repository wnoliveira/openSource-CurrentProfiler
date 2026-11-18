"""Serial communication and continuous CSV capture, outside the GUI thread.

SerialWorker owns the port and output file. GUI slots put requests on a queue;
the worker processes those requests between reads and sends results back through
Qt signals. Display refreshes therefore do not determine the acquisition rate.
"""

import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import queue
import random
import time

from PySide6 import QtCore
import serial

from . import __version__
from .protocol import BAUD, MASK32, Tracker, current_amp, decode, encode, planning


CSV_FIELDS = [
    "timestamp_utc_estimated",
    "elapsed_s",
    "device_read_us",
    "session",
    "sequence",
    "raw_shunt",
    "shunt_voltage_V",
    "current_A",
    "current_mA",
    "current_uA",
    "flags",
    "missing_before",
    "pga",
    "shunt_ohm",
    "zero_raw",
    "gain",
    "averages",
    "period_us",
]

TYPICAL_WINDOWS_US = {
    1: 532,
    2: 1060,
    4: 2130,
    8: 4260,
    16: 8510,
    32: 17020,
    64: 34050,
    128: 68100,
}


def csv_row(sample, meta, shunt, utc_anchor, missing):
    """Build one measurement row using the calibration captured at START.

    Relative time comes from the device. UTC is an estimate anchored to the PC
    clock when the START acknowledgement arrives, rather than a synchronized
    absolute timestamp.
    """
    elapsed_seconds = (sample.device_us - int(meta["epoch_us"])) / 1e6
    estimated_utc = utc_anchor + timedelta(seconds=elapsed_seconds)
    amperes = current_amp(
        sample.raw, shunt, meta.get("zero_raw", 0), meta.get("gain", 1)
    )
    return [
        estimated_utc.isoformat(timespec="microseconds"),
        f"{elapsed_seconds:.6f}",
        sample.device_us,
        meta["session"],
        sample.sequence,
        sample.raw,
        f"{sample.raw * 1e-5:.9g}",
        f"{amperes:.12g}",
        f"{amperes * 1e3:.12g}",
        f"{amperes * 1e6:.12g}",
        f"{sample.flags:02X}",
        missing,
        meta["pga"],
        shunt,
        meta.get("zero_raw", 0),
        meta.get("gain", 1),
        meta["averages"],
        meta["period_us"],
    ]


class DemoSerial:
    """Protocol-compatible synthetic source with a repeatable noise sequence.

    This source exercises the same decoder and recorder as the real device.
    Its output is marked DEMO in events and CSV metadata; it is not a model of
    the INA219's full analogue behavior.
    """

    def __init__(self):
        self.opened = time.perf_counter()
        self.meta = dict(
            protocol=1,
            firmware="DEMO",
            state="STOPPED",
            baud=BAUD,
            address=64,
            ack=[64],
            candidates=[64],
            pga=3,
            rate_hz=1000,
            period_us=1000,
            avg_requested=0,
            averages=1,
            window_us=532,
            zero_raw=0.0,
            gain=1.0,
            calibrated=False,
            session=0,
            epoch_us=0,
        )
        self.output = bytearray()
        self.seq = 0
        self.next_us = 0
        self.last_sync = 0
        self.rng = random.Random(219)
        self.zeros = [0.0] * 4
        self.gains = [1.0] * 4
        self.valid = [False] * 4

    def now(self):
        """Return elapsed microseconds using the same units as device events."""
        return int((time.perf_counter() - self.opened) * 1e6)

    def event(self, kind, **extra):
        event = dict(self.meta, type=kind)
        event.update(extra)
        payload = "@" + json.dumps(event, separators=(",", ":"))
        self.output.extend(encode(payload))

    def write(self, data):
        """Accept the firmware's line-oriented commands."""
        for command in data.decode("ascii").strip().splitlines():
            parts = command.split()
            if command in ("HELLO", "STATUS"):
                self.event("status")
                continue

            if command == "STOP":
                self.meta["state"] = "STOPPED"
                self.event("stopped")
                continue

            if self.meta["state"] == "RUNNING":
                self.event("error", message="STOP_REQUIRED")
                continue

            if command == "START":
                self.meta.update(
                    state="RUNNING",
                    session=self.meta["session"] + 1,
                    epoch_us=self.now() + 10000,
                )
                self.next_us = self.meta["epoch_us"]
                self.seq = 0
                self.event("started")
                continue

            try:
                self.apply_stopped_command(command, parts)
                self.meta["window_us"] = TYPICAL_WINDOWS_US[self.meta["averages"]]
                self.event("config")
            except (ValueError, AssertionError, IndexError) as exc:
                self.event("error", message=str(exc) or "INVALID_VALUE")
        return len(data)

    def apply_stopped_command(self, command, parts):
        """Update demo settings only while acquisition is stopped."""
        if command == "SCAN":
            return

        if parts[:2] == ["SET", "PGA"]:
            pga = int(parts[2])
            if not 0 <= pga <= 3:
                raise ValueError("INVALID_VALUE")
            self.meta.update(
                pga=pga,
                zero_raw=self.zeros[pga],
                gain=self.gains[pga],
                calibrated=self.valid[pga],
            )
        elif parts[:2] == ["SET", "RATE"]:
            rate_hz = int(parts[2])
            period_us, averages = planning(rate_hz, self.meta["avg_requested"])
            self.meta.update(
                rate_hz=rate_hz, period_us=period_us, averages=averages
            )
        elif parts[:2] == ["SET", "AVG"]:
            requested = 0 if parts[2] == "AUTO" else int(parts[2])
            _, averages = planning(self.meta["rate_hz"], requested)
            self.meta.update(avg_requested=requested, averages=averages)
        elif parts[:2] == ["SET", "ADDR"]:
            if int(parts[2], 16) != 64:
                raise ValueError("SENSOR_NOT_FOUND")
        elif command == "CAL ZERO":
            pga = self.meta["pga"]
            self.zeros[pga] = 2.0
            self.valid[pga] = True
            self.meta.update(zero_raw=2.0, calibrated=True)
        elif parts[:2] == ["CAL", "GAIN"]:
            if not self.meta["calibrated"]:
                raise ValueError("CAL_ZERO_FIRST")
            self.meta["gain"] = 1.0
            self.gains[self.meta["pga"]] = 1.0
        elif command == "CAL RESET":
            pga = self.meta["pga"]
            self.zeros[pga] = 0.0
            self.gains[pga] = 1.0
            self.valid[pga] = False
            self.meta.update(zero_raw=0.0, gain=1.0, calibrated=False)
        else:
            raise ValueError("UNKNOWN_COMMAND")

    def append_sample(self):
        """Generate a pulsed 1-ohm load and serialize one synthetic reading."""
        elapsed_seconds = (self.next_us - self.meta["epoch_us"]) / 1e6
        baseline = 200
        slow_variation = 80 * math.sin(2 * math.pi * 3 * elapsed_seconds)
        pulse = 1800 if elapsed_seconds % 0.2 < 0.035 else 0
        simulated_offset = 2
        noise = self.rng.gauss(0, 4 / math.sqrt(self.meta["averages"]))
        raw_shunt = baseline + slow_variation + pulse + simulated_offset + noise

        limit = 4000 * (1 << self.meta["pga"])
        flags = 0
        if not self.meta["calibrated"]:
            flags |= 4
        if abs(raw_shunt) >= limit:
            flags |= 1
        raw_shunt = int(max(-limit, min(limit, raw_shunt)))

        # The real timestamp is at the end of the I2C register read. This
        # synthetic delay imitates that convention, without asserting accuracy.
        read_finished_us = self.next_us + self.meta["window_us"] + 230
        payload = (
            f"D,{self.seq & MASK32},{read_finished_us & MASK32},"
            f"{raw_shunt},{flags:02X}"
        )
        self.output.extend(encode(payload))
        self.seq += 1
        self.next_us += self.meta["period_us"]

    def read(self, count):
        now_us = self.now()
        if self.meta["state"] == "RUNNING":
            # Bound each batch so the worker can still handle STOP and close.
            for _ in range(200):
                if self.next_us > now_us:
                    break
                self.append_sample()

            if now_us - self.last_sync > 1_000_000:
                self.last_sync = now_us
                telemetry = dict(
                    type="sync",
                    session=self.meta["session"],
                    seq=max(0, self.seq - 1),
                    t_us=now_us,
                    i2c_errors=0,
                    skipped=0,
                    tx_drops=0,
                    late=0,
                    max_late_us=0,
                )
                self.output.extend(encode("@" + json.dumps(telemetry)))

        result = bytes(self.output[:count])
        del self.output[:count]
        if not result:
            time.sleep(0.005)
        return result

    def close(self):
        """Match the serial-port interface; the demo owns no external resource."""
        pass


class SerialWorker(QtCore.QThread):
    """Own serial I/O, packet ordering and CSV capture in one worker thread."""

    samples = QtCore.Signal(object)
    event = QtCore.Signal(object)
    connection = QtCore.Signal(str)
    statistics = QtCore.Signal(object)
    problem = QtCore.Signal(str)

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.port = port
        self.commands = queue.Queue()
        self.tracker = Tracker()
        self.meta = {}
        self.capture_file = None
        self.capture_writer = None
        self.capture_rows = 0
        self.shunt = 1.0
        self.utc_anchor = datetime.now(timezone.utc)
        self.batch = []
        self.telemetry = {}
        self.link = None
        self.active = False

    def command(self, text):
        self.commands.put(("command", text))

    def capture(self, path, shunt):
        self.commands.put(("capture", (path, shunt)))

    def stop_capture(self):
        self.commands.put(("capture_stop", None))

    def close_capture(self):
        """Flush and close the current file, then report its final row count."""
        if self.capture_file is None:
            return

        path = self.capture_file.name
        try:
            self.capture_file.flush()
            self.capture_file.close()
        except OSError as exc:
            self.problem.emit(f"Failed to finish CSV: {exc}")
        self.capture_file = None
        self.capture_writer = None
        self.event.emit(
            dict(type="capture_stopped", path=path, rows=self.capture_rows)
        )

    def open_capture(self, path, shunt):
        """Start a CSV and sidecar using the current acquisition's metadata."""
        if not self.active:
            raise ValueError("Start acquisition before starting a capture")

        self.close_capture()
        self.shunt = shunt
        self.capture_file = open(path, "w", newline="", encoding="utf-8")
        self.capture_writer = csv.writer(self.capture_file)
        self.capture_writer.writerow(CSV_FIELDS)
        self.capture_rows = 0
        metadata = dict(
            self.meta,
            software_version=__version__,
            shunt_ohm=shunt,
            utc_anchor_estimated=self.utc_anchor.isoformat(),
            timestamp_definition=(
                "ESP32: end of I2C read. UTC anchored to START reception; "
                "no absolute clock synchronization."
            ),
            demo=self.port == "DEMO",
        )
        try:
            sidecar = Path(str(path) + ".json")
            sidecar.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            self.close_capture()
            raise
        self.event.emit(dict(type="capture_started", path=path))

    def publish_batch(self):
        """Deliver accumulated measurements without one Qt signal per sample."""
        if self.batch:
            self.samples.emit(self.batch)
            self.batch = []

    def handle(self, item):
        """Keep event state and sample state aligned before publishing either."""
        if isinstance(item, dict):
            self.publish_batch()
            kind = item["type"]
            if kind == "boot" and self.active:
                self.active = False
                self.close_capture()
                self.problem.emit("ESP32 restarted during acquisition")

            if kind in ("started", "status", "config", "boot", "stopped"):
                if item.get("protocol") != 1:
                    raise ValueError("Incompatible protocol version")
                self.meta.update(item)

            if kind == "started":
                self.close_capture()
                self.active = True
                self.tracker.reset(item["epoch_us"])
                self.utc_anchor = datetime.now(timezone.utc)
                item["utc_anchor_estimated"] = self.utc_anchor.isoformat()
            if kind == "stopped":
                self.active = False
                self.close_capture()
            if kind == "sync":
                self.telemetry = item
            self.event.emit(item)
            return

        # Ignore trailing packets after STOP; they belong to the old session.
        if not self.active:
            return
        losses_before = self.tracker.lost
        sample = self.tracker.accept(item)
        if sample is None:
            return

        self.batch.append(sample)
        if self.capture_writer:
            missing_before = self.tracker.lost - losses_before
            try:
                row = csv_row(
                    sample, self.meta, self.shunt, self.utc_anchor, missing_before
                )
                self.capture_writer.writerow(row)
                self.capture_rows += 1
            except (OSError, ValueError) as exc:
                self.close_capture()
                self.problem.emit(f"Capture interrupted: {exc}")

    def process_requests(self):
        """Drain GUI requests in order; only this thread touches the port/file."""
        while True:
            try:
                kind, value = self.commands.get_nowait()
            except queue.Empty:
                return

            if kind == "command":
                self.link.write((value + "\n").encode("ascii"))
            elif kind == "capture":
                try:
                    self.open_capture(*value)
                except (OSError, ValueError) as exc:
                    self.problem.emit(str(exc))
            elif kind == "capture_stop":
                self.close_capture()

    def process_received_lines(self, buffer):
        """Consume complete frames, leaving any partial last line in buffer."""
        ready = False
        while b"\n" in buffer:
            line, _, remaining = buffer.partition(b"\n")
            buffer = bytearray(remaining)
            if not line:
                continue
            try:
                item = decode(line)
                self.handle(item)
                if isinstance(item, dict) and item.get("protocol") == 1:
                    ready = True
            except (ValueError, KeyError, UnicodeError, TypeError):
                # Includes malformed frames as well as CRC failures. Waiting
                # for the next line boundary recovers without using bad data.
                self.tracker.bad_crc += 1
        return buffer, ready

    def publish_statistics(self):
        device_statistics = {
            key: value for key, value in self.telemetry.items() if key != "type"
        }
        self.statistics.emit(
            dict(
                received=self.tracker.received,
                lost=self.tracker.lost,
                crc=self.tracker.bad_crc,
                out_of_order=self.tracker.out_of_order,
                capture_rows=self.capture_rows,
                **device_statistics,
            )
        )

    def run(self):
        """Open the link, service it until interrupted, and always close it."""
        try:
            if self.port == "DEMO":
                self.link = DemoSerial()
            else:
                self.link = serial.Serial(
                    port=None, baudrate=BAUD, timeout=0.01, write_timeout=0.5
                )
                # Set control lines before opening to reduce unwanted resets.
                # USB-UART hardware/drivers can still reset the ESP32 on open.
                self.link.dtr = False
                self.link.rts = False
                self.link.port = self.port
                self.link.open()
            self.connection.emit("connected")

            buffer = bytearray()
            started_at = time.perf_counter()
            last_publish = started_at
            last_statistics = started_at
            last_flush = started_at
            last_received = started_at
            hello_due = 0
            ready = False

            while not self.isInterruptionRequested():
                now = time.perf_counter()
                if not ready and now >= hello_due:
                    self.link.write(b"HELLO\n")
                    hello_due = now + 0.5

                self.process_requests()
                data = self.link.read(4096)
                if data:
                    last_received = now
                    buffer.extend(data)
                    if len(buffer) > 8192:
                        # A lost newline must not allow unbounded allocation.
                        buffer.clear()
                        self.tracker.bad_crc += 1
                    buffer, received_handshake = self.process_received_lines(buffer)
                    ready = ready or received_handshake

                if now - last_publish >= 0.02:
                    self.publish_batch()
                    last_publish = now
                if now - last_statistics >= 0.25:
                    self.publish_statistics()
                    last_statistics = now
                if self.capture_file and now - last_flush >= 1:
                    try:
                        self.capture_file.flush()
                    except OSError as exc:
                        self.close_capture()
                        self.problem.emit(str(exc))
                    last_flush = now

                if not ready and now - started_at > 6:
                    raise TimeoutError(
                        "No response from firmware. Check the port, firmware and 460800 baud."
                    )
                if self.active and now - last_received > 4:
                    raise TimeoutError("No data for more than four seconds")
        except Exception as exc:
            self.problem.emit(f"Connection: {exc}")
        finally:
            self.publish_batch()
            self.close_capture()
            if self.link:
                try:
                    self.link.write(b"STOP\n")
                    self.link.close()
                except Exception:
                    # A removed USB cable can make both operations fail. The
                    # disconnected signal must still reach the GUI.
                    pass
            self.connection.emit("disconnected")

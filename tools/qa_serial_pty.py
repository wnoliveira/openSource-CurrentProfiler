"""Exercise genuine pySerial on a POSIX pseudo-terminal.

The emulator fragments lines and injects one missing frame and one bad CRC.
Windows does not provide POSIX PTYs, so the script reports that check as skipped.
"""

import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))


def run():
    if os.name != "posix":
        return {
            "status": "skipped",
            "reason": "The serial PTY integration check requires a POSIX host",
        }

    import pty
    import select

    from PySide6.QtCore import QCoreApplication

    from current_scope.worker import DemoSerial, SerialWorker

    master, slave = pty.openpty()
    port = os.ttyname(slave)
    finished = threading.Event()
    counts = {"injected_missing": 0, "injected_corrupt": 0}

    def emulate():
        """Translate PTY commands to DEMO responses with controlled corruption."""
        source = DemoSerial()
        commands = bytearray()
        pending = bytearray()
        while not finished.is_set():
            if select.select([master], [], [], 0.001)[0]:
                try:
                    commands.extend(os.read(master, 4096))
                except OSError:
                    break
                while b"\n" in commands:
                    command, _, remaining = commands.partition(b"\n")
                    commands = bytearray(remaining)
                    try:
                        source.write(command + b"\n")
                    except UnicodeError:
                        pass

            pending.extend(source.read(4096))
            while b"\n" in pending:
                line, _, remaining = pending.partition(b"\n")
                pending = bytearray(remaining)
                if line.startswith(b"D,"):
                    sequence = int(line.split(b",")[1])
                    if sequence == 100:
                        counts["injected_missing"] += 1
                        continue
                    if sequence == 200:
                        # Change a CRC digit while keeping framing intact.
                        last_digit = b"0" if line[-1:] != b"0" else b"1"
                        line = line[:-1] + last_digit
                        counts["injected_corrupt"] += 1

                # Serial reads need not have the same boundaries as writes.
                half = max(1, len(line) // 2)
                os.write(master, line[:half])
                os.write(master, line[half:] + b"\n")

    app = QCoreApplication.instance() or QCoreApplication([])
    thread = threading.Thread(target=emulate, daemon=True)
    worker = SerialWorker(port)
    events = []
    problems = []
    samples = []
    worker.event.connect(events.append)
    worker.problem.connect(problems.append)
    worker.samples.connect(lambda batch: samples.extend(batch))

    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    try:
        thread.start()
        worker.start()
        pump(0.4)
        assert any(event.get("protocol") == 1 for event in events), (events, problems)
        worker.command("START")
        pump(1.1)
        worker.command("STOP")
        pump(0.2)

        assert any(event["type"] == "stopped" for event in events)
        assert not problems, problems
        assert worker.tracker.lost == 2, worker.tracker.lost
        assert worker.tracker.bad_crc == 1, worker.tracker.bad_crc
        assert len(samples) > 800, len(samples)
        report = dict(
            status="ok",
            received=len(samples),
            lost=worker.tracker.lost,
            bad_crc=worker.tracker.bad_crc,
            **counts,
        )
        report_path = ROOT / "validation" / "serial_pty_report.json"
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        worker.requestInterruption()
        worker.wait(2500)
        finished.set()
        thread.join(1)
        os.close(master)
        os.close(slave)


if __name__ == "__main__":
    print(json.dumps(run()))

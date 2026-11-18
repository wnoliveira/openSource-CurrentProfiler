"""Offscreen integration check using the real GUI and synthetic serial data.

Artifacts are written to validation/. They demonstrate the software path only;
the report explicitly records that no physical device was tested.
"""

import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6 import QtCore, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from current_scope.app import MainWindow


def pump(app, seconds):
    """Keep Qt processing worker signals while allowing real time to pass."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def wait_for(app, condition, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for the DEMO acquisition")


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def run():
    output = ROOT / "validation"
    output.mkdir(exist_ok=True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    # Tests must not restore or overwrite the operator's last-used settings.
    with tempfile.TemporaryDirectory(prefix="scope-qa-settings-") as settings_folder:
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
        QtCore.QSettings.setPath(
            QtCore.QSettings.Format.IniFormat,
            QtCore.QSettings.Scope.UserScope,
            settings_folder,
        )
        window = MainWindow(demo=True)
        window.settings.setFallbacksEnabled(False)
        window.set_language("en")
        window.show()
        try:
            wait_for(app, lambda: window.connected and bool(window.meta))
            assert window.meta.get("address") == 64
            window.start_acquisition()
            wait_for(app, lambda: window.running and len(window.records) > 100)

            # Continuous capture must include every validated sample, even
            # though the displayed oscilloscope window is much shorter.
            capture_path = output / "capture_demo.csv"
            window.worker.capture(str(capture_path), 1.0)
            wait_for(
                app,
                lambda: window.capture_active and window.worker.capture_rows > 1000,
            )
            window.worker.stop_capture()
            wait_for(app, lambda: not window.capture_active)
            window.freeze.setChecked(True)
            assert window.display and len(window.display["records"]) > 10

            scope_path = output / "scope_demo.csv"
            png_path = output / "scope_demo.png"
            window.export_scope_csv(str(scope_path))
            window.export_scope_png(str(png_path))
            window.grab().save(str(output / "interface_demo.png"))
            window.grab().save(str(ROOT / "docs" / "interface_demo.png"))

            window.send_commands(["STOP"])
            wait_for(app, lambda: not window.running)
            window.rate.setValue(100)
            window.apply_config()
            wait_for(
                app,
                lambda: window.meta["rate_hz"] == 100 and not window.pending,
            )
            assert window.meta["averages"] == 16
            window.worker.command("CAL ZERO")
            wait_for(app, lambda: window.meta["calibrated"])

            # A calibration performed after STOP belongs to the next session.
            # Changing units on the frozen trace must use its original values.
            assert window.session_meta.get("zero_raw") == 0
            amperes_before = window.display["amps"].copy()
            window.unit.setCurrentIndex(1)
            pump(app, 0.05)
            _, displayed_values = window.curve.getData()
            assert np.allclose(
                displayed_values, amperes_before * 1e6, equal_nan=True
            )

            rows = read_csv(capture_path)
            assert len(rows) > 900, len(rows)
            device_times = [int(row["device_read_us"]) for row in rows]
            assert all(
                later > earlier
                for earlier, later in zip(device_times, device_times[1:])
            )
            assert all(int(row["missing_before"]) == 0 for row in rows)
            scope_rows = read_csv(scope_path)
            assert len(scope_rows) == len(window.display["records"])

            elapsed_us = device_times[-1] - device_times[0]
            report = dict(
                capture_samples=len(rows),
                scope_samples=len(scope_rows),
                observed_hz=(len(rows) - 1) * 1e6 / elapsed_us,
                png_bytes=png_path.stat().st_size,
                gui="offscreen",
                physical_hardware_tested=False,
            )
            report_path = output / "qa_report.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return report
        finally:
            window.close()
            pump(app, 0.1)


if __name__ == "__main__":
    print(json.dumps(run()))

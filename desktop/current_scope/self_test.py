"""Exercise the actual frozen application without hardware or persistent settings."""
import csv
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import traceback


def run(report):
    """Write a machine-readable result after exercising the packaged app."""
    result = {
        "status": "failed",
        "frozen": bool(getattr(sys, "frozen", False)),
        "bits": struct.calcsize("P") * 8,
    }
    window = None
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtGui, QtWidgets as W
        from .app import MainWindow
        from .licensing import license_directory

        app = W.QApplication.instance() or W.QApplication([sys.argv[0]])
        app.setStyle("Fusion")

        def wait_for(condition, timeout=6):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                app.processEvents()
                if condition():
                    return
                time.sleep(0.01)
            raise RuntimeError("Timed out waiting for the DEMO acquisition.")

        with tempfile.TemporaryDirectory(prefix="current-scope-test-") as temporary_folder:
            folder = Path(temporary_folder)
            QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
            QtCore.QSettings.setPath(
                QtCore.QSettings.Format.IniFormat,
                QtCore.QSettings.Scope.UserScope,
                str(folder),
            )
            window = MainWindow()
            window.settings.setFallbacksEnabled(False)
            # Check the catalog and Qt translation file inside the real bundle.
            window.set_language("pt")
            if window.start.text() != "Iniciar":
                raise RuntimeError("Portuguese application text was not available.")
            question = W.QMessageBox(
                W.QMessageBox.Icon.Question, "", "", W.QMessageBox.StandardButton.Yes
            )
            if question.button(W.QMessageBox.StandardButton.Yes).text() != "&Sim":
                raise RuntimeError("Portuguese Qt dialog translations were not bundled.")
            question.close()
            window.set_language("en")
            if window.start.text() != "Start":
                raise RuntimeError("English application text was not available.")
            for name in ("arrow-down.svg", "arrow-up.svg"):
                image = QtGui.QImage(str(Path(__file__).parent / "assets" / name))
                if image.isNull():
                    raise RuntimeError(f"Missing SVG or unavailable image plugin: {name}")
            if not (license_directory() / "LGPL-3.0.txt").is_file():
                raise RuntimeError("License notices were not included in the package.")
            # Use the real worker, parser and GUI with a synthetic source.
            window.connect_demo()
            wait_for(lambda: window.connected and bool(window.meta))
            window.start_acquisition()
            wait_for(lambda: window.running and window.display is not None)
            capture = folder / "capture.csv"
            window.worker.capture(str(capture), window.shunt_session)
            wait_for(
                lambda: window.capture_active and window.worker.capture_rows >= 50
            )
            window.worker.stop_capture()
            wait_for(lambda: not window.capture_active)
            window.apply_theme("dark")
            window.apply_theme("light")
            scope = folder / "scope.csv"
            png = folder / "scope.png"
            window.export_scope_csv(str(scope))
            window.export_scope_png(str(png))
            with capture.open(encoding="utf-8", newline="") as stream:
                captured = sum(1 for _ in csv.DictReader(stream))
            with scope.open(encoding="utf-8", newline="") as stream:
                exported = sum(1 for _ in csv.DictReader(stream))
            if captured < 50 or not exported or QtGui.QImage(str(png)).isNull():
                raise RuntimeError("Capture or export did not produce valid data.")
            # Both export paths must retain the source identity.
            for path in (capture, scope):
                sidecar = Path(str(path) + ".json")
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                if not metadata.get("demo"):
                    raise RuntimeError("Metadata did not identify the DEMO source.")
            result.update(
                status="ok",
                captured_samples=captured,
                exported_samples=exported,
                png_bytes=png.stat().st_size,
                checks=[
                    "Qt", "English/Portuguese", "Qt dialog translations",
                    "serial ports", "SVG", "licenses", "DEMO", "themes",
                    "capture CSV", "scope CSV", "metadata JSON", "PNG",
                ],
            )
            window.close()
            app.processEvents()
            window = None
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        if window is not None:
            window.close()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if result["status"] == "ok" else 1

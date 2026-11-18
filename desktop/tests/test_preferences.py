"""Preferences survive reopening without starting or configuring hardware."""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets as W

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from current_scope.app import MainWindow


class PreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.settings_path = str(Path(self.folder.name) / "preferences.ini")
        self.settings_type = QtCore.QSettings
        self.settings = self.settings_type(self.settings_path, self.settings_type.Format.IniFormat)
        self.factory = patch("current_scope.app.QtCore.QSettings", return_value=self.settings)
        self.settings_factory = self.factory.start()
        self.windows = []

    def tearDown(self):
        for window in reversed(self.windows):
            window.close()
        self.app.processEvents()
        self.factory.stop()
        self.folder.cleanup()

    def make_window(self):
        window = MainWindow()
        self.windows.append(window)
        return window

    def reopen(self, window):
        window.close()
        self.app.processEvents()
        # Read a new QSettings instance from disk so the test requires a flush.
        self.settings = self.settings_type(self.settings_path, self.settings_type.Format.IniFormat)
        self.settings_factory.return_value = self.settings
        return self.make_window()

    def wait_for(self, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(.005)
        self.fail("Timed out waiting for simulated device")

    def test_reopen_restores_display_sensor_and_layout_preferences(self):
        first = self.make_window()
        first.set_language("en")
        first.apply_theme("light")
        first.unit.setCurrentIndex(first.unit.findText("µA"))
        values = {
            "shunt": .22, "timebase": 125, "yscale": 2500,
            "yoffset": 7500, "threshold": 18000, "pretrigger": 65,
            "reference": 17.5, "rate": 125,
        }
        for attribute, value in values.items():
            getattr(first, attribute).setValue(value)
        first.trigger_mode.setCurrentIndex(first.trigger_mode.findData("Normal"))
        first.edge.setCurrentIndex(first.edge.findData("Falling"))
        first.pga.setCurrentIndex(first.pga.findData(1))
        first.average.setCurrentIndex(first.average.findData(4))
        first.addr.addItem("0x41", 0x41)
        first.port.setCurrentIndex(first.port.findData("DEMO"))
        first.inspector.setCurrentIndex(2)
        first.details_button.setChecked(True)

        restored = self.reopen(first)
        self.assertTrue(Path(self.settings_path).is_file())
        for attribute, value in values.items():
            self.assertEqual(getattr(restored, attribute).value(), value, attribute)
        self.assertEqual(restored.unit.currentText(), "µA")
        self.assertEqual(restored.trigger_mode.currentData(), "Normal")
        self.assertEqual(restored.edge.currentData(), "Falling")
        self.assertEqual(restored.pga.currentData(), 1)
        self.assertEqual(restored.average.currentData(), 4)
        self.assertEqual(restored.port.currentData(), "DEMO")
        self.assertEqual(restored.inspector.currentIndex(), 2)
        self.assertTrue(restored.details_button.isChecked())
        self.assertEqual(restored.theme, "light")
        self.assertEqual(restored.language_choice.currentData(), "en")
        self.assertAlmostEqual(restored.trigger_line.value(), 18000)
        self.assertAlmostEqual(restored.trigger_x.value(), .8125)
        self.assertIsNone(restored.worker)
        self.assertFalse(restored.running)
        self.assertFalse(restored.capture_active)
        self.assertFalse(restored.records)

        # The address is selected only after it appears in a device scan.
        restored.meta = dict(rate_hz=1000, pga=3, avg_requested=0,
                             candidates=[0x40, 0x41], address=0x40)
        restored.reflect_config()
        self.assertEqual(restored.addr.currentData(), 0x41)
        self.assertTrue(restored.configuration_dirty())

    def test_saved_sensor_preferences_require_apply_after_connection(self):
        self.settings.setValue("rate_hz", 100)
        self.settings.setValue("pga", 1)
        self.settings.setValue("average", 4)
        window = self.make_window()
        window.connect_demo()
        self.wait_for(lambda: window.connected and bool(window.meta))
        self.assertEqual(window.meta["rate_hz"], 1000)
        self.assertEqual(window.rate.value(), 100)
        self.assertEqual(window.pga.currentData(), 1)
        self.assertEqual(window.average.currentData(), 4)
        self.assertFalse(window.start.isEnabled())
        self.assertTrue(window.apply.isEnabled())
        self.assertFalse(window.running)

        # A subsequent status must retain the operator's latest pending edit.
        window.rate.setValue(125)
        window.reflect_config()
        self.assertEqual(window.rate.value(), 125)
        window.apply_config()
        self.wait_for(lambda: not window.pending and window.meta["rate_hz"] == 125)
        self.assertFalse(window.configuration_dirty())
        self.assertTrue(window.start.isEnabled())
        self.assertFalse(window.running)

    def test_corrupt_and_out_of_range_values_keep_usable_defaults(self):
        for key, value in {
            "shunt": "nan", "timebase_ms": "infinity", "yscale": -4,
            "yoffset": "bad", "threshold": "-inf", "pretrigger": 1000,
            "rate_hz": 0, "reference": "not a number", "unit": "invalid",
            "trigger_mode": "invalid", "trigger_edge": "invalid",
            "pga": 99, "average": 3, "address": "invalid",
            "inspector_tab": 999, "splitter_state": "invalid",
        }.items():
            self.settings.setValue(key, value)
        window = self.make_window()
        self.assertEqual(window.shunt.value(), 1)
        self.assertEqual(window.timebase.value(), 50)
        self.assertEqual(window.yscale.value(), 5)
        self.assertEqual(window.yoffset.value(), 10)
        self.assertEqual(window.threshold.value(), 10)
        self.assertEqual(window.pretrigger.value(), 30)
        self.assertEqual(window.rate.value(), 1000)
        self.assertEqual(window.unit.currentText(), "mA")
        self.assertEqual(window.trigger_mode.currentData(), "Auto")
        self.assertEqual(window.edge.currentData(), "Rising")
        self.assertEqual(window.pga.currentData(), 3)
        self.assertEqual(window.average.currentData(), 0)
        self.assertEqual(window.inspector.currentIndex(), 0)
        self.assertFalse(window._preserve_sensor_preferences)

    def test_existing_shunt_and_timebase_preferences_remain_compatible(self):
        self.settings.setValue("shunt", .1)
        self.settings.setValue("timebase_ms", 17.125)
        window = self.make_window()
        self.assertEqual(window.shunt.value(), .1)
        self.assertEqual(window.timebase.value(), 17.125)
        self.assertEqual(window.yscale.value(), 5)
        self.assertFalse(window._preserve_sensor_preferences)

    def test_saved_serial_port_is_selected_without_opening_a_connection(self):
        self.settings.setValue("port", "COM7")
        ports = [SimpleNamespace(device=name, description="Serial device")
                 for name in ("COM3", "COM7")]
        with patch("current_scope.app.serial.tools.list_ports.comports", return_value=ports):
            window = self.make_window()
        self.assertEqual(window.port.currentData(), "COM7")
        self.assertIsNone(window.worker)
        self.assertFalse(window.connected)

    def test_missing_saved_port_falls_back_without_opening_a_connection(self):
        self.settings.setValue("port", "COM7")
        ports = [SimpleNamespace(device="COM3", description="Serial device")]
        with patch("current_scope.app.serial.tools.list_ports.comports", return_value=ports):
            window = self.make_window()
        self.assertEqual(window.port.currentData(), "COM3")
        self.assertIsNone(window.worker)
        self.assertFalse(window.connected)


if __name__ == "__main__":
    unittest.main()

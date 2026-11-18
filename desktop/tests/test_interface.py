"""Desktop interaction regressions. Run: python -m unittest discover -s tests -v."""
import tempfile
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6 import QtCore, QtGui, QtTest, QtWidgets as W

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from current_scope.app import MainWindow
from current_scope import app as scope_app


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(str(Path(self.folder.name) / "settings.ini"),
                                         QtCore.QSettings.Format.IniFormat)
        self.factory = patch("current_scope.app.QtCore.QSettings", return_value=self.settings)
        self.factory.start()
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.factory.stop()
        self.folder.cleanup()

    def pump(self, seconds=.05):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.app.processEvents()
            time.sleep(.005)

    def connect_demo(self):
        self.window.connect_demo()
        self.pump(.3)
        self.assertTrue(self.window.connected)

    def test_all_tabs_fit_minimum_window_without_scroll_panels(self):
        w = self.window
        w.resize(w.minimumSize())
        w.show()
        for theme in ("light", "dark"):
            w.apply_theme(theme)
            for diagnostics in (False, True):
                w.details_button.setChecked(diagnostics)
                for index in range(w.inspector.count()):
                    w.inspector.setCurrentIndex(index)
                    self.pump()
                    page = w.inspector.currentWidget()
                    for control in page.findChildren(W.QWidget):
                        if isinstance(control, (W.QAbstractSpinBox, W.QComboBox, W.QPushButton)):
                            bounds = QtCore.QRect(control.mapTo(page, QtCore.QPoint()), control.size())
                            self.assertTrue(page.rect().contains(bounds),
                                            f"Tab {index}: {control} outside {page.size()}: {bounds}")
                self.assertTrue(w.plot.parentWidget().rect().contains(w.plot.geometry()))
        self.assertFalse(w.findChildren(W.QScrollArea))
        bar = w.inspector.tabBar()
        self.assertTrue(bar.rect().contains(bar.tabRect(bar.count() - 1)))

    def test_wheel_does_not_change_focused_controls(self):
        self.connect_demo()
        for control in (self.window.pga, self.window.rate, self.window.shunt, self.window.timebase):
            before = control.currentIndex() if isinstance(control, W.QComboBox) else control.value()
            control.setFocus()
            event = QtGui.QWheelEvent(QtCore.QPointF(10, 10), QtCore.QPointF(10, 10),
                                      QtCore.QPoint(), QtCore.QPoint(0, -120),
                                      QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.NoModifier,
                                      QtCore.Qt.ScrollPhase.ScrollUpdate, False)
            self.app.sendEvent(control, event)
            after = control.currentIndex() if isinstance(control, W.QComboBox) else control.value()
            self.assertEqual(before, after)

    def test_steps_and_typed_precision(self):
        value = self.window.timebase
        for expected in (100, 200, 500, 1000):
            value.stepUp()
            self.assertEqual(value.value(), expected)
        value.stepDown()
        self.assertEqual(value.value(), 500)
        value.lineEdit().setText(value.locale().toString(17.125, "f", 3) + value.suffix())
        value.interpretText()
        self.assertIn("17", value.text())
        self.assertEqual(value.value(), 17.125)
        shunt = self.window.shunt
        shunt.setValue(.000123)
        self.assertEqual(shunt.value(), .000123)
        self.assertNotIn("000000", shunt.text())
        self.assertGreater(shunt.minimum(), 0)

    def test_average_menu_shows_all_options_without_scrolling(self):
        self.connect_demo()
        w = self.window
        w.show()
        self.pump()
        w.average.showPopup()
        self.pump()
        view = w.average.view()
        last = w.average.model().index(w.average.count() - 1, 0)
        self.assertTrue(view.viewport().rect().contains(view.visualRect(last)))
        self.assertFalse(view.verticalScrollBar().isVisible())
        w.average.hidePopup()

    def test_pending_settings_block_start_until_acknowledged(self):
        self.connect_demo()
        w = self.window
        self.assertTrue(w.start.isEnabled())
        w.rate.setValue(100)
        self.assertFalse(w.start.isEnabled())
        self.assertTrue(w.config_hint.property("dirty"))
        w.apply.click()
        self.pump(.3)
        self.assertEqual(w.meta["rate_hz"], 100)
        self.assertTrue(w.start.isEnabled())
        self.assertFalse(w.config_hint.property("dirty"))

    def test_theme_switch_preserves_trace_and_is_remembered(self):
        self.connect_demo()
        w = self.window
        w.start_acquisition()
        self.pump(.7)
        self.assertIsNotNone(w.display)
        w.freeze.setChecked(True)
        before = w.curve.getData()[1].copy()
        for theme in ("dark", "light", "dark"):
            w.apply_theme(theme)
            self.app.processEvents()
            np.testing.assert_array_equal(w.curve.getData()[1], before)
            self.assertTrue(w.running)
            self.assertEqual(w.settings.value("theme"), theme)
        second = MainWindow()
        try:
            self.assertEqual(second.theme, "dark")
        finally:
            second.close()

    def test_free_trigger_and_single_rearm_controls(self):
        w = self.window
        w.trigger_mode.setCurrentIndex(w.trigger_mode.findData("Free"))
        self.assertFalse(w.threshold.isEnabled())
        self.assertFalse(w.trigger_line.isVisible())
        self.assertFalse(w.arm.isEnabled())
        w.trigger_mode.setCurrentIndex(w.trigger_mode.findData("Single"))
        self.assertTrue(w.arm.isEnabled())
        self.assertTrue(w.threshold.isEnabled())
        self.assertTrue(w.trigger_line.isVisible())

    def test_startup_opens_maximized(self):
        with patch.object(scope_app.W, "QApplication") as application, \
                patch.object(scope_app, "MainWindow") as window:
            application.return_value.exec.return_value = 0
            self.assertEqual(scope_app.main(), 0)
            window.return_value.showMaximized.assert_called_once_with()

    def test_fullscreen_shortcuts(self):
        w = self.window
        w.showFullScreen()
        self.pump()
        self.assertTrue(w.isFullScreen())
        QtTest.QTest.keyClick(w, QtCore.Qt.Key.Key_F11)
        self.pump()
        self.assertFalse(w.isFullScreen())
        QtTest.QTest.keyClick(w, QtCore.Qt.Key.Key_F11)
        self.pump()
        self.assertTrue(w.isFullScreen())
        QtTest.QTest.keyClick(w, QtCore.Qt.Key.Key_Escape)
        self.pump()
        self.assertFalse(w.isFullScreen())


if __name__ == "__main__":
    unittest.main()

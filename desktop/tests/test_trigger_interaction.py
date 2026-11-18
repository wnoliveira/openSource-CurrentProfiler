"""Exercise plot mouse selection, marker dragging and trigger control updates."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PySide6 import QtCore, QtGui, QtTest, QtWidgets as W

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from current_scope.app import MainWindow


class MouseTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        settings = QtCore.QSettings(str(Path(self.folder.name) / "settings.ini"),
                                    QtCore.QSettings.Format.IniFormat)
        self.settings_patch = patch("current_scope.app.QtCore.QSettings", return_value=settings)
        self.settings_patch.start()
        self.window = MainWindow()
        self.window.show()
        QtTest.QTest.qWait(30)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.settings_patch.stop()
        self.folder.cleanup()

    def plot_point(self, x, y):
        plot = self.window.plot
        scene = plot.getViewBox().mapViewToScene(QtCore.QPointF(x, y))
        return plot.mapFromScene(scene)

    def click_plot(self, x, y, button=QtCore.Qt.MouseButton.LeftButton):
        QtTest.QTest.mouseClick(self.window.plot.viewport(), button,
                               pos=self.plot_point(x, y))
        self.app.processEvents()

    def drag_plot(self, start, end):
        viewport = self.window.plot.viewport()
        # Pyqtgraph limits move handling to 100 Hz; allow real event intervals.
        QtTest.QTest.qWait(20)
        QtTest.QTest.mouseMove(viewport, start)
        QtTest.QTest.qWait(20)
        QtTest.QTest.mousePress(viewport, QtCore.Qt.MouseButton.LeftButton, pos=start)
        for ratio in (.25, .5, .75, 1):
            point = QtCore.QPointF(start + (end - start) * ratio)
            event = QtGui.QMouseEvent(
                QtCore.QEvent.Type.MouseMove, point, QtCore.QPointF(viewport.mapToGlobal(point.toPoint())),
                QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
            self.app.sendEvent(viewport, event)
            QtTest.QTest.qWait(20)
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()

    def test_click_selects_level_and_pretrigger_in_display_units(self):
        w = self.window
        self.click_plot(.32, 18)
        self.assertAlmostEqual(w.threshold.value(), 18, delta=.3)
        self.assertEqual(w.pretrigger.value(), 64)
        self.assertEqual(w.trigger_line.value(), w.threshold.value())
        self.assertAlmostEqual(w.trigger_x.value(), .32)
        w.unit.setCurrentIndex(w.unit.findText("µA"))
        self.click_plot(.2, 24000)
        self.assertAlmostEqual(w.threshold.value(), 24000, delta=300)
        self.assertEqual(w.pretrigger.value(), 40)
        self.assertEqual(w.trigger_line.value(), w.threshold.value())

    def test_clicks_ignore_free_mode_and_other_mouse_buttons(self):
        w = self.window
        before = w.threshold.value(), w.pretrigger.value()
        self.click_plot(.3, 20, QtCore.Qt.MouseButton.RightButton)
        self.assertEqual((w.threshold.value(), w.pretrigger.value()), before)
        QtTest.QTest.mouseClick(w.plot.viewport(), QtCore.Qt.MouseButton.LeftButton,
                               pos=QtCore.QPoint(4, w.plot.height() // 2))
        self.app.processEvents()
        self.assertEqual((w.threshold.value(), w.pretrigger.value()), before)
        w.trigger_mode.setCurrentIndex(w.trigger_mode.findData("Free"))
        self.click_plot(.3, 20)
        self.assertEqual((w.threshold.value(), w.pretrigger.value()), before)
        self.assertFalse(w.trigger_line.isVisible())
        self.assertFalse(w.trigger_x.isVisible())

    def test_drag_markers_updates_controls_and_timebase_updates_bounds(self):
        w = self.window
        self.drag_plot(self.plot_point(.4, 10), self.plot_point(.4, 23))
        self.assertAlmostEqual(w.threshold.value(), 23, delta=.5)
        self.assertEqual(w.trigger_line.value(), w.threshold.value())
        self.drag_plot(self.plot_point(.15, 0), self.plot_point(.4, 0))
        self.assertAlmostEqual(w.pretrigger.value(), 80, delta=1)
        w.timebase.setValue(100)
        self.assertAlmostEqual(w.trigger_x.value(), w.pretrigger.value() / 100)
        self.assertEqual(w.trigger_x.bounds(), (0, .9))
        self.click_plot(.98, 20)
        self.assertEqual(w.pretrigger.value(), 90)
        self.assertAlmostEqual(w.trigger_x.value(), .9)
        w.timebase.setValue(10)
        self.assertAlmostEqual(w.trigger_x.value(), .09)
        self.assertEqual(w.trigger_x.bounds(), (0, .09))
        self.click_plot(.001, 20)
        self.assertEqual(w.pretrigger.value(), 1)
        self.assertAlmostEqual(w.trigger_x.value(), .001)

    def test_mouse_change_rearms_single_capture(self):
        w = self.window
        w.trigger_mode.setCurrentIndex(w.trigger_mode.findData("Single"))
        w.single_armed = False
        w.freeze.setChecked(True)
        self.click_plot(.25, 18)
        self.assertTrue(w.single_armed)
        self.assertFalse(w.paused)
        w.single_armed = False
        w.freeze.setChecked(True)
        self.drag_plot(self.plot_point(.4, w.threshold.value()), self.plot_point(.4, 25))
        self.assertTrue(w.single_armed)
        self.assertFalse(w.paused)


if __name__ == "__main__":
    unittest.main()

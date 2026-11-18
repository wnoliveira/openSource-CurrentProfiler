"""Regression checks for language selection during a measurement session."""

import tempfile
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as W

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from current_scope import PROJECT_URL, __version__
from current_scope.app import MainWindow
from current_scope.i18n import Translator, system_language
from current_scope.licensing import show_licenses


class LanguageDetectionTests(unittest.TestCase):
    def test_portuguese_variants_and_english_fallback(self):
        for locale in ("pt_BR", "pt_PT", "pt-AO", "PT-br"):
            self.assertEqual(system_language(locale), "pt")
        for locale in ("en_US", "en-GB", "es_ES", "de_DE", "ja_JP", "C", ""):
            self.assertEqual(system_language(locale), "en")

    def test_device_errors_are_readable_in_both_languages(self):
        self.assertEqual(Translator("en").text("CAL_ZERO_FIRST"), "Calibrate zero first")
        self.assertEqual(Translator("pt").text("CAL_ZERO_FIRST"), "Calibre o zero primeiro")
        self.assertEqual(Translator("pt").text("Connection: COM5 unavailable"),
                         "Conexão: COM5 unavailable")
        self.assertEqual(Translator("pt").text("unknown external error"), "unknown external error")


class LocalizedWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(str(Path(self.folder.name) / "settings.ini"),
                                         QtCore.QSettings.Format.IniFormat)
        self.settings_patch = patch("current_scope.app.QtCore.QSettings", return_value=self.settings)
        self.settings_patch.start()
        self.locale_patch = patch("current_scope.localization.system_language", return_value="pt")
        self.locale_patch.start()
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.locale_patch.stop()
        self.settings_patch.stop()
        self.folder.cleanup()

    def wait_for(self, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for simulated acquisition")

    def connect_demo(self):
        self.window.connect_demo()
        self.wait_for(lambda: self.window.connected and bool(self.window.meta))

    def test_system_default_and_explicit_preference_are_remembered(self):
        self.assertEqual(self.window.translator.language, "pt")
        self.assertEqual(self.window.start.text(), "Iniciar")
        self.window.set_language("en")
        second = MainWindow()
        try:
            self.assertEqual(second.translator.language, "en")
            self.assertEqual(second.start.text(), "Start")
            second.set_language("system")
            self.assertEqual(second.translator.language, "pt")
        finally:
            second.close()

    def test_standard_dialog_buttons_follow_language(self):
        for language, expected in (("pt", "&Sim"), ("en", "&Yes"), ("pt", "&Sim")):
            self.window.set_language(language)
            dialog = W.QMessageBox(W.QMessageBox.Icon.Question, "", "",
                                   W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.No)
            self.assertEqual(dialog.button(W.QMessageBox.StandardButton.Yes).text(), expected)
            dialog.close()

    def test_language_choice_fits_all_labels_at_minimum_window_size(self):
        window = self.window
        window.resize(window.minimumSize())
        window.show()
        for language in ("en", "pt"):
            window.set_language(language)
            self.app.processEvents()
            combo = window.language_choice
            option = W.QStyleOptionComboBox()
            combo.initStyleOption(option)
            text_rect = combo.style().subControlRect(
                W.QStyle.ComplexControl.CC_ComboBox, option,
                W.QStyle.SubControl.SC_ComboBoxEditField, combo,
            )
            required = max(combo.fontMetrics().horizontalAdvance(combo.itemText(index))
                           for index in range(combo.count()))
            self.assertGreaterEqual(text_rect.width(), required)
            self.assertTrue(window.statusBar().rect().contains(combo.geometry()))

    def test_about_and_license_colors_follow_selected_theme(self):
        window = self.window
        role = QtGui.QPalette.ColorRole
        for theme in ("light", "dark", "light"):
            window.apply_theme(theme)

            def inspect_dialog(dialog):
                dialog.ensurePolished()
                colors = window.colors
                self.assertEqual(dialog.palette().color(role.Window).name(), colors["window"])
                for label in dialog.findChildren(W.QLabel):
                    label.ensurePolished()
                    self.assertEqual(label.palette().color(role.WindowText).name(), colors["text"])
                    if "href=" in label.text():
                        self.assertEqual(label.palette().color(role.Link).name(), colors["trace"])
                        document = QtGui.QTextDocument()
                        document.setHtml(label.text())
                        link = document.find(window.tr_text("Project on GitHub"))
                        self.assertFalse(link.isNull())
                        self.assertTrue(link.charFormat().isAnchor())
                        self.assertEqual(link.charFormat().foreground().color().name(), colors["trace"])
                for notices in dialog.findChildren(W.QPlainTextEdit):
                    notices.ensurePolished()
                    self.assertEqual(notices.palette().color(role.Base).name(), colors["field"])
                    self.assertEqual(notices.palette().color(role.Text).name(), colors["muted"])
                return 0

            with patch.object(W.QDialog, "exec", inspect_dialog):
                window.show_about()
                show_licenses(window, window.tr_text)
            for control in (window.about_button, window.licenses_button):
                control.ensurePolished()
                self.assertEqual(control.palette().color(role.Button).name(), window.colors["panel"])
                self.assertEqual(control.palette().color(role.ButtonText).name(), window.colors["text"])

    def test_language_switch_preserves_pending_settings_and_trigger_selection(self):
        self.connect_demo()
        window = self.window
        window.rate.setValue(100)
        window.trigger_mode.setCurrentIndex(window.trigger_mode.findData("Single"))
        window.edge.setCurrentIndex(window.edge.findData("Falling"))
        window.single_armed = False
        for language, title in (("en", "Single"), ("pt", "Único"), ("en", "Single")):
            window.set_language(language)
            self.assertEqual(window.rate.value(), 100)
            self.assertTrue(window.configuration_dirty())
            self.assertEqual(window.trigger_mode.currentData(), "Single")
            self.assertEqual(window.trigger_mode.currentText(), title)
            self.assertEqual(window.edge.currentData(), "Falling")
            self.assertFalse(window.single_armed)

    def test_language_switch_preserves_frozen_trace_and_active_capture(self):
        self.connect_demo()
        window = self.window
        window.start_acquisition()
        self.wait_for(lambda: window.running and window.display is not None)
        window.freeze.setChecked(True)
        trace = window.curve.getData()[1].copy()
        session = window.session_meta.copy()
        capture = Path(self.folder.name) / "capture.csv"
        window.worker.capture(str(capture), window.shunt_session)
        self.wait_for(lambda: window.capture_active)
        for language in ("en", "pt", "en"):
            window.set_language(language)
            self.app.processEvents()
            self.assertTrue(window.running)
            self.assertTrue(window.paused)
            self.assertTrue(window.capture_active)
            self.assertEqual(window.session_meta, session)
            np.testing.assert_array_equal(window.curve.getData()[1], trace)
        window.worker.stop_capture()
        self.wait_for(lambda: not window.capture_active)
        self.assertTrue(capture.is_file())

    def test_about_contains_version_author_and_repository(self):
        details = []

        def inspect_dialog(dialog):
            details.append("\n".join(label.text() for label in dialog.findChildren(W.QLabel)))
            return 0

        with patch.object(W.QDialog, "exec", inspect_dialog):
            self.window.show_about()
        self.assertIn(__version__, details[0])
        self.assertIn("Criado por: Wenderson Oliveira", details[0])
        self.assertIn(PROJECT_URL, details[0])

    def test_license_dialog_accepts_current_language(self):
        with patch.object(W.QDialog, "exec", return_value=0):
            self.window.licenses_button.click()
            self.app.processEvents()
        dialogs = self.window.findChildren(W.QDialog)
        self.assertTrue(any(dialog.windowTitle() == "Licenças e avisos de terceiros" for dialog in dialogs))


if __name__ == "__main__":
    unittest.main()

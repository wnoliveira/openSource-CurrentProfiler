"""Translate the instrument in place and show project information."""

from pathlib import Path
import sys

from PySide6 import QtCore, QtWidgets as W

from . import AUTHOR, PROJECT_URL, __version__
from .i18n import Translator, system_language
from .licensing import show_licenses


class LocalizedWindow:
    def tr_text(self, source, **values):
        return self.translator.text(source, **values)

    def initialize_language_controls(self):
        self.language_label = W.QLabel("Language")
        self.language_choice = W.QComboBox()
        self.language_choice.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.language_choice.setSizePolicy(W.QSizePolicy.Policy.Minimum, W.QSizePolicy.Policy.Fixed)
        self.language_choice.setMinimumWidth(180)
        for title, value in (("System default", "system"), ("English", "en"), ("Português", "pt")):
            self.language_choice.addItem(title, value)
        self.statusBar().addPermanentWidget(self.language_label)
        self.statusBar().addPermanentWidget(self.language_choice)
        self.language_choice.currentIndexChanged.connect(
            lambda: self.set_language(self.language_choice.currentData())
        )

        self.about_button = W.QToolButton(self)
        self.about_button.setText("About")
        self.about_button.clicked.connect(self.show_about)
        self.statusBar().addPermanentWidget(self.about_button)
        self.licenses_button = W.QToolButton(self)
        self.licenses_button.setText("Licenses")
        self.licenses_button.clicked.connect(lambda: show_licenses(self, self.tr_text))
        self.statusBar().addPermanentWidget(self.licenses_button)

        # Remember English source strings only once. Translating a translation
        # would make the second language switch lose its original catalog key.
        self.ui_text = []
        for widget in self.findChildren(W.QWidget):
            if isinstance(widget, (W.QLabel, W.QAbstractButton)) and widget.text():
                self.ui_text.append((widget, "text", widget.text()))
            if widget.toolTip():
                self.ui_text.append((widget, "tooltip", widget.toolTip()))
        self.tab_titles = [self.inspector.tabText(index) for index in range(self.inspector.count())]
        self.set_language(self.settings.value("language", "system"), persist=False)

    def set_language(self, preference, persist=True):
        """Leave all sample buffers, trigger state and device settings in place."""
        if preference not in ("system", "en", "pt"):
            preference = "system"
        language = system_language() if preference == "system" else preference
        self.translator = Translator(language)
        self.translate_standard_dialogs(language)
        if persist:
            self.settings.setValue("language", preference)
        self.setWindowTitle(self.tr_text("Current Scope — Current measurement"))
        for widget, kind, source in self.ui_text:
            if kind == "text":
                widget.setText(self.tr_text(source))
            else:
                text, separator, shortcut = source.rpartition(" (")
                translated = self.tr_text(text) + " (" + shortcut if separator else self.tr_text(source)
                widget.setToolTip(translated)
        for index, title in enumerate(self.tab_titles):
            self.inspector.setTabText(index, self.tr_text(title))

        # Item data is a language-independent identifier. Block text-change
        # signals because changing a label must not rearm a single trigger.
        for combo in (self.trigger_mode, self.edge):
            with QtCore.QSignalBlocker(combo):
                for index in range(combo.count()):
                    combo.setItemText(index, self.tr_text(combo.itemData(index)))
        with QtCore.QSignalBlocker(self.average):
            self.average.setItemText(0, self.tr_text("Automatic"))
            for index in range(1, self.average.count()):
                count = self.average.itemData(index)
                source = "{count} conversion" if count == 1 else "{count} conversions"
                self.average.setItemText(index, self.tr_text(source, count=count))
        with QtCore.QSignalBlocker(self.language_choice):
            self.language_choice.setItemText(0, self.tr_text("System default"))
            self.language_choice.setCurrentIndex(self.language_choice.findData(preference))
        demo_index = self.port.findData("DEMO")
        if demo_index >= 0:
            self.port.setItemText(demo_index, self.tr_text("Demonstration (no hardware)"))

        self.connect_button.setText(self.tr_text("Disconnect" if self.worker else "Connect"))
        self.freeze.setText(self.tr_text("Resume display" if self.paused else "Pause display"))
        self.toggle_diagnostics(self.details_button.isChecked())
        self.update_trigger_controls()
        self.update_calibration_text()
        self.preview_plan()
        self.update_controls()
        self.update_axes()
        if self.last_statistics is not None:
            self.on_stats(self.last_statistics)
        if self.capture_result and not self.capture_active:
            self.capture_label.setText(self.tr_text("CSV saved · {rows} samples\n{path}", **self.capture_result))
        if self.worker:
            if self.meta:
                address = self.meta.get("address", -1)
                sensor = f"0x{address:02X}" if address >= 0 else self.tr_text("not found")
                self.connection_label.setText(f"{self.worker.port} · INA219 {sensor}")
            else:
                self.connection_label.setText(self.tr_text("{port} · waiting for firmware", port=self.worker.port))
        else:
            self.connection_label.setText(self.tr_text("Disconnected"))
        if self.display:
            self.view_label.setText(self.tr_text("{points} points · {window:.3g} ms window",
                points=len(self.display["records"]), window=self.timebase.value() * 10))
        self.trigger_label.setText(self.tr_text(getattr(self, "trigger_status", "Auto")))
        message = ("Acquisition active. F6: stop · F7: pause display." if self.running else
                   "Connect the ESP32 or select Demonstration to work without hardware.")
        self.statusBar().showMessage(self.tr_text(message))

    def translate_standard_dialogs(self, language):
        """Use Qt's translation for standard buttons such as Yes, No and Cancel."""
        application = W.QApplication.instance()
        previous = getattr(application, "current_scope_qt_translation", None)
        if previous is not None:
            application.removeTranslator(previous)
        application.current_scope_qt_translation = None
        if language == "pt":
            if getattr(sys, "frozen", False):
                folder = Path(sys._MEIPASS) / "translations"
            else:
                folder = Path(QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath))
            translation = QtCore.QTranslator(application)
            if translation.load(str(folder / "qtbase_pt_BR.qm")):
                application.installTranslator(translation)
                application.current_scope_qt_translation = translation

    def update_calibration_text(self):
        state = "Zero calibrated in this range" if self.meta.get("calibrated") else "Zero not yet calibrated in this range"
        self.cal_label.setText(self.tr_text("Zero: {zero:.4f} counts | factor: {gain:.6f}\n{state}",
            zero=self.meta.get("zero_raw", 0), gain=self.meta.get("gain", 1), state=self.tr_text(state)))

    def show_about(self):
        dialog = W.QDialog(self)
        dialog.setPalette(self.palette())
        dialog.setWindowTitle(self.tr_text("About Current Scope"))
        dialog.setMinimumWidth(380)
        layout = W.QVBoxLayout(dialog)
        details = W.QLabel(
            "<h2>Current Scope</h2>"
            f"<p>{self.tr_text('Version {version}', version=__version__)}<br>"
            f"{self.tr_text('In development')}</p>"
            f"<p>{self.tr_text('Created by: {author}', author=AUTHOR)}</p>"
            f'<p><a href="{PROJECT_URL}" style="color:{self.colors["trace"]}">'
            f'{self.tr_text("Project on GitHub")}</a></p>'
        )
        details.setPalette(self.palette())
        details.setOpenExternalLinks(True)
        details.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(details)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Close)
        buttons.button(W.QDialogButtonBox.StandardButton.Close).setText(self.tr_text("Close"))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

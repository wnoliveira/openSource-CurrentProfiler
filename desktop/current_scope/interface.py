"""Instrument layout, input controls and light/dark palettes."""
import math
import os
from pathlib import Path
from string import Template
import sys

from PySide6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg

from .protocol import BAUD


PALETTES = {
    "light": dict(
        window="#f1f2f4", panel="#ffffff", field="#ffffff", soft="#f5f6f8",
        text="#262a30", muted="#686e78", disabled="#9399a2", border="#d5d8de",
        accent="#3b5f94", accent_hover="#304f7b", selection="#e9eef6",
        plot="#ffffff", grid="#a7afb9", trace="#365f9d", trigger="#9b7542",
        warning="#986024", warning_bg="#fbf3e7", success="#42684f",
    ),
    "dark": dict(
        window="#202124", panel="#292b2f", field="#24262a", soft="#303338",
        text="#e1e3e7", muted="#a2a7b0", disabled="#767c86", border="#454950",
        accent="#5579ad", accent_hover="#6387bb", selection="#36455c",
        plot="#24262a", grid="#737b87", trace="#91acd2", trigger="#c6a06a",
        warning="#d6b17d", warning_bg="#41382d", success="#a2bcaa",
    ),
}

STYLE = Template("""
QWidget { color:$text; font-family:'Segoe UI'; font-size:12px; }
QMainWindow, QDialog, QWidget#workspace { background:$window; }
QFrame#panel, QFrame#connectionBar, QFrame#metrics { background:$panel; border:1px solid $border; border-radius:5px; }
QFrame#separator { background:$border; border:0; }
QLabel { background:transparent; border:0; }
QLabel#title { font-size:20px; font-weight:600; }
QLabel#subtitle, QLabel#hint, QLabel#fieldLabel { color:$muted; }
QLabel#sectionTitle { font-size:13px; font-weight:600; }
QLabel#metric { font-size:25px; font-weight:500; font-family:'Segoe UI'; }
QLabel#badge { background:$soft; color:$muted; border:1px solid $border; border-radius:4px; padding:5px 9px; }
QLabel#badge[state='running'] { color:$success; }
QLabel#configHint { color:$muted; }
QLabel#configHint[dirty='true'] { color:$warning; }
QLabel#captureStatus { color:$muted; }
QLabel#captureStatus[active='true'] { color:$warning; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background:$field; border:1px solid $border; border-radius:4px;
    padding:4px 8px; min-height:22px; selection-background-color:$accent; selection-color:white;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus { border-color:$accent; }
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled { color:$disabled; background:$soft; }
QComboBox { padding-right:26px; }
QComboBox::drop-down { width:24px; border:0; }
QComboBox::down-arrow { image:url('$down_arrow'); width:12px; height:8px; }
QComboBox QAbstractItemView { background:$panel; color:$text; border:1px solid $border; selection-background-color:$selection; selection-color:$text; outline:0; padding:4px; }
QComboBox QAbstractItemView::item { min-height:28px; padding-left:6px; }
QSpinBox, QDoubleSpinBox { padding-right:26px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin:border; subcontrol-position:top right; width:23px; border-left:1px solid $border; border-top-right-radius:4px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin:border; subcontrol-position:bottom right; width:23px; border-left:1px solid $border; border-bottom-right-radius:4px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image:url('$up_arrow'); width:10px; height:7px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image:url('$down_arrow'); width:10px; height:7px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background:$selection; }
QPushButton { background:$panel; border:1px solid $border; border-radius:4px; padding:6px 12px; min-height:18px; }
QPushButton:hover { background:$soft; border-color:$muted; }
QPushButton:pressed { background:$selection; }
QPushButton:focus { border-color:$accent; }
QPushButton:checked { background:$selection; border-color:$accent; color:$text; }
QPushButton:disabled { color:$disabled; background:$soft; border-color:$border; }
QToolButton { background:$panel; color:$text; border:1px solid $border; border-radius:4px; padding:4px 10px; }
QToolButton:hover { background:$soft; border-color:$muted; }
QToolButton:pressed { background:$selection; }
QToolButton:focus { border-color:$accent; }
QPushButton#start { background:$accent; border-color:$accent; color:white; font-weight:600; }
QPushButton#start:hover { background:$accent_hover; }
QPushButton#start:disabled { background:$soft; border-color:$border; color:$disabled; }
QPushButton#themeButton { min-height:16px; padding:4px 11px; }
QPushButton#detailsButton { border:0; background:transparent; padding:3px 2px; color:$muted; }
QPushButton#detailsButton:checked { color:$text; }
QTabWidget::pane { background:$panel; border:1px solid $border; border-radius:5px; top:-1px; }
QTabBar::tab { background:transparent; color:$muted; padding:11px 9px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:$text; border-bottom-color:$accent; font-weight:600; }
QTabBar::tab:hover { color:$text; }
QWidget#tabPage { background:$panel; border-bottom-left-radius:5px; border-bottom-right-radius:5px; }
QPlainTextEdit { background:$field; color:$muted; border:1px solid $border; border-radius:4px; padding:5px; font-family:Consolas; font-size:11px; }
QStatusBar { color:$muted; background:$window; border-top:1px solid $border; }
QStatusBar::item { border:0; }
QSplitter::handle { background:transparent; }
QToolTip { background:$panel; color:$text; border:1px solid $border; padding:6px; }
""")


class Choice(W.QComboBox):
    """Wheel gestures never change an instrument setting accidentally."""

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMaxVisibleItems(16)
        self.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(5)
        self.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(70)
        self.setView(W.QListView())
        self.view().setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def wheelEvent(self, event):
        event.ignore()


class IntegerInput(W.QSpinBox):
    def __init__(self):
        super().__init__()
        self.setKeyboardTracking(False)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(120)

    def wheelEvent(self, event):
        event.ignore()


class NumberInput(W.QDoubleSpinBox):
    def __init__(self, low, high, value, decimals=3, suffix="", engineering=False):
        super().__init__()
        self.engineering = engineering
        self.setDecimals(decimals)
        self.setRange(low, high)
        self.setValue(value)
        self.setSuffix(suffix)
        self.setKeyboardTracking(False)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(120)
        self.setStepType(W.QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
        self.setToolTip('Type a value or use the arrows to adjust.' +
                        (' Steps of 1, 2 and 5 per decade.' if engineering else ""))

    def textFromValue(self, value):
        text = self.locale().toString(value, "f", self.decimals())
        if self.decimals():
            text = text.rstrip("0").rstrip(self.locale().decimalPoint())
        return text

    def wheelEvent(self, event):
        event.ignore()

    def stepBy(self, steps):
        if not self.engineering:
            return super().stepBy(steps)
        value = self.value()
        for _ in range(abs(steps)):
            decade = math.floor(math.log10(max(value, self.minimum(), 1e-12)))
            choices = sorted(n * 10. ** exponent
                             for exponent in range(decade - 1, decade + 3) for n in (1, 2, 5))
            if steps > 0:
                value = next((n for n in choices if n > value * (1 + 1e-9)), self.maximum())
            else:
                value = next((n for n in reversed(choices) if n < value * (1 - 1e-9)), self.minimum())
            value = min(self.maximum(), max(self.minimum(), value))
        self.setValue(value)


def label(text, role="hint", wrap=False):
    widget = W.QLabel(text)
    widget.setObjectName(role)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setMinimumWidth(0)
        widget.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Preferred)
    return widget


def button(text, tooltip="", shortcut=None):
    widget = W.QPushButton(text)
    widget.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    if shortcut:
        widget.setShortcut(QtGui.QKeySequence(shortcut))
        tooltip = f"{tooltip} ({shortcut})"
    widget.setToolTip(tooltip)
    return widget


def separator(vertical=False):
    widget = W.QFrame()
    widget.setObjectName("separator")
    if vertical:
        widget.setFixedWidth(1)
    else:
        widget.setFixedHeight(1)
    return widget


class InstrumentInterface:
    def build_ui(self):
        # Windows' offscreen Qt backend may discover no system fonts. Register
        # the existing Windows fonts for readable test captures and exports.
        # Normal desktop sessions use Qt's own system font discovery.
        if sys.platform == "win32" and QtGui.QGuiApplication.platformName() == "offscreen":
            if not QtGui.QFontDatabase.families():
                fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
                for filename in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
                    QtGui.QFontDatabase.addApplicationFont(str(fonts / filename))
        self.theme = "dark"
        central = W.QWidget()
        central.setObjectName("workspace")
        self.setCentralWidget(central)
        root = W.QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 8)
        root.setSpacing(12)

        header = W.QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(label("Current Scope", "title"))
        header.addWidget(label('Current measurement', "subtitle"))
        header.addStretch()
        self.badge = label('Disconnected', "badge")
        header.addWidget(self.badge)
        header.addSpacing(12)
        header.addWidget(label('Theme'))
        themes = W.QHBoxLayout()
        themes.setSpacing(4)
        self.theme_buttons = W.QButtonGroup(self)
        self.theme_buttons.setExclusive(True)
        self.light_button = button('Light', 'Use light theme')
        self.dark_button = button('Dark', 'Use dark theme')
        for theme, control in (("light", self.light_button), ("dark", self.dark_button)):
            control.setObjectName("themeButton")
            control.setCheckable(True)
            self.theme_buttons.addButton(control)
            control.clicked.connect(lambda checked=False, name=theme: self.apply_theme(name))
            themes.addWidget(control)
        header.addLayout(themes)
        root.addLayout(header)

        connection = W.QFrame()
        connection.setObjectName("connectionBar")
        row = W.QHBoxLayout(connection)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(8)
        row.addWidget(label('Device', "fieldLabel"))
        self.port = Choice()
        self.port.setMinimumWidth(225)
        self.port.setMaximumWidth(300)
        self.port.setToolTip('ESP32 serial port or demonstration source')
        self.refresh = button('Refresh', 'Find serial ports')
        self.connect_button = button('Connect', 'Open or close the serial connection')
        row.addWidget(self.port, 1)
        row.addWidget(self.refresh)
        row.addWidget(self.connect_button)
        row.addSpacing(8)
        row.addWidget(separator(True))
        row.addSpacing(8)
        self.start = button('Start', 'Start acquisition', "F5")
        self.start.setObjectName("start")
        self.stop = button('Stop', 'Stop acquisition and close the disk capture', "F6")
        self.freeze = button('Pause display', 'Pause the display; acquisition and recording continue', "F7")
        self.freeze.setCheckable(True)
        self.freeze.setMinimumWidth(105)
        for control in (self.start, self.stop, self.freeze):
            row.addWidget(control)
        row.addSpacing(12)
        self.connection_label = label('Select a device')
        self.connection_label.setMinimumWidth(0)
        self.connection_label.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Preferred)
        row.addWidget(self.connection_label, 1)
        root.addWidget(connection)

        body = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(12)
        root.addWidget(body, 1)
        workspace = W.QWidget()
        workspace_layout = W.QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(12)
        body.addWidget(workspace)

        metrics = W.QFrame()
        metrics.setObjectName("metrics")
        metrics_layout = W.QHBoxLayout(metrics)
        metrics_layout.setContentsMargins(16, 13, 16, 13)
        metrics_layout.setSpacing(16)
        self.metrics = []
        for i, caption in enumerate(('Current', 'Mean · 1 s', 'Standard deviation · 1 s', 'Observed rate')):
            if i:
                metrics_layout.addWidget(separator(True))
            col = W.QVBoxLayout()
            col.setSpacing(4)
            value = label("—", "metric")
            col.addWidget(label(caption))
            col.addWidget(value)
            metrics_layout.addLayout(col, 1)
            self.metrics.append(value)
        workspace_layout.addWidget(metrics)

        chart = W.QFrame()
        chart.setObjectName("panel")
        chart_layout = W.QVBoxLayout(chart)
        chart_layout.setContentsMargins(12, 10, 12, 10)
        chart_layout.setSpacing(8)
        chart_heading = W.QHBoxLayout()
        chart_heading.addWidget(label('Shunt current', "sectionTitle"))
        self.source_label = label('Waiting for acquisition')
        chart_heading.addWidget(self.source_label)
        chart_heading.addStretch()
        self.auto_y = button('Fit scale', 'Fit scale and center to the displayed signal', "Ctrl+0")
        chart_heading.addWidget(self.auto_y)
        chart_layout.addLayout(chart_heading)
        pg.setConfigOptions(antialias=False)
        self.plot = pg.PlotWidget()
        self.plot.setMinimumSize(360, 220)
        self.plot.showGrid(x=True, y=True, alpha=.2)
        self.plot.setLabel("bottom", 'Time', units="s")
        self.plot.setLabel("left", 'Current', units="mA")
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.setMenuEnabled(False)
        self.curve = self.plot.plot(connect="finite")
        self.trigger_line = pg.InfiniteLine(angle=0, movable=True)
        self.trigger_line.setToolTip('Drag to adjust the trigger level')
        self.trigger_x = pg.InfiniteLine(angle=90)
        self.plot.addItem(self.trigger_line)
        self.plot.addItem(self.trigger_x)
        chart_layout.addWidget(self.plot, 1)
        chart_footer = W.QHBoxLayout()
        self.trigger_label = label("Auto")
        self.view_label = label('Waiting for samples')
        chart_footer.addWidget(self.trigger_label)
        chart_footer.addStretch()
        chart_footer.addWidget(self.view_label)
        chart_layout.addLayout(chart_footer)
        workspace_layout.addWidget(chart, 1)

        self.inspector = W.QTabWidget()
        self.inspector.setMinimumWidth(350)
        self.inspector.setMaximumWidth(410)
        self.inspector.setUsesScrollButtons(False)
        self.inspector.tabBar().setExpanding(True)
        body.addWidget(self.inspector)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        body.setSizes([1000, 360])
        self.build_acquisition_page()
        self.build_display_page()
        self.build_calibration_page()
        self.build_files_page()

        footer = W.QHBoxLayout()
        self.details_button = button('Diagnostics ▸', 'Show device counters and event log')
        self.details_button.setObjectName("detailsButton")
        self.details_button.setCheckable(True)
        self.summary_label = label('No samples received')
        self.recording_label = label("", "captureStatus")
        footer.addWidget(self.details_button)
        footer.addSpacing(8)
        footer.addWidget(self.summary_label)
        footer.addStretch()
        footer.addWidget(self.recording_label)
        root.addLayout(footer)
        self.diagnostics = W.QWidget()
        diagnostics_layout = W.QVBoxLayout(self.diagnostics)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        diagnostics_layout.setSpacing(6)
        self.stats_label = label('Received: 0 | Lost: 0 | CRC: 0', wrap=True)
        diagnostics_layout.addWidget(self.stats_label)
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(100)
        self.log.setFixedHeight(76)
        diagnostics_layout.addWidget(self.log)
        self.diagnostics.hide()
        workspace_layout.addWidget(self.diagnostics)
        self.details_button.toggled.connect(self.toggle_diagnostics)
        self.statusBar().setSizeGripEnabled(True)
        self.statusBar().showMessage('Connect the ESP32 or select Demonstration to work without hardware.')

        self.refresh.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.start.clicked.connect(self.start_acquisition)
        self.stop.clicked.connect(lambda: self.send_commands(["STOP"]))
        self.freeze.toggled.connect(self.set_paused)
        self.auto_y.clicked.connect(self.autoscale)
        self.arm.clicked.connect(self.rearm)
        self.trigger_mode.currentTextChanged.connect(self.rearm)
        self.trigger_mode.currentTextChanged.connect(self.update_trigger_controls)
        self.unit.currentIndexChanged.connect(self.unit_changed)
        for control in (self.timebase, self.yscale, self.yoffset, self.threshold):
            control.valueChanged.connect(self.update_axes)
        self.pretrigger.valueChanged.connect(self.update_axes)
        self.update_axes()
        self.preview_plan()
        self.update_trigger_controls()
        self.apply_theme(self.settings.value("theme", "dark"))

    def page(self, title, description):
        page = W.QWidget()
        page.setObjectName("tabPage")
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(label(title, "sectionTitle"))
        layout.addWidget(label(description, wrap=True))
        self.inspector.addTab(page, title)
        return layout

    @staticmethod
    def form(layout):
        form = W.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(form)
        return form

    @staticmethod
    def field(form, caption, control):
        form.addRow(label(caption, "fieldLabel"), control)

    def build_acquisition_page(self):
        layout = self.page('Acquisition', 'INA219 sensor · ESP32\nSettings are available while acquisition is stopped.')
        form = self.form(layout)
        self.addr = Choice()
        self.scan_button = button('Scan', 'Find sensors on the I²C bus')
        address = W.QHBoxLayout()
        address.setSpacing(6)
        address.addWidget(self.addr, 1)
        address.addWidget(self.scan_button)
        self.field(form, 'I²C address', address)
        self.pga = Choice()
        for i, mv in enumerate((40, 80, 160, 320)):
            self.pga.addItem(f"±{mv} mV", i)
        self.pga.setCurrentIndex(3)
        self.pga.setToolTip('Shunt voltage range (INA219 PGA)')
        self.rate = IntegerInput()
        self.rate.setRange(1, 1000)
        self.rate.setValue(1000)
        self.rate.setSuffix(" Hz")
        self.average = Choice()
        self.average.addItem('Automatic', 0)
        for n in (1, 2, 4, 8, 16, 32, 64, 128):
            self.average.addItem(f"{n} conversion" if n == 1 else f"{n} conversions", n)
        self.shunt = NumberInput(.000001, 10000, 1., 6, " Ω")
        for caption, control in (('PGA range', self.pga), ('Sample rate', self.rate),
                                 ('Internal averaging', self.average), ("Shunt", self.shunt)):
            self.field(form, caption, control)
        layout.addWidget(separator())
        self.range_label = label("", wrap=True)
        self.plan_label = label("", wrap=True)
        self.plan_label.setToolTip('Lower rates allow more conversions per sample. Averaging can smooth short pulses.')
        layout.addWidget(self.range_label)
        layout.addWidget(self.plan_label)
        layout.addStretch()
        self.config_hint = label('Connect a device to configure it.', "configHint", wrap=True)
        self.apply = button('Apply settings', 'Send settings to the sensor')
        layout.addWidget(self.config_hint)
        layout.addWidget(self.apply)
        layout.addWidget(label(f"Serial: {BAUD} baud · 8N1"))
        self.scan_button.clicked.connect(lambda: self.send_commands(["SCAN"]))
        self.apply.clicked.connect(self.apply_config)
        for control in (self.rate, self.shunt):
            control.valueChanged.connect(self.preview_plan)
        for control in (self.pga, self.average, self.addr):
            control.currentIndexChanged.connect(self.preview_plan)

    def build_display_page(self):
        layout = self.page('Display', 'Display settings are independent of acquisition.')
        form = self.form(layout)
        self.timebase = NumberInput(.1, 6000, 50, 3, " ms/div", engineering=True)
        self.unit = Choice()
        self.unit.addItems(["mA", "µA"])
        self.yscale = NumberInput(.000001, 1e9, 5, 6, " mA/div", engineering=True)
        self.yoffset = NumberInput(-1e12, 1e12, 10, 6, " mA")
        vertical = W.QHBoxLayout()
        vertical.setSpacing(6)
        vertical.addWidget(self.yscale, 1)
        self.unit.setMinimumContentsLength(2)
        self.unit.setFixedWidth(80)
        self.unit.setSizePolicy(W.QSizePolicy.Policy.Fixed, W.QSizePolicy.Policy.Fixed)
        self.unit.setToolTip('Display and trigger current unit')
        vertical.addWidget(self.unit)
        for caption, control in (('Time', self.timebase), ("Vertical", vertical), ('Center', self.yoffset)):
            self.field(form, caption, control)
        layout.addWidget(label('Grid: 10 horizontal × 8 vertical divisions.', wrap=True))
        layout.addWidget(separator())
        layout.addWidget(label('Trigger', "sectionTitle"))
        trigger = self.form(layout)
        self.trigger_mode = Choice()
        for mode in ("Auto", "Normal", "Free", "Single"):
            self.trigger_mode.addItem(mode, mode)
        self.edge = Choice()
        for edge in ("Rising", "Falling"):
            self.edge.addItem(edge, edge)
        self.threshold = NumberInput(-1e12, 1e12, 10, 6, " mA")
        self.pretrigger = IntegerInput()
        self.pretrigger.setRange(0, 90)
        self.pretrigger.setValue(30)
        self.pretrigger.setSingleStep(5)
        self.pretrigger.setSuffix(" %")
        mode = W.QHBoxLayout()
        mode.setSpacing(6)
        mode.addWidget(self.trigger_mode, 1)
        mode.addWidget(self.edge, 1)
        self.edge.setToolTip('Trigger edge: rising or falling')
        for caption, control in (('Mode / edge', mode), ('Level', self.threshold), ('Pre-trigger', self.pretrigger)):
            self.field(trigger, caption, control)
        self.arm = button('Rearm trigger', 'Wait for a new edge in Single mode')
        layout.addWidget(self.arm)
        self.trigger_hint = label("", wrap=True)
        layout.addWidget(self.trigger_hint)
        layout.addStretch()

    def build_calibration_page(self):
        layout = self.page('Calibration', 'Coefficients are saved on the ESP32 for each PGA range.')
        self.cal_label = label('Zero: 0 counts | factor: 1', wrap=True)
        layout.addWidget(self.cal_label)
        layout.addWidget(separator())
        layout.addWidget(label('1. Zero adjustment', "sectionTitle"))
        layout.addWidget(label('Remove the load and keep the INA219 powered.', wrap=True))
        self.zero = button('Calibrate zero', 'Measure the no-load offset in the current range')
        layout.addWidget(self.zero)
        layout.addWidget(separator())
        layout.addWidget(label('2. Gain adjustment', "sectionTitle"))
        layout.addWidget(label('Apply a known, stable current. Check the shunt value before continuing.', wrap=True))
        form = self.form(layout)
        self.reference = NumberInput(-100000, 100000, 10, 6, " mA")
        self.field(form, 'Reference', self.reference)
        self.gain_button = button('Calibrate gain', 'Use the reference current to correct the gain')
        layout.addWidget(self.gain_button)
        layout.addStretch()
        self.reset_cal = button('Reset range calibration', 'Remove zero and gain corrections for the current range')
        layout.addWidget(self.reset_cal)
        self.zero.clicked.connect(self.calibrate_zero)
        self.gain_button.clicked.connect(self.calibrate_gain)
        self.reset_cal.clicked.connect(self.reset_calibration)

    def build_files_page(self):
        layout = self.page('Files', 'Record the entire session or export the displayed plot window.')
        layout.addWidget(label('Continuous capture', "sectionTitle"))
        layout.addWidget(label('Save every received sample to CSV, even while the display is paused.', wrap=True))
        self.capture_start = button('Start CSV capture…', 'Choose a file and start continuous recording')
        self.capture_stop = button('Finish capture', 'Close the session CSV file')
        self.capture_label = label('No active capture', "captureStatus", wrap=True)
        layout.addWidget(self.capture_start)
        layout.addWidget(self.capture_stop)
        layout.addWidget(self.capture_label)
        layout.addWidget(separator())
        layout.addWidget(label('Displayed window', "sectionTitle"))
        layout.addWidget(label('Pause the display to choose a section before exporting.', wrap=True))
        self.export_csv = button('Export points to CSV…', 'Save samples from the displayed window')
        self.export_png = button('Export plot to PNG…', 'Save the plot image in the current theme')
        layout.addWidget(self.export_csv)
        layout.addWidget(self.export_png)
        layout.addStretch()
        layout.addWidget(label('Each CSV includes a JSON file with measurement metadata.', wrap=True))
        self.capture_start.clicked.connect(self.begin_capture)
        self.capture_stop.clicked.connect(lambda: self.worker and self.worker.stop_capture())
        self.export_csv.clicked.connect(self.export_scope_csv)
        self.export_png.clicked.connect(self.export_scope_png)

    def apply_theme(self, name):
        self.theme = name if name in PALETTES else "dark"
        self.colors = PALETTES[self.theme]
        colors = self.colors
        palette = QtGui.QPalette()
        for role, color in (("Window", "window"), ("WindowText", "text"), ("Base", "field"),
                            ("AlternateBase", "soft"), ("Text", "text"), ("Button", "panel"),
                            ("ButtonText", "text"), ("Highlight", "accent"), ("PlaceholderText", "muted"),
                            ("ToolTipBase", "panel"), ("ToolTipText", "text"),
                            ("Link", "trace"), ("LinkVisited", "trigger")):
            palette.setColor(getattr(QtGui.QPalette.ColorRole, role), QtGui.QColor(colors[color]))
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("white"))
        palette.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text, QtGui.QColor(colors["disabled"]))
        palette.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(colors["disabled"]))
        assets = Path(__file__).parent / "assets"
        self.setStyleSheet(STYLE.substitute(colors, down_arrow=(assets / "arrow-down.svg").as_posix(),
                                           up_arrow=(assets / "arrow-up.svg").as_posix()))
        self.setPalette(palette)
        self.light_button.setChecked(self.theme == "light")
        self.dark_button.setChecked(self.theme == "dark")
        self.plot.setBackground(colors["plot"])
        for side in ("left", "bottom"):
            axis = self.plot.getAxis(side)
            axis.setPen(pg.mkPen(colors["grid"]))
            axis.setTextPen(pg.mkPen(colors["muted"]))
            axis.setTickFont(QtGui.QFont("Segoe UI", 9))
            axis.setStyle(tickLength=-4)
        self.update_axes()
        self.curve.setPen(pg.mkPen(colors["trace"], width=1.5))
        self.trigger_line.setPen(pg.mkPen(colors["trigger"], width=1, style=QtCore.Qt.PenStyle.DashLine))
        self.trigger_line.setHoverPen(pg.mkPen(colors["trigger"], width=2))
        self.trigger_x.setPen(pg.mkPen(colors["grid"], style=QtCore.Qt.PenStyle.DotLine))
        self.update_trace_caption()
        self.settings.setValue("theme", self.theme)

    @staticmethod
    def state_property(widget, name, value):
        if widget.property(name) != value:
            widget.setProperty(name, value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def toggle_diagnostics(self, checked):
        self.diagnostics.setVisible(checked)
        self.details_button.setText(self.tr_text('Diagnostics ▾' if checked else 'Diagnostics ▸'))

    def update_trigger_controls(self, *args):
        mode = self.trigger_mode.currentData()
        for control in (self.edge, self.threshold, self.pretrigger):
            control.setEnabled(mode != 'Free')
        self.arm.setEnabled(mode == 'Single')
        self.trigger_line.setVisible(mode != 'Free')
        self.trigger_x.setVisible(mode != 'Free')
        descriptions = {
            "Auto": 'Updates continuously when no edge is found.',
            "Normal": 'Updates only when an edge crosses the chosen level.',
            'Free': 'Shows the latest samples without waiting for a trigger.',
            'Single': 'Captures one edge and pauses the display. Rearm to repeat.',
        }
        self.trigger_hint.setText(self.tr_text(descriptions[mode]))

    def update_trace_caption(self, clipping=None):
        if clipping is None:
            clipping = bool(self.display and any(s.flags & 1 for s in self.display["records"]))
        demo = bool(self.worker and self.worker.port == "DEMO") or self.display_meta.get("demo", False)
        source = 'Demonstration · simulated signal' if demo else (
            "INA219" if self.connected or self.display else 'Waiting for acquisition')
        self.source_label.setText(self.tr_text(source))
        self.plot.setTitle(self.tr_text("PGA range limit reached") if clipping else "",
                           color=self.colors["warning"] if clipping else self.colors["muted"], size="10pt")

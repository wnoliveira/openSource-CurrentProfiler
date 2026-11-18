"""Desktop oscilloscope for the ESP32/INA219 current profiler.

The window owns display settings and a bounded history for triggering. Serial
I/O and continuous disk capture belong to SerialWorker, so pausing the plot
does not pause measurement or recording.
"""

from collections import deque
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg
import pyqtgraph.exporters
import serial.tools.list_ports

from . import __version__
from .i18n import Translator
from .interface import InstrumentInterface
from .localization import LocalizedWindow
from .preferences import WindowPreferences
from .processing import scope_frame
from .protocol import MASK32, current_amp, planning
from .trigger_interaction import TriggerInteraction
from .worker import CSV_FIELDS, SerialWorker, csv_row


class MainWindow(LocalizedWindow, WindowPreferences, TriggerInteraction,
                 InstrumentInterface, W.QMainWindow):
    """Coordinate acknowledged device state, measurement history and display."""

    def __init__(self, demo=False):
        super().__init__()
        # Build from English text once, then apply the saved or system language.
        self.translator = Translator("en")
        self.setWindowTitle(self.tr_text("Current Scope — Current measurement"))
        self.setMinimumSize(1140, 720)
        available = self.screen().availableGeometry()
        self.resize(min(1460, available.width()), min(900, available.height()))
        self.settings = QtCore.QSettings("OpenInstrumentation", "IoTCurrentScope")

        self.worker = None
        self.connected = False
        self.running = False
        self.pending = 0
        self.busy_since = 0.0
        self.meta = {}

        # Session calibration is separate from editable device settings.
        # A zero calibration after STOP must not change an older trace.
        self.session_meta = {}
        self.records = deque(maxlen=65000)
        self.shunt_session = 1.0
        self.utc_anchor = datetime.now(timezone.utc)
        self.display = None
        self.display_meta = {}
        self.history_seconds = 60.0
        self.last_seq = None
        self.last_batch_time = 0.0

        self.paused = False
        self.single_armed = True
        self.arm_after_time = -1.0
        self.trigger_status = "Auto"
        self.capture_active = False
        self.capture_result = None
        self.last_statistics = None
        self.updating = False

        self.build_ui()
        self.initialize_trigger_interaction()
        self.restore()
        self.refresh_ports()
        self.initialize_language_controls()
        self.fullscreen_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence("F11"), self, activated=self.toggle_fullscreen
        )
        self.exit_fullscreen_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence("Escape"), self, activated=self.exit_fullscreen
        )
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.render)
        self.timer.start(33)
        self.update_controls()
        if demo:
            QtCore.QTimer.singleShot(100, self.connect_demo)

    def restore(self):
        """Restore display preferences; acquisition still starts stopped."""
        self.restore_preferences()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()

    def refresh_ports(self):
        previous_port = self.port.currentData() or self._preferred_port
        self.port.clear()
        for port in serial.tools.list_ports.comports():
            self.port.addItem(f"{port.device} · {port.description}", port.device)
        self.port.addItem(self.tr_text("Demonstration (no hardware)"), "DEMO")
        if previous_port is not None:
            previous_index = self.port.findData(previous_port)
            if previous_index >= 0:
                self.port.setCurrentIndex(previous_index)

    def connect_demo(self):
        self.port.setCurrentIndex(self.port.findData("DEMO"))
        self.toggle_connection()

    def toggle_connection(self):
        """Request a clean close, or start the worker for the selected port."""
        if self.worker:
            self.worker.requestInterruption()
            self.connect_button.setEnabled(False)
            return

        port = self.port.currentData()
        if not port:
            return
        self.worker = SerialWorker(port, self)
        self.worker.connection.connect(self.on_connection)
        self.worker.event.connect(self.on_event)
        self.worker.samples.connect(self.on_samples)
        self.worker.statistics.connect(self.on_stats)
        self.worker.problem.connect(self.on_problem)
        self.worker.finished.connect(self.on_finished)
        self.connect_button.setEnabled(False)
        self.connection_label.setText(self.tr_text("Connecting…"))
        self.worker.start()

    def on_connection(self, state):
        self.connected = state == "connected"
        if self.connected:
            self.connection_label.setText(
                self.tr_text("{port} · waiting for firmware", port=self.worker.port)
            )
            self.connect_button.setText(self.tr_text("Disconnect"))
            self.connect_button.setEnabled(True)
            message = "Connection open. Waiting for the device."
        else:
            self.running = False
            self.pending = 0
            self.capture_active = False
            self.connection_label.setText(self.tr_text("Disconnected"))
            message = "Device disconnected. Select a port to connect."
        self.statusBar().showMessage(self.tr_text(message))
        self.update_controls()

    def on_finished(self):
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        self.connect_button.setText(self.tr_text("Connect"))
        self.connect_button.setEnabled(True)
        self.update_controls()

    def on_problem(self, message):
        message = self.tr_text(message)
        self.pending = 0
        self.log.appendPlainText(self.tr_text("ERROR: {message}", message=message))
        self.statusBar().showMessage(message)
        self.update_controls()
        self.details_button.setChecked(True)

    def send_commands(self, commands):
        """Queue commands and wait for their acknowledgements before editing."""
        if not self.worker or not self.connected or self.pending:
            return
        self.pending = len(commands)
        self.busy_since = time.monotonic()
        for command in commands:
            self.worker.command(command)
        self.update_controls()

    def apply_config(self):
        """Validate the timing plan before asking the firmware to apply it."""
        try:
            planning(self.rate.value(), self.average.currentData())
        except ValueError as exc:
            self.on_problem(str(exc))
            return

        # A previous manual average might not fit the new rate. Clear it first,
        # then restore the requested manual value after changing the rate.
        commands = [
            "SET AVG AUTO",
            f"SET RATE {self.rate.value()}",
            f"SET PGA {self.pga.currentData()}",
        ]
        if self.addr.currentData() is not None:
            commands.append(f"SET ADDR {self.addr.currentData():02X}")
        if self.average.currentData():
            commands.append(f"SET AVG {self.average.currentData()}")
        if self.worker and self.connected and not self.pending:
            self._preserve_sensor_preferences = False
        self.send_commands(commands)

    def start_acquisition(self):
        """Require acknowledged settings before starting a new session."""
        if self.configuration_dirty():
            W.QMessageBox.information(
                self,
                self.tr_text("Pending settings"),
                self.tr_text("Click Apply settings before starting."),
            )
            return
        self.shunt_session = self.shunt.value()
        self.send_commands(["START"])

    def configuration_dirty(self):
        """Compare controls with settings confirmed by the firmware."""
        return any(
            (
                self.rate.value() != self.meta.get("rate_hz"),
                self.pga.currentData() != self.meta.get("pga"),
                self.average.currentData() != self.meta.get("avg_requested"),
                self.addr.currentData() != self.meta.get("address"),
            )
        )

    def reset_calibration(self):
        answer = W.QMessageBox.question(
            self,
            self.tr_text("Reset calibration"),
            self.tr_text("Remove zero and gain corrections for the current PGA range?"),
        )
        if answer == W.QMessageBox.StandardButton.Yes:
            self.send_commands(["CAL RESET"])

    def calibrate_zero(self):
        answer = W.QMessageBox.question(
            self,
            self.tr_text("INA219 zero"),
            self.tr_text(
                "Has the load been removed? Keep the INA219 powered.\n"
                "Calibration takes about 1.2 s."
            ),
        )
        if answer == W.QMessageBox.StandardButton.Yes:
            self.send_commands(["CAL ZERO"])

    def calibrate_gain(self):
        """Convert the external reference current to the voltage used by CAL GAIN."""
        if not self.meta.get("calibrated"):
            W.QMessageBox.information(
                self,
                self.tr_text("Calibration"),
                self.tr_text("Calibrate zero in this range before gain."),
            )
            return

        reference_amperes = self.reference.value() * 1e-3
        reference_volts = reference_amperes * self.shunt.value()
        reference_microvolts = reference_volts * 1e6
        full_scale_microvolts = (40, 80, 160, 320)[self.meta["pga"]] * 1000
        reference_too_small = abs(reference_microvolts) < 200
        reference_near_limit = abs(reference_microvolts) >= full_scale_microvolts * 0.9
        if reference_too_small or reference_near_limit:
            W.QMessageBox.warning(
                self,
                self.tr_text("Invalid reference"),
                self.tr_text(
                    "Use a reference drop of at least 200 µV and below 90% of the PGA range."
                ),
            )
            return

        answer = W.QMessageBox.question(
            self,
            self.tr_text("Gain"),
            self.tr_text(
                "Is the reference current applied and stable?\n"
                "Also check the shunt value."
            ),
        )
        if answer == W.QMessageBox.StandardButton.Yes:
            self.send_commands([f"CAL GAIN {reference_microvolts:.9f}"])

    def on_event(self, event):
        """Apply worker/device events before refreshing the enabled controls."""
        kind = event["type"]
        if kind == "error":
            self.on_problem(event.get("message", "Device error"))
            return

        if kind == "capture_started":
            self.capture_active = True
            self.capture_result = None
            self.capture_label.setText(
                self.tr_text("RECORDING: {path}", path=event["path"])
            )
            self.statusBar().showMessage(
                self.tr_text("Continuous capture in progress: {path}", path=event["path"])
            )
        elif kind == "capture_stopped":
            self.capture_active = False
            self.capture_result = {"rows": event["rows"], "path": event["path"]}
            self.capture_label.setText(
                self.tr_text("CSV saved · {rows} samples\n{path}", **self.capture_result)
            )
            self.statusBar().showMessage(
                self.tr_text("Capture finished: {rows:,} samples saved.", rows=event["rows"])
            )
        elif kind in ("boot", "status", "config", "started", "stopped"):
            if kind in ("config", "started", "stopped") and self.pending:
                self.pending -= 1
            self.meta.update(event)

            if kind == "started":
                self.session_meta = dict(
                    event,
                    software_version=__version__,
                    demo=self.worker is not None and self.worker.port == "DEMO",
                )
                self.running = True
                self.records.clear()
                self.last_seq = None
                self.display = None
                self.curve.setData([], [])
                self.single_armed = True
                self.arm_after_time = -1.0
                self.freeze.setChecked(False)
                self.utc_anchor = datetime.fromisoformat(event["utc_anchor_estimated"])
            if kind == "stopped":
                self.running = False
            if kind in ("status", "boot"):
                self.running = event.get("state") == "RUNNING"
            if not self.pending:
                self.reflect_config()

            address = event.get("address", -1)
            sensor = f"0x{address:02X}" if address >= 0 else self.tr_text("not found")
            self.connection_label.setText(f"{self.worker.port} · INA219 {sensor}")
            message = (
                "Acquisition active. F6: stop · F7: pause display."
                if self.running
                else "Acquisition stopped. Settings and calibration are available."
            )
            self.statusBar().showMessage(self.tr_text(message))
            self.log.appendPlainText(
                self.tr_text(
                    "{kind} · PGA {pga} · {rate} Hz · average {average}",
                    kind=kind.upper(),
                    pga=event.get("pga"),
                    rate=event.get("rate_hz"),
                    average=event.get("averages"),
                )
            )
        elif kind == "calibration":
            self.log.appendPlainText(self.tr_text("Calibration: {event}", event=event))
        self.update_controls()

    def reflect_config(self):
        """Show acknowledged settings without treating them as a user edit."""
        self.updating = True
        self.rate.setValue(self.meta.get("rate_hz", 1000))
        self.pga.setCurrentIndex(self.meta.get("pga", 3))
        average_index = self.average.findData(self.meta.get("avg_requested", 0))
        self.average.setCurrentIndex(max(0, average_index))
        self.addr.clear()
        for address in self.meta.get("candidates", []):
            self.addr.addItem(f"0x{address:02X}", address)
        self.addr.setCurrentIndex(self.addr.findData(self.meta.get("address")))
        self.restore_sensor_preferences()
        self.update_calibration_text()
        self.updating = False
        self.preview_plan()

    def update_controls(self):
        """Keep sensor edits separate from adjustments allowed during RUN."""
        can_edit_sensor = (
            self.connected and bool(self.meta) and not self.running and not self.pending
        )
        sensor_controls = (
            self.addr, self.scan_button, self.pga, self.rate, self.average,
            self.shunt, self.apply, self.zero, self.gain_button, self.reset_cal,
            self.reference,
        )
        for widget in sensor_controls:
            widget.setEnabled(can_edit_sensor)
        self.stop.setEnabled(self.connected and self.running and not self.pending)
        self.port.setEnabled(self.worker is None)
        self.refresh.setEnabled(self.worker is None)
        self.capture_start.setEnabled(self.running and not self.capture_active)
        self.capture_stop.setEnabled(self.capture_active)

        has_display = self.display is not None
        self.export_csv.setEnabled(has_display)
        self.export_png.setEnabled(has_display)
        self.auto_y.setEnabled(has_display)
        self.freeze.setEnabled(self.running or has_display)
        self.sync_config_state()

        if self.running:
            state = "Acquiring"
        elif self.connected and self.meta:
            state = "Ready"
        elif self.worker:
            state = "Connecting"
        else:
            state = "Disconnected"
        translated_state = self.tr_text(state)
        if self.worker and self.worker.port == "DEMO":
            translated_state = self.tr_text(
                "Demonstration · {state}", state=translated_state
            )
        self.badge.setText(translated_state)
        self.state_property(self.badge, "state", "running" if self.running else "idle")
        self.recording_label.setText(
            self.tr_text("Recording CSV") if self.capture_active else ""
        )
        for control in (self.capture_label, self.recording_label):
            self.state_property(control, "active", self.capture_active)
        self.update_trace_caption()

    def sync_config_state(self):
        dirty = bool(self.meta) and self.configuration_dirty()
        valid = True
        try:
            planning(self.rate.value(), self.average.currentData() or 0)
        except ValueError:
            valid = False

        if not self.connected:
            message = "Connect a device to configure it."
        elif self.pending:
            message = "Waiting for device confirmation…"
        elif self.running:
            message = "Stop acquisition to edit the sensor."
        elif not valid:
            message = "Reduce averaging or sample rate."
        elif dirty:
            message = "Pending changes. Apply before starting."
        else:
            message = "Settings applied. Ready to start."
        self.config_hint.setText(self.tr_text(message))
        self.state_property(self.config_hint, "dirty", dirty or not valid)

        can_apply = (
            self.connected
            and bool(self.meta)
            and not self.running
            and not self.pending
            and valid
        )
        sensor_found = self.meta.get("address", -1) >= 0
        self.apply.setEnabled(can_apply)
        self.start.setEnabled(can_apply and sensor_found and not dirty)

    def preview_plan(self):
        """Explain the selected timing and shunt range before applying them."""
        try:
            period_us, average_count = planning(
                self.rate.value(), self.average.currentData() or 0
            )
            self.plan_label.setText(
                self.tr_text(
                    "Period: {period:.3f} ms\n"
                    "Conversions per sample: {count} · 12 bits",
                    period=period_us / 1000,
                    count=average_count,
                )
            )
        except ValueError as exc:
            self.plan_label.setText(self.tr_text(str(exc)))

        shunt_ohm = self.shunt.value()
        pga_index = max(0, self.pga.currentIndex())
        full_scale_volts = (0.04, 0.08, 0.16, 0.32)[pga_index]
        current_limit_amperes = full_scale_volts / shunt_ohm
        microamperes_per_count = 10 / shunt_ohm
        self.range_label.setText(
            self.tr_text(
                "Nominal range: ±{limit:.6g} mA\n"
                "Register scale: {scale:.6g} µA/count",
                limit=current_limit_amperes * 1e3,
                scale=microamperes_per_count,
            )
        )
        if hasattr(self, "config_hint") and not self.updating:
            self.sync_config_state()

    def on_samples(self, batch):
        """Append readings, using None to mark visible sequence gaps."""
        if not batch:
            return

        for sample in batch:
            if self.last_seq is not None:
                sequence_step = (sample.sequence - self.last_seq) & MASK32
                if sequence_step != 1:
                    self.records.append(None)
            self.records.append(sample)
            self.last_seq = sample.sequence

        newest_us = batch[-1].device_us
        cutoff_us = newest_us - int(self.history_seconds * 1e6)
        while self.records:
            oldest = self.records[0]
            if oldest is not None and oldest.device_us >= cutoff_us:
                break
            self.records.popleft()
        self.last_batch_time = time.monotonic()

    def on_stats(self, statistics):
        """Keep a copy so a language change can redraw counters immediately."""
        self.last_statistics = dict(statistics)
        self.summary_label.setText(
            self.tr_text(
                "{received:,} samples  ·  {lost:,} lost  ·  {crc} CRC errors",
                received=statistics.get("received", 0),
                lost=statistics.get("lost", 0),
                crc=statistics.get("crc", 0),
            )
        )
        self.stats_label.setText(
            self.tr_text(
                "I²C: {i2c} errors  ·  Skipped periods: {skipped}  ·  TX queue: {drops}\n"
                "Out of order: {order}  ·  Maximum trigger delay: {late} µs",
                i2c=statistics.get("i2c_errors", 0),
                skipped=statistics.get("skipped", 0),
                drops=statistics.get("tx_drops", 0),
                order=statistics.get("out_of_order", 0),
                late=statistics.get("max_late_us", 0),
            )
        )
        if self.capture_active:
            message = self.tr_text(
                "Recording CSV · {rows:,} samples",
                rows=statistics.get("capture_rows", 0),
            )
            self.capture_label.setText(message)
            self.recording_label.setText(message)

    def set_paused(self, paused):
        self.paused = paused
        self.freeze.setText(
            self.tr_text("Resume display" if paused else "Pause display")
        )
        if not paused:
            message = "Display resumed."
        elif self.running:
            message = "Display paused. Acquisition and disk capture continue."
        else:
            message = "Display paused."
        self.statusBar().showMessage(self.tr_text(message))

    def rearm(self, *args):
        """Require a crossing newer than the latest sample at the time of arming."""
        self.single_armed = True
        self.freeze.setChecked(False)
        latest_sample = next(
            (sample for sample in reversed(self.records) if sample is not None), None
        )
        if latest_sample:
            epoch_us = self.session_meta.get("epoch_us", 0)
            self.arm_after_time = (latest_sample.device_us - epoch_us) / 1e6
        else:
            self.arm_after_time = -1.0

    def unit_changed(self):
        # Stored measurements stay in amperes; only controls and plotting change.
        control_factor = 1000 if self.unit.currentText() == "µA" else 0.001
        for control in (self.yscale, self.yoffset, self.threshold):
            control.setValue(control.value() * control_factor)
        self.update_axes()
        if self.display:
            display_factor = 1e6 if self.unit.currentText() == "µA" else 1e3
            self.curve.setData(
                self.display["x"],
                self.display["amps"] * display_factor,
                connect="finite",
            )

    def update_axes(self, *args):
        span_seconds = self.timebase.value() * 10 / 1000
        current_per_division = self.yscale.value()
        center_current = self.yoffset.value()
        self.plot.setXRange(0, span_seconds, padding=0)
        self.plot.setYRange(
            center_current - 4 * current_per_division,
            center_current + 4 * current_per_division,
            padding=0,
        )

        unit = self.unit.currentText()
        self.yscale.setSuffix(" /div")
        self.yoffset.setSuffix(f" {unit}")
        self.threshold.setSuffix(f" {unit}")
        color = getattr(self, "colors", {}).get("muted", "#686e78")
        self.plot.setLabel("left", self.tr_text("Current"), units=unit, color=color)
        self.plot.setLabel("bottom", self.tr_text("Time"), units="s", color=color)
        self.plot.getAxis("bottom").setTickSpacing(span_seconds / 10, span_seconds / 50)
        self.plot.getAxis("left").setTickSpacing(
            current_per_division, current_per_division / 5
        )
        self.update_trigger_bounds()
        self.trigger_line.setValue(self.threshold.value())
        self.trigger_x.setValue(span_seconds * self.pretrigger.value() / 100)
        self.trigger_x.setVisible(self.trigger_mode.currentData() != "Free")
        if self.display_meta:
            self.display_meta.update(
                unit=unit,
                timebase_ms_div=self.timebase.value(),
                vertical_div=current_per_division,
                center=center_current,
                threshold=self.threshold.value(),
            )

    def arrays(self):
        """Prepare times and amperes, retaining NaN breaks at sequence gaps."""
        records = list(self.records)
        if not records:
            return records, np.array([]), np.array([])

        epoch_us = int(self.session_meta.get("epoch_us", 0))
        zero_raw = self.session_meta.get("zero_raw", 0)
        gain = self.session_meta.get("gain", 1)
        elapsed_times = []
        amperes = []
        previous_time = 0.0
        for sample in records:
            if sample is None:
                elapsed_times.append(previous_time)
                amperes.append(np.nan)
                continue
            previous_time = (sample.device_us - epoch_us) / 1e6
            elapsed_times.append(previous_time)
            amperes.append(
                current_amp(sample.raw, self.shunt_session, zero_raw, gain)
            )
        return records, np.array(elapsed_times), np.array(amperes)

    def render(self):
        """Update metrics, select a trigger window and draw original samples."""
        if self.pending and time.monotonic() - self.busy_since > 6:
            self.on_problem(
                "Command not acknowledged. Check the device before continuing."
            )
        records, elapsed_times, amperes = self.arrays()
        if len(elapsed_times) < 2:
            return

        display_factor = 1e6 if self.unit.currentText() == "µA" else 1e3
        period_seconds = self.session_meta.get("period_us", 1000) / 1e6
        metric_window = max(1.0, 2 * period_seconds)
        valid_metrics = np.isfinite(amperes) & (
            elapsed_times >= elapsed_times[-1] - metric_window
        )
        current_values = amperes[valid_metrics] * display_factor
        if len(current_values):
            metric_values = (
                current_values[-1],
                np.mean(current_values),
                np.std(current_values),
            )
            for label, value in zip(self.metrics[:3], metric_values):
                label.setText(f"{value:.4g} {self.unit.currentText()}")
            metric_times = elapsed_times[valid_metrics]
            if len(metric_times) > 1 and metric_times[-1] > metric_times[0]:
                observed_hz = (len(metric_times) - 1) / (
                    metric_times[-1] - metric_times[0]
                )
                self.metrics[3].setText(f"{observed_hz:.1f} Hz")

        if self.paused:
            return
        mode = self.trigger_mode.currentData()
        if mode == "Single" and not self.single_armed:
            return

        span_seconds = self.timebase.value() * 10 / 1000
        # Search recent history so old crossings do not freeze Auto indefinitely.
        recent_window = max(span_seconds * 3, 2 * period_seconds)
        recent = elapsed_times >= elapsed_times[-1] - recent_window
        result = scope_frame(
            elapsed_times[recent],
            amperes[recent],
            span_seconds,
            "Normal" if mode == "Single" else mode,
            self.threshold.value() / display_factor,
            self.edge.currentData(),
            self.pretrigger.value() / 100,
        )
        if result is None:
            self.trigger_status = "Waiting for edge"
            self.trigger_label.setText(self.tr_text(self.trigger_status))
            return

        relative_times, frame_amperes, window_start, triggered = result
        crossing_time = window_start + span_seconds * self.pretrigger.value() / 100
        if mode == "Single" and crossing_time <= self.arm_after_time:
            self.trigger_status = "Waiting for a new edge"
            self.trigger_label.setText(self.tr_text(self.trigger_status))
            return

        in_window = (elapsed_times >= window_start) & (
            elapsed_times <= window_start + span_seconds
        )
        selected_samples = [
            sample
            for sample, selected in zip(records, in_window)
            if selected and sample is not None
        ]
        self.display = dict(
            x=relative_times.copy(),
            amps=frame_amperes.copy(),
            start=window_start,
            records=selected_samples,
        )
        self.display_meta = dict(
            self.session_meta,
            software_version=__version__,
            shunt_ohm=self.shunt_session,
            utc_anchor_estimated=self.utc_anchor.isoformat(),
            timebase_ms_div=self.timebase.value(),
            unit=self.unit.currentText(),
            vertical_div=self.yscale.value(),
            center=self.yoffset.value(),
            trigger=mode,
            threshold=self.threshold.value(),
        )
        self.curve.setData(
            relative_times, frame_amperes * display_factor, connect="finite"
        )
        if triggered:
            self.trigger_status = "Triggered"
        elif mode == "Free":
            self.trigger_status = "Free running"
        else:
            self.trigger_status = "Auto"
        self.trigger_label.setText(self.tr_text(self.trigger_status))
        self.view_label.setText(
            self.tr_text(
                "{points} points · {window:.3g} ms window",
                points=len(selected_samples),
                window=span_seconds * 1000,
            )
        )
        clipping = any(sample.flags & 1 for sample in selected_samples)
        self.update_trace_caption(clipping)
        if mode == "Single" and triggered:
            self.single_armed = False
            self.freeze.setChecked(True)
        self.export_csv.setEnabled(True)
        self.export_png.setEnabled(True)
        self.auto_y.setEnabled(True)
        self.freeze.setEnabled(True)

    def autoscale(self):
        """Center the visible current and leave a little room around its range."""
        if not self.display:
            return
        amperes = self.display["amps"]
        amperes = amperes[np.isfinite(amperes)]
        if not len(amperes):
            return

        display_factor = 1e6 if self.unit.currentText() == "µA" else 1e3
        minimum = float(np.min(amperes)) * display_factor
        maximum = float(np.max(amperes)) * display_factor
        self.yoffset.setValue((minimum + maximum) / 2)
        self.yscale.setValue(max((maximum - minimum) * 1.2 / 8, 0.001))
        self.update_axes()

    def begin_capture(self):
        path, _ = W.QFileDialog.getSaveFileName(
            self,
            self.tr_text("Start continuous capture"),
            "current_capture.csv",
            "CSV (*.csv)",
        )
        if path and self.worker:
            self.worker.capture(self.with_suffix(path, ".csv"), self.shunt_session)

    @staticmethod
    def with_suffix(path, suffix):
        return path if path.lower().endswith(suffix) else path + suffix

    def export_scope_csv(self, path=None):
        """Export actual visible samples with their original session calibration."""
        if not self.display:
            return
        if not isinstance(path, str):
            path, _ = W.QFileDialog.getSaveFileName(
                self,
                self.tr_text("Export displayed points"),
                "oscilloscope.csv",
                "CSV (*.csv)",
            )
        if not path:
            return

        path = self.with_suffix(path, ".csv")
        metadata = dict(self.display_meta)
        utc_anchor = datetime.fromisoformat(metadata["utc_anchor_estimated"])
        minimum_x, maximum_x = self.plot.viewRange()[0]
        try:
            with open(path, "w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["scope_x_s"] + CSV_FIELDS)
                last_sequence = None
                for sample in self.display["records"]:
                    session_seconds = (sample.device_us - metadata["epoch_us"]) / 1e6
                    scope_seconds = session_seconds - self.display["start"]
                    if not minimum_x <= scope_seconds <= maximum_x:
                        continue
                    if last_sequence is None:
                        missing_before = 0
                    else:
                        sequence_step = (sample.sequence - last_sequence) & MASK32
                        missing_before = sequence_step - 1
                    last_sequence = sample.sequence
                    row = csv_row(
                        sample,
                        metadata,
                        metadata["shunt_ohm"],
                        utc_anchor,
                        missing_before,
                    )
                    writer.writerow([f"{scope_seconds:.6f}"] + row)
            Path(path + ".json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.statusBar().showMessage(self.tr_text("Window saved: {path}", path=path))
        except (OSError, ValueError) as exc:
            self.on_problem(str(exc))

    def export_scope_png(self, path=None):
        if not self.display:
            return
        if not isinstance(path, str):
            path, _ = W.QFileDialog.getSaveFileName(
                self,
                self.tr_text("Export oscilloscope"),
                "oscilloscope.png",
                "PNG (*.png)",
            )
        if not path:
            return
        path = self.with_suffix(path, ".png")
        try:
            exporter = pg.exporters.ImageExporter(self.plot.plotItem)
            exporter.parameters()["width"] = 1800
            exporter.export(path)
            self.statusBar().showMessage(self.tr_text("PNG saved: {path}", path=path))
        except Exception as exc:
            self.on_problem(str(exc))

    def closeEvent(self, event):
        if self.worker:
            self.worker.requestInterruption()
            if not self.worker.wait(2500):
                event.ignore()
                self.on_problem("Waiting for connection to close…")
                return
        self.save_preferences()
        event.accept()


def main():
    app = W.QApplication(sys.argv)
    app.setApplicationName("IoTCurrentScope")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    window = MainWindow(demo="--demo" in sys.argv)
    window.showMaximized()
    return app.exec()

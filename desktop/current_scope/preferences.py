"""Persist operator preferences without starting or configuring a device."""

from contextlib import ExitStack
import math

from PySide6 import QtCore, QtWidgets as W


class WindowPreferences:
    """Keep display settings and requested sensor settings between sessions."""

    def number_preference(self, key, control):
        """Read a finite value inside the control's supported range."""
        try:
            value = float(self.settings.value(key))
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(value) or not control.minimum() <= value <= control.maximum():
            return None
        if isinstance(control, W.QSpinBox):
            return int(value) if value.is_integer() else None
        return value

    def choice_preference(self, key, control, integer=False):
        value = self.settings.value(key)
        if integer:
            try:
                number = float(value)
                if not math.isfinite(number) or not number.is_integer():
                    return None
                value = int(number)
            except (TypeError, ValueError, OverflowError):
                return None
        return value if control.findData(value) >= 0 else None

    def restore_preferences(self):
        """Restore widgets in their saved unit, leaving measurement stopped."""
        self._restored_sensor_preferences = {}
        numbers = (
            ("shunt", self.shunt), ("timebase_ms", self.timebase),
            ("yscale", self.yscale), ("yoffset", self.yoffset),
            ("threshold", self.threshold), ("pretrigger", self.pretrigger),
            ("reference", self.reference), ("rate_hz", self.rate),
        )
        choices = (
            ("trigger_mode", self.trigger_mode, False),
            ("trigger_edge", self.edge, False),
            ("pga", self.pga, True), ("average", self.average, True),
        )
        # Changing the unit normally converts scale and level values. Restoring
        # it with signals blocked avoids converting saved values a second time.
        with ExitStack() as blockers:
            for control in [self.unit] + [control for _, control in numbers] + [control for _, control, _ in choices]:
                blockers.enter_context(QtCore.QSignalBlocker(control))
            unit = self.settings.value("unit", "mA")
            self.unit.setCurrentIndex(max(0, self.unit.findText(str(unit))))
            for key, control in numbers:
                value = self.number_preference(key, control)
                if value is not None:
                    control.setValue(value)
                    if key == "rate_hz":
                        self._restored_sensor_preferences[key] = control.value()
            for key, control, integer in choices:
                value = self.choice_preference(key, control, integer)
                if value is not None:
                    control.setCurrentIndex(control.findData(value))
                    if key in ("pga", "average"):
                        self._restored_sensor_preferences[key] = value

        try:
            address = int(self.settings.value("address"))
        except (TypeError, ValueError, OverflowError):
            address = -1
        if 0x40 <= address <= 0x4f:
            self._restored_sensor_preferences["address"] = address
        self._preserve_sensor_preferences = bool(self._restored_sensor_preferences)
        # If the operator edits a restored setting before Apply, keep that edit
        # when a later firmware status or scan repopulates the controls.
        self.rate.valueChanged.connect(
            lambda value: self.remember_sensor_preference("rate_hz", value)
        )
        for key, control in (("pga", self.pga), ("average", self.average), ("address", self.addr)):
            control.currentIndexChanged.connect(
                lambda index, key=key, control=control:
                    self.remember_sensor_preference(key, control.currentData())
            )

        port = self.settings.value("port")
        self._preferred_port = port if isinstance(port, str) and port else None
        try:
            tab = int(str(self.settings.value("inspector_tab", 0)))
        except (TypeError, ValueError, OverflowError):
            tab = 0
        if 0 <= tab < self.inspector.count():
            self.inspector.setCurrentIndex(tab)
        diagnostics = self.settings.value("diagnostics", False)
        self.details_button.setChecked(str(diagnostics).lower() in ("true", "1"))
        splitter_state = self.settings.value("splitter_state")
        splitter = self.centralWidget().findChild(W.QSplitter)
        if splitter is not None and isinstance(splitter_state, QtCore.QByteArray):
            splitter.restoreState(splitter_state)
        self.update_axes()
        self.update_trigger_controls()
        self.preview_plan()

    def remember_sensor_preference(self, key, value):
        if self._preserve_sensor_preferences and not self.updating and value is not None:
            self._restored_sensor_preferences[key] = value

    def restore_sensor_preferences(self):
        """Keep requested values distinct from acknowledged firmware metadata."""
        if not self._preserve_sensor_preferences:
            return
        requested = self._restored_sensor_preferences
        if "rate_hz" in requested:
            self.rate.setValue(requested["rate_hz"])
        for key, control in (("pga", self.pga), ("average", self.average), ("address", self.addr)):
            if key in requested:
                index = control.findData(requested[key])
                if index >= 0:
                    control.setCurrentIndex(index)

    def save_preferences(self):
        """Flush preferences only after the window can finish closing."""
        for key, control in (
            ("shunt", self.shunt), ("timebase_ms", self.timebase),
            ("yscale", self.yscale), ("yoffset", self.yoffset),
            ("threshold", self.threshold), ("pretrigger", self.pretrigger),
            ("reference", self.reference), ("rate_hz", self.rate),
        ):
            self.settings.setValue(key, control.value())
        for key, control in (
            ("trigger_mode", self.trigger_mode), ("trigger_edge", self.edge),
            ("pga", self.pga), ("average", self.average), ("address", self.addr),
            ("port", self.port), ("language", self.language_choice),
        ):
            value = control.currentData()
            if value is not None:
                self.settings.setValue(key, value)
        self.settings.setValue("unit", self.unit.currentText())
        self.settings.setValue("theme", self.theme)
        self.settings.setValue("inspector_tab", self.inspector.currentIndex())
        self.settings.setValue("diagnostics", self.details_button.isChecked())
        splitter = self.centralWidget().findChild(W.QSplitter)
        if splitter is not None:
            self.settings.setValue("splitter_state", splitter.saveState())
        self.settings.sync()

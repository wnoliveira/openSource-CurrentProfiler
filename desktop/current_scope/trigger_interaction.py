"""Keep mouse trigger selection in sync with the instrument controls."""

from PySide6 import QtCore


class TriggerInteraction:
    def initialize_trigger_interaction(self):
        self.plot.setToolTip(
            "Click to select the trigger level and position, or drag the trigger lines."
        )
        self.trigger_x.setMovable(True)
        self.trigger_line.sigDragged.connect(self.drag_trigger_level)
        self.trigger_x.sigDragged.connect(self.drag_trigger_position)
        self.trigger_line.sigPositionChangeFinished.connect(self.finish_trigger_drag)
        self.trigger_x.sigPositionChangeFinished.connect(self.finish_trigger_drag)
        self.plot.scene().sigMouseClicked.connect(self.select_trigger_at_mouse)
        self.update_trigger_bounds()

    def update_trigger_bounds(self):
        """The vertical marker follows the supported pre-trigger percentage."""
        span = self.timebase.value() * 10 / 1000
        self.trigger_x.setBounds((
            span * self.pretrigger.minimum() / 100,
            span * self.pretrigger.maximum() / 100,
        ))
        self.trigger_line.setBounds((self.threshold.minimum(), self.threshold.maximum()))

    def select_trigger_at_mouse(self, event):
        """A left click in the data area selects level and pre-trigger time."""
        if (event.button() != QtCore.Qt.MouseButton.LeftButton
                or event.isAccepted() or self.trigger_mode.currentData() == "Free"):
            return
        view = self.plot.getViewBox()
        if not view.sceneBoundingRect().contains(event.scenePos()):
            return
        point = view.mapSceneToView(event.scenePos())
        self.threshold.setValue(point.y())
        self.set_trigger_position(point.x())
        self.update_axes()
        self.rearm_mouse_trigger()
        event.accept()

    def set_trigger_position(self, seconds):
        span = self.timebase.value() * 10 / 1000
        self.pretrigger.setValue(round(seconds / span * 100))

    def drag_trigger_level(self, line):
        if self.trigger_mode.currentData() != "Free":
            self.threshold.setValue(line.value())

    def drag_trigger_position(self, line):
        if self.trigger_mode.currentData() != "Free":
            self.set_trigger_position(line.value())

    def finish_trigger_drag(self, line):
        if self.trigger_mode.currentData() == "Free":
            return
        # Snap to the controls' precision, including an unchanged rounded value.
        if line is self.trigger_line:
            self.drag_trigger_level(line)
        else:
            self.drag_trigger_position(line)
        self.update_axes()
        self.rearm_mouse_trigger()

    def rearm_mouse_trigger(self):
        if self.trigger_mode.currentData() == "Single":
            self.rearm()

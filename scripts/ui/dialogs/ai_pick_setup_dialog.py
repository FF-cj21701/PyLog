from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QCheckBox,
    QVBoxLayout,
)

from ..base_dialog import ThemeDialog


class _EditableDoubleSpinBox(QDoubleSpinBox):
    """A spin box that remains convenient for replacing long depth values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Do not push partially typed values through QDoubleSpinBox's bounded
        # validator. Commit once the user presses Enter or leaves the field.
        self.setKeyboardTracking(False)
        self.setCorrectionMode(QAbstractSpinBox.CorrectToPreviousValue)


class AIPickSetupDialog(ThemeDialog):
    """Collect the depth interval and outer sliding-window size for AI Pick."""

    def __init__(self, visible_start, visible_end, available_start, available_end, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Pick Range")
        self.setFixedWidth(390)
        self.setMinimumHeight(350)

        low, high = sorted((float(available_start), float(available_end)))
        self._available_low = low
        self._available_high = high
        visible_low, visible_high = sorted((float(visible_start), float(visible_end)))
        visible_low = max(low, min(high, visible_low))
        visible_high = max(low, min(high, visible_high))

        root = QVBoxLayout()
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)
        self.setLayout(root)

        description = QLabel("Select the depth interval and the vertical size of each AI inspection window.")
        description.setWordWrap(True)
        root.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        root.addLayout(form)

        self.depth_start_spin = self._depth_spin(low, high, visible_low)
        self.depth_end_spin = self._depth_spin(low, high, visible_high)
        self.window_size_spin = _EditableDoubleSpinBox()
        self.window_size_spin.setDecimals(2)
        self.window_size_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.window_size_spin.setSingleStep(0.25)
        self.window_size_spin.setSuffix(" m")
        self.window_size_spin.setValue(min(3.0, max(0.10, high - low)))
        self.entry_level_combo = QComboBox()
        self.entry_level_combo.addItem("Confirmed", "confirmed")
        self.entry_level_combo.addItem("Suspected", "suspected")
        self.fast_mode_check = QCheckBox("Skip additional view navigation")
        self.fast_mode_check.setChecked(True)

        form.addRow("Start depth", self.depth_start_spin)
        form.addRow("End depth", self.depth_end_spin)
        form.addRow("Window size", self.window_size_spin)
        form.addRow("Pick from", self.entry_level_combo)
        form.addRow("Fast mode", self.fast_mode_check)

        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        root.addWidget(self.validation_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.depth_start_spin.valueChanged.connect(self._validate)
        self.depth_end_spin.valueChanged.connect(self._validate)
        self.window_size_spin.valueChanged.connect(self._validate)
        self._validate()
        self.adjustSize()

    @staticmethod
    def _depth_spin(low, high, value):
        spin = _EditableDoubleSpinBox()
        spin.setDecimals(3)
        # The dialog validates against the available interval. A broad editor
        # range lets users freely replace individual digits without Qt
        # rejecting temporary out-of-range text during the edit.
        spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spin.setSingleStep(0.1)
        spin.setSuffix(" m")
        spin.setValue(value)
        return spin

    def _validate(self):
        start = self.depth_start_spin.value()
        end = self.depth_end_spin.value()
        window_size = self.window_size_spin.value()
        in_available_range = (
            self._available_low <= start <= self._available_high
            and self._available_low <= end <= self._available_high
        )
        ordered = end > start
        positive_window = window_size > 0.0
        valid = in_available_range and ordered and positive_window
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(valid)
        if not in_available_range:
            message = (
                f"Depth must be between {self._available_low:.3f} m "
                f"and {self._available_high:.3f} m."
            )
        elif not ordered:
            message = "End depth must be greater than start depth."
        elif not positive_window:
            message = "Window size must be greater than zero."
        else:
            message = ""
        self.validation_label.setText(message)

    def accept(self):
        for spin in (self.depth_start_spin, self.depth_end_spin, self.window_size_spin):
            spin.interpretText()
        self._validate()
        if self.buttons.button(QDialogButtonBox.Ok).isEnabled():
            super().accept()

    def values(self):
        span = self.depth_end_spin.value() - self.depth_start_spin.value()
        return {
            "depth_start": self.depth_start_spin.value(),
            "depth_end": self.depth_end_spin.value(),
            "sliding_window_m": min(self.window_size_spin.value(), span),
            "pick_entry_level": self.entry_level_combo.currentData(),
            "fast_mode": self.fast_mode_check.isChecked(),
        }

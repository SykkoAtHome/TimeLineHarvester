# gui2/widgets/time_selector.py
"""
Time Selector Widget

Provides a widget for selecting time-related values (frames, timecode)
with appropriate labels and validation.
"""

import logging
from typing import Optional, Callable, Union, Tuple

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSpinBox, QDoubleSpinBox,
    QLabel, QCheckBox, QComboBox, QFormLayout
)
from PyQt5.QtCore import pyqtSignal, pyqtSlot, Qt

from opentimelineio import opentime

from ..utils.qt_helpers import create_hbox_layout

logger = logging.getLogger(__name__)


class TimeFormatSelector(QWidget):
    """
    Widget for selecting the time display format (Frames/Timecode).
    """
    # Signal emitted when format changes
    formatChanged = pyqtSignal(str)  # format_name

    def __init__(self,
                 label: str = "Time Display",
                 parent=None):
        """
        Initialize the TimeFormatSelector.

        Args:
            label: Label text
            parent: Parent widget
        """
        super().__init__(parent)

        self._label = label
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = create_hbox_layout(self, margin=0)

        # Add label
        layout.addWidget(QLabel(f"{self._label}:"))

        # Add combo box
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Timecode", "Frames"])
        layout.addWidget(self.format_combo)

        # Add stretch to push controls to the left
        layout.addStretch()

    def _connect_signals(self):
        """Connect widget signals."""
        self.format_combo.currentTextChanged.connect(self.formatChanged)

    def get_format(self) -> str:
        """Get the current format."""
        return self.format_combo.currentText()

    def set_format(self, format_name: str):
        """Set the current format."""
        index = self.format_combo.findText(format_name)
        if index >= 0:
            self.format_combo.setCurrentIndex(index)


class TimeSelector(QWidget):
    """
    Widget for selecting time values (frames, timecode, etc.)

    Provides a SpinBox with appropriate units and validation for
    frame counts, handle lengths, etc.
    """
    # Signal emitted when the value changes
    valueChanged = pyqtSignal(int)

    # Signal emitted when the enabled/disabled state changes via the linked checkbox
    enabledChanged = pyqtSignal(bool)

    def __init__(self,
                 label: str,
                 value: int = 0,
                 minimum: int = 0,
                 maximum: int = 10000,
                 suffix: str = "frames",
                 with_checkbox: bool = False,
                 checkbox_text: Optional[str] = None,
                 special_value_text: Optional[str] = None,
                 tooltip: Optional[str] = None,
                 parent=None):
        """
        Initialize the TimeSelector.

        Args:
            label: Label text
            value: Initial value
            minimum: Minimum allowed value
            maximum: Maximum allowed value
            suffix: Unit suffix (e.g., "frames", "seconds")
            with_checkbox: If True, includes a checkbox to enable/disable
            checkbox_text: Text for the checkbox (if with_checkbox is True)
            special_value_text: Text to display for the minimum value
            tooltip: Tooltip text
            parent: Parent widget
        """
        super().__init__(parent)

        self._label = label
        self._with_checkbox = with_checkbox
        self._checkbox_text = checkbox_text or f"Enable {label.lower()}"

        self._init_ui(value, minimum, maximum, suffix, special_value_text, tooltip)
        self._connect_signals()

        logger.debug(f"TimeSelector '{label}' initialized with value {value}")

    def _init_ui(self, value, minimum, maximum, suffix, special_value_text, tooltip):
        """Initialize the user interface."""
        if self._with_checkbox:
            # When using checkbox, we need a vertical layout
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(2)

            # Add checkbox
            self.checkbox = QCheckBox(self._checkbox_text)
            main_layout.addWidget(self.checkbox)

            # Create horizontal layout for spinbox and label
            spinbox_layout = create_hbox_layout(margin=0)

            # Add label only if provided
            if self._label:
                spinbox_layout.addWidget(QLabel(f"{self._label}:"))

            # Create and add spinbox
            self.spinbox = QSpinBox()
            self.spinbox.setRange(minimum, maximum)
            self.spinbox.setValue(value)
            if suffix:
                self.spinbox.setSuffix(f" {suffix}")
            if special_value_text:
                self.spinbox.setSpecialValueText(special_value_text)
            if tooltip:
                self.spinbox.setToolTip(tooltip)
            spinbox_layout.addWidget(self.spinbox)

            # Add a stretch to push controls to the left
            spinbox_layout.addStretch()

            # Add the spinbox layout to the main layout
            main_layout.addLayout(spinbox_layout)
        else:
            # When not using checkbox, use horizontal layout
            main_layout = create_hbox_layout(self, margin=0)

            # Add label only if provided
            if self._label:
                main_layout.addWidget(QLabel(f"{self._label}:"))

            # Create and add spinbox
            self.spinbox = QSpinBox()
            self.spinbox.setRange(minimum, maximum)
            self.spinbox.setValue(value)
            if suffix:
                self.spinbox.setSuffix(f" {suffix}")
            if special_value_text:
                self.spinbox.setSpecialValueText(special_value_text)
            if tooltip:
                self.spinbox.setToolTip(tooltip)
            main_layout.addWidget(self.spinbox)

            # Add a stretch to push controls to the left
            main_layout.addStretch()

    def _connect_signals(self):
        """Connect widget signals."""
        self.spinbox.valueChanged.connect(self._on_value_changed)

        if self._with_checkbox:
            self.checkbox.stateChanged.connect(self._on_checkbox_changed)

            # Initial state
            self._on_checkbox_changed(self.checkbox.checkState())

    @pyqtSlot(int)
    def _on_value_changed(self, value):
        """Handle spinbox value change."""
        # Simply re-emit the signal
        self.valueChanged.emit(value)

    @pyqtSlot(int)
    def _on_checkbox_changed(self, state):
        """Handle checkbox state change."""
        enabled = (state == Qt.Checked)
        self.spinbox.setEnabled(enabled)
        self.enabledChanged.emit(enabled)

    def value(self) -> int:
        """Get the current value."""
        return self.spinbox.value()

    def set_value(self, value: int):
        """Set the current value."""
        self.spinbox.setValue(value)

    def set_enabled(self, enabled: bool):
        """Set the enabled state."""
        if self._with_checkbox:
            self.checkbox.setChecked(enabled)
        else:
            self.spinbox.setEnabled(enabled)

    def is_enabled(self) -> bool:
        """Get the enabled state."""
        if self._with_checkbox:
            return self.checkbox.isChecked()
        else:
            return self.spinbox.isEnabled()


class TimeDisplay(QWidget):
    """
    Widget for displaying time values in different formats.

    Displays a fixed time value that can switch between frames and timecode.
    """

    def __init__(self,
                 label: str,
                 rational_time: Optional[opentime.RationalTime] = None,
                 frame_rate: float = 25.0,
                 format: str = "Timecode",
                 parent=None):
        """
        Initialize the TimeDisplay.

        Args:
            label: Label text
            rational_time: Initial time value as RationalTime
            frame_rate: Frame rate for timecode display
            format: Initial format ("Timecode" or "Frames")
            parent: Parent widget
        """
        super().__init__(parent)

        self._label = label
        self._rational_time = rational_time
        self._frame_rate = max(1.0, frame_rate)
        self._format = format

        self._init_ui()
        self._update_display()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = create_hbox_layout(self, margin=0)

        # Add label
        layout.addWidget(QLabel(f"{self._label}:"))

        # Add value label
        self.value_label = QLabel("--:--:--:--")
        layout.addWidget(self.value_label)

        # Add stretch to push controls to the left
        layout.addStretch()

    def _update_display(self):
        """Update the display based on current time and format."""
        if self._rational_time is None:
            self.value_label.setText("N/A")
            return

        try:
            if self._format == "Timecode":
                # Format as timecode
                tc_str = opentime.to_timecode(self._rational_time, self._frame_rate)
                self.value_label.setText(tc_str)
            else:
                # Format as frames
                frame_count = round(self._rational_time.value)
                self.value_label.setText(f"{frame_count} frames")
        except Exception as e:
            logger.warning(f"Error formatting time display: {e}")
            self.value_label.setText("Error")

    def set_time(self, rational_time: opentime.RationalTime):
        """Set the time value."""
        self._rational_time = rational_time
        self._update_display()

    def set_frame_rate(self, frame_rate: float):
        """Set the frame rate for timecode display."""
        self._frame_rate = max(1.0, frame_rate)
        self._update_display()

    def set_format(self, format: str):
        """Set the display format."""
        if format in ("Timecode", "Frames"):
            self._format = format
            self._update_display()


class HandleSelector(QWidget):
    """
    Specialized widget for selecting handles with linked start/end values.

    Provides two spin boxes for start and end handles with an option to link them.
    """
    # Signal emitted when either handle value changes
    handleValuesChanged = pyqtSignal(int, int)  # (start_handles, end_handles)

    def __init__(self,
                 start_value: int = 25,
                 end_value: Optional[int] = None,
                 minimum: int = 0,
                 maximum: int = 10000,
                 linked: bool = True,
                 parent=None):
        """
        Initialize the HandleSelector.

        Args:
            start_value: Initial start handle value
            end_value: Initial end handle value (if None, uses start_value)
            minimum: Minimum handle value
            maximum: Maximum handle value
            linked: Whether start and end handles should be linked
            parent: Parent widget
        """
        super().__init__(parent)

        # If end_value not specified, use start_value
        if end_value is None:
            end_value = start_value

        self._linked = linked

        self._init_ui(start_value, end_value, minimum, maximum)
        self._connect_signals()

        logger.debug(f"HandleSelector initialized with start={start_value}, end={end_value}, linked={linked}")

    def _init_ui(self, start_value, end_value, minimum, maximum):
        """Initialize the user interface."""
        # Main layout using form layout for better alignment
        main_layout = QFormLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # Create start handle selector
        start_layout = create_hbox_layout(margin=0)
        self.start_spinbox = QSpinBox()
        self.start_spinbox.setRange(minimum, maximum)
        self.start_spinbox.setValue(start_value)
        self.start_spinbox.setSuffix(" frames")
        self.start_spinbox.setToolTip("Number of frames to add before each clip")
        start_layout.addWidget(self.start_spinbox)
        start_layout.addStretch()

        # Create end handle selector
        end_layout = create_hbox_layout(margin=0)
        self.end_spinbox = QSpinBox()
        self.end_spinbox.setRange(minimum, maximum)
        self.end_spinbox.setValue(end_value)
        self.end_spinbox.setSuffix(" frames")
        self.end_spinbox.setToolTip("Number of frames to add after each clip")
        end_layout.addWidget(self.end_spinbox)
        end_layout.addStretch()

        # Add to form layout
        main_layout.addRow("Start Handles:", start_layout)
        main_layout.addRow("End Handles:", end_layout)

        # Add checkbox for linking
        self.link_checkbox = QCheckBox("Use same value for handles")
        self.link_checkbox.setChecked(self._linked)
        main_layout.addRow("", self.link_checkbox)

        # Initial update of end spinbox enabled state
        self.end_spinbox.setEnabled(not self._linked)

    def _connect_signals(self):
        """Connect widget signals."""
        self.start_spinbox.valueChanged.connect(self._on_start_value_changed)
        self.end_spinbox.valueChanged.connect(self._on_end_value_changed)
        self.link_checkbox.stateChanged.connect(self._on_link_changed)

    @pyqtSlot(int)
    def _on_start_value_changed(self, value):
        """Handle start handle value change."""
        # If linked, update end handle to match
        if self.link_checkbox.isChecked():
            self.end_spinbox.blockSignals(True)
            self.end_spinbox.setValue(value)
            self.end_spinbox.blockSignals(False)

        # Emit combined signal
        self.handleValuesChanged.emit(self.start_spinbox.value(), self.end_spinbox.value())

    @pyqtSlot(int)
    def _on_end_value_changed(self, value):
        """Handle end handle value change."""
        # Emit combined signal
        self.handleValuesChanged.emit(self.start_spinbox.value(), self.end_spinbox.value())

    @pyqtSlot(int)
    def _on_link_changed(self, state):
        """Handle link checkbox state change."""
        linked = (state == Qt.Checked)
        self._linked = linked

        # Enable/disable end handle spinbox based on link state
        self.end_spinbox.setEnabled(not linked)

        # If linked, update end handle to match start handle
        if linked:
            self.end_spinbox.blockSignals(True)
            self.end_spinbox.setValue(self.start_spinbox.value())
            self.end_spinbox.blockSignals(False)

            # Emit updated values
            self.handleValuesChanged.emit(self.start_spinbox.value(), self.end_spinbox.value())

    def get_values(self) -> Tuple[int, int]:
        """
        Get the current handle values.

        Returns:
            Tuple of (start_handles, end_handles)
        """
        return self.start_spinbox.value(), self.end_spinbox.value()

    def set_values(self, start_value: int, end_value: Optional[int] = None):
        """
        Set the handle values.

        Args:
            start_value: Start handle value
            end_value: End handle value (if None, uses start_value)
        """
        if end_value is None:
            end_value = start_value

        self.start_spinbox.blockSignals(True)
        self.end_spinbox.blockSignals(True)

        self.start_spinbox.setValue(start_value)

        if self._linked:
            self.end_spinbox.setValue(start_value)
        else:
            self.end_spinbox.setValue(end_value)

        self.start_spinbox.blockSignals(False)
        self.end_spinbox.blockSignals(False)

        # Emit updated values
        self.handleValuesChanged.emit(self.start_spinbox.value(), self.end_spinbox.value())

    def set_linked(self, linked: bool):
        """Set whether handles are linked."""
        self.link_checkbox.setChecked(linked)

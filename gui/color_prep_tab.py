# gui/color_prep_tab.py (modified to use EnhancedResultsDisplayWidget)
"""
Widget managing the Color Grading Preparation stage UI and actions.
"""
import logging
from typing import Dict, Tuple

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSpinBox, QCheckBox, QLabel,
                             QPushButton, QSplitter)

# Import the enhanced results display
from .enhanced_results_display import EnhancedResultsDisplayWidget

logger = logging.getLogger(__name__)


class ColorPrepTabWidget(QWidget):
    """
    Widget managing the Color Grading Preparation stage.

    Provides UI for configuring color grading preparation settings, including
    handle frames, separator gaps, and split thresholds. Also includes controls
    to analyze sources, calculate segments, and export EDL/XML.
    """
    # Signals emitted to MainWindow to trigger actions or indicate changes
    settingsChanged = pyqtSignal()
    analyzeSourcesClicked = pyqtSignal()
    calculateSegmentsClicked = pyqtSignal()
    exportEdlXmlClicked = pyqtSignal()

    def __init__(self, harvester_instance, parent=None):
        """
        Initialize the ColorPrepTabWidget.

        Args:
            harvester_instance: Instance of the harvester (currently unused but kept for compatibility)
            parent: Parent widget
        """
        super().__init__(parent)

        # Initialize instance variables
        self.start_handles_spin = None
        self.end_handles_spin = None
        self.same_handles_check = None
        self.separator_spin = None
        self.split_gap_spin = None
        self.analyze_button = None
        self.calculate_button = None
        self.export_button = None
        self.results_widget = None

        self.init_ui()
        self.connect_signals()
        logger.info("ColorPrepTabWidget initialized.")

    def init_ui(self):
        """Initialize the user interface components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # Top part: Settings & Actions
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # Settings Group
        settings_group = QGroupBox("Color Prep Settings")
        settings_form_layout = QFormLayout(settings_group)
        settings_form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Handle Frames Settings
        start_handle_layout = QHBoxLayout()
        self.start_handles_spin = QSpinBox(minimum=0, maximum=10000, value=25)
        self.start_handles_spin.setToolTip("Frames added before each segment")
        self.start_handles_spin.setFixedWidth(100)
        start_handle_layout.addWidget(self.start_handles_spin)
        start_handle_layout.addWidget(QLabel("frames"))
        start_handle_layout.addStretch()
        settings_form_layout.addRow("Start Handles:", start_handle_layout)

        end_handle_layout = QHBoxLayout()
        self.end_handles_spin = QSpinBox(minimum=0, maximum=10000, value=25, enabled=False)
        self.end_handles_spin.setToolTip("Frames added after each segment")
        self.end_handles_spin.setFixedWidth(100)
        end_handle_layout.addWidget(self.end_handles_spin)
        end_handle_layout.addWidget(QLabel("frames"))
        end_handle_layout.addStretch()
        settings_form_layout.addRow("End Handles:", end_handle_layout)

        self.same_handles_check = QCheckBox("Use same value for End Handles", checked=True)
        settings_form_layout.addRow("", self.same_handles_check)

        # Separator Setting
        separator_layout = QHBoxLayout()
        self.separator_spin = QSpinBox(minimum=0, maximum=1000, value=0)
        self.separator_spin.setToolTip("Insert black gap of this duration between segments in the exported EDL/XML.")
        self.separator_spin.setFixedWidth(100)
        separator_layout.addWidget(self.separator_spin)
        separator_layout.addWidget(QLabel("frames"))
        separator_layout.addStretch()
        settings_form_layout.addRow("Segment Separator Gap:", separator_layout)

        # Split Gap Threshold Setting
        split_gap_layout = QHBoxLayout()
        self.split_gap_spin = QSpinBox(minimum=-1, maximum=99999, value=-1)
        self.split_gap_spin.setToolTip(
            "Split segments if the gap between them (after handles) exceeds this many frames.\n"
            "Set to -1 to disable splitting.")
        self.split_gap_spin.setSpecialValueText("Disabled")
        self.split_gap_spin.setFixedWidth(100)
        split_gap_layout.addWidget(self.split_gap_spin)
        split_gap_layout.addWidget(QLabel("frames"))
        split_gap_layout.addStretch()
        settings_form_layout.addRow("Split Gap Threshold:", split_gap_layout)

        top_layout.addWidget(settings_group)

        # Action Buttons
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 10, 0, 0)
        self.analyze_button = QPushButton("1. Analyze Sources")
        self.calculate_button = QPushButton("2. Calculate Segments")
        self.export_button = QPushButton("3. Export EDL/XML...")
        self.analyze_button.setEnabled(False)
        self.calculate_button.setEnabled(False)
        self.export_button.setEnabled(False)
        button_layout.addWidget(self.analyze_button)
        button_layout.addWidget(self.calculate_button)
        button_layout.addWidget(self.export_button)
        button_layout.addStretch()
        top_layout.addLayout(button_layout)

        splitter.addWidget(top_widget)

        # Bottom part: Enhanced Results Display
        self.results_widget = EnhancedResultsDisplayWidget()
        splitter.addWidget(self.results_widget)
        splitter.setSizes([200, 500])

    def connect_signals(self):
        """Connect widget signals to their handlers."""
        # Connect internal UI elements
        self.same_handles_check.stateChanged.connect(self._update_handles_state)
        self.start_handles_spin.valueChanged.connect(self._update_end_handles_if_linked)
        self.separator_spin.valueChanged.connect(self._update_separator_value)

        # Emit settingsChanged when relevant values change
        self.start_handles_spin.valueChanged.connect(self._emit_settings_changed)
        self.end_handles_spin.valueChanged.connect(self._emit_settings_changed)
        self.same_handles_check.stateChanged.connect(self._emit_settings_changed)
        self.separator_spin.valueChanged.connect(self._emit_settings_changed)
        self.split_gap_spin.valueChanged.connect(self._emit_settings_changed)

        # Connect action buttons to this widget's signals (emitted to MainWindow)
        self.analyze_button.clicked.connect(self.analyzeSourcesClicked.emit)
        self.calculate_button.clicked.connect(self.calculateSegmentsClicked.emit)
        self.export_button.clicked.connect(self.exportEdlXmlClicked.emit)

    @pyqtSlot()
    def _emit_settings_changed(self):
        """Emit the settingsChanged signal."""
        self.settingsChanged.emit()

    @pyqtSlot(int)
    def _update_handles_state(self, state):
        """
        Enable/disable end handles spinbox based on checkbox.

        Args:
            state: Qt.Checked or Qt.Unchecked
        """
        is_checked = (state == Qt.Checked)
        self.end_handles_spin.setEnabled(not is_checked)
        if is_checked:
            self.end_handles_spin.setValue(self.start_handles_spin.value())
        self.settingsChanged.emit()

        # Update handle value in enhanced display widget
        handle_frames = self.start_handles_spin.value()
        self.results_widget.set_handle_frames(handle_frames)

    @pyqtSlot(int)
    def _update_end_handles_if_linked(self, value):
        """
        Sync end handles if checkbox is checked.

        Args:
            value: New value from start_handles_spin
        """
        if self.same_handles_check.isChecked():
            self.end_handles_spin.blockSignals(True)
            self.end_handles_spin.setValue(value)
            self.end_handles_spin.blockSignals(False)

        # Update handle value in enhanced display widget
        self.results_widget.set_handle_frames(value)

    @pyqtSlot(int)
    def _update_separator_value(self, value):
        """
        Update separator frames in the enhanced display widget.

        Args:
            value: New separator frames value
        """
        self.results_widget.set_separator_frames(value)

    def get_handles(self) -> Tuple[int, int]:
        """
        Get the number of start and end handle frames.

        Returns:
            Tuple containing (start_handles, end_handles)
        """
        start_h = self.start_handles_spin.value()
        end_h = self.end_handles_spin.value() if not self.same_handles_check.isChecked() else start_h
        return start_h, end_h

    def get_separator_frames(self) -> int:
        """
        Get the number of frames for the separator gap.

        Returns:
            Number of separator frames
        """
        return self.separator_spin.value()

    def get_split_gap_threshold(self) -> int:
        """
        Get the threshold value for splitting segments.

        Returns:
            Split gap threshold in frames (-1 if disabled)
        """
        return self.split_gap_spin.value()

    def clear_tab(self):
        """Reset the tab settings and clear results."""
        self.start_handles_spin.setValue(25)
        self.same_handles_check.setChecked(True)
        self.separator_spin.setValue(0)
        self.split_gap_spin.setValue(-1)

        self.results_widget.clear_results()

        self.update_button_states(False, False, False)
        logger.info("ColorPrepTabWidget cleared.")

    def update_button_states(self, can_analyze: bool, can_calculate: bool, can_export: bool):
        """
        Update the enabled state of action buttons on this tab.

        Args:
            can_analyze: Whether the Analyze button should be enabled
            can_calculate: Whether the Calculate button should be enabled
            can_export: Whether the Export button should be enabled
        """
        self.analyze_button.setEnabled(can_analyze)
        self.calculate_button.setEnabled(can_calculate)
        self.export_button.setEnabled(can_export)

    def load_tab_settings(self, settings: Dict):
        """
        Load settings specific to this tab from a dictionary.

        Args:
            settings: Dictionary containing tab settings
        """
        self.start_handles_spin.setValue(settings.get('color_prep_start_handles', 25))
        same = settings.get('color_prep_same_handles', True)
        self.same_handles_check.setChecked(same)

        # Set end value correctly based on checkbox state after loading
        end_val = settings.get('color_prep_end_handles', self.start_handles_spin.value())
        self.end_handles_spin.setValue(end_val if not same else self.start_handles_spin.value())
        self.end_handles_spin.setEnabled(not same)

        # Set separator and gap threshold
        separator_frames = settings.get('color_prep_separator', 0)
        self.separator_spin.setValue(separator_frames)
        self.split_gap_spin.setValue(settings.get('split_gap_threshold_frames', -1))

        # Update enhanced display widget
        handle_frames = self.start_handles_spin.value()
        self.results_widget.set_handle_frames(handle_frames)
        self.results_widget.set_separator_frames(separator_frames)

    def get_tab_settings(self) -> Dict:
        """
        Retrieve settings specific to this tab as a dictionary.

        Returns:
            Dictionary containing the current tab settings
        """
        start_h, end_h = self.get_handles()
        settings = {
            'color_prep_start_handles': start_h,
            'color_prep_same_handles': self.same_handles_check.isChecked(),
            'color_prep_end_handles': end_h,
            'color_prep_separator': self.get_separator_frames(),
            'split_gap_threshold_frames': self.get_split_gap_threshold(),
        }
        return settings

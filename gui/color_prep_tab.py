# gui/color_prep_tab.py
"""
Widget managing the Color Grading Preparation stage UI and actions.
"""
import logging
from typing import Dict, Tuple

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSpinBox, QCheckBox, QLabel,
                             QPushButton, QSplitter)

# Import the reusable results display
from .results_display import ResultsDisplayWidget

logger = logging.getLogger(__name__)


class ColorPrepTabWidget(QWidget):
    """Widget managing the Color Grading Preparation stage."""
    # Signals emitted to MainWindow to trigger actions or indicate changes
    settingsChanged = pyqtSignal()
    analyzeSourcesClicked = pyqtSignal()
    calculateSegmentsClicked = pyqtSignal()
    exportEdlXmlClicked = pyqtSignal()

    def __init__(self, harvester_instance, parent=None):
        super().__init__(parent)
        # self.harvester = harvester_instance # Store harvester if needed directly, maybe not
        self.init_ui()
        self.connect_signals()
        logger.info("ColorPrepTabWidget initialized.")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)  # Padding around the tab content
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # --- Top part: Settings & Actions ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # --- Settings Group ---
        settings_group = QGroupBox("Color Prep Settings")
        settings_form_layout = QFormLayout(settings_group)
        settings_form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # --- Handle Frames Settings ---
        start_handle_layout = QHBoxLayout()
        self.start_handles_spin = QSpinBox(minimum=0, maximum=10000, value=24)  # Removed suffix for cleaner get/set
        self.start_handles_spin.setToolTip("Frames added before each segment")
        self.start_handles_spin.setFixedWidth(100)
        start_handle_layout.addWidget(self.start_handles_spin)
        start_handle_layout.addWidget(QLabel("frames"))
        start_handle_layout.addStretch()
        settings_form_layout.addRow("Start Handles:", start_handle_layout)

        end_handle_layout = QHBoxLayout()
        self.end_handles_spin = QSpinBox(minimum=0, maximum=10000, value=24, enabled=False)
        self.end_handles_spin.setToolTip("Frames added after each segment")
        self.end_handles_spin.setFixedWidth(100)
        end_handle_layout.addWidget(self.end_handles_spin)
        end_handle_layout.addWidget(QLabel("frames"))
        end_handle_layout.addStretch()
        settings_form_layout.addRow("End Handles:", end_handle_layout)

        self.same_handles_check = QCheckBox("Use same value for End Handles", checked=True)
        settings_form_layout.addRow("", self.same_handles_check)

        # --- Separator Setting ---
        separator_layout = QHBoxLayout()
        self.separator_spin = QSpinBox(minimum=0, maximum=1000, value=0)
        self.separator_spin.setToolTip("Insert black gap of this duration between segments in the exported EDL/XML.")
        self.separator_spin.setFixedWidth(100)
        separator_layout.addWidget(self.separator_spin)
        separator_layout.addWidget(QLabel("frames"))
        separator_layout.addStretch()
        settings_form_layout.addRow("Segment Separator Gap:", separator_layout)

        # --- Split Gap Threshold Setting ---
        split_gap_layout = QHBoxLayout()
        self.split_gap_spin = QSpinBox(minimum=-1, maximum=99999, value=-1)  # Allow -1 for disabled
        self.split_gap_spin.setToolTip(
            "Split segments if the gap between them (after handles) exceeds this many frames.\nSet to -1 to disable splitting.")
        self.split_gap_spin.setSpecialValueText("Disabled")  # Show text for -1
        self.split_gap_spin.setFixedWidth(100)
        split_gap_layout.addWidget(self.split_gap_spin)
        split_gap_layout.addWidget(QLabel("frames"))
        split_gap_layout.addStretch()
        settings_form_layout.addRow("Split Gap Threshold:", split_gap_layout)

        top_layout.addWidget(settings_group)

        # --- Action Buttons ---
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

        # --- Bottom part: Results Display ---
        self.results_widget = ResultsDisplayWidget()
        # Configure columns for color prep (hide transcode status/error)
        try:
            # Assume standard indices if names change
            # Index 4: "Transcode Status", Index 5: "Error / Notes"
            self.results_widget.segments_table.setColumnHidden(4, True)
            self.results_widget.segments_table.setColumnHidden(5, True)
        except Exception as e:
            logger.warning(f"Could not hide columns in segments table: {e}")
        splitter.addWidget(self.results_widget)

        splitter.setSizes([200, 500])  # Adjust initial sizes if needed

    def connect_signals(self):
        # Connect internal UI elements
        self.same_handles_check.stateChanged.connect(self._update_handles_state)
        self.start_handles_spin.valueChanged.connect(self._update_end_handles_if_linked)

        # Emit settingsChanged when relevant values change
        self.start_handles_spin.valueChanged.connect(self._emit_settings_changed)
        self.end_handles_spin.valueChanged.connect(self._emit_settings_changed)
        self.same_handles_check.stateChanged.connect(self._emit_settings_changed)
        self.separator_spin.valueChanged.connect(self._emit_settings_changed)
        self.split_gap_spin.valueChanged.connect(self._emit_settings_changed)  # Connect new spinbox

        # Connect action buttons to this widget's signals (emitted to MainWindow)
        self.analyze_button.clicked.connect(self.analyzeSourcesClicked.emit)
        self.calculate_button.clicked.connect(self.calculateSegmentsClicked.emit)
        self.export_button.clicked.connect(self.exportEdlXmlClicked.emit)
        logger.debug("ColorPrepTabWidget signals connected.")

    @pyqtSlot()
    def _emit_settings_changed(self):
        """Emits the settingsChanged signal."""
        self.settingsChanged.emit()

    @pyqtSlot(int)
    def _update_handles_state(self, state):
        """Enable/disable end handles spinbox based on checkbox."""
        is_checked = (state == Qt.Checked)
        self.end_handles_spin.setEnabled(not is_checked)
        if is_checked:
            self.end_handles_spin.setValue(self.start_handles_spin.value())
        self.settingsChanged.emit()  # Emit change also when checkbox state changes

    @pyqtSlot(int)
    def _update_end_handles_if_linked(self, value):
        """Sync end handles if checkbox is checked."""
        if self.same_handles_check.isChecked():
            self.end_handles_spin.blockSignals(True)
            self.end_handles_spin.setValue(value)
            self.end_handles_spin.blockSignals(False)
            # No need to emit settingsChanged here, it's emitted by start_handles_spin

    # --- Public Methods ---
    def get_handles(self) -> Tuple[int, int]:
        """Returns the number of start and end handle frames."""
        start_h = self.start_handles_spin.value()
        end_h = self.end_handles_spin.value() if not self.same_handles_check.isChecked() else start_h
        return start_h, end_h

    def get_separator_frames(self) -> int:
        """Returns the number of frames for the separator gap."""
        return self.separator_spin.value()

    def get_split_gap_threshold(self) -> int:
        """Returns the threshold value from the spinbox."""
        return self.split_gap_spin.value()

    def clear_tab(self):
        """Resets the tab settings and clears results."""
        self.start_handles_spin.setValue(24)
        self.same_handles_check.setChecked(True)
        self.separator_spin.setValue(0)
        self.split_gap_spin.setValue(-1)  # Reset threshold
        if hasattr(self.results_widget, 'clear_results'):
            self.results_widget.clear_results()
        self.update_button_states(False, False, False)
        logger.info("ColorPrepTabWidget cleared.")

    def update_button_states(self, can_analyze: bool, can_calculate: bool, can_export: bool):
        """Updates the enabled state of action buttons on this tab."""
        self.analyze_button.setEnabled(can_analyze)
        self.calculate_button.setEnabled(can_calculate)
        self.export_button.setEnabled(can_export)
        logger.debug(
            f"ColorPrepTab buttons updated: Analyze={can_analyze}, Calculate={can_calculate}, Export={can_export}")

    def load_tab_settings(self, settings: Dict):
        """Loads settings specific to this tab from a dictionary."""
        self.start_handles_spin.setValue(settings.get('color_prep_start_handles', 24))
        same = settings.get('color_prep_same_handles', True)
        self.same_handles_check.setChecked(same)
        # Set end value correctly based on checkbox state after loading
        end_val = settings.get('color_prep_end_handles', self.start_handles_spin.value())
        self.end_handles_spin.setValue(end_val if not same else self.start_handles_spin.value())
        self.end_handles_spin.setEnabled(not same)
        self.separator_spin.setValue(settings.get('color_prep_separator', 0))
        self.split_gap_spin.setValue(settings.get('split_gap_threshold_frames', -1))  # Load threshold
        logger.debug("ColorPrepTab settings loaded.")

    def get_tab_settings(self) -> Dict:
        """Retrieves settings specific to this tab as a dictionary."""
        start_h, end_h = self.get_handles()
        settings = {
            'color_prep_start_handles': start_h,
            'color_prep_same_handles': self.same_handles_check.isChecked(),
            'color_prep_end_handles': end_h,
            'color_prep_separator': self.get_separator_frames(),
            'split_gap_threshold_frames': self.get_split_gap_threshold(),  # Get threshold
        }
        logger.debug("Retrieved settings from ColorPrepTab.")
        return settings

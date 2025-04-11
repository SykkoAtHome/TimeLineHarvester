# gui/color_prep_tab.py

import logging
from typing import Dict, Tuple

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSpinBox, QCheckBox,
                             QPushButton, QSplitter)  # Added QSpacerItem, QSizePolicy

from .results_display import ResultsDisplayWidget

logger = logging.getLogger(__name__)

class ColorPrepTabWidget(QWidget):
    """Widget managing the Color Grading Preparation stage."""
    settingsChanged = pyqtSignal()
    analyzeSourcesClicked = pyqtSignal()
    calculateSegmentsClicked = pyqtSignal()
    exportEdlXmlClicked = pyqtSignal()

    def __init__(self, harvester_instance, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.connect_signals()
        logger.info("ColorPrepTabWidget initialized.")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # --- Top part: Settings & Actions ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0,0,0,0)

        # --- Settings Group ---
        settings_group = QGroupBox("Color Prep Settings")
        settings_form_layout = QFormLayout(settings_group) # Use FormLayout for alignment
        settings_form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow) # Allow fields to expand slightly

        # --- Handle Frames Settings ---
        # Use QHBoxLayout to control SpinBox width
        start_handle_layout = QHBoxLayout()
        self.start_handles_spin = QSpinBox(minimum=0, maximum=10000, value=24, suffix=" frames")
        self.start_handles_spin.setToolTip("Frames added before each segment")
        self.start_handles_spin.setFixedWidth(100) # Set fixed width for spinbox
        start_handle_layout.addWidget(self.start_handles_spin)
        start_handle_layout.addStretch() # Push spinbox left
        settings_form_layout.addRow("Start Handles:", start_handle_layout)

        end_handle_layout = QHBoxLayout()
        self.end_handles_spin = QSpinBox(minimum=0, maximum=10000, value=24, suffix=" frames", enabled=False)
        self.end_handles_spin.setToolTip("Frames added after each segment")
        self.end_handles_spin.setFixedWidth(100) # Set fixed width
        end_handle_layout.addWidget(self.end_handles_spin)
        end_handle_layout.addStretch()
        settings_form_layout.addRow("End Handles:", end_handle_layout)

        self.same_handles_check = QCheckBox("Use same value for End Handles", checked=True)
        settings_form_layout.addRow("", self.same_handles_check)

        # --- Separator Setting ---
        separator_layout = QHBoxLayout()
        self.separator_spin = QSpinBox(minimum=0, maximum=1000, value=0, suffix=" frames")
        self.separator_spin.setToolTip("Insert black gap of this duration between segments in the exported EDL/XML.")
        self.separator_spin.setFixedWidth(100) # Set fixed width
        separator_layout.addWidget(self.separator_spin)
        separator_layout.addStretch()
        settings_form_layout.addRow("Segment Separator Gap:", separator_layout)

        top_layout.addWidget(settings_group) # Add settings group to top layout

        # --- Action Buttons ---
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 10, 0, 0) # Add some space above buttons
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

        splitter.addWidget(top_widget) # Add settings/actions widget to splitter

        # --- Bottom part: Results Display ---
        self.results_widget = ResultsDisplayWidget()
        # Configure results display (e.g., hide irrelevant columns)
        segments_tab_index = self.results_widget.tabs.indexOf(self.results_widget.segments_tab) # Find by object
        if segments_tab_index != -1:
             self.results_widget.segments_table.setColumnHidden(4, True) # Hide "Transcode Status"
             self.results_widget.segments_table.setColumnHidden(5, True) # Hide "Error / Notes"
        splitter.addWidget(self.results_widget)

        splitter.setSizes([200, 500]) # Adjust initial sizes if needed
        logger.debug("ColorPrepTabWidget UI updated with separate handles and separator.")

    def connect_signals(self):
        # Connect internal UI elements
        self.same_handles_check.stateChanged.connect(self._update_handles_state)
        self.start_handles_spin.valueChanged.connect(self._update_end_handles_if_linked)
        # Emit settingsChanged when relevant values change
        self.start_handles_spin.valueChanged.connect(self._emit_settings_changed)
        self.end_handles_spin.valueChanged.connect(self._emit_settings_changed)
        self.same_handles_check.stateChanged.connect(self._emit_settings_changed)
        self.separator_spin.valueChanged.connect(self._emit_settings_changed)

        # Connect action buttons to this widget's signals
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
        # Emit change signal when checkbox state changes
        self.settingsChanged.emit()


    @pyqtSlot(int)
    def _update_end_handles_if_linked(self, value):
        """Sync end handles if checkbox is checked."""
        if self.same_handles_check.isChecked():
            # Block signals temporarily to avoid recursive loops or double emits
            self.end_handles_spin.blockSignals(True)
            self.end_handles_spin.setValue(value)
            self.end_handles_spin.blockSignals(False)
            # Note: settingsChanged is already emitted by start_handles_spin.valueChanged

    # --- Public Methods ---
    def get_handles(self) -> Tuple[int, int]:
        """Returns the number of start and end handle frames."""
        start_h = self.start_handles_spin.value()
        end_h = self.end_handles_spin.value() if not self.same_handles_check.isChecked() else start_h
        return start_h, end_h

    def get_separator_frames(self) -> int:
        """Returns the number of frames for the separator gap."""
        return self.separator_spin.value()

    def clear_tab(self):
        """Resets the tab settings and clears results."""
        self.start_handles_spin.setValue(24)
        self.same_handles_check.setChecked(True) # This will trigger update_handles_state
        self.separator_spin.setValue(0)
        if hasattr(self.results_widget, 'clear_results'):
            self.results_widget.clear_results()
        self.update_button_states(False, False, False)
        logger.info("ColorPrepTabWidget cleared.")

    def update_button_states(self, can_analyze: bool, can_calculate: bool, can_export: bool):
         """Updates the enabled state of action buttons on this tab."""
         self.analyze_button.setEnabled(can_analyze)
         self.calculate_button.setEnabled(can_calculate)
         self.export_button.setEnabled(can_export)
         logger.debug(f"ColorPrepTab buttons updated: Analyze={can_analyze}, Calculate={can_calculate}, Export={can_export}")

    def load_tab_settings(self, settings: Dict):
         """Loads settings specific to this tab."""
         self.start_handles_spin.setValue(settings.get('color_prep_start_handles', 24)) # Use specific keys
         same = settings.get('color_prep_same_handles', True)
         self.same_handles_check.setChecked(same)
         if not same:
             self.end_handles_spin.setValue(settings.get('color_prep_end_handles', 24))
         else: # Ensure end value syncs if checkbox is checked
              self.end_handles_spin.setValue(self.start_handles_spin.value())
         self.end_handles_spin.setEnabled(not same) # Set enabled state correctly
         self.separator_spin.setValue(settings.get('color_prep_separator', 0))
         logger.debug("ColorPrepTab settings loaded.")

    def get_tab_settings(self) -> Dict:
         """Retrieves settings specific to this tab."""
         start_h, end_h = self.get_handles()
         settings = {
             'color_prep_start_handles': start_h,
             'color_prep_same_handles': self.same_handles_check.isChecked(),
             'color_prep_end_handles': end_h,
             'color_prep_separator': self.get_separator_frames(),
         }
         logger.debug("Retrieved settings from ColorPrepTab.")
         return settings
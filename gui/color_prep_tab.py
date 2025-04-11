# gui/color_prep_tab.py
"""
Widget for the 'Prepare for Color Grading' tab.
Contains settings specific to this stage (handles) and displays
relevant results using the ResultsDisplayWidget.
"""
import logging
from typing import Dict

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSpinBox, QPushButton, QSplitter)  # Added QSplitter

# Import the dedicated results display widget
from .results_display import ResultsDisplayWidget

logger = logging.getLogger(__name__)


class ColorPrepTabWidget(QWidget):
    """Widget managing the Color Grading Preparation stage."""
    # Signals emitted by this tab
    settingsChanged = pyqtSignal()
    analyzeSourcesClicked = pyqtSignal()
    calculateSegmentsClicked = pyqtSignal()
    exportEdlXmlClicked = pyqtSignal()

    def __init__(self, harvester_instance, parent=None):
        super().__init__(parent)
        # self.harvester = harvester_instance # Keep if direct access needed, but signals are better
        self.init_ui()
        self.connect_signals()
        logger.info("ColorPrepTabWidget initialized.")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)  # Add some padding

        # Use a splitter for Settings/Actions vs Results
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # --- Top part: Settings & Actions ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # Handle Frames Settings Group
        self.handles_group = QGroupBox("Handles for Color Prep")
        handles_layout = QFormLayout(self.handles_group)
        self.start_handles_spin = QSpinBox(minimum=0, maximum=1000, value=24, suffix=" frames")
        self.start_handles_spin.setToolTip("Frames added before AND after each segment for color grading.")
        # Removed end_handles and same_handles checkbox for simplicity in this stage
        # self.end_handles_spin = QSpinBox(...)
        # self.same_handles_check = QCheckBox(...)
        handles_layout.addRow("Handles (Start & End):", self.start_handles_spin)
        # handles_layout.addRow("", self.same_handles_check) # Removed
        top_layout.addWidget(self.handles_group)  # Add handles group to top layout

        # Action Buttons Layout
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 5, 0, 0)  # Add some top margin
        self.analyze_button = QPushButton("1. Analyze Sources")
        self.analyze_button.setToolTip("Parse edit files and find original sources using paths from Project Panel.")
        self.calculate_button = QPushButton("2. Calculate Segments")
        self.calculate_button.setToolTip("Calculate needed segments from originals, including handles.")
        self.export_button = QPushButton("3. Export EDL/XML...")
        self.export_button.setToolTip("Export the calculated segment list for color grading system.")
        # Set initial disabled state
        self.analyze_button.setEnabled(False)
        self.calculate_button.setEnabled(False)
        self.export_button.setEnabled(False)
        button_layout.addWidget(self.analyze_button)
        button_layout.addWidget(self.calculate_button)
        button_layout.addWidget(self.export_button)
        button_layout.addStretch()
        top_layout.addLayout(button_layout)  # Add buttons below handles

        splitter.addWidget(top_widget)  # Add settings/actions widget to splitter

        # --- Bottom part: Results Display ---
        self.results_widget = ResultsDisplayWidget()  # Use the dedicated results widget
        # Disable tabs not relevant for this stage (e.g., transcode status)
        # Find tab index by name - more robust than hardcoding index
        segments_tab_index = -1
        for i in range(self.results_widget.tabs.count()):
            if self.results_widget.tabs.tabText(i) == "Calculated Segments":
                segments_tab_index = i
                break
        if segments_tab_index != -1:
            # In Color Prep, the "Transcode Status" column isn't relevant yet
            # We could hide the column, or just leave it blank. Hiding is cleaner.
            self.results_widget.segments_table.setColumnHidden(4, True)  # Hide "Transcode Status"
            self.results_widget.segments_table.setColumnHidden(5, True)  # Hide "Error / Notes" (for transcode)

        splitter.addWidget(self.results_widget)  # Add results display to splitter

        # Set initial splitter sizes (less space for settings, more for results)
        splitter.setSizes([150, 500])
        logger.debug("ColorPrepTabWidget UI created.")

    def connect_signals(self):
        # Emit settingsChanged when handles value changes
        self.start_handles_spin.valueChanged.connect(self.settingsChanged)
        # self.same_handles_check.stateChanged.connect(self.settingsChanged) # Removed

        # Connect action buttons to this widget's signals for MainWindow to catch
        self.analyze_button.clicked.connect(self.analyzeSourcesClicked)
        self.calculate_button.clicked.connect(self.calculateSegmentsClicked)
        self.export_button.clicked.connect(self.exportEdlXmlClicked)
        logger.debug("ColorPrepTabWidget signals connected.")

    # Removed internal handle state update slots as end_handles is removed

    # --- Public Methods ---
    def get_handles(self) -> int:
        """Returns the number of handle frames set in this tab."""
        return self.start_handles_spin.value()

    def clear_tab(self):
        """Resets the tab settings and clears results."""
        self.start_handles_spin.setValue(24)  # Reset handles
        self.results_widget.clear_results()  # Clear the results display
        # Reset button states (will be updated by MainWindow)
        self.update_button_states(False, False, False)
        logger.info("ColorPrepTabWidget cleared.")

    def update_button_states(self, can_analyze: bool, can_calculate: bool, can_export: bool):
        """Updates the enabled state of action buttons specific to this tab."""
        self.analyze_button.setEnabled(can_analyze)
        self.calculate_button.setEnabled(can_calculate)
        self.export_button.setEnabled(can_export)
        logger.debug(
            f"ColorPrepTab buttons updated: Analyze={can_analyze}, Calculate={can_calculate}, Export={can_export}")

    def load_tab_settings(self, settings: Dict):
        """Loads settings specific to this tab (handles)."""
        self.start_handles_spin.setValue(settings.get('color_prep_handles', 24))  # Use specific key
        logger.debug("ColorPrepTab settings loaded.")

    def get_tab_settings(self) -> Dict:
        """Retrieves settings specific to this tab."""
        settings = {
            # Use specific key for saving
            'color_prep_handles': self.get_handles(),
        }
        logger.debug("Retrieved settings from ColorPrepTab.")
        return settings

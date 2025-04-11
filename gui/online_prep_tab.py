# gui/online_prep_tab.py
"""
Placeholder Widget for the 'Prepare for Online' tab.

Contains basic structure and placeholder methods required by MainWindow.
Actual UI and logic for online preparation will be implemented later.
"""
import logging
from typing import Dict

from PyQt5.QtCore import pyqtSignal, Qt  # Import QObject for signal inheritance
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

logger = logging.getLogger(__name__)


class OnlinePrepTabWidget(QWidget):
    """Placeholder widget managing the Online Preparation stage."""

    # --- Signals (Define even if not used yet) ---
    settingsChanged = pyqtSignal()
    # Define signals for potential actions, even if buttons don't exist yet
    analyzeGradedClicked = pyqtSignal()
    calculateOnlineClicked = pyqtSignal()
    transcodeClicked = pyqtSignal()

    def __init__(self, harvester_instance, parent=None):
        super().__init__(parent)
        # self.harvester = harvester_instance # Store if needed later
        self._init_ui()
        # No signals to connect internally yet
        logger.info("OnlinePrepTabWidget initialized (Placeholder).")

    def _init_ui(self):
        """Sets up a basic placeholder UI."""
        layout = QVBoxLayout(self)
        # Simple label indicating it's a placeholder
        label = QLabel("Online Preparation Stage\n\n(Functionality to be implemented)")
        label.setStyleSheet("font-style: italic; color: grey;")
        label.setAlignment(Qt.AlignCenter)  # Requires importing Qt from QtCore
        layout.addWidget(label)
        layout.addStretch()  # Push label to top

    # --- Placeholder Methods Called by MainWindow ---

    def clear_tab(self):
        """Resets the tab to its initial state (does nothing yet)."""
        # No UI elements to clear yet
        logger.info("OnlinePrepTabWidget cleared (Placeholder).")

    def load_tab_settings(self, settings: Dict):
        """Loads settings specific to this tab (does nothing yet)."""
        # No settings UI to load into yet
        logger.debug(f"OnlinePrepTab settings load called (Placeholder): {settings}")
        pass  # Ignore settings for now

    def get_tab_settings(self) -> Dict:
        """Retrieves settings specific to this tab (returns empty dict)."""
        # No settings UI to get from yet
        logger.debug("Retrieved settings from OnlinePrepTab (Placeholder).")
        return {}  # Return empty dictionary

    def update_button_states(self, can_analyze: bool, can_calculate: bool, can_transcode: bool):
        """Updates the enabled state of action buttons (does nothing yet)."""
        # No buttons to update yet
        logger.debug(
            f"OnlinePrepTab buttons update called (Placeholder): Analyze={can_analyze}, Calculate={can_calculate}, Transcode={can_transcode}")
        pass

    # --- Placeholder for Results Display (If results are shown directly here) ---
    # If using a separate ResultsDisplayWidget like in ColorPrepTab, these would go there.
    # def display_analysis_summary(self, summary: List[Dict]):
    #     pass
    # def display_plan_summary(self, summary: List[Dict]):
    #     pass
    # def display_unresolved_summary(self, summary: List[Dict]):
    #     pass

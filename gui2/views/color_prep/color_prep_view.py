# gui2/views/color_prep/color_prep_view.py
"""
Color Preparation Workflow View

Main container for the color preparation workflow, integrating configuration,
actions, and results components.
"""

import logging
from typing import Dict, Any, Optional

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QVBoxLayout

from ...models.ui_state_model import UIStateModel
from ...services.event_bus_service import EventBusService, EventType, EventData

from ..workflows.workflow_base_view import WorkflowBaseView
from .color_prep_config_panel import ColorPrepConfigPanel
from .color_prep_actions_panel import ColorPrepActionsPanel
from .color_prep_results_view import ColorPrepResultsView

logger = logging.getLogger(__name__)


class ColorPrepView(WorkflowBaseView):
    """
    Main view for the color preparation workflow.

    Integrates the config panel, actions panel, and results view
    into a complete workflow interface.
    """

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """
        Initialize the color preparation view.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            parent: Parent widget
        """
        super().__init__(ui_state, event_bus, parent)

        # Create and set up subcomponents
        self._setup_components()

        # Connect to additional events specific to color workflow
        self._connect_color_specific_events()

        logger.debug("ColorPrepView initialized")

    def _setup_components(self):
        """Create and set up the workflow components."""
        # Create the config panel
        self.config_panel = ColorPrepConfigPanel(self.ui_state, self.event_bus)
        self.set_config_panel(self.config_panel)

        # Create the actions panel
        self.actions_panel = ColorPrepActionsPanel(self.ui_state, self.event_bus)
        self.set_actions_panel(self.actions_panel)

        # Create the results view
        self.results_view = ColorPrepResultsView(self.ui_state, self.event_bus)
        self.set_results_view(self.results_view)

    def _connect_color_specific_events(self):
        """Connect to events specific to the color preparation workflow."""
        # Subscribe to calculation completed event to update UI
        self.event_bus.subscribe(EventType.COLOR_CALCULATION_COMPLETED, self._on_color_calculation_completed)

        # Subscribe to export completed event
        self.event_bus.subscribe(EventType.COLOR_EXPORT_COMPLETED, self._on_color_export_completed)

    @pyqtSlot(EventData)
    def _on_color_calculation_completed(self, event_data: EventData):
        """Handle color calculation completed event."""
        logger.debug("Color calculation completed, updating view")
        # Additional UI updates specific to color workflow can be added here
        # The basic updates are handled by the results view

    @pyqtSlot(EventData)
    def _on_color_export_completed(self, event_data: EventData):
        """Handle color export completed event."""
        logger.debug("Color export completed, updating view")
        # Additional UI updates specific to color workflow can be added here

    def clear_view(self):
        """Clear all view contents."""
        super().clear_view()

        # Clear config panel settings
        if self.config_panel:
            self.config_panel.reset_to_defaults()

        # Clear results
        if self.results_view:
            self.results_view.clear_results()

    def load_settings(self, settings: Dict[str, Any]):
        """
        Load settings for this workflow.

        Args:
            settings: Settings dictionary
        """
        if self.config_panel:
            self.config_panel.load_settings(settings)

    def get_settings(self) -> Dict[str, Any]:
        """
        Get current settings for this workflow.

        Returns:
            Dictionary of settings
        """
        if self.config_panel:
            return self.config_panel.get_settings()
        return {}
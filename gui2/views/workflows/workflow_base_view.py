# gui2/views/workflows/workflow_base_view.py
"""
Base Workflow View

Provides a foundation for workflow-specific views with common functionality.
"""

import logging
from typing import Optional, List, Dict, Any

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSplitter

from ...models.ui_state_model import UIStateModel
from ...services.event_bus_service import EventBusService, EventType, EventData

logger = logging.getLogger(__name__)


class WorkflowBaseView(QWidget):
    """
    Base class for workflow views.

    Provides common functionality for workflow views:
    - Config panel container
    - Actions panel container
    - Results view container
    - State management
    - Event handling

    Subclasses should implement the specific panels for their workflow.
    """

    # Signals for workflow actions
    workflowSettingsChanged = pyqtSignal()

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """
        Initialize the workflow view.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            parent: Parent widget
        """
        super().__init__(parent)

        self.ui_state = ui_state
        self.event_bus = event_bus

        # Layout elements to be set by subclasses
        self._config_panel: Optional[QWidget] = None
        self._actions_panel: Optional[QWidget] = None
        self._results_view: Optional[QWidget] = None

        # Initialize base UI structure
        self._init_base_ui()

        # Connect to global events
        self._connect_to_events()

        logger.debug(f"{self.__class__.__name__} base initialized")

    def _init_base_ui(self):
        """Initialize the base UI structure."""
        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Splitter for config/actions and results
        self.splitter = QSplitter(Qt.Vertical)
        self.main_layout.addWidget(self.splitter)

        # Top panel container
        self.top_container = QWidget()
        self.top_layout = QVBoxLayout(self.top_container)
        self.top_layout.setContentsMargins(5, 5, 5, 5)

        # Bottom panel container (for results)
        self.bottom_container = QWidget()
        self.bottom_layout = QVBoxLayout(self.bottom_container)
        self.bottom_layout.setContentsMargins(5, 5, 5, 5)

        # Add containers to splitter
        self.splitter.addWidget(self.top_container)
        self.splitter.addWidget(self.bottom_container)

        # Set initial sizes
        self.splitter.setSizes([200, 600])  # Top panel smaller, results larger

    def _connect_to_events(self):
        """Connect to global events."""
        # Subscribe to events
        self.event_bus.subscribe(EventType.PROJECT_LOADED, self._on_project_loaded)

        # Connect to UI state changes
        self.ui_state.bulkStateChanged.connect(self._update_from_ui_state)

    def set_config_panel(self, panel: QWidget):
        """
        Set the configuration panel.

        Args:
            panel: The configuration panel widget
        """
        # Remove old panel if exists
        if self._config_panel:
            self.top_layout.removeWidget(self._config_panel)
            self._config_panel.deleteLater()

        # Set new panel
        self._config_panel = panel
        if panel:
            self.top_layout.addWidget(panel)

    def set_actions_panel(self, panel: QWidget):
        """
        Set the actions panel.

        Args:
            panel: The actions panel widget
        """
        # Remove old panel if exists
        if self._actions_panel:
            self.top_layout.removeWidget(self._actions_panel)
            self._actions_panel.deleteLater()

        # Set new panel
        self._actions_panel = panel
        if panel:
            self.top_layout.addWidget(panel)

    def set_results_view(self, view: QWidget):
        """
        Set the results view.

        Args:
            view: The results view widget
        """
        # Remove old view if exists
        if self._results_view:
            self.bottom_layout.removeWidget(self._results_view)
            self._results_view.deleteLater()

        # Set new view
        self._results_view = view
        if view:
            self.bottom_layout.addWidget(view)

    def clear_view(self):
        """Clear all view contents."""
        # This method should be overridden by subclasses
        # to clear workflow-specific state
        logger.debug(f"{self.__class__.__name__} clear_view() called")

    def load_settings(self, settings: Dict[str, Any]):
        """
        Load settings for this workflow.

        Args:
            settings: Settings dictionary
        """
        # This method should be overridden by subclasses
        # to load workflow-specific settings
        logger.debug(f"{self.__class__.__name__} load_settings() called")

    def get_settings(self) -> Dict[str, Any]:
        """
        Get current settings for this workflow.

        Returns:
            Dictionary of settings
        """
        # This method should be overridden by subclasses
        # to return workflow-specific settings
        logger.debug(f"{self.__class__.__name__} get_settings() called")
        return {}

    @pyqtSlot(EventData)
    def _on_project_loaded(self, event_data: EventData):
        """Handle project loaded event."""
        # Check if this is a loaded project (has a path) or a new one
        project_path = getattr(event_data, 'project_path', None)
        is_new_project = project_path is None

        # Only clear view when a new project is created, not when loading an existing one
        if is_new_project:
            self.clear_view()

        # Update from current UI state
        self._update_from_ui_state()

    def _update_from_ui_state(self):
        """Update the view from the current UI state."""
        # This method should be overridden by subclasses
        # to update workflow-specific UI elements
        logger.debug(f"{self.__class__.__name__} _update_from_ui_state() called")
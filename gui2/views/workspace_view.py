# gui2/views/workspace_view.py
# -*- coding: utf-8 -*-
"""
Workspace View for TimelineHarvester

Central tabbed interface containing workflow areas for different tasks.
"""

import logging
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtWidgets import QWidget, QTabWidget, QVBoxLayout

from ..models.ui_state_model import UIStateModel
from ..services.event_bus_service import EventBusService, EventType, EventData

# Import actual workflow views
from .color_prep.color_prep_view import ColorPrepView
from .online_prep.online_prep_view import OnlinePrepView

logger = logging.getLogger(__name__)


class WorkspaceView(QWidget):
    """
    Tabbed widget container for different workflow areas.

    Responsibilities:
    - Host and manage different workflow tabs
    - Switch between workflows
    - Propagate events to/from workflow components
    """

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """Initialize the workspace view."""
        super().__init__(parent)

        self.ui_state = ui_state
        self.event_bus = event_bus

        self.color_prep_view: Optional[ColorPrepView] = None
        self.online_prep_view: Optional[OnlinePrepView] = None

        self._init_ui()
        self._connect_signals()

        logger.debug("WorkspaceView initialized")

    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create tab widget for different workflows
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setTabsClosable(False)

        # Add tab widget to layout - Tabs will be added by replace_placeholder_tabs
        main_layout.addWidget(self.tab_widget)

    def replace_placeholder_tabs(self, color_prep_view: ColorPrepView, online_prep_view: OnlinePrepView):
        """
        Replace initial placeholder tabs with actual workflow views.
        This method is now intended to be called from MainWindow after initialization.

        Args:
            color_prep_view: The color preparation workflow view instance.
            online_prep_view: The online preparation workflow view instance.
        """
        if self.tab_widget.count() > 0:
             logger.warning("Replacing existing tabs in WorkspaceView.")
             # Clear existing tabs if any (shouldn't happen with current flow)
             while self.tab_widget.count() > 0:
                 self.tab_widget.removeTab(0)

        # Store references and add actual views as tabs
        self.color_prep_view = color_prep_view
        self.tab_widget.addTab(self.color_prep_view, "1. Prepare for Color Grading")

        self.online_prep_view = online_prep_view
        self.tab_widget.addTab(self.online_prep_view, "2. Prepare for Online")

        logger.debug("Actual workflow views added to WorkspaceView tabs.")

    def _connect_signals(self):
        """Connect widget signals to handlers."""
        # Connect tab changed signal
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Subscribe to events
        self.event_bus.subscribe(EventType.PROJECT_LOADED, self._on_project_loaded)

        # Connect to UI state changes
        self.ui_state.stateChanged.connect(self._on_ui_state_changed)

    @pyqtSlot(int)
    def _on_tab_changed(self, index: int):
        """Handle tab change."""
        logger.debug(f"Active tab changed to index {index}")

        # Update UI state
        self.ui_state.set('active_tab_index', index)

        # Emit event
        self.event_bus.publish(EventData(
            EventType.TAB_CHANGED,
            tab_index=index,
            tab_name=self.tab_widget.tabText(index)
        ))

    @pyqtSlot(EventData)
    def _on_project_loaded(self, event_data: EventData):
        """Handle project loaded event."""
        # Reset to first tab
        self.tab_widget.setCurrentIndex(0)

    @pyqtSlot(str, object)
    def _on_ui_state_changed(self, key: str, value: object):
        """Handle UI state changes."""
        # If active tab index changes in UI state, update the tab widget
        if key == 'active_tab_index':
            index = int(value)
            if 0 <= index < self.tab_widget.count() and self.tab_widget.currentIndex() != index:
                self.tab_widget.setCurrentIndex(index)
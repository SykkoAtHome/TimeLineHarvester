# gui2/views/workspace_view.py
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

        self._init_ui()
        self._connect_signals()

        logger.debug("WorkspaceView initialized")

    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create tab widget for different workflows
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)  # More modern look
        self.tab_widget.setTabsClosable(False)  # Tabs cannot be closed

        # Create placeholder tabs - actual workflow views will be added later
        # For now, we'll just add placeholder widgets
        self.color_prep_placeholder = QWidget()
        self.online_prep_placeholder = QWidget()

        # Add tabs
        self.tab_widget.addTab(self.color_prep_placeholder, "1. Prepare for Color Grading")
        self.tab_widget.addTab(self.online_prep_placeholder, "2. Prepare for Online")

        # Add tab widget to layout
        main_layout.addWidget(self.tab_widget)

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

    def add_workflow_tab(self, widget: QWidget, title: str, index: Optional[int] = None):
        """
        Add or replace a workflow tab.

        Args:
            widget: The workflow widget to add
            title: The tab title
            index: Optional index where to insert the tab. If None, appends to the end.
                  If the index already exists, replaces the tab at that position.
        """
        if index is not None and 0 <= index < self.tab_widget.count():
            # Replace existing tab
            old_widget = self.tab_widget.widget(index)
            self.tab_widget.removeTab(index)
            self.tab_widget.insertTab(index, widget, title)

            # Clean up old widget if needed
            if old_widget:
                old_widget.deleteLater()
        else:
            # Add new tab
            self.tab_widget.addTab(widget, title)

    def replace_placeholder_tabs(self, color_prep_view: QWidget, online_prep_view: QWidget):
        """
        Replace placeholder tabs with actual workflow views.

        Args:
            color_prep_view: The color preparation workflow view
            online_prep_view: The online preparation workflow view
        """
        # Replace color prep tab
        self.add_workflow_tab(color_prep_view, "1. Prepare for Color Grading", 0)

        # Replace online prep tab
        self.add_workflow_tab(online_prep_view, "2. Prepare for Online", 1)

        # Clean up placeholders
        self.color_prep_placeholder.deleteLater()
        self.online_prep_placeholder.deleteLater()

        # Reset references
        self.color_prep_placeholder = None
        self.online_prep_placeholder = None

        logger.debug("Placeholder tabs replaced with actual workflow views")
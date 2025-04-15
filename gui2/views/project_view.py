# gui2/views/project_view.py
"""
Project View for TimelineHarvester

Displays and manages project settings and file/path configurations.
"""

import logging
from typing import List

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtWidgets import (
    QWidget, QGroupBox, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel
)

from ..models.ui_state_model import UIStateModel
from ..services.event_bus_service import EventBusService, EventType, EventData
from ..widgets.file_path_selector import FilePathSelector

logger = logging.getLogger(__name__)


class ProjectView(QWidget):
    """
    Widget for displaying and managing project settings.

    Responsibilities:
    - Display and edit project files and paths
    - Handle project configuration settings
    - Update the UI state when settings change
    """

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """Initialize the project view."""
        super().__init__(parent)

        self.ui_state = ui_state
        self.event_bus = event_bus

        self._init_ui()
        self._connect_signals()

        # Initial update from UI state
        self._update_from_ui_state()

        logger.debug("ProjectView initialized")

    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Use splitter for resizable sections
        splitter = QSplitter(Qt.Horizontal)

        # Edit Files section
        edit_files_group = QGroupBox("Edit Files")
        edit_files_layout = QVBoxLayout(edit_files_group)
        self.edit_files_selector = FilePathSelector(
            title="",  # GroupBox has title
            file_filter="Edit Files (*.edl *.xml *.fcpxml *.aaf);;All Files (*.*)",
            select_directories=False,
            allow_multiple=True
        )
        edit_files_layout.addWidget(self.edit_files_selector)
        splitter.addWidget(edit_files_group)

        # Original Source Paths section
        original_paths_group = QGroupBox("Original Source Paths")
        original_paths_layout = QVBoxLayout(original_paths_group)
        self.original_paths_selector = FilePathSelector(
            title="",
            select_directories=True,
            allow_multiple=True
        )
        original_paths_layout.addWidget(self.original_paths_selector)
        splitter.addWidget(original_paths_group)

        # Graded Source Paths section
        graded_paths_group = QGroupBox("Graded Source Paths (Optional)")
        graded_paths_layout = QVBoxLayout(graded_paths_group)
        self.graded_paths_selector = FilePathSelector(
            title="",
            select_directories=True,
            allow_multiple=True
        )
        graded_paths_layout.addWidget(self.graded_paths_selector)
        splitter.addWidget(graded_paths_group)

        # Add splitter to main layout
        main_layout.addWidget(splitter)

        # Set equal widths initially
        splitter.setSizes([1, 1, 1])

    def _connect_signals(self):
        """Connect widget signals to handlers."""
        # Connect path selector signals
        self.edit_files_selector.pathsChanged.connect(self._on_edit_files_changed)
        self.original_paths_selector.pathsChanged.connect(self._on_original_paths_changed)
        self.graded_paths_selector.pathsChanged.connect(self._on_graded_paths_changed)

        # Subscribe to events
        self.event_bus.subscribe(EventType.PROJECT_LOADED, self._on_project_loaded)

        # Connect to UI state changes
        self.ui_state.bulkStateChanged.connect(self._update_from_ui_state)

    @pyqtSlot(list)
    def _on_edit_files_changed(self, paths: List[str]):
        """Handle changes to the edit files list."""
        logger.debug(f"Edit files changed: {len(paths)} files")
        # Publish event through event bus to inform controllers
        self.event_bus.publish(EventData(
            EventType.SETTINGS_CHANGED,
            setting="edit_files",
            value=paths
        ))

    @pyqtSlot(list)
    def _on_original_paths_changed(self, paths: List[str]):
        """Handle changes to original source paths."""
        logger.debug(f"Original source paths changed: {len(paths)} paths")
        # Publish event through event bus to inform controllers
        self.event_bus.publish(EventData(
            EventType.SETTINGS_CHANGED,
            setting="source_search_paths",
            value=paths
        ))

    @pyqtSlot(list)
    def _on_graded_paths_changed(self, paths: List[str]):
        """Handle changes to graded source paths."""
        logger.debug(f"Graded source paths changed: {len(paths)} paths")
        # Publish event through event bus to inform controllers
        self.event_bus.publish(EventData(
            EventType.SETTINGS_CHANGED,
            setting="graded_source_paths",
            value=paths
        ))

    @pyqtSlot(EventData)
    def _on_project_loaded(self, event_data: EventData):
        """Handle project loaded event."""
        # Update UI from current state
        self._update_from_ui_state()

    def _update_from_ui_state(self):
        """Update UI components from the current UI state."""
        # Update file selectors without triggering change events
        self.edit_files_selector.blockSignals(True)
        self.original_paths_selector.blockSignals(True)
        self.graded_paths_selector.blockSignals(True)

        # Set paths from state
        self.edit_files_selector.set_paths(self.ui_state.get('edit_files', []))
        self.original_paths_selector.set_paths(self.ui_state.get('source_search_paths', []))
        self.graded_paths_selector.set_paths(self.ui_state.get('graded_source_paths', []))

        # Restore signals
        self.edit_files_selector.blockSignals(False)
        self.original_paths_selector.blockSignals(False)
        self.graded_paths_selector.blockSignals(False)
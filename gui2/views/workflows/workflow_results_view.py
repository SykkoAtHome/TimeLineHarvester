# gui2/views/workflows/workflow_results_view.py
"""
Workflow Results View

Provides a tabbed interface for displaying workflow results:
- Analysis results
- Segments table
- Unresolved items
- Timeline visualization
"""

import logging
from typing import Optional, List, Dict, Any

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QComboBox, QLabel, QCheckBox
)

from ...models.ui_state_model import UIStateModel
from ...services.event_bus_service import EventBusService, EventType, EventData
from ...widgets.tables.edit_shots_table import EditShotsTable
from ...widgets.tables.segments_table import SegmentsTable
from ...widgets.tables.unresolved_items_table import UnresolvedItemsTable
from ...widgets.timeline_display import TimelineDisplayWidget

logger = logging.getLogger(__name__)


class WorkflowResultsView(QWidget):
    """
    Widget for displaying workflow results in a tabbed interface.

    Provides tabs for:
    - Analysis results table
    - Segments table
    - Unresolved items table
    - Timeline visualization

    Also provides controls for time display format and filters.
    """

    def __init__(
            self,
            ui_state: UIStateModel,
            event_bus: EventBusService,
            workflow: str = 'color',
            parent=None
    ):
        """
        Initialize the workflow results view.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            workflow: Workflow type ('color' or 'online')
            parent: Parent widget
        """
        super().__init__(parent)

        self.ui_state = ui_state
        self.event_bus = event_bus
        self.workflow = workflow

        # Initialize UI
        self._init_ui()
        self._connect_signals()

        logger.debug(f"WorkflowResultsView for {workflow} initialized")

    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Controls row
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(5, 5, 5, 0)

        # Time format selector
        controls_layout.addWidget(QLabel("Time Display:"))
        self.time_format_combo = QComboBox()
        self.time_format_combo.addItems(["Timecode", "Frames"])
        controls_layout.addWidget(self.time_format_combo)

        # Hide unresolved checkbox
        self.hide_unresolved_checkbox = QCheckBox("Hide Unresolved Items")
        controls_layout.addWidget(self.hide_unresolved_checkbox)

        # Add stretch to push controls to the left
        controls_layout.addStretch()

        main_layout.addLayout(controls_layout)

        # Tabs for results
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # Create and add tables
        self.edit_shots_table = EditShotsTable()
        self.segments_table = SegmentsTable()
        self.unresolved_table = UnresolvedItemsTable()
        self.timeline_widget = TimelineDisplayWidget()

        # Add tabs
        self.tab_widget.addTab(self.edit_shots_table, "Analysis Results")
        self.tab_widget.addTab(self.segments_table, "Segments")
        self.tab_widget.addTab(self.unresolved_table, "Unresolved Items")
        self.tab_widget.addTab(self.timeline_widget, "Timeline View")

        main_layout.addWidget(self.tab_widget, 1)  # Stretch

    def _connect_signals(self):
        """Connect widget signals to handlers."""
        # Connect time format combo
        self.time_format_combo.currentTextChanged.connect(self._on_time_format_changed)

        # Connect hide unresolved checkbox
        self.hide_unresolved_checkbox.stateChanged.connect(self._on_hide_unresolved_changed)

        # Connect to UI state changes
        data_key_prefix = 'color_' if self.workflow == 'color' else 'online_'
        self.ui_state.stateChanged.connect(lambda key, value: self._on_ui_state_changed(key, value, data_key_prefix))

        # Subscribe to events
        self.event_bus.subscribe(EventType.ANALYSIS_COMPLETED, self._on_analysis_completed)
        if self.workflow == 'color':
            self.event_bus.subscribe(EventType.COLOR_CALCULATION_COMPLETED, self._on_calculation_completed)
        else:
            self.event_bus.subscribe(EventType.ONLINE_CALCULATION_COMPLETED, self._on_calculation_completed)
            self.event_bus.subscribe(EventType.TRANSCODE_PROGRESS, self._on_transcode_progress)
            self.event_bus.subscribe(EventType.TRANSCODE_COMPLETED, self._on_transcode_completed)

    @pyqtSlot(str)
    def _on_time_format_changed(self, format_name: str):
        """Handle time format change."""
        logger.debug(f"Time format changed to: {format_name}")

        # Update table time displays
        self.edit_shots_table.set_time_format(format_name)
        self.segments_table.set_time_format(format_name)

    @pyqtSlot(int)
    def _on_hide_unresolved_changed(self, state: int):
        """Handle hide unresolved change."""
        hide = (state == Qt.Checked)
        logger.debug(f"Hide unresolved changed to: {hide}")

        # Update edit shots table filter
        self.edit_shots_table.set_hide_unresolved(hide)

    def _on_ui_state_changed(self, key: str, value: Any, data_key_prefix: str):
        """
        Handle UI state changes.

        Args:
            key: Changed state key
            value: New value
            data_key_prefix: Prefix for workflow-specific data keys
        """
        # Check for data updates
        analysis_data_key = 'analysis_data'
        segments_data_key = f'{data_key_prefix}segments_data'
        unresolved_data_key = 'unresolved_data'

        if key == analysis_data_key and value:
            self.update_analysis_data(value)
        elif key == segments_data_key and value:
            self.update_segments_data(value)
        elif key == unresolved_data_key and value:
            self.update_unresolved_data(value)

    @pyqtSlot(EventData)
    def _on_analysis_completed(self, event_data: EventData):
        """Handle analysis completed event."""
        # Analysis results are updated via UI state changes
        # Switch to analysis results tab
        self.tab_widget.setCurrentIndex(0)

    @pyqtSlot(EventData)
    def _on_calculation_completed(self, event_data: EventData):
        """Handle calculation completed event."""
        # Segments data is updated via UI state changes
        # Switch to segments tab
        self.tab_widget.setCurrentIndex(1)

    @pyqtSlot(EventData)
    def _on_transcode_progress(self, event_data: EventData):
        """Handle transcode progress event."""
        # Update segments table with latest status
        segments_data = self.ui_state.get(f'online_segments_data')
        if segments_data:
            self.update_segments_data(segments_data)

    @pyqtSlot(EventData)
    def _on_transcode_completed(self, event_data: EventData):
        """Handle transcode completed event."""
        # Final update of segments data
        segments_data = self.ui_state.get(f'online_segments_data')
        if segments_data:
            self.update_segments_data(segments_data)

    def update_analysis_data(self, analysis_data: List[Dict[str, Any]]):
        """
        Update analysis results table.

        Args:
            analysis_data: Analysis data from facade
        """
        logger.debug(f"Updating analysis data with {len(analysis_data)} items")
        self.edit_shots_table.populate_table(analysis_data)

    def update_segments_data(self, segments_data: List[Dict[str, Any]]):
        """
        Update segments table and timeline.

        Args:
            segments_data: Segments data from facade
        """
        logger.debug(f"Updating segments data with {len(segments_data)} items")

        # Update segments table
        self.segments_table.populate_table(segments_data)

        # Update timeline display
        # Determine handle frames and separator frames
        handle_frames = self.ui_state.get(f'{self.workflow}_handle_frames', 0)
        separator_frames = 0
        if self.workflow == 'color':
            separator_frames = self.ui_state.get('color_separator_frames', 0)

        # Update timeline frame rate
        frame_rate = None
        for segment in segments_data:
            if 'frame_rate' in segment and segment['frame_rate'] > 0:
                frame_rate = segment['frame_rate']
                break

        if frame_rate:
            self.timeline_widget.set_frame_rate(frame_rate)

        # Convert segments data for timeline display
        timeline_data = []
        for segment in segments_data:
            # Skip segments without duration
            if 'duration_sec' not in segment or segment['duration_sec'] <= 0:
                continue

            # Create timeline segment data
            timeline_segment = {
                'segment_id': segment.get('segment_id', f"Segment {len(timeline_data) + 1}"),
                'start_sec': segment.get('start_sec', 0),
                'duration_sec': segment.get('duration_sec', 0),
                'status': segment.get('status', 'pending')
            }

            # Add handle information if available
            if handle_frames > 0 and frame_rate:
                handle_sec = handle_frames / frame_rate
                timeline_segment['handle_start_sec'] = handle_sec
                timeline_segment['handle_end_sec'] = handle_sec

            timeline_data.append(timeline_segment)

        # Update timeline with data
        self.timeline_widget.update_timeline(timeline_data, separator_frames)

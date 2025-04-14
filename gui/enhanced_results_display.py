# gui/enhanced_results_display.py
"""
Enhanced Results Display Widget for TimelineHarvester

Provides an improved display of analysis results, segments, and unresolved items
with more detailed information and visual timeline representation.
"""

import logging
import os
from typing import List, Dict, Optional, Any, Union, Tuple

from PyQt5.QtCore import Qt, pyqtSlot, QVariant, pyqtSignal
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView, QCheckBox, QComboBox,
                             QLabel, QSizePolicy, QSpacerItem, QSplitter, QFrame)

from opentimelineio import opentime
from utils.time_utils import ensure_non_negative_time

# Import custom timeline display widget
# Assuming the file is placed in gui/custom_widgets/timeline_display.py
from .custom_widgets.timeline_display import TimelineDisplayWidget

logger = logging.getLogger(__name__)

# Define custom roles to store the raw RationalTime object and rate
RawTimeRole = Qt.UserRole + 1
RateRole = Qt.UserRole + 2


# --- Helper Function for Formatting Time ---
def format_time(value: Optional[opentime.RationalTime], rate: Optional[float], display_mode: str) -> str:
    """Format a time value as timecode or frames."""
    if not isinstance(value, opentime.RationalTime):
        return "N/A"

    current_rate = rate
    if current_rate is None or current_rate <= 0:
        inferred_rate = getattr(value, 'rate', None)
        if inferred_rate and inferred_rate > 0:
            current_rate = inferred_rate
        else:
            return f"{value.value} (Rate?)"

    current_rate = float(current_rate)
    try:
        if display_mode == "Timecode":
            result_str = opentime.to_timecode(value, current_rate)
        elif display_mode == "Frames":
            frames = round(value.rescaled_to(current_rate).value) if value.rate != current_rate else round(value.value)
            result_str = str(int(frames))
        else:  # Fallback
            result_str = str(value)
        return result_str
    except ValueError as ve:
        if "non-dropframe" in str(ve).lower():
            try:
                result_str = opentime.to_timecode(value, current_rate, opentime.DropFrameRate.ForceNo)
                return result_str
            except Exception:
                pass  # Fallback to error below
        logger.warning(f" -> Formatting FAILED (ValueError): {ve}", exc_info=False)
        return f"ErrFmt ({value.value})"
    except Exception as e:
        logger.warning(f" -> Formatting FAILED (Other): {e}", exc_info=False)
        return f"Err ({value.value})"


# --- Helper to calculate inclusive end ---
def get_inclusive_end(exclusive_end_rt, rate):
    """Calculate the inclusive end time (last frame) from an exclusive end time."""
    if isinstance(exclusive_end_rt, opentime.RationalTime) and rate and rate > 0:
        try:
            one_frame = opentime.RationalTime(1, rate)
            incl_end = exclusive_end_rt - one_frame
            # Ensure start time of the frame is not negative
            return opentime.RationalTime(max(0, incl_end.value), incl_end.rate)
        except Exception as e:
            logger.warning(f"Error calculating inclusive end time for {exclusive_end_rt}: {e}")
            pass  # Fall through to return None
    return None


class EnhancedResultsDisplayWidget(QWidget):
    """Enhanced widget for displaying analysis results with detailed tables and visualizations."""

    # --- Column definitions for the analysis table ---
    COL_IDX = 0
    COL_CLIP_NAME = 1
    COL_EDIT_MEDIA_ID = 2
    COL_SOURCE_PATH = 3
    COL_STATUS = 4
    COL_SOURCE_IN = 5
    COL_SOURCE_OUT = 6
    COL_SOURCE_DUR = 7
    COL_SOURCE_POINT_IN = 8
    COL_SOURCE_POINT_OUT = 9
    COL_SOURCE_POINT_DUR = 10
    COL_EDIT_IN = 11
    COL_EDIT_OUT = 12
    COL_EDIT_DUR = 13

    # Use dict for easier lookup of time columns
    TIME_COLUMNS_ANALYSIS = {
        COL_SOURCE_IN: 'source_in_rt',
        COL_SOURCE_OUT: 'source_out_rt_excl',
        COL_SOURCE_DUR: 'source_duration_rt',
        COL_SOURCE_POINT_IN: 'source_point_in_rt',
        COL_SOURCE_POINT_OUT: 'source_point_out_rt_excl',
        COL_SOURCE_POINT_DUR: 'source_point_duration_rt',
        COL_EDIT_IN: 'edit_in_rt',
        COL_EDIT_OUT: 'edit_out_rt_excl',
        COL_EDIT_DUR: 'edit_duration_rt'
    }

    # Map column to its relevant rate key
    RATE_KEYS_ANALYSIS = {
        COL_SOURCE_IN: 'source_rate',
        COL_SOURCE_OUT: 'source_rate',
        COL_SOURCE_DUR: 'source_rate',
        COL_SOURCE_POINT_IN: 'source_point_rate',
        COL_SOURCE_POINT_OUT: 'source_point_rate',
        COL_SOURCE_POINT_DUR: 'source_point_rate',
        COL_EDIT_IN: 'sequence_rate',
        COL_EDIT_OUT: 'sequence_rate',
        COL_EDIT_DUR: 'sequence_rate'
    }

    # Set of duration columns
    IS_DURATION_COLUMN = {COL_SOURCE_DUR, COL_SOURCE_POINT_DUR, COL_EDIT_DUR}
    TOTAL_ANALYSIS_COLS = 14

    # --- Column definitions for the segments table ---
    SEG_COL_IDX = 0
    SEG_COL_NAME = 1
    SEG_COL_SOURCE_NAME = 2
    SEG_COL_SOURCE_PATH = 3
    SEG_COL_TC_IN = 4
    SEG_COL_TC_OUT = 5
    SEG_COL_USE_TC_IN = 6
    SEG_COL_USE_TC_OUT = 7
    SEG_COL_DURATION = 8
    SEG_COL_STATUS = 9
    SEG_COL_ERROR = 10

    # Time columns in segments table
    TIME_COLUMNS_SEGMENTS = {
        SEG_COL_TC_IN: 'tc_in_rt',
        SEG_COL_TC_OUT: 'tc_out_rt',
        SEG_COL_USE_TC_IN: 'use_tc_in_rt',
        SEG_COL_USE_TC_OUT: 'use_tc_out_rt'
    }

    # Duration column in segments table
    DURATION_COLUMN_SEGMENTS = {SEG_COL_DURATION}

    def __init__(self, parent=None):
        """Initialize the enhanced results display widget."""
        super().__init__(parent)
        self._current_time_format = "Timecode"
        self._hide_unresolved = False
        self._segment_separator_frames = 0
        self._handle_frames = 0
        self._segments_frame_rate = 25.0  # Default frame rate

        # Initialize the UI
        self._init_ui()
        self._connect_signals()
        logger.debug("EnhancedResultsDisplayWidget initialized.")

    def _init_ui(self):
        """Initialize the user interface components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create the tab widget
        self.tabs = QTabWidget()

        # Create the tab pages
        self.analysis_tab = QWidget()
        self.segments_tab = QWidget()
        self.unresolved_tab = QWidget()

        # Set up individual tabs
        self._setup_analysis_tab()
        self._setup_segments_tab()
        self._setup_unresolved_tab()

        # Add tabs to the tab widget
        self.tabs.addTab(self.analysis_tab, "Source Analysis Status")
        self.tabs.addTab(self.segments_tab, "Calculated Segments")
        self.tabs.addTab(self.unresolved_tab, "Unresolved / Errors")

        # Add tab widget to the main layout
        main_layout.addWidget(self.tabs)

    def _setup_analysis_tab(self):
        """Set up the Source Analysis Status tab (keep simple for now)."""
        layout = QVBoxLayout(self.analysis_tab)
        layout.setContentsMargins(2, 2, 2, 2)

        # Controls layout (time format, hide unresolved checkbox)
        controls_layout = QHBoxLayout()

        # Time format control
        controls_layout.addWidget(QLabel("Time Display:"))
        self.time_format_combo = QComboBox()
        self.time_format_combo.addItems(["Timecode", "Frames"])
        controls_layout.addWidget(self.time_format_combo)

        # Add a spacer
        controls_layout.addSpacerItem(QSpacerItem(20, 10, QSizePolicy.Fixed, QSizePolicy.Minimum))

        # Hide unresolved control
        self.hide_unresolved_checkbox = QCheckBox("Hide Unresolved (Not Found / Error)")
        controls_layout.addWidget(self.hide_unresolved_checkbox)

        # Add stretch to push controls to the left
        controls_layout.addStretch()

        # Add controls to the main layout
        layout.addLayout(controls_layout)

        # Create a splitter for future enhancement (placeholder for now)
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)  # Give the splitter stretch factor

        # Analysis table
        self.analysis_table = QTableWidget()
        self.analysis_table.setColumnCount(self.TOTAL_ANALYSIS_COLS)
        self.analysis_table.setHorizontalHeaderLabels([
            "#", "Clip Name", "Edit Media ID", "Source Path", "Status",
            "Source IN", "Source OUT", "Source Dur",
            "Src Pt IN", "Src Pt OUT", "Src Pt Dur",
            "Edit IN", "Edit OUT", "Edit Dur"
        ])

        self._configure_table_widget(self.analysis_table)

        # Set column resize modes
        header = self.analysis_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_CLIP_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_EDIT_MEDIA_ID, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_SOURCE_PATH, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_IDX, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeToContents)

        # Make time columns resize to contents
        for col_idx in self.TIME_COLUMNS_ANALYSIS:
            header.setSectionResizeMode(col_idx, QHeaderView.ResizeToContents)

        # Add analysis table to splitter
        splitter.addWidget(self.analysis_table)

        # Add placeholder for future timeline visualization in analysis tab
        analysis_timeline_placeholder = QFrame()
        analysis_timeline_placeholder.setFrameShape(QFrame.StyledPanel)
        analysis_timeline_placeholder.setFrameShadow(QFrame.Sunken)
        analysis_timeline_placeholder.setMinimumHeight(100)
        analysis_timeline_placeholder.setMaximumHeight(150)

        # Add a label inside the placeholder
        placeholder_layout = QVBoxLayout(analysis_timeline_placeholder)
        placeholder_label = QLabel("Timeline visualization will be added here in future updates")
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_label.setStyleSheet("color: gray; font-style: italic;")
        placeholder_layout.addWidget(placeholder_label)

        # Add placeholder to splitter
        splitter.addWidget(analysis_timeline_placeholder)

        # Set initial splitter sizes (more space for table, less for placeholder)
        splitter.setSizes([700, 100])

    def _setup_segments_tab(self):
        """Set up the Calculated Segments tab with enhanced features."""
        layout = QVBoxLayout(self.segments_tab)
        layout.setContentsMargins(2, 2, 2, 2)

        # Controls layout
        controls_layout = QHBoxLayout()

        # Time format control
        controls_layout.addWidget(QLabel("Time Display:"))
        self.segments_time_format_combo = QComboBox()
        self.segments_time_format_combo.addItems(["Timecode", "Frames"])
        controls_layout.addWidget(self.segments_time_format_combo)

        # Add stretch to push controls to the left
        controls_layout.addStretch()

        # Add controls to the main layout
        layout.addLayout(controls_layout)

        # Create a splitter for table and timeline visualization
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)  # Give the splitter stretch factor

        # Enhanced segments table
        self.segments_table = QTableWidget()
        self.segments_table.setColumnCount(11)  # Increased column count
        self.segments_table.setHorizontalHeaderLabels([
            "#", "Segment Name", "Source Name", "Source Path",
            "Segment TC IN", "Segment TC OUT", "Use TC IN", "Use TC OUT",
            "Duration", "Status", "Error/Notes"
        ])

        self._configure_table_widget(self.segments_table)

        # Set column resize modes
        header = self.segments_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(self.SEG_COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.SEG_COL_SOURCE_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.SEG_COL_SOURCE_PATH, QHeaderView.Stretch)
        header.setSectionResizeMode(self.SEG_COL_ERROR, QHeaderView.Stretch)
        header.setSectionResizeMode(self.SEG_COL_IDX, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.SEG_COL_STATUS, QHeaderView.ResizeToContents)

        # Make time columns resize to contents
        for col_idx in self.TIME_COLUMNS_SEGMENTS:
            header.setSectionResizeMode(col_idx, QHeaderView.ResizeToContents)

        # Add segments table to splitter
        splitter.addWidget(self.segments_table)

        # Add timeline visualization
        self.segments_timeline = TimelineDisplayWidget()
        self.segments_timeline.setMinimumHeight(150)

        # Add timeline to splitter
        splitter.addWidget(self.segments_timeline)

        # Set initial splitter sizes (more space for table, less for timeline)
        splitter.setSizes([600, 200])

    def _setup_unresolved_tab(self):
        """Set up the Unresolved / Errors tab with list of unresolved items."""
        layout = QVBoxLayout(self.unresolved_tab)
        layout.setContentsMargins(2, 2, 2, 2)

        # Unresolved table
        self.unresolved_table = QTableWidget()
        self.unresolved_table.setColumnCount(4)
        self.unresolved_table.setHorizontalHeaderLabels([
            "Clip Name", "Edit Media ID", "Lookup Status", "Edit Range"
        ])

        self._configure_table_widget(self.unresolved_table)

        # Set column resize modes
        header = self.unresolved_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Edit Media ID column
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Status column

        # Add unresolved table to layout
        layout.addWidget(self.unresolved_table)

    def _configure_table_widget(self, table: QTableWidget):
        """Configure common settings for table widgets."""
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.setSortingEnabled(True)

        # Configure header
        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setSectionResizeMode(QHeaderView.Interactive)

    def _connect_signals(self):
        """Connect widget signals to their handlers."""
        # Analysis tab signals
        self.time_format_combo.currentTextChanged.connect(self._on_analysis_time_format_changed)
        self.hide_unresolved_checkbox.stateChanged.connect(self._on_hide_unresolved_changed)

        # Segments tab signals
        self.segments_time_format_combo.currentTextChanged.connect(self._on_segments_time_format_changed)

    @pyqtSlot(str)
    def _on_analysis_time_format_changed(self, new_format: str):
        """Handle time format change in the analysis tab."""
        logger.debug(f"Analysis time format changed to: {new_format}")
        self._current_time_format = new_format
        self._refresh_analysis_time_display()

    @pyqtSlot(str)
    def _on_segments_time_format_changed(self, new_format: str):
        """Handle time format change in the segments tab."""
        logger.debug(f"Segments time format changed to: {new_format}")
        self._current_time_format = new_format
        self._refresh_segments_time_display()

    @pyqtSlot(int)
    def _on_hide_unresolved_changed(self, state: int):
        """Handle change in the hide unresolved checkbox."""
        self._hide_unresolved = (state == Qt.Checked)
        self._apply_row_visibility_filter()

    def _apply_row_visibility_filter(self):
        """Apply the filter to hide unresolved rows in the analysis table."""
        table = self.analysis_table
        logger.debug(f"Applying row visibility filter (Hide unresolved: {self._hide_unresolved})")
        table.blockSignals(True)
        for row in range(table.rowCount()):
            status_item = table.item(row, self.COL_STATUS)
            should_hide = False
            if status_item:
                status_text = status_item.text().lower()
                is_unresolved = ("not_found" in status_text or "error" in status_text)
                should_hide = self._hide_unresolved and is_unresolved
            if table.isRowHidden(row) != should_hide:
                table.setRowHidden(row, should_hide)
        table.blockSignals(False)

    def _refresh_analysis_time_display(self):
        """Refreshes the display text of all time cells in the analysis table."""
        logger.debug(f"Refreshing analysis time display for format: {self._current_time_format}")
        table = self.analysis_table
        table.blockSignals(True)
        for row in range(table.rowCount()):
            for col_idx in self.TIME_COLUMNS_ANALYSIS.keys():
                item = table.item(row, col_idx)
                if item:
                    rt_value = item.data(RawTimeRole)
                    rate = item.data(RateRole)
                    if isinstance(rt_value, opentime.RationalTime):
                        self._update_cell_time_display(item, rt_value, rate)
        table.blockSignals(False)
        table.viewport().update()  # Force redraw

    def _refresh_segments_time_display(self):
        """Refreshes the display text of all time cells in the segments table."""
        logger.debug(f"Refreshing segments time display for format: {self._current_time_format}")
        table = self.segments_table
        table.blockSignals(True)
        for row in range(table.rowCount()):
            for col_idx in list(self.TIME_COLUMNS_SEGMENTS.keys()) + list(self.DURATION_COLUMN_SEGMENTS):
                item = table.item(row, col_idx)
                if item:
                    rt_value = item.data(RawTimeRole)
                    rate = item.data(RateRole)
                    if isinstance(rt_value, opentime.RationalTime):
                        self._update_cell_time_display(item, rt_value, rate)
        table.blockSignals(False)
        table.viewport().update()  # Force redraw

    def _update_cell_time_display(self, item: QTableWidgetItem, rt_value: Optional[opentime.RationalTime],
                                  rate: Optional[float]):
        """Helper to update the display text of a single time cell."""
        if item and isinstance(rt_value, opentime.RationalTime):
            display_text = format_time(rt_value, rate, self._current_time_format)
            item.setText(display_text)
        elif item:  # Handle cases where rt_value might be None or invalid
            item.setText("N/A")

    def clear_results(self):
        """Clear all result tables and reset UI state."""
        logger.debug("Clearing EnhancedResultsDisplayWidget tables and timelines.")

        # Clear all tables
        for table in [self.analysis_table, self.segments_table, self.unresolved_table]:
            table.blockSignals(True)
            table.setSortingEnabled(False)
            table.setRowCount(0)
            table.setSortingEnabled(True)
            table.blockSignals(False)

        # Reset UI controls
        self.time_format_combo.setCurrentIndex(0)
        self.segments_time_format_combo.setCurrentIndex(0)
        self.hide_unresolved_checkbox.setChecked(False)

        # Clear timeline visualization
        self.segments_timeline.clear()

    def display_analysis_summary(self, analysis_summary_data: List[Dict]):
        """Populates the analysis table with data, storing raw times in items."""
        logger.debug(f"Populating analysis summary table for {len(analysis_summary_data)} shots.")
        table = self.analysis_table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setRowCount(len(analysis_summary_data))

        status_colors = {"found": QBrush(QColor(200, 255, 200)), "not_found": QBrush(QColor(255, 200, 200)),
                         "error": QBrush(QColor(255, 160, 122)), "pending": QBrush(QColor(255, 255, 200)),
                         "default": QBrush(Qt.white)}

        for row, shot_info in enumerate(analysis_summary_data):
            status = shot_info.get('status', 'unknown').lower()
            row_brush = status_colors.get(status, status_colors["default"])

            def create_std_item(value: Any, tooltip: Optional[str] = None) -> QTableWidgetItem:
                item = QTableWidgetItem(str(value))
                item.setBackground(row_brush)
                if tooltip:
                    item.setToolTip(tooltip)
                return item

            def create_time_item(rt_value: Optional[opentime.RationalTime], rate: Optional[float]) -> QTableWidgetItem:
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setBackground(row_brush)
                numeric_val = None
                if isinstance(rt_value, opentime.RationalTime) and rate and rate > 0:
                    item.setData(RawTimeRole, rt_value)
                    item.setData(RateRole, rate)
                    try:
                        numeric_val = int(round(rt_value.rescaled_to(rate).value))
                    except:
                        pass
                elif isinstance(rt_value, opentime.RationalTime):  # Store even if rate is bad
                    item.setData(RawTimeRole, rt_value)
                    item.setData(RateRole, rate)
                if numeric_val is not None: item.setData(Qt.EditRole, QVariant(numeric_val))
                # Set initial display text using the helper
                self._update_cell_time_display(item, rt_value, rate)
                return item

            # --- Populate Row ---
            index_val = shot_info.get("index", row + 1)
            index_item = QTableWidgetItem(str(index_val))
            index_item.setData(Qt.EditRole, QVariant(index_val))
            index_item.setBackground(row_brush)
            index_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, self.COL_IDX, index_item)

            table.setItem(row, self.COL_CLIP_NAME, create_std_item(shot_info.get("clip_name", "N/A")))
            edit_media_id = shot_info.get("edit_media_id", "N/A")
            id_item = create_std_item(edit_media_id, tooltip=edit_media_id)
            table.setItem(row, self.COL_EDIT_MEDIA_ID, id_item)
            source_path = shot_info.get("source_path", "N/A")
            path_item = create_std_item(source_path, tooltip=source_path)
            table.setItem(row, self.COL_SOURCE_PATH, path_item)
            table.setItem(row, self.COL_STATUS, create_std_item(status.upper()))

            # --- Get Raw Time Data ---
            source_rate = shot_info.get('source_rate')
            source_in_rt = shot_info.get('source_in_rt')
            source_out_rt_excl = shot_info.get('source_out_rt_excl')
            source_dur_rt = shot_info.get('source_duration_rt')
            source_point_rate = shot_info.get('source_point_rate')
            source_point_in_rt = shot_info.get('source_point_in_rt')
            source_point_out_rt_excl = shot_info.get('source_point_out_rt_excl')
            source_point_dur_rt = shot_info.get('source_point_duration_rt')
            sequence_rate = shot_info.get('sequence_rate')
            edit_in_rt = shot_info.get('edit_in_rt')
            edit_out_rt_excl = shot_info.get('edit_out_rt_excl')
            edit_dur_rt = shot_info.get('edit_duration_rt')

            # --- Calculate Inclusive End Times ---
            source_out_rt_incl = get_inclusive_end(source_out_rt_excl, source_rate)
            source_point_out_rt_incl = get_inclusive_end(source_point_out_rt_excl, source_point_rate)
            edit_out_rt_incl = get_inclusive_end(edit_out_rt_excl, sequence_rate)

            # --- Set Time Items ---
            table.setItem(row, self.COL_SOURCE_IN, create_time_item(source_in_rt, source_rate))
            table.setItem(row, self.COL_SOURCE_OUT, create_time_item(source_out_rt_incl, source_rate))
            table.setItem(row, self.COL_SOURCE_DUR, create_time_item(source_dur_rt, source_rate))
            table.setItem(row, self.COL_SOURCE_POINT_IN, create_time_item(source_point_in_rt, source_point_rate))
            table.setItem(row, self.COL_SOURCE_POINT_OUT, create_time_item(source_point_out_rt_incl, source_point_rate))
            table.setItem(row, self.COL_SOURCE_POINT_DUR, create_time_item(source_point_dur_rt, source_point_rate))
            table.setItem(row, self.COL_EDIT_IN, create_time_item(edit_in_rt, sequence_rate))
            table.setItem(row, self.COL_EDIT_OUT, create_time_item(edit_out_rt_incl, sequence_rate))
            table.setItem(row, self.COL_EDIT_DUR, create_time_item(edit_dur_rt, sequence_rate))

        table.blockSignals(False)
        table.setSortingEnabled(True)
        self._apply_row_visibility_filter()  # Apply visibility filter

    def display_plan_summary(self, segment_summary: List[Dict]):
        """
        Displays the transfer segment plan in the segments table and timeline.

        Args:
            segment_summary: List of segment dictionaries with information.
        """
        logger.debug(f"Displaying transfer plan summary for {len(segment_summary)} segments.")

        # --- Update the segments table ---
        table = self.segments_table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setRowCount(len(segment_summary))

        status_colors = {
            "completed": QBrush(QColor(200, 255, 200)),  # Light green
            "failed": QBrush(QColor(255, 150, 150)),  # Light red
            "running": QBrush(QColor(173, 216, 230)),  # Light blue
            "pending": QBrush(QColor(225, 225, 225)),  # Light gray
            "calculated": QBrush(QColor(255, 255, 200)),  # Light yellow
            "default": QBrush(Qt.white)  # White default
        }

        # Keep track of timeline data for visualization
        timeline_data = []

        # Process each segment
        for row, seg_info in enumerate(segment_summary):
            # Extract basic info
            status = seg_info.get('status', 'pending').lower()
            source_path = seg_info.get('source_path', 'N/A')
            source_basename = os.path.basename(source_path)
            row_brush = status_colors.get(status, status_colors["default"])

            # --- Simplified Segment Name Handling ---
            # Directly use the segment_id passed from the facade.
            # Fallback to a generic name if ID is missing (shouldn't happen with facade fix).
            segment_name_from_facade = seg_info.get('segment_id', f'Segment {row + 1}')
            # --- End Simplified Handling ---

            # Extract time information
            start_tc_str = seg_info.get('range_start_tc', 'N/A') # Original string from facade (for reference)
            duration_sec = seg_info.get('duration_sec', 0.0)

            # Store frame rate for timeline display and calculations
            frame_rate = self._segments_frame_rate # Use default or previously set rate
            if 'frame_rate' in seg_info and seg_info['frame_rate'] > 0:
                frame_rate = seg_info['frame_rate']
                self._segments_frame_rate = frame_rate # Update default if a new rate is found

            # Handle calculation for use TC (without handles)
            handle_frames = self._handle_frames
            handle_sec = handle_frames / frame_rate if frame_rate > 0 else 0

            # Create helper function to create standard cell items
            def create_std_item(text: Any, align=Qt.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setBackground(row_brush)
                if align != Qt.AlignLeft:
                    item.setTextAlignment(align | Qt.AlignVCenter) # Add vertical center align
                return item

            # Create helper function to create time items
            def create_time_item(rt_value: Optional[opentime.RationalTime], rate: Optional[float]) -> QTableWidgetItem:
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setBackground(row_brush)

                if isinstance(rt_value, opentime.RationalTime) and rate and rate > 0:
                    item.setData(RawTimeRole, rt_value)
                    item.setData(RateRole, rate)
                    try:
                        # Store numeric value (frames) for sorting
                        numeric_val = int(round(rt_value.rescaled_to(rate).value))
                        item.setData(Qt.EditRole, QVariant(numeric_val))
                    except Exception as e:
                        logger.warning(f"Could not set numeric sort value for {rt_value}: {e}")
                        pass # Continue even if numeric sorting fails
                    # Set initial display text
                    self._update_cell_time_display(item, rt_value, rate)
                else:
                    # Set N/A if time object or rate is invalid
                    item.setText("N/A")
                    # Set data roles to None for invalid time
                    item.setData(RawTimeRole, None)
                    item.setData(RateRole, None)
                    item.setData(Qt.EditRole, QVariant()) # Clear numeric sort value

                return item

            # --- Fill table row ---

            # Index column
            index_val = row + 1
            index_item = QTableWidgetItem(str(index_val))
            index_item.setData(Qt.EditRole, QVariant(index_val))
            index_item.setBackground(row_brush)
            index_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, self.SEG_COL_IDX, index_item)

            # Segment name (uses the simplified name from facade)
            table.setItem(row, self.SEG_COL_NAME, create_std_item(segment_name_from_facade))

            # Source name and path
            table.setItem(row, self.SEG_COL_SOURCE_NAME, create_std_item(source_basename))
            source_path_item = create_std_item(source_path)
            source_path_item.setToolTip(source_path)
            table.setItem(row, self.SEG_COL_SOURCE_PATH, source_path_item)

            # --- Handle time fields ---

            # Get RationalTime objects passed from facade (if available)
            start_rt = seg_info.get('start_rt')
            duration_rt = seg_info.get('duration_rt')

            # Calculate end time from start + duration if both are valid
            end_rt = None
            if isinstance(start_rt, opentime.RationalTime) and isinstance(duration_rt, opentime.RationalTime):
                try:
                    # Ensure rates match before addition, rescaled if needed
                    if start_rt.rate == duration_rt.rate:
                        end_rt = start_rt + duration_rt
                    elif frame_rate > 0:
                         # Rescale both to the determined frame_rate for consistency
                         start_rescaled = start_rt.rescaled_to(frame_rate)
                         duration_rescaled = duration_rt.rescaled_to(frame_rate)
                         end_rt = start_rescaled + duration_rescaled
                    else:
                         logger.warning(f"Cannot calculate end time for segment {segment_name_from_facade}: Rates differ and no valid frame_rate.")
                except Exception as e:
                    logger.warning(f"Could not calculate end time for segment {segment_name_from_facade}: {e}")

            # Calculate inclusive end time for display
            end_rt_incl = get_inclusive_end(end_rt, frame_rate)

            # Calculate use TC in/out (without handles)
            use_tc_in_rt = None
            use_tc_out_rt = None
            if isinstance(start_rt, opentime.RationalTime) and isinstance(end_rt_incl, opentime.RationalTime) and handle_frames > 0 and frame_rate > 0:
                try:
                    handle_frames_rt = opentime.RationalTime(handle_frames, frame_rate)
                    # Start without handle
                    use_tc_in_rt = start_rt + handle_frames_rt
                    # End without handle (use calculated inclusive end)
                    use_tc_out_rt = end_rt_incl - handle_frames_rt

                    # Ensure non-negative times
                    use_tc_in_rt = ensure_non_negative_time(use_tc_in_rt)
                    if isinstance(use_tc_out_rt, opentime.RationalTime):
                        use_tc_out_rt = ensure_non_negative_time(use_tc_out_rt)

                except Exception as e:
                    logger.warning(f"Could not calculate use TC for segment {segment_name_from_facade}: {e}")

            # Set time cells using the helper function
            table.setItem(row, self.SEG_COL_TC_IN, create_time_item(start_rt, frame_rate))
            table.setItem(row, self.SEG_COL_TC_OUT, create_time_item(end_rt_incl, frame_rate)) # Display inclusive end
            table.setItem(row, self.SEG_COL_USE_TC_IN, create_time_item(use_tc_in_rt, frame_rate))
            table.setItem(row, self.SEG_COL_USE_TC_OUT, create_time_item(use_tc_out_rt, frame_rate))

            # Set duration as a time item (for consistent formatting/sorting)
            table.setItem(row, self.SEG_COL_DURATION, create_time_item(duration_rt, frame_rate))

            # Set status and error
            table.setItem(row, self.SEG_COL_STATUS, create_std_item(status.upper()))
            error_msg = seg_info.get('error', '')
            table.setItem(row, self.SEG_COL_ERROR, create_std_item(error_msg))

            # --- Store timeline data ---
            # Collect necessary data for the timeline display widget
            if isinstance(start_rt, opentime.RationalTime) and duration_sec > 0:
                timeline_item = {
                    'segment_id': segment_name_from_facade, # Use the correct name here too
                    'start_sec': start_rt.to_seconds(),
                    'duration_sec': duration_sec,
                    'frame_rate': frame_rate,
                    'status': status
                }

                # Add handle information if available and applicable
                if handle_frames > 0:
                    handle_sec = handle_frames / frame_rate if frame_rate > 0 else 0
                    timeline_item['handle_start_sec'] = handle_sec
                    timeline_item['handle_end_sec'] = handle_sec # Assuming symmetric handles for visualization

                timeline_data.append(timeline_item)

        # --- Finalize table ---
        table.blockSignals(False)
        table.setSortingEnabled(True)
        # Optionally resize columns to fit content after populating
        # table.resizeColumnsToContents()

        # --- Update timeline visualization ---
        self.segments_timeline.clear()
        self.segments_timeline.set_frame_rate(self._segments_frame_rate) # Ensure timeline widget uses the latest rate

        # Only update if we have data and timeline is initialized
        if timeline_data:
            self.segments_timeline.update_timeline(timeline_data, self._segment_separator_frames)
            logger.debug(f"Updated timeline visualization with {len(timeline_data)} segments")
        else:
            logger.debug("No valid timeline data available for visualization")

    def display_unresolved_summary(self, unresolved_summary: List[Dict]):
        """Displays the unresolved items in the unresolved table."""
        logger.debug(f"Displaying {len(unresolved_summary)} unresolved/error items.")
        table = self.unresolved_table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setRowCount(len(unresolved_summary))

        status_colors = {
            "not_found": QBrush(QColor(255, 200, 200)),  # Light red
            "error": QBrush(QColor(255, 160, 122)),  # Salmon
            "pending": QBrush(QColor(255, 255, 200)),  # Light yellow
            "default": QBrush(Qt.white)  # White default
        }

        for row, shot_info in enumerate(unresolved_summary):
            status = shot_info.get('status', 'unknown').lower()
            edit_path_id = shot_info.get('proxy_path', 'N/A')
            row_brush = status_colors.get(status, status_colors["default"])

            def create_std_item(text: Any) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setBackground(row_brush)
                return item

            # Create and add items to table
            name_item = create_std_item(shot_info.get('name', 'N/A'))
            id_item = create_std_item(edit_path_id)
            id_item.setToolTip(edit_path_id)

            table.setItem(row, 0, name_item)
            table.setItem(row, 1, id_item)
            table.setItem(row, 2, create_std_item(status.upper()))
            table.setItem(row, 3, create_std_item(shot_info.get('edit_range', 'N/A')))

        table.blockSignals(False)
        table.setSortingEnabled(True)

    def set_handle_frames(self, frames: int):
        """Sets the handle frames value for segment display calculations."""
        self._handle_frames = max(0, frames)

    def set_separator_frames(self, frames: int):
        """Sets the separator frames value for timeline visualization."""
        self._segment_separator_frames = max(0, frames)
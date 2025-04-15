# gui2/widgets/tables/segments_table.py
"""
Segments Table Widget

Specialized table for displaying transfer segments.
"""

import logging
import os
from typing import List, Dict, Any, Optional

from PyQt5.QtWidgets import QTableWidgetItem
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QBrush

from opentimelineio import opentime

from .base_table import BaseTableWidget

logger = logging.getLogger(__name__)

# Define custom roles for storing time data
RawTimeRole = Qt.UserRole + 1
RateRole = Qt.UserRole + 2


class SegmentsTable(BaseTableWidget):
    """
    Table widget for displaying transfer segments.

    Features:
    - Display of segment names, sources, and ranges
    - Time display in frames or timecode format
    - Status-based row coloring
    - Filtering
    """
    # Signal emitted when time format changes
    timeFormatChanged = pyqtSignal(str)  # format_name

    # Column indices constants for easy reference
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

    def __init__(self, parent=None):
        """Initialize the SegmentsTable."""
        # Define columns
        headers = [
            "#", "Segment Name", "Source Name", "Source Path",
            "Segment TC IN", "Segment TC OUT", "Use TC IN", "Use TC OUT",
            "Duration", "Status", "Error/Notes"
        ]

        column_keys = [
            "index", "segment_id", "source_basename", "source_path",
            "tc_in", "tc_out", "use_tc_in", "use_tc_out",
            "duration_sec", "status", "error"
        ]

        # Columns to stretch (text fields)
        stretch_columns = [
            self.SEG_COL_NAME,
            self.SEG_COL_SOURCE_NAME,
            self.SEG_COL_SOURCE_PATH,
            self.SEG_COL_ERROR
        ]

        # Columns with fixed width (numbers, status)
        fixed_columns = [
            self.SEG_COL_IDX,
            self.SEG_COL_STATUS
        ]

        super().__init__(
            headers,
            column_keys,
            stretch_columns,
            fixed_columns,
            with_filter=True,
            parent=parent
        )

        # Current time display format - Default to Timecode
        self._time_format = "Timecode"

        # Mapping of time columns to data field names
        self._time_columns = {
            self.SEG_COL_TC_IN: 'start_rt',
            self.SEG_COL_TC_OUT: 'end_rt_excl',
            self.SEG_COL_USE_TC_IN: 'use_tc_in_rt',
            self.SEG_COL_USE_TC_OUT: 'use_tc_out_rt',
        }

        # Set of duration columns (handle differently)
        self._duration_columns = {self.SEG_COL_DURATION}

        # Frame rate for the segments (defaults to 25)
        self._frame_rate = 25.0

        logger.debug("SegmentsTable initialized")

    def get_row_color(self, row_data: Dict[str, Any]) -> QColor:
        """
        Get the background color for a row based on its status.

        Args:
            row_data: Dictionary containing row data

        Returns:
            QColor to use for the row background
        """
        status = row_data.get('status', '').lower()

        # Status-based colors
        status_colors = {
            "completed": QColor(120, 220, 120),  # Green
            "running": QColor(120, 180, 250),  # Blue
            "pending": QColor(200, 200, 200),  # Light gray
            "failed": QColor(250, 120, 120),  # Red
            "calculated": QColor(255, 255, 200),  # Light yellow
            "default": QColor(255, 255, 255)  # White
        }

        # Check if source is verified (add special handling for missing sources)
        if 'source_verified' in row_data and not row_data['source_verified']:
            # Orange-ish color for segments with missing source files
            return QColor(255, 165, 0, 127)  # Semi-transparent orange

        return status_colors.get(status, status_colors["default"])

    def populate_table(self, data: List[Dict[str, Any]]):
        """
        Populate the table with segment data.

        This overrides the base implementation to handle time values specially.

        Args:
            data: List of segment dictionaries
        """
        # Store the data
        self._rows_data = data

        # Determine frame rate from data if available
        # Use the first segment's rate as a representative rate for the table
        self._frame_rate = 25.0  # Default
        if data:
            first_segment_rate = data[0].get('frame_rate')
            if first_segment_rate and first_segment_rate > 0:
                self._frame_rate = first_segment_rate
            else:
                # Fallback: try finding rate from first segment's time data if main rate missing
                start_rt = data[0].get('start_rt')
                if isinstance(start_rt, opentime.RationalTime) and start_rt.rate > 0:
                    self._frame_rate = start_rt.rate

        logger.debug(f"Using frame rate {self._frame_rate} for segments table population")

        # Disable sorting temporarily for better performance
        self.table.setSortingEnabled(False)

        # Clear existing rows
        self.table.clearContents()
        self.table.setRowCount(len(data))

        # Populate the table
        for row_index, row_data in enumerate(data):
            # Get row color based on status
            row_color = self.get_row_color(row_data)

            # Create and add items for each column
            for col_index, key in enumerate(self._column_keys):
                item: Optional[QTableWidgetItem] = None  # Define item variable scope

                # Handle time columns specially using the modified helpers
                if col_index in self._time_columns:
                    item = self._create_time_item(
                        row_data,
                        self._time_columns[col_index],
                        self._frame_rate,
                        False,  # Not a duration
                        row_index
                    )
                # Handle duration column specially using the modified helper
                elif col_index in self._duration_columns:
                    # Get the duration value in seconds (or from duration_rt if available)
                    duration_rt = row_data.get('duration_rt')
                    duration_sec = 0.0
                    if isinstance(duration_rt, opentime.RationalTime) and duration_rt.rate > 0:
                        duration_sec = duration_rt.to_seconds()
                    elif isinstance(row_data.get(key), (int, float)):  # Fallback to duration_sec key
                        duration_sec = row_data.get(key, 0.0)

                    item = self._create_duration_item(
                        duration_sec,
                        self._frame_rate,
                        row_index
                    )
                else:
                    # Handle non-time columns
                    value = self._get_nested_value(row_data, key)

                    # Customize display for certain columns
                    if col_index == self.SEG_COL_SOURCE_NAME and value is None:
                        # Generate basename from source_path if not provided
                        source_path = row_data.get('source_path', '')
                        value = os.path.basename(source_path) if source_path else "N/A"

                    # Create the standard item
                    alignment = Qt.AlignRight if isinstance(value, (int, float)) else Qt.AlignLeft
                    str_value = str(value) if value is not None else "N/A"
                    item = self.create_table_item(
                        str_value,
                        row_index,
                        tooltip=str_value,
                        alignment=alignment
                    )

                    # Add numeric data for index column sorting
                    if col_index == self.SEG_COL_IDX and isinstance(value, (int, float)):
                        item.setData(Qt.EditRole, value)

                # Set background color and add item to table if created
                if item is not None:
                    item.setBackground(QBrush(row_color))
                    self.table.setItem(row_index, col_index, item)
                else:
                    # Fallback: Create an empty item if helper returned None unexpectedly
                    logger.warning(f"Item creation failed for row {row_index}, col {col_index}")
                    self.table.setItem(row_index, col_index, QTableWidgetItem("Error"))

        # Re-enable sorting AFTER the loop
        self.table.setSortingEnabled(True)

        # Update count label
        visible_count = sum(1 for row in range(self.table.rowCount())
                            if not self.table.isRowHidden(row))
        self.count_label.setText(f"{visible_count} of {len(data)} items")

        # Apply filter if active
        if self._with_filter and self.filter_input.text():
            self._apply_filter()

        # Apply current time format to ensure proper display AFTER population
        # This is the crucial single call that formats all time cells
        self.refresh_time_display()

    def _create_time_item(self,
                          row_data: Dict[str, Any],
                          time_key: str,
                          frame_rate: float,
                          is_duration: bool,  # Keep argument, but don't use it here
                          row_index: int) -> QTableWidgetItem:
        """
        Create a table item for a time value, storing raw data.
        Display text will be set by refresh_time_display.

        Args:
            row_data: Dictionary containing row data
            time_key: Key for the time value in the row data
            frame_rate: Frame rate to use for formatting
            is_duration: Whether this column represents a duration
            row_index: Original index in the data list

        Returns:
            Configured QTableWidgetItem
        """
        item = QTableWidgetItem()  # Create item without text initially
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        item.setData(Qt.UserRole, row_index)  # Store original index

        # Get the time value
        rt_value = row_data.get(time_key)

        if isinstance(rt_value, opentime.RationalTime):
            # Store raw time and rate data for future formatting
            item.setData(RawTimeRole, rt_value)
            item.setData(RateRole, frame_rate)

            # --- REMOVED THIS CALL ---
            # self._update_time_display(item, rt_value, frame_rate)

            # Store numeric value for sorting
            try:
                # Need to rescale if rates differ
                if rt_value.rate != frame_rate:
                    numeric_val = int(round(rt_value.rescaled_to(frame_rate).value))
                else:
                    numeric_val = int(round(rt_value.value))
                item.setData(Qt.EditRole, numeric_val)
            except Exception as e:
                logger.warning(f"Error converting time to numeric value: {e}")
                item.setText("N/A")  # Set text only on error here
                item.setData(Qt.EditRole, None)  # Ensure no sort value on error

        else:
            item.setText("N/A")  # Set text if no valid time data
            item.setData(Qt.EditRole, None)

        return item

    def _create_duration_item(self,
                              duration_sec: float,
                              frame_rate: float,
                              row_index: int) -> QTableWidgetItem:
        """
        Create a table item for a duration value in seconds, storing raw data.
        Display text will be set by refresh_time_display.

        Args:
            duration_sec: Duration in seconds
            frame_rate: Frame rate to use for formatting
            row_index: Original index in the data list

        Returns:
            Configured QTableWidgetItem
        """
        item = QTableWidgetItem()  # Create item without text initially
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        item.setData(Qt.UserRole, row_index)  # Store original index

        if duration_sec > 0 and frame_rate > 0:
            # Create RationalTime from seconds
            frame_count = round(duration_sec * frame_rate)
            rt_value = opentime.RationalTime(frame_count, frame_rate)

            # Store raw time and rate data for future formatting
            item.setData(RawTimeRole, rt_value)
            item.setData(RateRole, frame_rate)

            # --- REMOVED THIS CALL ---
            # self._update_time_display(item, rt_value, frame_rate, is_duration=True)

            # Store numeric value for sorting (in frames)
            item.setData(Qt.EditRole, frame_count)

            # Add tooltip with seconds
            item.setToolTip(f"{duration_sec:.3f} seconds")
        else:
            item.setText("0")  # Set text only for zero duration
            item.setData(Qt.EditRole, 0)

        return item

    def _update_time_display(self,
                             item: QTableWidgetItem,
                             rt_value: opentime.RationalTime,
                             rate: float,
                             is_duration: bool = False):
        """
        Update the display text of a time item based on current format.

        Args:
            item: Table item to update
            rt_value: Time value as RationalTime
            rate: Frame rate to use for formatting
            is_duration: Whether this item represents a duration
        """
        try:
            if self._time_format == "Timecode":
                # Format as timecode
                if is_duration:
                    # For durations, format as frames if short, otherwise as timecode
                    if rt_value.value < 60 * rate:  # Less than 1 minute
                        frame_count = round(rt_value.value)
                        item.setText(f"{frame_count} frames")
                    else:
                        tc_str = opentime.to_timecode(rt_value, rate)
                        item.setText(tc_str)
                else:
                    tc_str = opentime.to_timecode(rt_value, rate)
                    item.setText(tc_str)
            else:
                # Format as frames
                if rt_value.rate != rate:
                    frame_count = round(rt_value.rescaled_to(rate).value)
                else:
                    frame_count = round(rt_value.value)
                item.setText(f"{frame_count}")
        except Exception as e:
            logger.warning(f"Error formatting time display: {e}")
            item.setText(f"Err ({rt_value.value})")

    def refresh_time_display(self):
        """Refresh the display of all time columns."""
        logger.debug(f"Refreshing time display for format: {self._time_format}")

        # Iterate through all time columns and update display
        for row in range(self.table.rowCount()):
            # Handle time columns
            for col in self._time_columns:
                item = self.table.item(row, col)
                if item:
                    rt_value = item.data(RawTimeRole)
                    rate = item.data(RateRole)
                    if isinstance(rt_value, opentime.RationalTime):
                        self._update_time_display(item, rt_value, rate)

            # Handle duration column
            for col in self._duration_columns:
                item = self.table.item(row, col)
                if item:
                    rt_value = item.data(RawTimeRole)
                    rate = item.data(RateRole)
                    if isinstance(rt_value, opentime.RationalTime):
                        self._update_time_display(item, rt_value, rate, is_duration=True)

    def set_time_format(self, format_name: str):
        """
        Set the time display format.

        Args:
            format_name: The format name ("Timecode" or "Frames")
        """
        if format_name in ("Timecode", "Frames") and format_name != self._time_format:
            logger.info(f"Setting segments table time format to: {format_name}")
            self._time_format = format_name
            self.refresh_time_display()
            self.timeFormatChanged.emit(format_name)

    def get_time_format(self) -> str:
        """Get the current time display format."""
        return self._time_format

    def set_frame_rate(self, rate: float):
        """
        Set the frame rate used for time formatting.

        Args:
            rate: The frame rate to use
        """
        if rate > 0 and rate != self._frame_rate:
            self._frame_rate = rate
            self.refresh_time_display()

    def get_selected_segments(self) -> List[Dict[str, Any]]:
        """
        Get the data for selected segments.

        Returns:
            List of dictionaries for selected segments
        """
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        selected_data = []
        for row in selected_rows:
            if 0 <= row < len(self._rows_data):
                # Get the original data for this row
                original_index = int(self.table.item(row, 0).data(Qt.UserRole))
                if 0 <= original_index < len(self._rows_data):
                    selected_data.append(self._rows_data[original_index])

        return selected_data

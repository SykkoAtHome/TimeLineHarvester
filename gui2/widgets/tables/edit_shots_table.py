# gui2/widgets/tables/edit_shots_table.py
"""
Edit Shots Table Widget

Specialized table for displaying edit shots analysis results.
"""

import logging
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


class EditShotsTable(BaseTableWidget):
    """
    Table widget for displaying edit shots analysis results.

    Features:
    - Display of clip names, sources, and status
    - Time display in frames or timecode format
    - Status-based row coloring
    - Filtering
    """
    # Signal emitted when time format changes
    timeFormatChanged = pyqtSignal(str)  # format_name

    # Column indices constants for easy reference
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

    def __init__(self, parent=None):
        """Initialize the EditShotsTable."""
        # Define columns
        headers = [
            "#", "Clip Name", "Edit Media ID", "Source Path", "Status",
            "Source IN", "Source OUT", "Source Dur",
            "Src Pt IN", "Src Pt OUT", "Src Pt Dur",
            "Edit IN", "Edit OUT", "Edit Dur"
        ]

        column_keys = [
            "index", "clip_name", "edit_media_id", "source_path", "status",
            "source_in", "source_out", "source_duration",
            "source_point_in", "source_point_out", "source_point_duration",
            "edit_in", "edit_out", "edit_duration"
        ]

        # Columns to stretch (text fields)
        stretch_columns = [
            self.COL_CLIP_NAME,
            self.COL_EDIT_MEDIA_ID,
            self.COL_SOURCE_PATH
        ]

        # Columns with fixed width (numbers, status)
        fixed_columns = [
            self.COL_IDX,
            self.COL_STATUS
        ]

        super().__init__(
            headers,
            column_keys,
            stretch_columns,
            fixed_columns,
            with_filter=True,
            parent=parent
        )

        # Current time display format
        self._time_format = "Timecode"

        # Mapping of time columns to data field names
        self._time_columns = {
            self.COL_SOURCE_IN: 'source_in_rt',
            self.COL_SOURCE_OUT: 'source_out_rt_excl',
            self.COL_SOURCE_DUR: 'source_duration_rt',
            self.COL_SOURCE_POINT_IN: 'source_point_in_rt',
            self.COL_SOURCE_POINT_OUT: 'source_point_out_rt_excl',
            self.COL_SOURCE_POINT_DUR: 'source_point_duration_rt',
            self.COL_EDIT_IN: 'edit_in_rt',
            self.COL_EDIT_OUT: 'edit_out_rt_excl',
            self.COL_EDIT_DUR: 'edit_duration_rt'
        }

        # Mapping of columns to rate field names
        self._rate_columns = {
            self.COL_SOURCE_IN: 'source_rate',
            self.COL_SOURCE_OUT: 'source_rate',
            self.COL_SOURCE_DUR: 'source_rate',
            self.COL_SOURCE_POINT_IN: 'source_point_rate',
            self.COL_SOURCE_POINT_OUT: 'source_point_rate',
            self.COL_SOURCE_POINT_DUR: 'source_point_rate',
            self.COL_EDIT_IN: 'sequence_rate',
            self.COL_EDIT_OUT: 'sequence_rate',
            self.COL_EDIT_DUR: 'sequence_rate'
        }

        # Set of duration columns
        self._duration_columns = {
            self.COL_SOURCE_DUR,
            self.COL_SOURCE_POINT_DUR,
            self.COL_EDIT_DUR
        }

        logger.debug("EditShotsTable initialized")

    def populate_table(self, data: List[Dict[str, Any]]):
        """
        Populate the table with edit shots data.

        This overrides the base implementation to handle time values specially.

        Args:
            data: List of edit shot dictionaries
        """
        # Store the data
        self._rows_data = data

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
                # Handle time columns specially
                if col_index in self._time_columns:
                    # Create time item
                    item = self._create_time_item(
                        row_data,
                        self._time_columns[col_index],
                        self._rate_columns[col_index],
                        col_index in self._duration_columns,
                        row_index
                    )

                    # Set background color
                    item.setBackground(QBrush(row_color))

                    # Add to table
                    self.table.setItem(row_index, col_index, item)
                else:
                    # Get the value for this cell
                    value = self._get_nested_value(row_data, key)

                    # Create the item
                    alignment = Qt.AlignRight if isinstance(value, (int, float)) else Qt.AlignLeft

                    # For index column, ensure proper numeric sorting
                    if col_index == self.COL_IDX and isinstance(value, (int, float)):
                        item = self.create_table_item(
                            str(value),
                            row_index,
                            tooltip=None,
                            alignment=alignment
                        )
                        item.setData(Qt.EditRole, value)  # For numeric sorting
                    else:
                        item = self.create_table_item(
                            str(value) if value is not None else "N/A",
                            row_index,
                            tooltip=str(value) if value is not None else None,
                            alignment=alignment
                        )

                    # Set background color
                    item.setBackground(QBrush(row_color))

                    # Add to table
                    self.table.setItem(row_index, col_index, item)

        # Re-enable sorting
        self.table.setSortingEnabled(True)

        # Update count label
        visible_count = sum(1 for row in range(self.table.rowCount())
                            if not self.table.isRowHidden(row))
        self.count_label.setText(f"{visible_count} of {len(data)} items")

        # Apply filter if active
        if self._with_filter and self.filter_input.text():
            self._apply_filter()

    def _create_time_item(self,
                          row_data: Dict[str, Any],
                          time_key: str,
                          rate_key: str,
                          is_duration: bool,
                          row_index: int) -> QTableWidgetItem:
        """
        Create a table item for a time value.

        Args:
            row_data: Dictionary containing row data
            time_key: Key for the time value in the row data
            rate_key: Key for the frame rate in the row data
            is_duration: Whether this column represents a duration
            row_index: Original index in the data list

        Returns:
            Configured QTableWidgetItem
        """
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        item.setData(Qt.UserRole, row_index)  # Store original index

        # Get the time and rate values
        rt_value = row_data.get(time_key)
        rate = row_data.get(rate_key)

        if isinstance(rt_value, opentime.RationalTime) and rate and rate > 0:
            # Store raw time and rate data for future formatting
            item.setData(RawTimeRole, rt_value)
            item.setData(RateRole, rate)

            # Format display text based on current format
            self._update_time_display(item, rt_value, rate)

            # Store numeric value for sorting
            try:
                numeric_val = int(round(rt_value.rescaled_to(rate).value))
                item.setData(Qt.EditRole, numeric_val)
            except Exception as e:
                logger.warning(f"Error converting time to numeric value: {e}")
        else:
            item.setText("N/A")

        return item

    def _update_time_display(self,
                             item: QTableWidgetItem,
                             rt_value: opentime.RationalTime,
                             rate: float):
        """
        Update the display text of a time item based on current format.

        Args:
            item: Table item to update
            rt_value: Time value as RationalTime
            rate: Frame rate to use for formatting
        """
        try:
            if self._time_format == "Timecode":
                # Format as timecode
                tc_str = opentime.to_timecode(rt_value, rate)
                item.setText(tc_str)
            else:
                # Format as frames
                frame_count = round(rt_value.rescaled_to(rate).value)
                item.setText(f"{frame_count}")
        except Exception as e:
            logger.warning(f"Error formatting time display: {e}")
            item.setText(f"Err ({rt_value.value})")

    def refresh_time_display(self):
        """Refresh the display of all time columns."""
        logger.debug(f"Refreshing time display for format: {self._time_format}")

        # Iterate through all time columns and update display
        for row in range(self.table.rowCount()):
            for col in self._time_columns:
                item = self.table.item(row, col)
                if item:
                    rt_value = item.data(RawTimeRole)
                    rate = item.data(RateRole)
                    if isinstance(rt_value, opentime.RationalTime):
                        self._update_time_display(item, rt_value, rate)

    def set_time_format(self, format_name: str):
        """
        Set the time display format.

        Args:
            format_name: The format name ("Timecode" or "Frames")
        """
        if format_name in ("Timecode", "Frames") and format_name != self._time_format:
            self._time_format = format_name
            self.refresh_time_display()
            self.timeFormatChanged.emit(format_name)

    def get_time_format(self) -> str:
        """Get the current time display format."""
        return self._time_format

    def get_selected_shots(self) -> List[Dict[str, Any]]:
        """
        Get the data for selected shots.

        Returns:
            List of dictionaries for selected shots
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

    def set_hide_unresolved(self, hide: bool):
        """
        Set whether to hide unresolved shots.

        Args:
            hide: Whether to hide unresolved shots
        """
        for row in range(self.table.rowCount()):
            status_item = self.table.item(row, self.COL_STATUS)
            should_hide = False
            if status_item and hide:
                status_text = status_item.text().lower()
                is_unresolved = ("not_found" in status_text or "error" in status_text)
                should_hide = is_unresolved

            self.table.setRowHidden(row, should_hide)

        # Update count label
        visible_count = sum(1 for row in range(self.table.rowCount())
                            if not self.table.isRowHidden(row))
        total_count = len(self._rows_data)

        if visible_count != total_count:
            self.count_label.setText(f"{visible_count} of {total_count} items")
        else:
            self.count_label.setText(f"{total_count} items")

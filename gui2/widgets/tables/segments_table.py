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

# Check if opentime is available, handle potential import error
try:
    from opentimelineio import opentime

    OTIO_AVAILABLE = True
except ImportError:
    logging.getLogger(__name__).error("Failed to import opentimelineio. Time features will be limited.")


    class opentime_stub:  # Define a placeholder if OTIO is missing
        RationalTime = type(None)


    opentime = opentime_stub
    OTIO_AVAILABLE = False

from .base_table import BaseTableWidget

logger = logging.getLogger(__name__)

# Define custom roles for storing time data
RawTimeRole = Qt.UserRole + 1
RateRole = Qt.UserRole + 2


class SegmentsTable(BaseTableWidget):
    """
    Table widget for displaying transfer segments.
    """
    timeFormatChanged = pyqtSignal(str)

    # --- Column Indices ---
    SEG_COL_IDX = 0
    SEG_COL_NAME = 1
    SEG_COL_SOURCE_NAME = 2
    SEG_COL_SOURCE_PATH = 3
    SEG_COL_TC_IN = 4  # Segment IN (with handles)
    SEG_COL_TC_OUT = 5  # Segment OUT (with handles, inclusive)
    SEG_COL_USE_TC_IN = 6  # Use IN (without handles)
    SEG_COL_USE_TC_OUT = 7  # Use OUT (without handles, inclusive)
    SEG_COL_DURATION = 8  # Segment Duration (with handles)
    SEG_COL_STATUS = 9
    SEG_COL_ERROR = 10

    def __init__(self, parent=None):
        """Initialize the SegmentsTable."""
        headers = [
            "#", "Segment Name", "Source Name", "Source Path",
            "Segment IN", "Segment OUT", "Use IN", "Use OUT",
            "Duration", "Status", "Error/Notes"
        ]

        # --- Define COMPLETE Column Key Mapping ---
        # This maps each COLUMN INDEX directly to the KEY expected in the input data dictionary
        self._column_data_keys = {
            self.SEG_COL_IDX: "index",
            self.SEG_COL_NAME: "segment_id",
            self.SEG_COL_SOURCE_NAME: "source_basename",
            self.SEG_COL_SOURCE_PATH: "source_path",
            self.SEG_COL_TC_IN: "start_rt",  # Raw time for Segment IN
            self.SEG_COL_TC_OUT: "end_rt_incl",  # Raw time for Segment OUT
            self.SEG_COL_USE_TC_IN: "use_tc_in_rt",  # Raw time for Use IN
            self.SEG_COL_USE_TC_OUT: "use_tc_out_rt_incl",  # Raw time for Use OUT
            self.SEG_COL_DURATION: "duration_rt",  # Raw time for Duration
            self.SEG_COL_STATUS: "status",
            self.SEG_COL_ERROR: "error",
        }

        # Use the keys from the mapping for the base class initialization (order matters)
        ordered_keys_for_base = [self._column_data_keys[i] for i in range(len(headers))]

        stretch_columns = [
            self.SEG_COL_NAME, self.SEG_COL_SOURCE_NAME,
            self.SEG_COL_SOURCE_PATH, self.SEG_COL_ERROR
        ]
        fixed_columns = [self.SEG_COL_IDX, self.SEG_COL_STATUS]

        # Pass the ordered keys to the base class
        super().__init__(
            headers,
            ordered_keys_for_base,  # Pass the correctly ordered keys
            stretch_columns,
            fixed_columns,
            with_filter=True,
            parent=parent
        )

        self._time_format = "Timecode"

        # Identify which column indices need special time handling
        self._time_point_columns = {
            self.SEG_COL_TC_IN, self.SEG_COL_TC_OUT,
            self.SEG_COL_USE_TC_IN, self.SEG_COL_USE_TC_OUT
        }
        self._duration_column_index = self.SEG_COL_DURATION

        self._frame_rate = 25.0

        logger.debug("SegmentsTable initialized with corrected key mapping")

    def get_row_color(self, row_data: Dict[str, Any]) -> QColor:
        """Gets the background color based on segment status."""
        status = row_data.get('status', '').lower()
        status_colors = {
            "completed": QColor(120, 220, 120), "running": QColor(120, 180, 250),
            "pending": QColor(200, 200, 200), "failed": QColor(250, 120, 120),
            "calculated": QColor(255, 255, 200), "default": QColor(255, 255, 255)
        }
        if row_data.get('source_verified') is False:
            return QColor(255, 165, 0, 127)  # Semi-transparent orange
        return status_colors.get(status, status_colors["default"])

    def populate_table(self, data: List[Dict[str, Any]]):
        """Populate the table using the corrected column key mapping."""
        self._rows_data = data

        # Determine frame rate
        self._frame_rate = 25.0
        if data:
            rate = data[0].get('frame_rate')
            if rate and rate > 0:
                self._frame_rate = rate
            else:
                start_rt = data[0].get(self._column_data_keys[self.SEG_COL_TC_IN])  # Use mapping
                if OTIO_AVAILABLE and isinstance(start_rt, opentime.RationalTime) and start_rt.rate > 0:
                    self._frame_rate = start_rt.rate
        logger.debug(f"Using frame rate {self._frame_rate} for segments table population")

        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(data))

        for row_index, row_data in enumerate(data):
            row_color = self.get_row_color(row_data)

            for col_index in range(self.table.columnCount()):
                item: Optional[QTableWidgetItem] = None
                data_key = self._column_data_keys.get(col_index)  # Get the correct data key

                if not data_key:
                    logger.warning(f"No data key mapped for column index {col_index}")
                    item = QTableWidgetItem("Mapping Error")
                    continue  # Skip to next column

                # Handle time point columns (IN/OUT)
                if col_index in self._time_point_columns:
                    item = self._create_time_item(row_data, data_key, self._frame_rate, row_index)

                # Handle duration column
                elif col_index == self._duration_column_index:
                    duration_rt = row_data.get(data_key)  # Use mapped key
                    item = self._create_duration_item(duration_rt, self._frame_rate, row_index)

                # Handle all other columns generically
                else:
                    value = self._get_nested_value(row_data, data_key)  # Use mapped key

                    # Custom display logic (e.g., source basename)
                    if col_index == self.SEG_COL_SOURCE_NAME and value is None:
                        source_path_key = self._column_data_keys[self.SEG_COL_SOURCE_PATH]
                        source_path = row_data.get(source_path_key, '')
                        value = os.path.basename(source_path) if source_path else "N/A"

                    alignment = Qt.AlignRight if isinstance(value, (int, float)) else Qt.AlignLeft
                    str_value = str(value) if value is not None else "N/A"
                    item = self.create_table_item(str_value, row_index, tooltip=str_value, alignment=alignment)

                    # Add numeric data for index column sorting
                    if col_index == self.SEG_COL_IDX and isinstance(value, (int, float)):
                        item.setData(Qt.EditRole, value)

                # Set background and add item
                if item is not None:
                    item.setBackground(QBrush(row_color))
                    self.table.setItem(row_index, col_index, item)
                else:
                    logger.warning(f"Item creation failed for row {row_index}, col {col_index}, key {data_key}")
                    self.table.setItem(row_index, col_index, QTableWidgetItem("Creation Error"))

        self.table.setSortingEnabled(True)
        self.update_count_label()  # Use helper
        if self._with_filter and hasattr(self, 'filter_input') and self.filter_input.text():
            self._apply_filter()
        self.refresh_time_display()

    def update_count_label(self):
        """Updates the item count label."""
        visible_count = sum(1 for row in range(self.table.rowCount()) if not self.table.isRowHidden(row))
        total_count = len(self._rows_data)
        self.count_label.setText(
            f"{visible_count} of {total_count} items" if visible_count != total_count else f"{total_count} items")

    def _create_time_item(self, row_data: Dict[str, Any], time_key: str, frame_rate: float,
                          row_index: int) -> QTableWidgetItem:
        """Creates table item for IN/OUT time points, storing raw OTIO data."""
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        item.setData(Qt.UserRole, row_index)

        if not OTIO_AVAILABLE:
            item.setText("OTIO N/A");
            return item

        rt_value = row_data.get(time_key)

        if isinstance(rt_value, opentime.RationalTime) and frame_rate > 0:
            item.setData(RawTimeRole, rt_value)
            item.setData(RateRole, frame_rate)
            try:
                numeric_val = int(round(rt_value.rescaled_to(frame_rate).value))
                item.setData(Qt.EditRole, numeric_val)  # For sorting
            except Exception as e:
                logger.warning(f"Error converting time {rt_value} to numeric at rate {frame_rate}: {e}")
                item.setText("N/A");
                item.setData(Qt.EditRole, None)
        else:
            item.setText("N/A");
            item.setData(Qt.EditRole, None)
        return item

    def _create_duration_item(self, duration_rt: Optional[opentime.RationalTime], frame_rate: float,
                              row_index: int) -> QTableWidgetItem:
        """Creates table item for duration, storing raw OTIO data."""
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        item.setData(Qt.UserRole, row_index)

        if not OTIO_AVAILABLE:
            item.setText("OTIO N/A");
            return item

        if isinstance(duration_rt, opentime.RationalTime) and frame_rate > 0:
            try:
                duration_rt = duration_rt.rescaled_to(frame_rate)  # Ensure correct rate
                frame_count = round(duration_rt.value)
                if frame_count >= 0:
                    item.setData(RawTimeRole, duration_rt)
                    item.setData(RateRole, frame_rate)
                    item.setData(Qt.EditRole, frame_count)  # For sorting
                    try:
                        item.setToolTip(f"{duration_rt.to_seconds():.3f} seconds")
                    except Exception:
                        pass
                else:
                    item.setText("0"); item.setData(Qt.EditRole, 0)
            except Exception as e:
                logger.warning(f"Error processing duration {duration_rt} at rate {frame_rate}: {e}")
                item.setText("Error");
                item.setData(Qt.EditRole, None)
        else:
            item.setText("0");
            item.setData(Qt.EditRole, 0)
        return item

    def _update_time_display(self, item: QTableWidgetItem, rt_value: opentime.RationalTime, rate: float,
                             is_duration: bool = False):
        """Updates the display text of a time item based on current format."""
        if not OTIO_AVAILABLE: item.setText("OTIO N/A"); return

        try:
            if not isinstance(rate, (float, int)) or rate <= 0: raise ValueError("Invalid rate")
            rescaled_rt = rt_value.rescaled_to(rate)  # Rescale for formatting

            if self._time_format == "Timecode":
                item.setText(opentime.to_timecode(rescaled_rt, rate))
            else:  # Frames
                item.setText(f"{round(rescaled_rt.value)}")
        except Exception as e:
            logger.warning(f"Error formatting time display: {e}")
            item.setText("Format Error")

    def refresh_time_display(self):
        """Refresh display text for all time and duration columns."""
        logger.debug(f"Refreshing time display for format: {self._time_format}")
        for row in range(self.table.rowCount()):
            # Time point columns
            for col in self._time_point_columns:
                item = self.table.item(row, col)
                if item:
                    rt_value = item.data(RawTimeRole)
                    rate = item.data(RateRole)
                    current_rate = rate if isinstance(rate, (float, int)) and rate > 0 else self._frame_rate
                    if OTIO_AVAILABLE and isinstance(rt_value, opentime.RationalTime):
                        self._update_time_display(item, rt_value, current_rate, is_duration=False)
            # Duration column
            col = self._duration_column_index
            item = self.table.item(row, col)
            if item:
                rt_value = item.data(RawTimeRole)
                rate = item.data(RateRole)
                current_rate = rate if isinstance(rate, (float, int)) and rate > 0 else self._frame_rate
                if OTIO_AVAILABLE and isinstance(rt_value, opentime.RationalTime):
                    self._update_time_display(item, rt_value, current_rate, is_duration=True)

    def set_time_format(self, format_name: str):
        """Set the time display format ("Timecode" or "Frames")."""
        if format_name in ("Timecode", "Frames") and format_name != self._time_format:
            logger.info(f"Setting segments table time format to: {format_name}")
            self._time_format = format_name
            self.refresh_time_display()
            self.timeFormatChanged.emit(format_name)

    def get_time_format(self) -> str:
        """Get the current time display format."""
        return self._time_format

    def set_frame_rate(self, rate: float):
        """Set the frame rate used for time formatting."""
        if rate > 0 and rate != self._frame_rate:
            self._frame_rate = rate
            self.refresh_time_display()  # Update display with new rate

    def get_selected_segments(self) -> List[Dict[str, Any]]:
        """Get the original data dictionaries for selected segments."""
        selected_rows = set()
        for item in self.table.selectedItems(): selected_rows.add(item.row())
        selected_data = []
        for row in sorted(list(selected_rows)):
            item_with_index = self.table.item(row, self.SEG_COL_IDX)
            if item_with_index:
                original_index = item_with_index.data(Qt.UserRole)
                if isinstance(original_index, int) and 0 <= original_index < len(self._rows_data):
                    selected_data.append(self._rows_data[original_index])
                else:
                    logger.warning(f"Invalid original index in row {row}: {original_index}")
            else:
                logger.warning(f"No index item found in row {row}")
        return selected_data

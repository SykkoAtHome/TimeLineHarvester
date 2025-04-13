# gui/results_display.py
import logging
import os
from typing import List, Dict, Optional, Any  # Added Any

from PyQt5.QtCore import Qt, pyqtSlot, QVariant
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView, QCheckBox, QComboBox,
                             QLabel, QSizePolicy, QSpacerItem)
from opentimelineio import opentime

logger = logging.getLogger(__name__)

# Define custom roles to store the raw RationalTime object and rate
RawTimeRole = Qt.UserRole + 1
RateRole = Qt.UserRole + 2


# --- Helper Function for Formatting Time (unchanged logic, no semicolons) ---
def format_time(value: Optional[opentime.RationalTime], rate: Optional[float], display_mode: str) -> str:
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


# --- ResultsDisplayWidget Class ---
class ResultsDisplayWidget(QWidget):
    # --- (Column definitions unchanged) ---
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
    TIME_COLUMNS_ANALYSIS = {  # Use dict for easier lookup
        COL_SOURCE_IN: 'source_in_rt', COL_SOURCE_OUT: 'source_out_rt_excl', COL_SOURCE_DUR: 'source_duration_rt',
        COL_SOURCE_POINT_IN: 'source_point_in_rt', COL_SOURCE_POINT_OUT: 'source_point_out_rt_excl',
        COL_SOURCE_POINT_DUR: 'source_point_duration_rt',
        COL_EDIT_IN: 'edit_in_rt', COL_EDIT_OUT: 'edit_out_rt_excl', COL_EDIT_DUR: 'edit_duration_rt'
    }
    RATE_KEYS_ANALYSIS = {  # Map column to its relevant rate key
        COL_SOURCE_IN: 'source_rate', COL_SOURCE_OUT: 'source_rate', COL_SOURCE_DUR: 'source_rate',
        COL_SOURCE_POINT_IN: 'source_point_rate', COL_SOURCE_POINT_OUT: 'source_point_rate',
        COL_SOURCE_POINT_DUR: 'source_point_rate',
        COL_EDIT_IN: 'sequence_rate', COL_EDIT_OUT: 'sequence_rate', COL_EDIT_DUR: 'sequence_rate'
    }
    IS_DURATION_COLUMN = {COL_SOURCE_DUR, COL_SOURCE_POINT_DUR, COL_EDIT_DUR}  # Set of duration columns
    TOTAL_ANALYSIS_COLS = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        # Removed self._analysis_data
        self._current_time_format = "Timecode"
        self._hide_unresolved = False
        self._init_ui()
        self._connect_signals()
        logger.debug("ResultsDisplayWidget initialized.")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.analysis_tab = QWidget()
        self.segments_tab = QWidget()
        self.unresolved_tab = QWidget()
        self._setup_analysis_tab()
        self._setup_segments_tab()
        self._setup_unresolved_tab()
        self.tabs.addTab(self.analysis_tab, "Source Analysis Status")
        self.tabs.addTab(self.segments_tab, "Calculated Segments")
        self.tabs.addTab(self.unresolved_tab, "Unresolved / Errors")
        main_layout.addWidget(self.tabs)

    def _setup_analysis_tab(self):
        layout = QVBoxLayout(self.analysis_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Time Display:"))
        self.time_format_combo = QComboBox()
        self.time_format_combo.addItems(["Timecode", "Frames"])
        controls_layout.addWidget(self.time_format_combo)
        controls_layout.addSpacerItem(QSpacerItem(20, 10, QSizePolicy.Fixed, QSizePolicy.Minimum))
        self.hide_unresolved_checkbox = QCheckBox("Hide Unresolved (Not Found / Error)")
        controls_layout.addWidget(self.hide_unresolved_checkbox)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        self.analysis_table = QTableWidget()
        self.analysis_table.setColumnCount(self.TOTAL_ANALYSIS_COLS)
        self.analysis_table.setHorizontalHeaderLabels(
            ["#", "Clip Name", "Edit Media ID", "Source Path", "Status", "Source IN", "Source OUT", "Source Dur",
             "Src Pt IN", "Src Pt OUT", "Src Pt Dur", "Edit IN", "Edit OUT", "Edit Dur"])
        self._configure_table_widget(self.analysis_table)
        header = self.analysis_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_CLIP_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_EDIT_MEDIA_ID, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_SOURCE_PATH, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_IDX, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeToContents)
        for col_idx in self.TIME_COLUMNS_ANALYSIS:  # Use keys from dict
            header.setSectionResizeMode(col_idx, QHeaderView.ResizeToContents)
        layout.addWidget(self.analysis_table)

    def _setup_segments_tab(self):
        layout = QVBoxLayout(self.segments_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        self.segments_table = QTableWidget()
        self.segments_table.setColumnCount(6)
        self.segments_table.setHorizontalHeaderLabels(
            ["#", "Original Source", "Start TC", "Duration (sec)", "Transcode Status", "Error / Notes"])
        self._configure_table_widget(self.segments_table)
        header = self.segments_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        try:
            header.setSectionHidden(4, True)
            header.setSectionHidden(5, True)
        except Exception as e:
            logger.warning(f"Could not hide columns in segments tab: {e}")
        layout.addWidget(self.segments_table)

    def _setup_unresolved_tab(self):
        layout = QVBoxLayout(self.unresolved_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        self.unresolved_table = QTableWidget()
        self.unresolved_table.setColumnCount(4)
        self.unresolved_table.setHorizontalHeaderLabels(["Clip Name", "Edit Media ID", "Lookup Status", "Edit Range"])
        self._configure_table_widget(self.unresolved_table)
        header = self.unresolved_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.unresolved_table)

    def _configure_table_widget(self, table: QTableWidget):
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.setSortingEnabled(True)
        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setSectionResizeMode(QHeaderView.Interactive)

    def _connect_signals(self):
        self.time_format_combo.currentTextChanged.connect(self._on_time_format_changed)
        self.hide_unresolved_checkbox.stateChanged.connect(self._on_hide_unresolved_changed)

    @pyqtSlot(str)
    def _on_time_format_changed(self, new_format: str):
        logger.debug(f"Time format changed to: {new_format}")
        self._current_time_format = new_format
        self._refresh_time_display()  # Call dedicated refresh method

    @pyqtSlot(int)
    def _on_hide_unresolved_changed(self, state: int):
        self._hide_unresolved = (state == Qt.Checked)
        self._apply_row_visibility_filter()

    def _apply_row_visibility_filter(self):
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

    def clear_results(self):
        logger.debug("Clearing ResultsDisplayWidget tables.")
        # Removed self._analysis_data
        for table in [self.analysis_table, self.segments_table, self.unresolved_table]:
            table.blockSignals(True)
            table.setSortingEnabled(False)
            table.setRowCount(0)
            table.setSortingEnabled(True)
            table.blockSignals(False)
        self.time_format_combo.setCurrentIndex(0)
        self.hide_unresolved_checkbox.setChecked(False)

    def _refresh_time_display(self):
        """Refreshes the display text of all time cells based on current format."""
        logger.debug(f"Refreshing time display for format: {self._current_time_format}")
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

    def _update_cell_time_display(self, item: QTableWidgetItem, rt_value: Optional[opentime.RationalTime],
                                  rate: Optional[float]):
        """Helper to update the display text of a single time cell."""
        if item and isinstance(rt_value, opentime.RationalTime):
            display_text = format_time(rt_value, rate, self._current_time_format)
            item.setText(display_text)
        elif item:  # Handle cases where rt_value might be None or invalid
            item.setText("N/A")

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
            # --- End Time Columns ---

        table.blockSignals(False)
        table.setSortingEnabled(True)
        self._apply_row_visibility_filter()  # Apply visibility filter

    def display_plan_summary(self, segment_summary: List[Dict]):
        logger.debug(f"Displaying transfer plan summary for {len(segment_summary)} segments.")
        table = self.segments_table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setRowCount(len(segment_summary))
        status_colors = {"completed": QBrush(QColor(200, 255, 200)), "failed": QBrush(QColor(255, 150, 150)),
                         "running": QBrush(QColor(173, 216, 230)), "pending": QBrush(QColor(225, 225, 225)),
                         "calculated": QBrush(QColor(255, 255, 200)), "default": QBrush(Qt.white)}
        for i, seg_info in enumerate(segment_summary):
            status = seg_info.get('status', 'pending').lower()
            source_path = seg_info.get('source_path', 'N/A')
            row_brush = status_colors.get(status, status_colors["default"])

            def create_std_item(text: Any) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setBackground(row_brush)
                return item

            index_val = seg_info.get('index', i + 1)
            idx_item = QTableWidgetItem(str(index_val))
            idx_item.setData(Qt.EditRole, QVariant(index_val))
            idx_item.setBackground(row_brush)
            idx_item.setTextAlignment(Qt.AlignCenter)
            source_item = create_std_item(os.path.basename(source_path))
            source_item.setToolTip(source_path)
            table.setItem(i, 0, idx_item)
            table.setItem(i, 1, source_item)
            table.setItem(i, 2, create_std_item(seg_info.get('range_start_tc', 'N/A')))
            table.setItem(i, 3, create_std_item(f"{seg_info.get('duration_sec', 0.0):.3f}"))
            table.setItem(i, 4, create_std_item(status.upper()))
            table.setItem(i, 5, create_std_item(seg_info.get('error', '')))
        table.blockSignals(False)
        table.setSortingEnabled(True)

    def display_unresolved_summary(self, unresolved_summary: List[Dict]):
        logger.debug(f"Displaying {len(unresolved_summary)} unresolved/error items.")
        table = self.unresolved_table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setRowCount(len(unresolved_summary))
        status_colors = {"not_found": QBrush(QColor(255, 200, 200)), "error": QBrush(QColor(255, 160, 122)),
                         "pending": QBrush(QColor(255, 255, 200)), "default": QBrush(Qt.white)}
        for i, shot_info in enumerate(unresolved_summary):
            status = shot_info.get('status', 'unknown').lower()
            edit_path_id = shot_info.get('proxy_path', 'N/A')
            row_brush = status_colors.get(status, status_colors["default"])

            def create_std_item(text: Any) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setBackground(row_brush)
                return item

            name_item = create_std_item(shot_info.get('name', 'N/A'))
            id_item = create_std_item(edit_path_id)
            id_item.setToolTip(edit_path_id)
            table.setItem(i, 0, name_item)
            table.setItem(i, 1, id_item)
            table.setItem(i, 2, create_std_item(status.upper()))
            table.setItem(i, 3, create_std_item(shot_info.get('edit_range', 'N/A')))
        table.blockSignals(False)
        table.setSortingEnabled(True)

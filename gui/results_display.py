# gui/results_display.py
"""
Reusable widget for displaying analysis and segment results in tables.
Used within different workflow stage tabs. Includes time format switching
and filtering options for the Source Analysis tab.
"""
import logging
import os
from typing import List, Dict, Optional, Union

import opentimelineio
from PyQt5.QtCore import Qt, pyqtSlot, QVariant, QModelIndex
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView, QCheckBox, QComboBox,
                             QLabel, QSizePolicy, QSpacerItem)
# Import opentime explicitly if not already done project-wide via __init__
from opentimelineio import opentime

logger = logging.getLogger(__name__)


# --- Helper Function for Formatting Time ---
def format_time(value: Optional[opentimelineio.opentime.RationalTime], rate: Optional[float], display_mode: str) -> str:
    """Formats RationalTime to Timecode or Frames string."""
    if not isinstance(value, opentime.RationalTime):
        return "N/A"
    # Use rate directly if it's valid, otherwise indicate issue
    current_rate = rate
    if current_rate is None or current_rate <= 0:
        inferred_rate = getattr(value, 'rate', None)
        if inferred_rate and inferred_rate > 0:
            current_rate = inferred_rate
            # logger.debug(f"format_time using inferred rate: {current_rate}") # Optional log
        else:
            return f"{value.value} (Rate?)"  # Cannot format without rate
    # Ensure rate is float for OTIO functions
    current_rate = float(current_rate)

    try:
        if display_mode == "Timecode":
            return opentime.to_timecode(value, current_rate)
        elif display_mode == "Frames":
            if value.rate == current_rate:
                frames = round(value.value)
            else:
                frames = round(value.rescaled_to(current_rate).value)
            return str(int(frames))
        else:  # Fallback
            return str(value)
    except ValueError as ve:
        if "non-dropframe" in str(ve).lower():
            try:
                return opentime.to_timecode(value, current_rate, opentime.DropFrameRate.ForceNo)
            except:
                pass
        logger.warning(f"Error formatting time {value} rate {current_rate} mode {display_mode}: {ve}")
        return f"ErrFmt ({value.value})"
    except Exception as e:
        logger.warning(f"Error formatting time {value} rate {current_rate} mode {display_mode}: {e}")
        return f"Err ({value.value})"


# --- Custom Table Widget Item for numerical sorting ---
# Using standard QTableWidgetItem and setData(Qt.EditRole, ...) for sorting

class ResultsDisplayWidget(QWidget):
    """A widget with tabs to display analysis, segments, and unresolved items."""

    # Column Indices for Analysis Table
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
    TIME_COLUMNS_ANALYSIS = [COL_SOURCE_IN, COL_SOURCE_OUT, COL_SOURCE_DUR,
                             COL_SOURCE_POINT_IN, COL_SOURCE_POINT_OUT, COL_SOURCE_POINT_DUR,
                             COL_EDIT_IN, COL_EDIT_OUT, COL_EDIT_DUR]
    TOTAL_ANALYSIS_COLS = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._analysis_data: List[Dict] = []
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
        """Sets up the analysis tab with new structure and controls."""
        layout = QVBoxLayout(self.analysis_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        # Controls Row
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
        # Table
        self.analysis_table = QTableWidget()
        self.analysis_table.setColumnCount(self.TOTAL_ANALYSIS_COLS)
        self.analysis_table.setHorizontalHeaderLabels(["#", "Clip Name", "Edit Media ID", "Source Path", "Status",
                                                       "Source IN", "Source OUT", "Source Dur",
                                                       "Src Pt IN", "Src Pt OUT", "Src Pt Dur",
                                                       "Edit IN", "Edit OUT", "Edit Dur"])
        self._configure_table_widget(self.analysis_table)
        header = self.analysis_table.horizontalHeader()
        # Set desired initial modes
        header.setSectionResizeMode(QHeaderView.Interactive)  # Default
        header.setSectionResizeMode(self.COL_CLIP_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_EDIT_MEDIA_ID, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_SOURCE_PATH, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_IDX, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeToContents)
        for col_idx in self.TIME_COLUMNS_ANALYSIS: header.setSectionResizeMode(col_idx, QHeaderView.ResizeToContents)
        layout.addWidget(self.analysis_table)

    def _setup_segments_tab(self):
        """Sets up the tab displaying calculated TransferSegments."""
        layout = QVBoxLayout(self.segments_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        self.segments_table = QTableWidget()
        self.segments_table.setColumnCount(6)
        self.segments_table.setHorizontalHeaderLabels(
            ["#", "Original Source", "Start TC", "Duration (sec)", "Transcode Status", "Error / Notes"])
        self._configure_table_widget(self.segments_table)
        header = self.segments_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # Default
        header.setSectionResizeMode(1, QHeaderView.Stretch);
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        try:
            header.setSectionHidden(4, True); header.setSectionHidden(5, True)  # Hide for Color Prep
        except Exception as e:
            logger.warning(f"Could not hide columns in segments tab: {e}")
        layout.addWidget(self.segments_table)

    def _setup_unresolved_tab(self):
        """Sets up the tab displaying unresolved shots."""
        layout = QVBoxLayout(self.unresolved_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        self.unresolved_table = QTableWidget()
        self.unresolved_table.setColumnCount(4)
        self.unresolved_table.setHorizontalHeaderLabels(["Clip Name", "Edit Media ID", "Lookup Status", "Edit Range"])
        self._configure_table_widget(self.unresolved_table)
        header = self.unresolved_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # Default
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Edit Media ID
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Status
        layout.addWidget(self.unresolved_table)

    def _configure_table_widget(self, table: QTableWidget):
        """Applies common settings ensuring interactive resizing."""
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
        # Ensure default is Interactive AFTER setting sorting enabled maybe?
        header.setSectionResizeMode(QHeaderView.Interactive)

    def _connect_signals(self):
        """Connect signals for controls."""
        self.time_format_combo.currentTextChanged.connect(self._on_time_format_changed)
        self.hide_unresolved_checkbox.stateChanged.connect(self._on_hide_unresolved_changed)

    @pyqtSlot(str)
    def _on_time_format_changed(self, new_format: str):
        self._current_time_format = new_format
        self.display_analysis_summary(self._analysis_data)  # Re-populate

    @pyqtSlot(int)
    def _on_hide_unresolved_changed(self, state: int):
        self._hide_unresolved = (state == Qt.Checked)
        self._apply_row_visibility_filter()

    def _apply_row_visibility_filter(self):
        table = self.analysis_table
        for row in range(table.rowCount()):
            status_item = table.item(row, self.COL_STATUS)
            should_hide = False
            if status_item:
                status = status_item.text().lower()
                is_unresolved = (status == 'not_found' or status == 'error')
                should_hide = self._hide_unresolved and is_unresolved
            else:
                should_hide = True
            table.setRowHidden(row, should_hide)

    def clear_results(self):
        logger.debug("Clearing ResultsDisplayWidget tables and data.")
        self._analysis_data = []
        for table in [self.analysis_table, self.segments_table, self.unresolved_table]:
            table.blockSignals(True);
            table.setSortingEnabled(False);
            table.setRowCount(0);
            table.setSortingEnabled(True);
            table.blockSignals(False)
        self.time_format_combo.setCurrentIndex(0)
        self.hide_unresolved_checkbox.setChecked(False)

    def display_analysis_summary(self, analysis_summary_data: List[Dict]):
        """Updates the 'Source Analysis Status' table with new data structure."""
        logger.debug(f"Displaying analysis summary for {len(analysis_summary_data)} shots.")
        self._analysis_data = analysis_summary_data
        table = self.analysis_table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setRowCount(len(self._analysis_data))

        status_colors = {"found": QBrush(QColor(200, 255, 200)), "not_found": QBrush(QColor(255, 200, 200)),
                         "error": QBrush(QColor(255, 160, 122)), "pending": QBrush(QColor(255, 255, 200)),
                         "default": QBrush(Qt.white)}

        for row, shot_info in enumerate(self._analysis_data):
            status = shot_info.get('status', 'unknown').lower()
            row_brush = status_colors.get(status, status_colors["default"])

            # Helper to create standard items
            def create_std_item(text: str) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                item.setBackground(row_brush)
                return item

            # Helper to create time items with data for sorting
            def create_time_item(rt_value: Optional[opentime.RationalTime], rate: Optional[float]) -> QTableWidgetItem:
                text = format_time(rt_value, rate, self._current_time_format)
                item = QTableWidgetItem(text)  # Use standard item
                numeric_val = None
                # Store frame number for sorting when in Frames mode
                if self._current_time_format == "Frames" and isinstance(rt_value,
                                                                        opentime.RationalTime) and rate and rate > 0:
                    try:
                        numeric_val = int(round(rt_value.rescaled_to(rate).value))
                    except Exception:
                        pass  # Ignore rescale errors
                if numeric_val is not None:
                    item.setData(Qt.EditRole, numeric_val)  # Store data for sorting
                item.setBackground(row_brush)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                return item

            # --- Populate Row ---
            # Index
            index_val = shot_info.get("index", row + 1)
            index_item = QTableWidgetItem(str(index_val))
            index_item.setData(Qt.EditRole, index_val)  # Data for sorting
            index_item.setBackground(row_brush)
            index_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, self.COL_IDX, index_item)

            # Standard Columns
            table.setItem(row, self.COL_CLIP_NAME, create_std_item(shot_info.get("clip_name", "N/A")))
            edit_media_id = shot_info.get("edit_media_id", "N/A");
            id_item = create_std_item(edit_media_id);
            id_item.setToolTip(edit_media_id);
            table.setItem(row, self.COL_EDIT_MEDIA_ID, id_item)
            source_path = shot_info.get("source_path", "N/A");
            path_item = create_std_item(source_path);
            path_item.setToolTip(source_path);
            table.setItem(row, self.COL_SOURCE_PATH, path_item)
            table.setItem(row, self.COL_STATUS, create_std_item(status.upper()))

            # Time Columns
            # Source Times
            source_rate = shot_info.get('source_rate')
            source_in_rt = shot_info.get('source_in_rt')
            source_out_rt_excl = shot_info.get('source_out_rt_excl')
            source_dur_rt = shot_info.get('source_duration_rt')
            source_out_rt_incl = None
            if source_in_rt and source_dur_rt:
                try:
                    source_out_rt_incl = source_in_rt + opentime.RationalTime(source_dur_rt.value - 1,
                                                                              source_dur_rt.rate) if source_dur_rt.value > 0 else source_in_rt
                except Exception:
                    pass
            table.setItem(row, self.COL_SOURCE_IN, create_time_item(source_in_rt, source_rate))
            table.setItem(row, self.COL_SOURCE_OUT, create_time_item(source_out_rt_incl, source_rate))
            table.setItem(row, self.COL_SOURCE_DUR, create_time_item(source_dur_rt, source_rate))

            # Source Point Times
            source_point_rate = shot_info.get('source_point_rate')
            source_point_in_rt = shot_info.get('source_point_in_rt')
            source_point_out_rt_excl = shot_info.get('source_point_out_rt_excl')
            source_point_dur_rt = shot_info.get('source_point_duration_rt')  # Corrected variable name
            source_point_out_rt_incl = None
            if source_point_in_rt and source_point_dur_rt:
                try:
                    source_point_out_rt_incl = source_point_in_rt + opentime.RationalTime(source_point_dur_rt.value - 1,
                                                                                          source_point_dur_rt.rate) if source_point_dur_rt.value > 0 else source_point_in_rt
                except Exception:
                    pass
            table.setItem(row, self.COL_SOURCE_POINT_IN, create_time_item(source_point_in_rt, source_point_rate))
            table.setItem(row, self.COL_SOURCE_POINT_OUT, create_time_item(source_point_out_rt_incl, source_point_rate))
            table.setItem(row, self.COL_SOURCE_POINT_DUR, create_time_item(source_point_dur_rt, source_point_rate))

            # Edit Position Times
            sequence_rate = shot_info.get('sequence_rate')
            edit_in_rt = shot_info.get('edit_in_rt')
            edit_out_rt_excl = shot_info.get('edit_out_rt_excl')
            edit_dur_rt = shot_info.get('edit_duration_rt')
            edit_out_rt_incl = None
            if edit_in_rt and edit_dur_rt:
                try:
                    edit_out_rt_incl = edit_in_rt + opentime.RationalTime(edit_dur_rt.value - 1,
                                                                          edit_dur_rt.rate) if edit_dur_rt.value > 0 else edit_in_rt
                except Exception:
                    pass
            table.setItem(row, self.COL_EDIT_IN, create_time_item(edit_in_rt, sequence_rate))
            table.setItem(row, self.COL_EDIT_OUT, create_time_item(edit_out_rt_incl, sequence_rate))
            table.setItem(row, self.COL_EDIT_DUR, create_time_item(edit_dur_rt, sequence_rate))
            # --- End Time Columns ---

        table.blockSignals(False)
        table.setSortingEnabled(True)
        self._apply_row_visibility_filter()  # Apply filter after filling

    def display_plan_summary(self, segment_summary: List[Dict]):
        """Updates the 'Calculated Segments' table."""
        logger.debug(f"Displaying transfer plan summary for {len(segment_summary)} segments.")
        table = self.segments_table;
        table.setSortingEnabled(False);
        table.blockSignals(True);
        table.setRowCount(len(segment_summary))
        status_colors = {"completed": QBrush(QColor(200, 255, 200)), "failed": QBrush(QColor(255, 150, 150)),
                         "running": QBrush(QColor(173, 216, 230)), "pending": QBrush(QColor(225, 225, 225)),
                         "calculated": QBrush(QColor(255, 255, 200)), "default": QBrush(Qt.white)}
        for i, seg_info in enumerate(segment_summary):
            status = seg_info.get('status', 'pending').lower();
            source_path = seg_info.get('source_path', 'N/A');
            row_brush = status_colors.get(status, status_colors["default"])

            def create_std_item(text: str) -> QTableWidgetItem: item = QTableWidgetItem(text); item.setBackground(
                row_brush); return item

            index_val = seg_info.get('index', i + 1);
            idx_item = QTableWidgetItem(str(index_val));
            idx_item.setData(Qt.EditRole, index_val);
            idx_item.setBackground(row_brush);
            idx_item.setTextAlignment(Qt.AlignCenter)
            source_item = create_std_item(os.path.basename(source_path));
            source_item.setToolTip(source_path)
            table.setItem(i, 0, idx_item);
            table.setItem(i, 1, source_item);
            table.setItem(i, 2, create_std_item(seg_info.get('range_start_tc', 'N/A')))
            table.setItem(i, 3, create_std_item(f"{seg_info.get('duration_sec', 0.0):.3f}"));
            table.setItem(i, 4, create_std_item(status.upper()));
            table.setItem(i, 5, create_std_item(seg_info.get('error', '')))
        table.blockSignals(False);
        table.setSortingEnabled(True)

    def display_unresolved_summary(self, unresolved_summary: List[Dict]):
        """Updates the 'Unresolved / Errors' table."""
        logger.debug(f"Displaying {len(unresolved_summary)} unresolved/error items.")
        table = self.unresolved_table;
        table.setSortingEnabled(False);
        table.blockSignals(True);
        table.setRowCount(len(unresolved_summary))
        status_colors = {"not_found": QBrush(QColor(255, 200, 200)), "error": QBrush(QColor(255, 160, 122)),
                         "pending": QBrush(QColor(255, 255, 200)), "default": QBrush(Qt.white)}
        for i, shot_info in enumerate(unresolved_summary):
            status = shot_info.get('status', 'unknown').lower();
            edit_path_id = shot_info.get('proxy_path', 'N/A');
            row_brush = status_colors.get(status, status_colors["default"])

            def create_std_item(text: str) -> QTableWidgetItem: item = QTableWidgetItem(text); item.setBackground(
                row_brush); return item

            name_item = create_std_item(shot_info.get('name', 'N/A'));
            id_item = create_std_item(edit_path_id);
            id_item.setToolTip(edit_path_id)
            table.setItem(i, 0, name_item);
            table.setItem(i, 1, id_item);
            table.setItem(i, 2, create_std_item(status.upper()));
            table.setItem(i, 3, create_std_item(shot_info.get('edit_range', 'N/A')))
        table.blockSignals(False);
        table.setSortingEnabled(True)

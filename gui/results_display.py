# gui/results_display.py
"""
Reusable widget for displaying analysis and segment results in tables.
Used within different workflow stage tabs.
"""
import logging
import os
from typing import List, Dict

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView)

logger = logging.getLogger(__name__)


class ResultsDisplayWidget(QWidget):
    """A widget with tabs to display analysis, segments, and unresolved items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        logger.debug("ResultsDisplayWidget initialized.")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)  # No margins when embedded

        self.tabs = QTabWidget()
        # Create tab widgets (these will hold the tables)
        self.analysis_tab = QWidget()
        self.segments_tab = QWidget()
        self.unresolved_tab = QWidget()

        # Setup layout and table for each tab
        self._setup_analysis_tab()
        self._setup_segments_tab()
        self._setup_unresolved_tab()

        # Add tabs
        self.tabs.addTab(self.analysis_tab, "Source Analysis Status")
        self.tabs.addTab(self.segments_tab, "Calculated Segments")
        self.tabs.addTab(self.unresolved_tab, "Unresolved / Errors")

        main_layout.addWidget(self.tabs)

    def _setup_analysis_tab(self):
        """Sets up the tab displaying EditShots and their source lookup status."""
        layout = QVBoxLayout(self.analysis_tab)
        layout.setContentsMargins(2, 2, 2, 2)  # Small margins inside tab
        self.analysis_table = QTableWidget()
        self.analysis_table.setColumnCount(5)
        self.analysis_table.setHorizontalHeaderLabels([
            "Clip Name", "Edit Media (Proxy/Mezz)", "Found Original Source", "Lookup Status", "Edit Range (Source)"
        ])
        self._configure_table_widget(self.analysis_table)
        self.analysis_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.analysis_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.analysis_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.analysis_table)

    def _setup_segments_tab(self):
        """Sets up the tab displaying calculated TransferSegments."""
        layout = QVBoxLayout(self.segments_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        self.segments_table = QTableWidget()
        self.segments_table.setColumnCount(6)
        self.segments_table.setHorizontalHeaderLabels([
            "#", "Original Source", "Start TC", "Duration (sec)", "Transcode Status", "Error / Notes"
        ])
        self._configure_table_widget(self.segments_table)
        self.segments_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.segments_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.segments_table)

    def _setup_unresolved_tab(self):
        """Sets up the tab displaying shots that couldn't be resolved or had errors."""
        layout = QVBoxLayout(self.unresolved_tab)
        layout.setContentsMargins(2, 2, 2, 2)
        self.unresolved_table = QTableWidget()
        self.unresolved_table.setColumnCount(4)
        self.unresolved_table.setHorizontalHeaderLabels([
            "Clip Name", "Edit Media Path", "Status", "Edit Range (Source)"
        ])
        self._configure_table_widget(self.unresolved_table)
        self.unresolved_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.unresolved_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.unresolved_table)

    def _configure_table_widget(self, table: QTableWidget):
        """Applies common settings to table widgets."""
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.setSortingEnabled(True)
        # Adjust interactive columns for content size initially
        for i in range(table.columnCount()):
            if table.horizontalHeader().sectionResizeMode(i) == QHeaderView.Interactive:
                table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)

    # --- Public Methods to Update UI ---

    def clear_results(self):
        """Clears all tables in the results display."""
        logger.debug("Clearing ResultsDisplayWidget tables.")
        for table in [self.analysis_table, self.segments_table, self.unresolved_table]:
            table.setSortingEnabled(False)
            table.setRowCount(0)
            table.setSortingEnabled(True)

    def display_analysis_summary(self, analysis_summary: List[Dict]):
        """Updates the 'Source Analysis Status' table."""
        logger.debug(f"Displaying analysis summary for {len(analysis_summary)} edit shots.")
        table = self.analysis_table
        table.setSortingEnabled(False)
        table.setRowCount(len(analysis_summary))
        status_colors = {"found": QColor(200, 255, 200), "not_found": QColor(255, 200, 200),
                         "error": QColor(255, 160, 122), "pending": QColor(255, 255, 200), "default": QColor(Qt.white)}

        for i, shot_info in enumerate(analysis_summary):
            status = shot_info.get('status', 'unknown')
            original_path = shot_info.get('original_path', 'N/A')
            edit_path = shot_info.get('proxy_path', 'N/A')

            items = [
                QTableWidgetItem(shot_info.get('name', 'N/A')),
                QTableWidgetItem(edit_path),
                QTableWidgetItem(original_path if status == 'found' else 'N/A'),
                QTableWidgetItem(status),
                QTableWidgetItem(shot_info.get('edit_range', 'N/A'))
            ]
            items[1].setToolTip(edit_path)
            if status == 'found': items[2].setToolTip(original_path)

            row_color = status_colors.get(status, status_colors["default"])
            for col, item in enumerate(items):
                item.setBackground(row_color)
                table.setItem(i, col, item)

        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

    def display_plan_summary(self, segment_summary: List[Dict]):
        """Updates the 'Calculated Segments' table."""
        logger.debug(f"Displaying transfer plan summary for {len(segment_summary)} segments.")
        table = self.segments_table
        table.setSortingEnabled(False)
        table.setRowCount(len(segment_summary))
        status_colors = {"completed": QColor(200, 255, 200), "failed": QColor(255, 150, 150),
                         "running": QColor(173, 216, 230), "pending": QColor(225, 225, 225),
                         "calculated": QColor(255, 255, 200), "default": QColor(Qt.white)}

        for i, seg_info in enumerate(segment_summary):
            status = seg_info.get('status', 'pending')
            source_path = seg_info.get('source_path', 'N/A')

            items = [
                QTableWidgetItem(str(seg_info.get('index', i + 1))),
                QTableWidgetItem(os.path.basename(source_path)),
                QTableWidgetItem(seg_info.get('range_start_tc', 'N/A')),
                QTableWidgetItem(f"{seg_info.get('duration_sec', 0.0):.3f}"),
                QTableWidgetItem(status),
                QTableWidgetItem(seg_info.get('error', ''))
            ]
            items[0].setTextAlignment(Qt.AlignCenter)
            items[1].setToolTip(source_path)

            row_color = status_colors.get(status, status_colors["default"])
            for col, item in enumerate(items):
                item.setBackground(row_color)
                table.setItem(i, col, item)

        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

    def display_unresolved_summary(self, unresolved_summary: List[Dict]):
        """Updates the 'Unresolved / Errors' table."""
        logger.debug(f"Displaying {len(unresolved_summary)} unresolved/error items.")
        table = self.unresolved_table
        table.setSortingEnabled(False)
        table.setRowCount(len(unresolved_summary))
        status_colors = {"not_found": QColor(255, 200, 200), "error": QColor(255, 160, 122),
                         "pending": QColor(255, 255, 200), "default": QColor(Qt.white)}

        for i, shot_info in enumerate(unresolved_summary):
            status = shot_info.get('status', 'unknown')
            edit_path = shot_info.get('proxy_path', 'N/A')
            items = [
                QTableWidgetItem(shot_info.get('name', 'N/A')),
                QTableWidgetItem(edit_path),
                QTableWidgetItem(status),
                QTableWidgetItem(shot_info.get('edit_range', 'N/A'))
            ]
            items[1].setToolTip(edit_path)

            row_color = status_colors.get(status, status_colors["default"])
            for col, item in enumerate(items):
                item.setBackground(row_color)
                table.setItem(i, col, item)

        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

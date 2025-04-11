# gui/results_panel.py
"""
Results Panel Module - Updated for Summary Data

Displays analysis results (EditShot status), transfer plan segments,
and unresolved shots using summary data provided by MainWindow's worker thread.
"""

import logging
import os
from typing import List, Dict, Any, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QAbstractItemView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor  # For row coloring

logger = logging.getLogger(__name__)


class ResultsPanel(QWidget):
    """Panel for displaying analysis results and transfer plan information."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        logger.info("ResultsPanel initialized.")

    def init_ui(self):
        """Set up the user interface."""
        main_layout = QVBoxLayout(self)
        title_label = QLabel("3. Results & Plan")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title_label)

        self.tabs = QTabWidget()

        # Create tab widgets
        self.edit_shots_tab = QWidget()
        self.transfer_segments_tab = QWidget()
        self.unresolved_tab = QWidget()

        # Setup layout and widgets for each tab
        self._setup_edit_shots_tab()
        self._setup_transfer_segments_tab()
        self._setup_unresolved_tab()

        # Add tabs
        self.tabs.addTab(self.edit_shots_tab, "Source Analysis Status")  # More descriptive name
        self.tabs.addTab(self.transfer_segments_tab, "Calculated Transfer Segments")
        self.tabs.addTab(self.unresolved_tab, "Unresolved / Lookup Errors")

        main_layout.addWidget(self.tabs)
        logger.debug("ResultsPanel UI created.")

    def _setup_edit_shots_tab(self):
        """Sets up the tab displaying EditShots and their source lookup status."""
        layout = QVBoxLayout(self.edit_shots_tab)
        self.edit_shots_table = QTableWidget()
        # Columns match keys in the summary dict from get_edit_shots_summary
        self.edit_shots_table.setColumnCount(5)
        self.edit_shots_table.setHorizontalHeaderLabels([
            "Clip Name", "Edit Media (Proxy/Mezz)", "Found Original Source", "Lookup Status", "Edit Range (Source)"
        ])
        self._configure_table_widget(self.edit_shots_table)
        # Column sizing adjustments
        self.edit_shots_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.edit_shots_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.edit_shots_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.edit_shots_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.edit_shots_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        layout.addWidget(self.edit_shots_table)

    def _setup_transfer_segments_tab(self):
        """Sets up the tab displaying calculated TransferSegments."""
        layout = QVBoxLayout(self.transfer_segments_tab)
        self.segments_table = QTableWidget()
        # Columns match keys in the summary dict from get_transfer_segments_summary
        self.segments_table.setColumnCount(6)
        self.segments_table.setHorizontalHeaderLabels([
            "#", "Original Source", "Start TC", "Duration (sec)", "Transcode Status", "Error / Notes"
        ])
        self._configure_table_widget(self.segments_table)
        # Column sizing adjustments
        self.segments_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.segments_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.segments_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.segments_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.segments_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.segments_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.segments_table)

    def _setup_unresolved_tab(self):
        """Sets up the tab displaying shots that couldn't be resolved or had errors."""
        layout = QVBoxLayout(self.unresolved_tab)
        self.unresolved_table = QTableWidget()
        # Columns match keys in the summary dict from get_unresolved_shots_summary
        self.unresolved_table.setColumnCount(4)
        self.unresolved_table.setHorizontalHeaderLabels([
            "Clip Name", "Edit Media Path", "Lookup Status", "Edit Range (Source)"
        ])
        self._configure_table_widget(self.unresolved_table)
        # Column sizing adjustments
        self.unresolved_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.unresolved_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.unresolved_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.unresolved_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        layout.addWidget(self.unresolved_table)

    def _configure_table_widget(self, table: QTableWidget):
        """Applies common settings to table widgets."""
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        # Enable sorting
        table.setSortingEnabled(True)

    # --- Public Methods to Update UI ---

    def clear_results(self):
        """Clears all tables in the results panel."""
        logger.debug("Clearing ResultsPanel tables.")
        self.edit_shots_table.setSortingEnabled(False)  # Disable sorting during clear
        self.edit_shots_table.setRowCount(0)
        self.edit_shots_table.setSortingEnabled(True)

        self.segments_table.setSortingEnabled(False)
        self.segments_table.setRowCount(0)
        self.segments_table.setSortingEnabled(True)

        self.unresolved_table.setSortingEnabled(False)
        self.unresolved_table.setRowCount(0)
        self.unresolved_table.setSortingEnabled(True)
        logger.info("ResultsPanel views cleared.")

    def display_analysis_summary(self, edit_shot_summary: List[Dict]):
        """
        Updates the 'Source Analysis Status' tab with EditShot summary data.

        Args:
            edit_shot_summary: List of dicts from harvester.get_edit_shots_summary().
        """
        logger.info(f"Displaying analysis summary for {len(edit_shot_summary)} edit shots.")
        self.edit_shots_table.setSortingEnabled(False)
        self.edit_shots_table.setRowCount(len(edit_shot_summary))
        unresolved_list = []  # Collect items for the unresolved tab

        # Define colors for statuses
        status_colors = {
            "found": QColor(200, 255, 200),  # Light green
            "not_found": QColor(255, 200, 200),  # Light red
            "error": QColor(255, 160, 122),  # Light salmon/orange
            "pending": QColor(255, 255, 200),  # Light yellow
            "default": QColor(Qt.white)
        }

        for i, shot_info in enumerate(edit_shot_summary):
            # --- Get data from summary dictionary ---
            clip_name = shot_info.get('name', 'N/A')
            edit_path = shot_info.get('proxy_path', 'N/A')
            original_path = shot_info.get('original_path', 'N/A')
            status = shot_info.get('status', 'unknown')
            edit_range_str = shot_info.get('edit_range', 'N/A')

            # --- Create QTableWidgetItems ---
            name_item = QTableWidgetItem(clip_name)
            edit_path_item = QTableWidgetItem(edit_path)
            edit_path_item.setToolTip(edit_path)  # Show full path on hover
            original_path_item = QTableWidgetItem(original_path)  # Show full path here
            if status == 'found': original_path_item.setToolTip(original_path)
            status_item = QTableWidgetItem(status)
            range_item = QTableWidgetItem(edit_range_str)

            # --- Populate Row ---
            self.edit_shots_table.setItem(i, 0, name_item)
            self.edit_shots_table.setItem(i, 1, edit_path_item)
            self.edit_shots_table.setItem(i, 2, original_path_item)
            self.edit_shots_table.setItem(i, 3, status_item)
            self.edit_shots_table.setItem(i, 4, range_item)

            # --- Color Row ---
            row_color = status_colors.get(status, status_colors["default"])
            for col in range(self.edit_shots_table.columnCount()):
                self.edit_shots_table.item(i, col).setBackground(row_color)

            # --- Add to unresolved list if needed ---
            if status != 'found':
                unresolved_list.append(shot_info)

        self.edit_shots_table.setSortingEnabled(True)
        self.edit_shots_table.resizeColumnsToContents()  # Adjust columns after populating
        self.display_unresolved_summary(unresolved_list)  # Update the other tab
        self.tabs.setCurrentIndex(0)  # Switch view to this tab

    def display_plan_summary(self, segment_summary: List[Dict]):
        """
        Updates the 'Transfer Plan Segments' tab with segment summary data.

        Args:
            segment_summary: List of dicts from harvester.get_transfer_segments_summary().
        """
        logger.info(f"Displaying transfer plan summary for {len(segment_summary)} segments.")
        self.segments_table.setSortingEnabled(False)
        self.segments_table.setRowCount(len(segment_summary))

        # Define colors for statuses
        status_colors = {
            "completed": QColor(200, 255, 200),  # Light green
            "failed": QColor(255, 150, 150),  # Stronger red
            "running": QColor(173, 216, 230),  # Light blue
            "pending": QColor(225, 225, 225),  # Light grey for pending transcode
            "calculated": QColor(255, 255, 200),  # Light yellow for ready-to-transcode
            "default": QColor(Qt.white)
        }

        for i, seg_info in enumerate(segment_summary):
            # --- Get data from summary dictionary ---
            index = seg_info.get('index', i + 1)
            source_path = seg_info.get('source_path', 'N/A')
            start_tc = seg_info.get('range_start_tc', 'N/A')
            duration_sec = seg_info.get('duration_sec', 0.0)
            status = seg_info.get('status', 'pending')
            error_notes = seg_info.get('error', '')

            # --- Create QTableWidgetItems ---
            index_item = QTableWidgetItem(str(index))
            index_item.setTextAlignment(Qt.AlignCenter)
            source_item = QTableWidgetItem(os.path.basename(source_path))
            source_item.setToolTip(source_path)  # Full path on hover
            tc_item = QTableWidgetItem(start_tc)
            duration_item = QTableWidgetItem(f"{duration_sec:.3f}")  # Show milliseconds
            status_item = QTableWidgetItem(status)
            error_item = QTableWidgetItem(error_notes)

            # --- Populate Row ---
            self.segments_table.setItem(i, 0, index_item)
            self.segments_table.setItem(i, 1, source_item)
            self.segments_table.setItem(i, 2, tc_item)
            self.segments_table.setItem(i, 3, duration_item)
            self.segments_table.setItem(i, 4, status_item)
            self.segments_table.setItem(i, 5, error_item)

            # --- Color Row ---
            row_color = status_colors.get(status, status_colors["default"])
            for col in range(self.segments_table.columnCount()):
                if self.segments_table.item(i, col):  # Check item exists
                    self.segments_table.item(i, col).setBackground(row_color)

        self.segments_table.setSortingEnabled(True)
        self.segments_table.resizeColumnsToContents()
        self.tabs.setCurrentIndex(1)  # Switch view to this tab

    def display_unresolved_summary(self, unresolved_summary: List[Dict]):
        """Updates the 'Unresolved / Errors' tab."""
        logger.info(f"Displaying {len(unresolved_summary)} unresolved/error items.")
        self.unresolved_table.setSortingEnabled(False)
        self.unresolved_table.setRowCount(len(unresolved_summary))

        # Define colors
        status_colors = {
            "not_found": QColor(255, 200, 200),  # Light red
            "error": QColor(255, 160, 122),  # Light salmon/orange
            "pending": QColor(255, 255, 200),  # Light yellow (shouldn't be here if analysis ran)
            "default": QColor(Qt.white)
        }

        for i, shot_info in enumerate(unresolved_summary):
            # --- Get data ---
            clip_name = shot_info.get('name', 'N/A')
            edit_path = shot_info.get('proxy_path', 'N/A')
            status = shot_info.get('status', 'unknown')
            edit_range_str = shot_info.get('edit_range', 'N/A')

            # --- Create items ---
            name_item = QTableWidgetItem(clip_name)
            edit_path_item = QTableWidgetItem(edit_path)
            edit_path_item.setToolTip(edit_path)
            status_item = QTableWidgetItem(status)
            range_item = QTableWidgetItem(edit_range_str)

            # --- Populate row ---
            self.unresolved_table.setItem(i, 0, name_item)
            self.unresolved_table.setItem(i, 1, edit_path_item)
            self.unresolved_table.setItem(i, 2, status_item)
            self.unresolved_table.setItem(i, 3, range_item)

            # --- Color row ---
            row_color = status_colors.get(status, status_colors["default"])
            for col in range(self.unresolved_table.columnCount()):
                self.unresolved_table.item(i, col).setBackground(row_color)

        self.unresolved_table.setSortingEnabled(True)
        self.unresolved_table.resizeColumnsToContents()
        # Do not automatically switch to this tab, let user navigate
        logger.debug("Unresolved/Errors tab updated.")

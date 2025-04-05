"""
Results Panel Module

This module defines the ResultsPanel widget, which displays analysis results,
transfer plan information, and visualizations of the optimized media segments.
"""

import logging
from typing import List, Dict, Any, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QLabel, QTextEdit, QGroupBox, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

import opentimelineio as otio

from core.models import TransferPlan

# Configure logging
logger = logging.getLogger(__name__)


class ResultsPanel(QWidget):
    """
    Panel for displaying analysis results and transfer plan information.

    This panel shows information about source files, gaps, optimized segments,
    and potential savings.
    """

    def __init__(self, parent=None):
        """
        Initialize the results panel.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        # Set up the UI
        self.init_ui()

        logger.info("Results panel initialized")

    def init_ui(self):
        """Set up the user interface."""
        # Main layout
        main_layout = QVBoxLayout(self)

        # Title
        title_label = QLabel("Analysis Results")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title_label)

        # Tab widget for different result views
        self.tabs = QTabWidget()

        # Create tabs
        self.source_tab = QWidget()
        self.analysis_tab = QWidget()
        self.plan_tab = QWidget()
        self.segments_tab = QWidget()

        self.setup_source_tab()
        self.setup_analysis_tab()
        self.setup_plan_tab()
        self.setup_segments_tab()

        # Add tabs to tab widget
        self.tabs.addTab(self.source_tab, "Source Files")
        self.tabs.addTab(self.analysis_tab, "Gap Analysis")
        self.tabs.addTab(self.plan_tab, "Transfer Plan")
        self.tabs.addTab(self.segments_tab, "Segments")

        # Add tab widget to main layout
        main_layout.addWidget(self.tabs)

    def setup_source_tab(self):
        """Set up the Source Files tab."""
        layout = QVBoxLayout(self.source_tab)

        # Source files tree
        self.source_tree = QTreeWidget()
        self.source_tree.setHeaderLabels(["Source File", "Usage Count", "Duration"])
        self.source_tree.setAlternatingRowColors(True)
        self.source_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.source_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.source_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        layout.addWidget(self.source_tree)

    def setup_analysis_tab(self):
        """Set up the Gap Analysis tab."""
        layout = QVBoxLayout(self.analysis_tab)

        # Splitter for dividable sections
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)

        # Group for gap statistics
        gap_stats_group = QGroupBox("Gap Statistics")
        gap_stats_layout = QVBoxLayout(gap_stats_group)

        self.gap_stats_text = QTextEdit()
        self.gap_stats_text.setReadOnly(True)
        gap_stats_layout.addWidget(self.gap_stats_text)

        # Group for detected gaps
        gaps_group = QGroupBox("Detected Gaps")
        gaps_layout = QVBoxLayout(gaps_group)

        self.gaps_tree = QTreeWidget()
        self.gaps_tree.setHeaderLabels(["Source File", "Gap Start", "Gap End", "Duration (sec)"])
        self.gaps_tree.setAlternatingRowColors(True)
        self.gaps_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)

        gaps_layout.addWidget(self.gaps_tree)

        # Add groups to splitter
        splitter.addWidget(gap_stats_group)
        splitter.addWidget(gaps_group)

        # Set initial splitter sizes
        splitter.setSizes([100, 300])

    def setup_plan_tab(self):
        """Set up the Transfer Plan tab."""
        layout = QVBoxLayout(self.plan_tab)

        # Plan info
        plan_info_group = QGroupBox("Plan Information")
        plan_info_layout = QVBoxLayout(plan_info_group)

        self.plan_info_text = QTextEdit()
        self.plan_info_text.setReadOnly(True)
        plan_info_layout.addWidget(self.plan_info_text)

        # Savings info
        savings_group = QGroupBox("Estimated Savings")
        savings_layout = QVBoxLayout(savings_group)

        self.savings_text = QTextEdit()
        self.savings_text.setReadOnly(True)
        savings_layout.addWidget(self.savings_text)

        # Add groups to layout
        layout.addWidget(plan_info_group)
        layout.addWidget(savings_group)

    def setup_segments_tab(self):
        """Set up the Segments tab."""
        layout = QVBoxLayout(self.segments_tab)

        # Segments table
        self.segments_table = QTableWidget()
        self.segments_table.setColumnCount(5)
        self.segments_table.setHorizontalHeaderLabels(
            ["Segment Name", "Source File", "Start Time", "End Time", "Duration (sec)"]
        )
        self.segments_table.setAlternatingRowColors(True)
        self.segments_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.segments_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        layout.addWidget(self.segments_table)

    def clear_results(self):
        """Clear all result displays."""
        # Clear source tab
        self.source_tree.clear()

        # Clear analysis tab
        self.gap_stats_text.clear()
        self.gaps_tree.clear()

        # Clear plan tab
        self.plan_info_text.clear()
        self.savings_text.clear()

        # Clear segments tab
        self.segments_table.setRowCount(0)

    def set_analysis_results(self, source_files: List[str],
                             savings: Dict[str, Any],
                             stats: Dict[str, Any]):
        """
        Set the analysis results data.

        Args:
            source_files: List of source file paths
            savings: Dictionary with gap savings information
            stats: Dictionary with timeline statistics
        """
        # Clear existing results
        self.clear_results()

        # Update source files tree
        self._update_source_files(source_files, stats)

        # Update gap analysis information
        self._update_gap_analysis(savings)

        # Select source files tab
        self.tabs.setCurrentIndex(0)

        logger.info("Analysis results updated")

    def set_plan_results(self, plan: TransferPlan):
        """
        Set the transfer plan results data.

        Args:
            plan: TransferPlan object with plan information
        """
        # Update plan information
        self._update_plan_info(plan)

        # Update segments information
        self._update_segments_info(plan.get_segments())

        # Select transfer plan tab
        self.tabs.setCurrentIndex(2)

        logger.info("Transfer plan results updated")

    def _update_source_files(self, source_files: List[str], stats: Dict[str, Any]):
        """
        Update the source files tree with data.

        Args:
            source_files: List of source file paths
            stats: Dictionary with timeline statistics
        """
        self.source_tree.clear()

        # Source usage info if available in stats
        source_usage = {}
        if 'source_usage' in stats:
            source_usage = stats['source_usage']

        for source_file in source_files:
            item = QTreeWidgetItem(self.source_tree)

            # Get basename for display
            base_name = source_file.split('/')[-1] if '/' in source_file else source_file.split('\\')[-1]

            # Set file name (column 0)
            item.setText(0, base_name)
            item.setToolTip(0, source_file)

            # Set usage count (column 1)
            usage_count = len(source_usage.get(source_file, [])) if source_usage else 0
            item.setText(1, str(usage_count))

            # No duration info at this point (column 2)
            item.setText(2, "Unknown")

        # Adjust column widths
        for i in range(self.source_tree.columnCount()):
            self.source_tree.resizeColumnToContents(i)

    def _update_gap_analysis(self, savings: Dict[str, Any]):
        """
        Update the gap analysis information.

        Args:
            savings: Dictionary with gap savings information
        """
        # Update gap statistics text
        stats_text = ""

        # Total gaps and total gap duration
        total_gaps = savings.get('total_gaps', 0)
        total_gap_duration = savings.get('total_gap_duration')

        if total_gap_duration:
            if hasattr(total_gap_duration, 'value') and hasattr(total_gap_duration, 'rate'):
                gap_seconds = total_gap_duration.value / total_gap_duration.rate
                stats_text += f"Total Gaps: {total_gaps}\n"
                stats_text += f"Total Gap Duration: {gap_seconds:.2f} seconds\n\n"

        # Savings by source
        if 'savings_by_source' in savings:
            stats_text += "Savings by Source:\n"
            for source, info in savings['savings_by_source'].items():
                base_name = source.split('/')[-1] if '/' in source else source.split('\\')[-1]

                num_gaps = info.get('num_gaps', 0)
                source_gap_duration = info.get('total_gap_duration')

                if source_gap_duration:
                    if hasattr(source_gap_duration, 'value') and hasattr(source_gap_duration, 'rate'):
                        gap_seconds = source_gap_duration.value / source_gap_duration.rate
                        stats_text += f"- {base_name}: {num_gaps} gaps, {gap_seconds:.2f} seconds\n"

        self.gap_stats_text.setText(stats_text)

        # Update gaps tree
        self.gaps_tree.clear()

        # Group gaps by source file
        if 'savings_by_source' in savings:
            for source, info in savings['savings_by_source'].items():
                base_name = source.split('/')[-1] if '/' in source else source.split('\\')[-1]

                # Create parent item for this source
                source_item = QTreeWidgetItem(self.gaps_tree)
                source_item.setText(0, base_name)
                source_item.setToolTip(0, source)

                # Add gap details if available
                if 'gaps' in info:
                    for gap in info['gaps']:
                        gap_item = QTreeWidgetItem(source_item)

                        # Start and end times
                        if 'gap_start' in gap and hasattr(gap['gap_start'], 'value') and hasattr(gap['gap_start'],
                                                                                                 'rate'):
                            start_seconds = gap['gap_start'].value / gap['gap_start'].rate
                            gap_item.setText(1, f"{start_seconds:.2f}s")

                        if 'gap_end' in gap and hasattr(gap['gap_end'], 'value') and hasattr(gap['gap_end'], 'rate'):
                            end_seconds = gap['gap_end'].value / gap['gap_end'].rate
                            gap_item.setText(2, f"{end_seconds:.2f}s")

                        # Duration
                        if 'duration' in gap and hasattr(gap['duration'], 'value') and hasattr(gap['duration'], 'rate'):
                            duration_seconds = gap['duration'].value / gap['duration'].rate
                            gap_item.setText(3, f"{duration_seconds:.2f}")

        # Expand all items
        self.gaps_tree.expandAll()

        # Adjust column widths
        for i in range(self.gaps_tree.columnCount()):
            self.gaps_tree.resizeColumnToContents(i)

    def _update_plan_info(self, plan: TransferPlan):
        """
        Update the transfer plan information.

        Args:
            plan: TransferPlan object with plan information
        """
        # Update plan info text
        info_text = f"<h3>Transfer Plan: {plan.name}</h3>\n\n"

        # Basic information
        info_text += "<b>Settings:</b><br>"
        info_text += f"Minimum Gap Duration: {plan.min_gap_duration} seconds<br>"
        info_text += f"Start Handles: {plan.start_handles} frames<br>"
        info_text += f"End Handles: {plan.end_handles} frames<br><br>"

        # Statistics
        if hasattr(plan, 'statistics') and plan.statistics:
            stats = plan.statistics

            info_text += "<b>Statistics:</b><br>"
            info_text += f"Timelines: {stats.get('timeline_count', 0)}<br>"
            info_text += f"Unique Sources: {stats.get('unique_sources', 0)}<br>"
            info_text += f"Total Segments: {stats.get('segment_count', 0)}<br>"

            # Total duration
            total_duration = stats.get('total_duration')
            if total_duration and hasattr(total_duration, 'value') and hasattr(total_duration, 'rate'):
                duration_seconds = total_duration.value / total_duration.rate
                info_text += f"Total Duration: {duration_seconds:.2f} seconds<br>"

        self.plan_info_text.setHtml(info_text)

        # Update savings text
        savings_text = "<h3>Estimated Savings</h3>\n\n"

        # Get savings information
        savings = plan.estimate_savings()

        if 'original_duration' in savings and 'optimized_duration' in savings:
            original = savings['original_duration']
            optimized = savings['optimized_duration']

            if (hasattr(original, 'value') and hasattr(original, 'rate') and
                    hasattr(optimized, 'value') and hasattr(optimized, 'rate')):

                orig_seconds = original.value / original.rate
                opt_seconds = optimized.value / optimized.rate

                savings_text += f"<b>Original Duration:</b> {orig_seconds:.2f} seconds<br>"
                savings_text += f"<b>Optimized Duration:</b> {opt_seconds:.2f} seconds<br>"

                if orig_seconds > 0:
                    reduction = orig_seconds - opt_seconds
                    percentage = (reduction / orig_seconds) * 100

                    savings_text += f"<b>Duration Reduction:</b> {reduction:.2f} seconds ({percentage:.2f}%)<br>"

        self.savings_text.setHtml(savings_text)

    def _update_segments_info(self, segments):
        """
        Update the segments table.

        Args:
            segments: List of TransferSegment objects
        """
        # Clear existing rows
        self.segments_table.setRowCount(0)

        # Add rows for each segment
        self.segments_table.setRowCount(len(segments))

        for i, segment in enumerate(segments):
            # Segment name
            name_item = QTableWidgetItem(segment.name)
            self.segments_table.setItem(i, 0, name_item)

            # Source file (basename)
            base_name = segment.source_file.split('/')[-1] if '/' in segment.source_file else \
            segment.source_file.split('\\')[-1]
            source_item = QTableWidgetItem(base_name)
            source_item.setToolTip(segment.source_file)
            self.segments_table.setItem(i, 1, source_item)

            # Start time
            if segment.source_start and hasattr(segment.source_start, 'value') and hasattr(segment.source_start,
                                                                                           'rate'):
                start_seconds = segment.source_start.value / segment.source_start.rate
                start_item = QTableWidgetItem(f"{start_seconds:.2f}s")
                self.segments_table.setItem(i, 2, start_item)

            # End time
            if segment.source_end and hasattr(segment.source_end, 'value') and hasattr(segment.source_end, 'rate'):
                end_seconds = segment.source_end.value / segment.source_end.rate
                end_item = QTableWidgetItem(f"{end_seconds:.2f}s")
                self.segments_table.setItem(i, 3, end_item)

            # Duration
            if segment.duration and hasattr(segment.duration, 'value') and hasattr(segment.duration, 'rate'):
                duration_seconds = segment.duration.value / segment.duration.rate
                duration_item = QTableWidgetItem(f"{duration_seconds:.2f}")
                self.segments_table.setItem(i, 4, duration_item)

        # Adjust column widths
        for i in range(self.segments_table.columnCount()):
            self.segments_table.resizeColumnToContents(i)
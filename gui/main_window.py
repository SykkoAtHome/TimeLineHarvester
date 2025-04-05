"""
Main Window Module

This module defines the main application window for the TimelineHarvester GUI.
It serves as the central point of user interaction, integrating all the
different panels and components of the application.
"""

import os
import logging
from typing import List, Optional, Dict, Any

from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QWidget, QSplitter,
    QTabWidget, QPushButton, QLabel, QStatusBar
)
from PyQt5.QtCore import Qt, QSettings, QSize, QPoint
from PyQt5.QtGui import QIcon

from gui.file_panel import FilePanel
from gui.settings_panel import SettingsPanel
from gui.results_panel import ResultsPanel
from gui.status_bar import StatusBarManager

# Import core functionality
from core.timeline_harvester import TimelineHarvester
from core.models import Timeline, TransferPlan

# Configure logging
logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """
    Main application window for TimelineHarvester.

    This window integrates the file panel, settings panel, and results panel
    to provide a complete interface for analyzing timelines and creating
    transfer plans.
    """

    def __init__(self, harvester: TimelineHarvester):
        """
        Initialize the main window.

        Args:
            harvester: The TimelineHarvester instance for core functionality
        """
        super().__init__()

        # Store the harvester reference
        self.harvester = harvester

        # Initialize window properties
        self.setWindowTitle("TimelineHarvester")
        self.setMinimumSize(1000, 700)

        # Create status bar
        self.status_manager = StatusBarManager(self.statusBar())

        # Create the central widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # Create the main splitter for resizable panels
        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_layout.addWidget(self.main_splitter)

        # Create the panels
        self.create_panels()

        # Create actions and menus
        self.create_actions()
        self.create_menus()

        # Create toolbar
        self.create_toolbar()

        # Connect signals and slots
        self.connect_signals()

        # Load settings
        self.load_settings()

        # Initialize state
        self.current_plan = None

        logger.info("Main window initialized")

    def create_panels(self):
        """Create and set up all the panels in the main window."""
        # Upper panel - File selection and parameters
        self.upper_panel = QWidget()
        upper_layout = QHBoxLayout(self.upper_panel)

        # File panel (left side)
        self.file_panel = FilePanel()

        # Settings panel (right side)
        self.settings_panel = SettingsPanel()

        upper_layout.addWidget(self.file_panel, 2)  # Weight 2
        upper_layout.addWidget(self.settings_panel, 1)  # Weight 1

        # Lower panel - Results and visualization
        self.results_panel = ResultsPanel()

        # Add to main splitter
        self.main_splitter.addWidget(self.upper_panel)
        self.main_splitter.addWidget(self.results_panel)

        # Set initial splitter sizes
        self.main_splitter.setSizes([300, 400])

    def create_actions(self):
        """Create the actions for menus and toolbars."""
        # File actions
        self.action_open = QAction("&Open Timeline(s)...", self)
        self.action_open.setShortcut("Ctrl+O")
        self.action_open.setStatusTip("Open timeline file(s) for analysis")

        self.action_save_plan = QAction("&Save Transfer Plan...", self)
        self.action_save_plan.setShortcut("Ctrl+S")
        self.action_save_plan.setStatusTip("Save the current transfer plan")
        self.action_save_plan.setEnabled(False)

        self.action_export_segments = QAction("Export &Segments...", self)
        self.action_export_segments.setStatusTip("Export segments as individual files")
        self.action_export_segments.setEnabled(False)

        self.action_generate_report = QAction("Generate &Report...", self)
        self.action_generate_report.setStatusTip("Generate a detailed report of the transfer plan")
        self.action_generate_report.setEnabled(False)

        self.action_exit = QAction("E&xit", self)
        self.action_exit.setShortcut("Alt+F4")
        self.action_exit.setStatusTip("Exit the application")

        # Analysis actions
        self.action_analyze = QAction("&Analyze Timeline(s)", self)
        self.action_analyze.setShortcut("F5")
        self.action_analyze.setStatusTip("Analyze the loaded timeline(s)")
        self.action_analyze.setEnabled(False)

        self.action_create_plan = QAction("Create &Transfer Plan", self)
        self.action_create_plan.setShortcut("F6")
        self.action_create_plan.setStatusTip("Create an optimized transfer plan")
        self.action_create_plan.setEnabled(False)

        # Help actions
        self.action_about = QAction("&About TimelineHarvester", self)
        self.action_about.setStatusTip("Show information about TimelineHarvester")

    def create_menus(self):
        """Create and populate the menu bar."""
        # File menu
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.action_open)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_save_plan)
        self.file_menu.addAction(self.action_export_segments)
        self.file_menu.addAction(self.action_generate_report)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_exit)

        # Analysis menu
        self.analysis_menu = self.menuBar().addMenu("&Analysis")
        self.analysis_menu.addAction(self.action_analyze)
        self.analysis_menu.addAction(self.action_create_plan)

        # Help menu
        self.help_menu = self.menuBar().addMenu("&Help")
        self.help_menu.addAction(self.action_about)

    def create_toolbar(self):
        """Create and populate the toolbar."""
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setMovable(False)

        self.toolbar.addAction(self.action_open)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_analyze)
        self.toolbar.addAction(self.action_create_plan)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_save_plan)
        self.toolbar.addAction(self.action_export_segments)

    def connect_signals(self):
        """Connect signals to slots for interaction between components."""
        # Connect actions
        self.action_open.triggered.connect(self.open_timelines)
        self.action_save_plan.triggered.connect(self.save_transfer_plan)
        self.action_export_segments.triggered.connect(self.export_segments)
        self.action_generate_report.triggered.connect(self.generate_report)
        self.action_exit.triggered.connect(self.close)

        self.action_analyze.triggered.connect(self.analyze_timelines)
        self.action_create_plan.triggered.connect(self.create_transfer_plan)

        self.action_about.triggered.connect(self.show_about_dialog)

        # Connect panel signals
        self.file_panel.filesLoaded.connect(self.on_files_loaded)
        self.settings_panel.createPlanClicked.connect(self.create_transfer_plan)

    def load_settings(self):
        """Load saved application settings."""
        settings = QSettings("TimelineHarvester", "App")

        # Restore window size and position if available
        size = settings.value("window_size", QSize(1000, 700))
        pos = settings.value("window_position", QPoint(100, 100))

        self.resize(size)
        self.move(pos)

        # Restore last used directories
        self.last_timeline_dir = settings.value("last_timeline_dir", "")
        self.last_export_dir = settings.value("last_export_dir", "")

    def save_settings(self):
        """Save application settings."""
        settings = QSettings("TimelineHarvester", "App")

        # Save window size and position
        settings.setValue("window_size", self.size())
        settings.setValue("window_position", self.pos())

        # Save last used directories
        settings.setValue("last_timeline_dir", self.last_timeline_dir)
        settings.setValue("last_export_dir", self.last_export_dir)

    def closeEvent(self, event):
        """Handle the window close event."""
        self.save_settings()
        event.accept()

    def open_timelines(self):
        """Open timeline file(s) for analysis."""
        # Determine starting directory
        start_dir = self.last_timeline_dir if self.last_timeline_dir else os.path.expanduser("~")

        # Show file dialog
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Open Timeline File(s)")
        file_dialog.setDirectory(start_dir)
        file_dialog.setNameFilter("Timeline Files (*.edl *.xml *.fcpxml *.aaf);;All Files (*.*)")
        file_dialog.setFileMode(QFileDialog.ExistingFiles)

        if file_dialog.exec_():
            file_paths = file_dialog.selectedFiles()
            if file_paths:
                # Save the last used directory
                self.last_timeline_dir = os.path.dirname(file_paths[0])

                # Load the timelines
                self.load_timeline_files(file_paths)

    def load_timeline_files(self, file_paths: List[str]):
        """
        Load timeline files into the application.

        Args:
            file_paths: List of paths to the timeline files
        """
        self.status_manager.set_status(f"Loading {len(file_paths)} timeline files...")

        try:
            # Get frame rate from settings
            fps = self.settings_panel.get_fps()

            # Load timelines using the harvester
            timelines = []
            for path in file_paths:
                try:
                    timeline = self.harvester.load_timeline(path, fps)
                    timelines.append(timeline)
                except Exception as e:
                    logger.error(f"Failed to load timeline {path}: {str(e)}")
                    QMessageBox.warning(self, "Load Error",
                                        f"Failed to load timeline {os.path.basename(path)}: {str(e)}")

            if timelines:
                # Update the file panel
                self.file_panel.set_loaded_files(file_paths)

                # Update status
                self.status_manager.set_status(f"Loaded {len(timelines)} timeline(s)")

                # Enable analyze action
                self.action_analyze.setEnabled(True)

                # Reset results panel
                self.results_panel.clear_results()
            else:
                self.status_manager.set_status("No timelines loaded")

        except Exception as e:
            logger.error(f"Error loading timelines: {str(e)}")
            QMessageBox.critical(self, "Load Error", f"Error loading timelines: {str(e)}")
            self.status_manager.set_status("Error loading timelines")

    def on_files_loaded(self, file_paths: List[str]):
        """
        Handle the signal that files were loaded from the file panel.

        Args:
            file_paths: List of paths to the loaded files
        """
        self.load_timeline_files(file_paths)

    def analyze_timelines(self):
        """Analyze the loaded timelines and display the results."""
        self.status_manager.set_status("Analyzing timelines...")

        try:
            # Get list of source files
            source_files = self.harvester.get_source_files()

            # Calculate potential savings
            min_gap_duration = self.settings_panel.get_min_gap_duration()
            savings = self.harvester.calculate_potential_savings(min_gap_duration)

            # Get timeline statistics
            stats = self.harvester.get_statistics()

            # Update results panel with analysis results
            self.results_panel.set_analysis_results(source_files, savings, stats)

            # Enable create plan action
            self.action_create_plan.setEnabled(True)

            # Update status
            self.status_manager.set_status(f"Analyzed {len(source_files)} source files")

        except Exception as e:
            logger.error(f"Error analyzing timelines: {str(e)}")
            QMessageBox.critical(self, "Analysis Error", f"Error analyzing timelines: {str(e)}")
            self.status_manager.set_status("Error analyzing timelines")

    def create_transfer_plan(self):
        """Create an optimized transfer plan."""
        self.status_manager.set_status("Creating transfer plan...")

        try:
            # Get settings from the settings panel
            min_gap_duration = self.settings_panel.get_min_gap_duration()
            start_handles = self.settings_panel.get_start_handles()
            end_handles = self.settings_panel.get_end_handles()
            plan_name = self.settings_panel.get_plan_name()

            # Create the transfer plan
            plan = self.harvester.create_transfer_plan(
                min_gap_duration=min_gap_duration,
                start_handles=start_handles,
                end_handles=end_handles,
                name=plan_name
            )

            # Store the current plan
            self.current_plan = plan

            # Update results panel with plan details
            self.results_panel.set_plan_results(plan)

            # Enable save/export actions
            self.action_save_plan.setEnabled(True)
            self.action_export_segments.setEnabled(True)
            self.action_generate_report.setEnabled(True)

            # Update status
            self.status_manager.set_status(f"Created transfer plan with {len(plan.segments)} segments")

        except Exception as e:
            logger.error(f"Error creating transfer plan: {str(e)}")
            QMessageBox.critical(self, "Transfer Plan Error", f"Error creating transfer plan: {str(e)}")
            self.status_manager.set_status("Error creating transfer plan")

    def save_transfer_plan(self):
        """Save the current transfer plan to a file."""
        if not self.current_plan:
            QMessageBox.warning(self, "Save Error", "No transfer plan to save")
            return

        # Determine starting directory
        start_dir = self.last_export_dir if self.last_export_dir else os.path.expanduser("~")

        # Show save dialog
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Save Transfer Plan")
        file_dialog.setDirectory(start_dir)
        file_dialog.setNameFilter("EDL Files (*.edl);;XML Files (*.xml);;All Files (*.*)")
        file_dialog.setAcceptMode(QFileDialog.AcceptSave)
        file_dialog.setDefaultSuffix("edl")

        if file_dialog.exec_():
            file_path = file_dialog.selectedFiles()[0]
            if file_path:
                # Save the last used directory
                self.last_export_dir = os.path.dirname(file_path)

                try:
                    # Determine format from extension
                    _, ext = os.path.splitext(file_path)
                    format_name = None
                    if ext.lower() == ".edl":
                        format_name = "edl"
                    elif ext.lower() == ".xml":
                        format_name = "xml"

                    # Export the plan
                    self.harvester.export_transfer_plan(file_path, format_name)

                    # Update status
                    self.status_manager.set_status(f"Saved transfer plan to {file_path}")

                except Exception as e:
                    logger.error(f"Error saving transfer plan: {str(e)}")
                    QMessageBox.critical(self, "Save Error", f"Error saving transfer plan: {str(e)}")
                    self.status_manager.set_status("Error saving transfer plan")

    def export_segments(self):
        """Export segments as individual files."""
        if not self.current_plan:
            QMessageBox.warning(self, "Export Error", "No transfer plan to export segments from")
            return

        # Determine starting directory
        start_dir = self.last_export_dir if self.last_export_dir else os.path.expanduser("~")

        # Show directory dialog
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Export Directory", start_dir, QFileDialog.ShowDirsOnly
        )

        if dir_path:
            # Save the last used directory
            self.last_export_dir = dir_path

            try:
                # Export the segments
                self.harvester.export_segments(dir_path, "edl")

                # Update status
                self.status_manager.set_status(f"Exported segments to {dir_path}")

                # Show confirmation
                QMessageBox.information(
                    self, "Export Complete",
                    f"Successfully exported {len(self.current_plan.segments)} segments to {dir_path}"
                )

            except Exception as e:
                logger.error(f"Error exporting segments: {str(e)}")
                QMessageBox.critical(self, "Export Error", f"Error exporting segments: {str(e)}")
                self.status_manager.set_status("Error exporting segments")

    def generate_report(self):
        """Generate a detailed report of the transfer plan."""
        if not self.current_plan:
            QMessageBox.warning(self, "Report Error", "No transfer plan to generate report from")
            return

        # Determine starting directory
        start_dir = self.last_export_dir if self.last_export_dir else os.path.expanduser("~")

        # Show save dialog
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Save Report")
        file_dialog.setDirectory(start_dir)
        file_dialog.setNameFilter("Markdown Files (*.md);;Text Files (*.txt);;All Files (*.*)")
        file_dialog.setAcceptMode(QFileDialog.AcceptSave)
        file_dialog.setDefaultSuffix("md")

        if file_dialog.exec_():
            file_path = file_dialog.selectedFiles()[0]
            if file_path:
                # Save the last used directory
                self.last_export_dir = os.path.dirname(file_path)

                try:
                    # Generate the report
                    self.harvester.generate_report(file_path)

                    # Update status
                    self.status_manager.set_status(f"Generated report to {file_path}")

                    # Show confirmation
                    QMessageBox.information(self, "Report Generated", f"Report saved to {file_path}")

                except Exception as e:
                    logger.error(f"Error generating report: {str(e)}")
                    QMessageBox.critical(self, "Report Error", f"Error generating report: {str(e)}")
                    self.status_manager.set_status("Error generating report")

    def show_about_dialog(self):
        """Show information about the application."""
        QMessageBox.about(
            self,
            "About TimelineHarvester",
            "<h2>TimelineHarvester</h2>"
            "<p>Version 1.0.0</p>"
            "<p>An application for analyzing editing timelines and optimizing media transfers.</p>"
            "<p>TimelineHarvester helps identify source file usage in editing projects "
            "and creates optimized transfer plans with only the necessary media segments.</p>"
        )
# gui/main_window.py
"""
Main Window Module for TimelineHarvester GUI

Defines the main application window, integrates panels (File, Settings, Results),
manages actions, menus, toolbar, status bar, and orchestrates background tasks
using a worker thread (QThread).
"""

import os
import logging
from typing import List, Optional, Dict, Any

# --- PyQt5 Imports ---
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QVBoxLayout,
    QHBoxLayout, QWidget, QSplitter, QTabWidget, QPushButton, QLabel,
    QStatusBar, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QPlainTextEdit # Added for ProfileEditDialog (might move later)
)
from PyQt5.QtCore import Qt, QSettings, QSize, QPoint, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QIcon # For potential future icon usage

# --- GUI Component Imports ---
from .file_panel import FilePanel
# Import the specific ProfileEditDialog if it stays here, or SettingsPanel if it contains it
from .settings_panel import SettingsPanel, ProfileEditDialog
from .results_panel import ResultsPanel
from .status_bar import StatusBarManager

# --- Core Logic Imports ---
from core.timeline_harvester import TimelineHarvester
# Import models only if directly needed
from core.models import EditFileMetadata

logger = logging.getLogger(__name__)

# --- Worker Thread Definition ---
class WorkerThread(QThread):
    """Thread to run background tasks (analysis, plan, transcode) without freezing the GUI."""
    # --- Signals ---
    analysis_finished = pyqtSignal(list) # list of EditShot summary dicts
    plan_finished = pyqtSignal(list)     # list of TransferSegment summary dicts
    transcode_finished = pyqtSignal(bool, str) # success, message
    progress_update = pyqtSignal(int, str)    # percent (0-100), message
    error_occurred = pyqtSignal(str)          # error message

    def __init__(self, harvester: TimelineHarvester, task: str, params: Optional[Dict] = None):
        super().__init__()
        self.harvester = harvester
        self.task = task
        self.params = params if params else {}
        self._is_running = True # Flag for potential interruption
        logger.info(f"WorkerThread initialized for task: {self.task}")

    def stop(self):
        """Request the thread to stop."""
        self._is_running = False
        logger.info(f"Stop requested for worker thread task: {self.task}")

    def run(self):
        """Execute the requested task in the background."""
        logger.info(f"WorkerThread starting task: {self.task}")
        try:
            if self.task == 'analyze':
                self.harvester.parse_added_edit_files()
                if not self._is_running: raise InterruptedError("Task stopped.")
                self.harvester.find_original_sources()
                if not self._is_running: raise InterruptedError("Task stopped.")
                summary = self.harvester.get_edit_shots_summary()
                if self._is_running: self.analysis_finished.emit(summary)

            elif self.task == 'create_plan':
                handles = self.params.get('handles', 0)
                output_dir = self.params.get('output_dir', '.')
                self.harvester.calculate_transfer(handles, output_dir)
                if not self._is_running: raise InterruptedError("Task stopped.")
                segment_summary = self.harvester.get_transfer_segments_summary()
                if self._is_running: self.plan_finished.emit(segment_summary)

            elif self.task == 'transcode':
                def progress_callback(current, total, message):
                    if not self._is_running:
                        raise InterruptedError("Transcode stopped by user request.")
                    percent = int((current / total) * 100) if total > 0 else 0
                    # Avoid flooding logs, maybe emit less frequently or check log level
                    # logger.debug(f"Progress update: {percent}% - {message}")
                    self.progress_update.emit(percent, message)

                self.harvester.run_transcoding(progress_callback)
                if self._is_running:
                    self.transcode_finished.emit(True, "Transcoding completed successfully.")
            else:
                raise ValueError(f"Unknown worker task: {self.task}")

            if self._is_running:
                logger.info(f"WorkerThread finished task: {self.task}")

        except InterruptedError as stop_err:
             logger.warning(f"WorkerThread task '{self.task}' stopped by user request.")
             self.error_occurred.emit(f"Task '{self.task}' cancelled.")
        except Exception as e:
            logger.error(f"WorkerThread error during task '{self.task}': {e}", exc_info=True)
            if self._is_running:
                self.error_occurred.emit(f"Error during {self.task}: {str(e)}")


# --- Main Window Class ---
class MainWindow(QMainWindow):
    """Main application window integrating all components."""

    def __init__(self, harvester: TimelineHarvester):
        super().__init__()
        self.harvester = harvester
        self.worker_thread: Optional[WorkerThread] = None
        # Initialize directory paths (will be loaded/updated)
        self.last_timeline_dir = os.path.expanduser("~") # Default to home
        self.last_export_dir = os.path.expanduser("~") # Default to home

        self.setWindowTitle("TimelineHarvester")
        self.setMinimumSize(1100, 750) # Adjusted minimum size

        # --- Initialize UI Components ---
        self.status_manager = StatusBarManager(self.statusBar())
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_layout.addWidget(self.main_splitter)

        self.create_panels()
        self.create_actions()
        self.create_menus()
        self.create_toolbar()
        self.connect_signals()

        self.load_settings()
        self._update_ui_initial_state()

        logger.info("MainWindow initialized.")

    # --- UI Creation Methods ---
    def create_panels(self):
        """Creates and arranges the main UI panels."""
        self.upper_panel = QWidget()
        upper_layout = QHBoxLayout(self.upper_panel)
        self.file_panel = FilePanel() # Panel for adding/removing edit files
        self.settings_panel = SettingsPanel() # Panel for all settings
        upper_layout.addWidget(self.file_panel, 2) # Give file panel less space initially
        upper_layout.addWidget(self.settings_panel, 3) # Settings panel more space

        self.results_panel = ResultsPanel() # Panel for displaying results

        self.main_splitter.addWidget(self.upper_panel)
        self.main_splitter.addWidget(self.results_panel)
        self.main_splitter.setSizes([350, 450]) # Adjust initial split ratio (more space for results)
        logger.debug("UI Panels created and added to splitter.")

    def create_actions(self):
        """Creates QAction objects for menus and toolbars using dedicated methods."""
        # File Actions
        self.action_open = QAction(QIcon(), "&Open Edit File(s)...", self)
        self.action_open.setShortcut("Ctrl+O")
        self.action_open.setStatusTip("Open timeline file(s) (EDL, XML, AAF...)")

        self.action_save_plan = QAction(QIcon(), "&Save Transfer Plan...", self)
        self.action_save_plan.setShortcut("Ctrl+S")
        self.action_save_plan.setStatusTip("Save the calculated transfer plan definition (e.g., as JSON)")
        self.action_save_plan.setEnabled(False)

        self.action_export_segments = QAction(QIcon(), "Export Segment &List...", self)
        self.action_export_segments.setStatusTip("Export list of calculated segments (e.g., EDL/XML per segment)")
        self.action_export_segments.setEnabled(False)

        self.action_generate_report = QAction(QIcon(), "Generate &Report...", self)
        self.action_generate_report.setStatusTip("Generate a summary report of the plan")
        self.action_generate_report.setEnabled(False)

        self.action_exit = QAction(QIcon(), "E&xit", self)
        self.action_exit.setShortcut(Qt.CTRL + Qt.Key_Q) # Use Ctrl+Q for exit
        self.action_exit.setStatusTip("Exit the application")
        self.action_exit.triggered.connect(self.close) # Connect directly

        # Process Actions
        self.action_analyze = QAction(QIcon(), "&Analyze Files", self)
        self.action_analyze.setShortcut("F5")
        self.action_analyze.setStatusTip("Parse files and find original sources based on settings")
        self.action_analyze.setEnabled(False)

        self.action_create_plan = QAction(QIcon(), "&Calculate Plan", self)
        self.action_create_plan.setShortcut("F6")
        self.action_create_plan.setStatusTip("Calculate optimized transfer segments based on analysis and settings")
        self.action_create_plan.setEnabled(False)

        self.action_transcode = QAction(QIcon(), "&Transcode Plan", self)
        self.action_transcode.setShortcut("F7")
        self.action_transcode.setStatusTip("Start transcoding the calculated plan using FFmpeg")
        self.action_transcode.setEnabled(False)

        # Help Actions
        self.action_about = QAction(QIcon(), "&About TimelineHarvester", self)
        self.action_about.setStatusTip("Show application information")
        self.action_about.triggered.connect(self.show_about_dialog) # Connect directly

        logger.debug("UI Actions created.")

    def create_menus(self):
        """Creates the main menu bar."""
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.action_open)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_save_plan)
        self.file_menu.addAction(self.action_export_segments)
        self.file_menu.addAction(self.action_generate_report)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_exit)

        self.process_menu = self.menuBar().addMenu("&Process")
        self.process_menu.addAction(self.action_analyze)
        self.process_menu.addAction(self.action_create_plan)
        self.process_menu.addAction(self.action_transcode)

        self.help_menu = self.menuBar().addMenu("&Help")
        self.help_menu.addAction(self.action_about)
        logger.debug("UI Menus created.")

    def create_toolbar(self):
        """Creates the main application toolbar."""
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.addAction(self.action_open)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_analyze)
        self.toolbar.addAction(self.action_create_plan)
        self.toolbar.addAction(self.action_transcode)
        logger.debug("UI Toolbar created.")

    # --- Signal/Slot Connections ---
    def connect_signals(self):
        """Connects signals from UI elements and worker thread to slots."""
        # Actions -> Slots
        self.action_open.triggered.connect(self.open_timelines)
        # Exit and About connected in create_actions
        self.action_analyze.triggered.connect(self.start_analysis_task)
        self.action_create_plan.triggered.connect(self.start_create_plan_task)
        self.action_transcode.triggered.connect(self.start_transcode_task)
        self.action_save_plan.triggered.connect(self.save_transfer_plan)
        self.action_export_segments.triggered.connect(self.export_segments)
        self.action_generate_report.triggered.connect(self.generate_report)

        # Panel Signals -> Slots
        self.file_panel.filesChanged.connect(self.on_files_loaded) # Correct signal name
        self.settings_panel.createPlanClicked.connect(self.start_create_plan_task)

        logger.debug("UI Signals connected.")

    # --- Settings Persistence ---
    def load_settings(self):
        """Loads application and panel settings from QSettings."""
        logger.info("Loading application settings...")
        # Use consistent company/app names for QSettings
        settings = QSettings("TimelineHarvesterOrg", "TimelineHarvester")

        # Restore window geometry and state
        self.restoreGeometry(settings.value("window_geometry", self.saveGeometry()))
        self.restoreState(settings.value("window_state", self.saveState()))

        # Restore last used directories, defaulting to home
        self.last_timeline_dir = settings.value("last_timeline_dir", os.path.expanduser("~"))
        self.last_export_dir = settings.value("last_export_dir", os.path.expanduser("~"))

        # Load settings into the SettingsPanel
        panel_settings_dict = settings.value("panel_settings", {})
        if isinstance(panel_settings_dict, dict):
            try:
                self.settings_panel.load_panel_settings(panel_settings_dict)
                logger.info("SettingsPanel state loaded from QSettings.")
            except Exception as e:
                logger.error(f"Error applying loaded settings to SettingsPanel: {e}", exc_info=True)
        else:
            logger.warning("Could not load valid dictionary for panel_settings, using defaults.")

        # Update internal last_export_dir based on loaded panel settings
        self._update_internal_output_dir()
        logger.info("Window and panel settings loading complete.")

    def save_settings(self):
        """Saves application and panel settings using QSettings."""
        logger.info("Saving application settings...")
        settings = QSettings("TimelineHarvesterOrg", "TimelineHarvester")

        settings.setValue("window_geometry", self.saveGeometry())
        settings.setValue("window_state", self.saveState())
        settings.setValue("last_timeline_dir", self.last_timeline_dir)
        settings.setValue("last_export_dir", self.last_export_dir)

        panel_settings_dict = self.settings_panel.get_panel_settings()
        settings.setValue("panel_settings", panel_settings_dict)
        logger.info("Window and panel settings saved.")

    # --- Window Event Handlers ---
    def closeEvent(self, event):
        """Handles the window close event."""
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, "Task Running",
                                         "A background task is running.\nQuit anyway?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
            else:
                logger.warning("Closing application while worker thread is running. Attempting to stop.")
                self.worker_thread.stop() # Request stop
                # Optionally wait a short time, but don't block indefinitely
                # self.worker_thread.wait(500)
        self.save_settings()
        logger.info("--- Closing TimelineHarvester Application ---")
        event.accept()

    # --- UI State Management ---
    def _update_ui_initial_state(self):
        """Sets the initial enabled state of actions and buttons."""
        self._set_actions_enabled(True) # Enable based on initial state (no files loaded yet)

    def _update_internal_output_dir(self):
        """Updates the internal last_export_dir based on the SettingsPanel."""
        panel_out_dir = self.settings_panel.get_output_directory()
        if panel_out_dir and os.path.isdir(panel_out_dir):
            self.last_export_dir = panel_out_dir
            logger.debug(f"MainWindow.last_export_dir updated from SettingsPanel: {self.last_export_dir}")

    def _set_actions_enabled(self, processing_finished: bool):
        """Updates the enabled state of actions and buttons based on app state."""
        is_busy = self.worker_thread is not None and self.worker_thread.isRunning()
        can_interact = not is_busy and processing_finished # Allow interaction only when not busy AND finished

        # Determine current logical state
        files_loaded = len(self.harvester.edit_files) > 0
        analysis_done = len(self.harvester.edit_shots) > 0
        sources_found = analysis_done and any(s.lookup_status == 'found' for s in self.harvester.edit_shots)
        plan_calculated = self.harvester.transfer_batch is not None and bool(self.harvester.transfer_batch.segments)

        # Enable/Disable Actions based on state and whether busy
        self.action_open.setEnabled(not is_busy)
        self.action_analyze.setEnabled(not is_busy and files_loaded)
        self.action_create_plan.setEnabled(not is_busy and sources_found)
        self.action_transcode.setEnabled(not is_busy and plan_calculated)
        self.action_save_plan.setEnabled(not is_busy and plan_calculated)
        self.action_export_segments.setEnabled(not is_busy and plan_calculated)
        self.action_generate_report.setEnabled(not is_busy and plan_calculated)

        # Enable/Disable Panel Buttons
        self.settings_panel.create_plan_button.setEnabled(not is_busy and sources_found)
        self.file_panel.add_button.setEnabled(not is_busy)
        self.file_panel.update_button_states() # Let FilePanel manage its remove/clear

        logger.debug(f"Actions/Buttons enabled state updated (Busy: {is_busy}, Finished: {processing_finished})")

    def _is_worker_busy(self) -> bool:
        """Checks if the worker thread is active and shows a message if it is."""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "A background task is currently running.\nPlease wait for it to complete.")
            return True
        return False

    # --- File Handling Slots ---
    @pyqtSlot()
    def open_timelines(self):
        """Opens file dialog, updates file list, enables analysis."""
        if self._is_worker_busy(): return
        start_dir = self.last_timeline_dir or os.path.expanduser("~")
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Open Edit File(s)")
        file_dialog.setDirectory(start_dir)
        file_dialog.setNameFilter("Edit Files (*.edl *.xml *.fcpxml *.aaf);;All Files (*.*)")
        file_dialog.setFileMode(QFileDialog.ExistingFiles)

        if file_dialog.exec_():
            file_paths = file_dialog.selectedFiles()
            if file_paths:
                self.last_timeline_dir = os.path.dirname(file_paths[0])
                self.update_edit_file_list(file_paths)

    @pyqtSlot(list)
    def on_files_loaded(self, file_paths: List[str]):
        """Handles file list changes from FilePanel, updates harvester and UI state."""
        self.update_edit_file_list(file_paths)

    def update_edit_file_list(self, file_paths: List[str]):
        """Updates harvester state and UI when edit file list changes."""
        self.harvester.clear_state() # Reset core state when file list changes
        added_count = 0
        for path in file_paths:
            if self.harvester.add_edit_file_path(path):
                 added_count += 1
        current_paths = [f.path for f in self.harvester.edit_files]
        # Ensure FilePanel UI is updated (set_loaded_files does this now)
        self.file_panel.set_loaded_files(current_paths)
        # Update enabled state based on whether files are now loaded
        self._set_actions_enabled(True) # Enable based on new state (analysis possible if files > 0)
        self.results_panel.clear_results() # Clear old results display
        self.status_manager.set_status(f"Ready to analyze {len(current_paths)} file(s).")

    # --- Task Starting Slots ---
    @pyqtSlot()
    def start_analysis_task(self):
        """Configures harvester from settings and starts the 'analyze' task."""
        if self._is_worker_busy(): return
        if not self.harvester.edit_files:
            QMessageBox.warning(self, "No Files", "Please add edit files first using 'Open Edit File(s)...'.")
            return

        try:
            search_paths = self.settings_panel.get_search_paths()
            strategy = self.settings_panel.get_lookup_strategy()
            if not search_paths:
                 QMessageBox.warning(self, "Configuration Missing", "Please add at least one Source Search Path in the settings panel.")
                 return
            self.harvester.set_source_search_paths(search_paths)
            self.harvester.set_source_lookup_strategy(strategy)
            logger.info("Harvester configured for analysis.")
        except Exception as config_err:
             logger.error(f"Error reading settings panel configuration: {config_err}")
             QMessageBox.critical(self, "Settings Error", f"Could not read settings: {config_err}")
             return

        self._start_worker('analyze', "Analyzing files & finding sources...", {})

    @pyqtSlot()
    def start_create_plan_task(self):
        """Configures harvester and starts the 'create_plan' task."""
        if self._is_worker_busy(): return
        if not self.harvester.edit_shots or not any(s.lookup_status == 'found' for s in self.harvester.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete", "Please run 'Analyze Files' first and ensure original sources were successfully found.")
            return

        try:
            output_profiles_config = self.settings_panel.get_output_profiles_config()
            output_dir = self.settings_panel.get_output_directory()
            handles = self.settings_panel.get_start_handles() # Using symmetric handle value

            if not output_profiles_config:
                 QMessageBox.warning(self, "Configuration Missing", "Please define at least one Output Profile in settings.")
                 return
            if not output_dir:
                 QMessageBox.warning(self, "Configuration Missing", "Please select an Output Directory in settings.")
                 self.settings_panel.browse_output_directory()
                 output_dir = self.settings_panel.get_output_directory()
                 if not output_dir: return
            self.harvester.set_output_profiles(output_profiles_config)
            self._update_internal_output_dir()

            params = {'handles': handles, 'output_dir': output_dir}
            logger.info(f"Harvester configured for plan creation. Handles: {handles}, Output Dir: {output_dir}, Profiles: {len(output_profiles_config)}")
            self._start_worker('create_plan', "Calculating transfer plan...", params)

        except Exception as config_err:
             logger.error(f"Error reading settings or configuring harvester for plan: {config_err}", exc_info=True)
             QMessageBox.critical(self, "Settings Error", f"Could not read settings or configure for plan calculation:\n\n{config_err}")
             return

    @pyqtSlot()
    def start_transcode_task(self):
        """Starts the 'transcode' task after confirmation."""
        if self._is_worker_busy(): return
        if not self.harvester.transfer_batch or not self.harvester.transfer_batch.segments:
            QMessageBox.warning(self, "No Plan", "Please calculate a transfer plan first.")
            return

        segment_count = len(self.harvester.transfer_batch.segments)
        profile_count = len(self.harvester.transfer_batch.output_profiles_used)
        total_files = segment_count * profile_count
        output_dir = self.harvester.transfer_batch.output_directory

        reply = QMessageBox.question(self, "Confirm Transcode",
                                     f"Start transcoding {total_files} file(s)?\n"
                                     f"({segment_count} segments x {profile_count} profiles)\n\n"
                                     f"Output Directory:\n'{output_dir}'\n\n"
                                     f"(Ensure FFmpeg is accessible)",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._start_worker('transcode', f"Starting transcoding {total_files} files...", {})
        else:
            self.status_manager.set_status("Transcoding cancelled.")

    def _start_worker(self, task_name: str, busy_message: str, params: Dict):
        """Helper to create, connect signals, start, and manage worker thread."""
        logger.info(f"Starting worker task: {task_name}")
        self.status_manager.set_busy(True, busy_message)
        self._set_actions_enabled(False) # Disable UI during task

        self.worker_thread = WorkerThread(self.harvester, task_name, params)
        # Connect signals FROM worker TO main window slots (self)
        self.worker_thread.analysis_finished.connect(self.on_analysis_complete)
        self.worker_thread.plan_finished.connect(self.on_plan_complete)
        self.worker_thread.transcode_finished.connect(self.on_transcode_complete)
        self.worker_thread.progress_update.connect(self.on_progress_update)
        self.worker_thread.error_occurred.connect(self.on_task_error)
        self.worker_thread.finished.connect(self.on_task_finished) # Cleanup slot
        self.worker_thread.start() # Execute the run() method

    # --- Slots Handling Worker Thread Signals ---
    @pyqtSlot(list)
    def on_analysis_complete(self, analysis_summary: List[Dict]):
        """Handles successful completion of the 'analyze' task."""
        found_count = sum(1 for s in analysis_summary if s['status'] == 'found')
        status_msg = f"Analysis complete. Sources found for {found_count}/{len(analysis_summary)} clips."
        self.results_panel.display_analysis_summary(analysis_summary)
        logger.info(status_msg)
        # Status bar update and UI re-enabling happens in on_task_finished

    @pyqtSlot(list)
    def on_plan_complete(self, plan_summary: List[Dict]):
        """Handles successful completion of the 'create_plan' task."""
        unresolved_summary = self.harvester.get_unresolved_shots_summary()
        errors = self.harvester.transfer_batch.calculation_errors if self.harvester.transfer_batch else []
        status_msg = f"Plan calculated: {len(plan_summary)} segments."
        if errors: status_msg += f" ({len(errors)} calculation errors)."
        # Display results
        self.results_panel.display_plan_summary(plan_summary)
        self.results_panel.display_unresolved_summary(unresolved_summary)
        logger.info(status_msg)
        # Status bar update and UI re-enabling happens in on_task_finished

    @pyqtSlot(bool, str)
    def on_transcode_complete(self, success: bool, message: str):
        """Handles completion (success or failure reported by thread) of 'transcode' task."""
        if success:
            # Set persistent success message only on success
            self.status_manager.set_status(message, temporary=False)
            QMessageBox.information(self, "Transcoding Complete", message)
            logger.info(f"Transcoding task reported success: {message}")
        else:
            # Error message already logged by worker, update status bar persistently
            self.status_manager.set_status(f"Transcoding Failed: {message}", temporary=False)
            QMessageBox.critical(self, "Transcoding Failed", message)
            logger.error(f"Transcoding task reported failure: {message}")
        # Actual UI re-enabling happens in on_task_finished

    @pyqtSlot(int, str)
    def on_progress_update(self, percent: int, message: str):
        """Handles progress updates during tasks like transcoding."""
        self.status_manager.show_progress(percent, 100, message)

    @pyqtSlot(str)
    def on_task_error(self, error_message: str):
        """Handles unexpected errors propagated from the worker thread's run() method."""
        logger.error(f"Received error signal from worker thread: {error_message}")
        # Set persistent error message
        self.status_manager.set_status(f"Error: {error_message}", temporary=False)
        QMessageBox.critical(self, "Background Task Error", error_message)
        # UI re-enabling happens in on_task_finished

    @pyqtSlot()
    def on_task_finished(self):
        """Slot connected to QThread.finished signal. Called ALWAYS after run() completes."""
        logger.info("Worker thread finished signal received.")
        self.status_manager.hide_progress()
        # If status bar doesn't show an error or completion message, set to Ready
        current_status = self.status_manager.status_label.text()
        if not any(current_status.startswith(prefix) for prefix in ["Error:", "Transcoding Failed:", "Transcoding completed", "Analysis complete", "Plan calculated"]):
            self.status_manager.set_status("Ready.")
        # Re-enable UI elements based on the *current* state of the harvester
        self._set_actions_enabled(True)
        self.worker_thread = None # Clear the reference to the finished thread
        logger.info("Worker thread cleanup complete.")

    # --- Placeholder Methods for Export/Save ---
    def save_transfer_plan(self):
         if not self.harvester.transfer_batch: QMessageBox.warning(self, "Save Error", "No transfer plan calculated."); return
         logger.warning("Save Transfer Plan function not implemented.")
         QMessageBox.information(self, "Not Implemented", "Saving transfer plan definition (e.g., as JSON) is not yet implemented.")
         # TODO: Implement saving self.harvester.transfer_batch

    def export_segments(self):
         if not self.harvester.transfer_batch: QMessageBox.warning(self, "Export Error", "No transfer plan calculated."); return
         logger.warning("Export Segments function not implemented.")
         QMessageBox.information(self, "Not Implemented", "Exporting segment lists (e.g., EDL/XML per segment) is not yet implemented.")
         # TODO: Implement export logic

    def generate_report(self):
         if not self.harvester.transfer_batch: QMessageBox.warning(self, "Report Error", "No transfer plan calculated."); return
         logger.warning("Generate Report function not implemented.")
         QMessageBox.information(self, "Not Implemented", "Generating a report (e.g., Markdown/Text) is not yet implemented.")
         # TODO: Implement report generation

    # --- About Dialog ---
    def show_about_dialog(self):
        QMessageBox.about(self, "About TimelineHarvester",
                          "<h2>TimelineHarvester</h2>"
                          "<p>Version 1.0 (Development)</p>"
                          "<p>Analyzes edit files to find used media ranges and helps "
                          "create optimized media transfer packages using original sources.</p>"
                          "<p>(Uses OpenTimelineIO and FFmpeg/FFprobe)</p>")

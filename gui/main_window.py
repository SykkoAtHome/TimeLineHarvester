# gui/main_window.py
"""
Main Window Module - Uses TimelineHarvesterFacade

Integrates ProjectPanel and Tab Widgets (ColorPrep, OnlinePrep).
Handles project state via the Facade, background tasks via WorkerThread,
and UI updates. Connects UI actions to the Facade.
"""

import logging
import os
from typing import List, Optional, Dict

from PyQt5.QtCore import QSettings, QThread, pyqtSignal, pyqtSlot, Qt, QCoreApplication
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QVBoxLayout,
    QWidget, QTabWidget, QApplication
)

# Import the Facade
from core.timeline_harvester_facade import TimelineHarvesterFacade

# Import GUI components
from .color_prep_tab import ColorPrepTabWidget
from .online_prep_tab import OnlinePrepTabWidget
from .project_panel import ProjectPanel
from .status_bar import StatusBarManager

logger = logging.getLogger(__name__)


class WorkerThread(QThread):
    """Worker thread for executing background tasks via the Facade."""

    analysis_finished = pyqtSignal(list, list)  # Pass both analysis and unresolved summaries
    plan_finished = pyqtSignal(list, list, str)  # Pass plan, unresolved, and stage
    transcode_finished = pyqtSignal(bool, str)
    progress_update = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, harvester_facade: TimelineHarvesterFacade, task: str, params: Optional[Dict] = None):
        super().__init__()
        self.harvester = harvester_facade
        self.task = task
        self.params = params if params else {}
        self._is_running = True
        logger.info(f"WorkerThread initialized for task: {self.task}")

    def stop(self):
        """Signal the thread to stop."""
        self._is_running = False
        logger.info(f"Stop requested for worker thread task: {self.task}")

    def run(self):
        """Execute the thread's task."""
        logger.info(f"WorkerThread starting task: {self.task}")
        try:
            if self.task == 'analyze':
                # Call the single analysis method on the facade
                success = self.harvester.run_source_analysis()
                if not self._is_running:
                    raise InterruptedError("Task stopped.")
                if not success:
                    raise RuntimeError("Analysis process failed (check logs).")

                # Get summaries after analysis is complete
                analysis_summary = self.harvester.get_edit_shots_summary()
                unresolved_summary = self.harvester.get_unresolved_shots_summary()
                if self._is_running:
                    self.analysis_finished.emit(analysis_summary, unresolved_summary)

            elif self.task == 'calculate_plan':
                stage = self.params.get('stage', 'color')
                logger.info(f"Worker calculating plan for stage: {stage}")

                # Call calculation method on the facade
                success = self.harvester.run_calculation(stage=stage)
                if not self._is_running:
                    raise InterruptedError("Task stopped.")
                if not success:
                    raise RuntimeError(f"Calculation process failed for stage {stage} (check logs).")

                # Get summaries after calculation
                segment_summary = self.harvester.get_transfer_segments_summary(stage=stage)
                unresolved_summary = self.harvester.get_unresolved_shots_summary()
                if self._is_running:
                    self.plan_finished.emit(segment_summary, unresolved_summary, stage)

            elif self.task == 'transcode':
                stage = self.params.get('stage', 'online')
                if stage != 'online':
                    raise ValueError("Transcoding implemented only for 'online' stage.")

                def progress_callback(current, total, message):
                    if not self._is_running:
                        raise InterruptedError("Transcode stopped by user.")
                    percent = int((current / total) * 100) if total > 0 else 0
                    # Check thread running state again before emitting signal
                    if self._is_running:
                        self.progress_update.emit(percent, message)
                    else:
                        # If stopped during callback, raise error to stop FFmpeg loop
                        raise InterruptedError("Transcode stopped during progress update.")

                # Call transcoding method on the facade
                self.harvester.run_online_transcoding(progress_callback)
                if self._is_running:
                    self.transcode_finished.emit(True, "Online transcoding process completed.")
            else:
                raise ValueError(f"Unknown worker task: {self.task}")

            if self._is_running:
                logger.info(f"WorkerThread finished task '{self.task}' successfully.")

        except InterruptedError:
            logger.warning(f"WorkerThread task '{self.task}' cancelled by user.")
        except Exception as e:
            logger.error(f"WorkerThread error during task '{self.task}': {e}", exc_info=True)
            # Emit error signal only if the thread wasn't stopped externally
            if self._is_running:
                self.error_occurred.emit(f"Error during '{self.task}': {str(e)}")


class MainWindow(QMainWindow):
    """Main application window integrating ProjectPanel and workflow tabs."""

    def __init__(self, harvester_facade: TimelineHarvesterFacade):
        super().__init__()
        # Store facade reference
        self.harvester = harvester_facade

        # Initialize worker thread and UI components to None
        self.worker_thread = None
        self.project_panel = None
        self.tab_widget = None
        self.color_prep_tab = None
        self.online_prep_tab = None
        self.status_manager = None

        # Store last known directories
        self.last_project_dir = os.path.expanduser("~")
        self.last_edit_file_dir = os.path.expanduser("~")
        self.last_export_dir = os.path.expanduser("~")

        # Initialize all action objects
        self.action_new_project = None
        self.action_open_project = None
        self.action_save_project = None
        self.action_save_project_as = None
        self.action_exit = None
        self.action_analyze = None
        self.action_calculate_color = None
        self.action_export_for_color = None
        self.action_calculate_online = None
        self.action_transcode = None
        self.action_about = None

        # Initialize menu objects
        self.file_menu = None
        self.process_menu = None
        self.help_menu = None

        # Initialize toolbar
        self.toolbar = None

        # Set initial window properties
        self.setWindowTitle("TimelineHarvester")
        self.setMinimumSize(1200, 800)

        # Initialize UI components
        self.init_ui()
        self.create_actions()
        self.create_menus()
        self.create_toolbar()
        self.connect_signals()
        self.load_settings()

        # Create a new project on startup
        self.new_project(confirm_save=False)
        logger.info("MainWindow initialized with Facade")

    def init_ui(self):
        """Sets up the main user interface layout."""
        self.status_manager = StatusBarManager(self.statusBar())
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        self.project_panel = ProjectPanel()
        main_layout.addWidget(self.project_panel)

        self.tab_widget = QTabWidget()
        self.tab_widget.setUsesScrollButtons(True)
        self.color_prep_tab = ColorPrepTabWidget(self.harvester)
        self.online_prep_tab = OnlinePrepTabWidget(self.harvester)
        self.tab_widget.addTab(self.color_prep_tab, "1. Prepare for Color Grading")
        self.tab_widget.addTab(self.online_prep_tab, "2. Prepare for Online")
        main_layout.addWidget(self.tab_widget, 1)
        logger.debug("Main window UI layout created")

    def create_actions(self):
        """Creates QAction objects for menus and toolbars."""
        # Create actions with parent properly set
        self.action_new_project = QAction("&New Project", self)
        self.action_new_project.setShortcut("Ctrl+N")
        self.action_new_project.setStatusTip("Create a new project")

        self.action_open_project = QAction("&Open Project...", self)
        self.action_open_project.setShortcut("Ctrl+O")
        self.action_open_project.setStatusTip("Open an existing project file (.thp)")

        self.action_save_project = QAction("&Save Project", self)
        self.action_save_project.setShortcut("Ctrl+S")
        self.action_save_project.setStatusTip("Save the current project")
        self.action_save_project.setEnabled(False)

        self.action_save_project_as = QAction("Save Project &As...", self)
        self.action_save_project_as.setStatusTip("Save the current project to a new file")

        self.action_exit = QAction("E&xit", self)
        self.action_exit.setShortcut("Ctrl+Q")
        self.action_exit.setStatusTip("Exit the application")

        # Process actions
        self.action_analyze = QAction("&Analyze Sources", self)
        self.action_analyze.setShortcut("F5")
        self.action_analyze.setStatusTip("Parse edit files and find original sources")
        self.action_analyze.setEnabled(False)

        self.action_calculate_color = QAction("&Calculate for Color", self)
        self.action_calculate_color.setShortcut("F6")
        self.action_calculate_color.setStatusTip("Calculate segments needed for color grading")
        self.action_calculate_color.setEnabled(False)

        self.action_export_for_color = QAction("Export EDL/XML for Color...", self)
        self.action_export_for_color.setStatusTip("Export list for color grading")
        self.action_export_for_color.setEnabled(False)

        self.action_calculate_online = QAction("Calculate for &Online", self)
        self.action_calculate_online.setShortcut("F7")
        self.action_calculate_online.setStatusTip("Calculate segments needed for online")
        self.action_calculate_online.setEnabled(False)

        self.action_transcode = QAction("&Transcode for Online", self)
        self.action_transcode.setShortcut("F8")
        self.action_transcode.setStatusTip("Transcode calculated segments for online")
        self.action_transcode.setEnabled(False)

        self.action_about = QAction("&About TimelineHarvester", self)
        self.action_about.setStatusTip("Show application information")

        logger.debug("UI Actions created")

    def create_menus(self):
        """Sets up the application menu bar."""
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.action_new_project)
        self.file_menu.addAction(self.action_open_project)
        self.file_menu.addAction(self.action_save_project)
        self.file_menu.addAction(self.action_save_project_as)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_exit)

        self.process_menu = self.menuBar().addMenu("&Process")
        color_menu = self.process_menu.addMenu("Color Grading Prep")
        color_menu.addAction(self.action_analyze)
        color_menu.addAction(self.action_calculate_color)
        color_menu.addAction(self.action_export_for_color)
        online_menu = self.process_menu.addMenu("Online Prep")
        online_menu.addAction(self.action_calculate_online)
        online_menu.addAction(self.action_transcode)

        self.help_menu = self.menuBar().addMenu("&Help")
        self.help_menu.addAction(self.action_about)
        logger.debug("UI Menus created")

    def create_toolbar(self):
        """Sets up the main toolbar."""
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setObjectName("mainToolbar")
        self.toolbar.setMovable(False)
        self.toolbar.addAction(self.action_new_project)
        self.toolbar.addAction(self.action_open_project)
        self.toolbar.addAction(self.action_save_project)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_analyze)
        self.toolbar.addAction(self.action_calculate_color)
        self.toolbar.addAction(self.action_export_for_color)
        logger.debug("UI Toolbar created")

    def connect_signals(self):
        """Connects UI signals to their respective slots."""
        # Project Actions
        self.action_new_project.triggered.connect(self.new_project)
        self.action_open_project.triggered.connect(self.open_project)
        self.action_save_project.triggered.connect(self.save_project)
        self.action_save_project_as.triggered.connect(self.save_project_as)
        self.action_exit.triggered.connect(self.close)
        self.action_about.triggered.connect(self.show_about_dialog)

        # Global Process Actions
        self.action_analyze.triggered.connect(self.start_analysis_task)
        self.action_calculate_color.triggered.connect(self.start_calculate_color_task)
        self.action_export_for_color.triggered.connect(self.start_export_for_color_task)
        self.action_calculate_online.triggered.connect(self.start_calculate_online_task)
        self.action_transcode.triggered.connect(self.start_transcode_task)

        # ProjectPanel -> MainWindow
        self.project_panel.editFilesChanged.connect(self.on_edit_files_changed)
        self.project_panel.originalSourcePathsChanged.connect(self.on_original_paths_changed)
        self.project_panel.gradedSourcePathsChanged.connect(self.on_graded_paths_changed)

        # ColorPrepTab -> MainWindow
        self.color_prep_tab.settingsChanged.connect(self.on_color_settings_changed)
        self.color_prep_tab.analyzeSourcesClicked.connect(self.start_analysis_task)
        self.color_prep_tab.calculateSegmentsClicked.connect(self.start_calculate_color_task)
        self.color_prep_tab.exportEdlXmlClicked.connect(self.start_export_for_color_task)

        # OnlinePrepTab -> MainWindow
        self.online_prep_tab.settingsChanged.connect(self.on_online_settings_changed)
        self.online_prep_tab.calculateOnlineClicked.connect(self.start_calculate_online_task)
        self.online_prep_tab.transcodeClicked.connect(self.start_transcode_task)

        logger.debug("UI Signals connected")

    # --- Project State Management ---

    @pyqtSlot(list)
    def on_edit_files_changed(self, paths: list):
        """Handles changes to the edit files list."""
        logger.debug("Edit files list changed in UI")
        self.harvester.set_edit_file_paths(paths)
        self._update_ui_state()
        self.update_window_title()

    @pyqtSlot(list)
    def on_original_paths_changed(self, paths: list):
        """Handles changes to the original source paths list."""
        logger.debug("Original search paths changed in UI")
        self.harvester.set_source_search_paths(paths)
        self._update_ui_state()
        self.update_window_title()

    @pyqtSlot(list)
    def on_graded_paths_changed(self, paths: list):
        """Handles changes to the graded paths list."""
        logger.debug("Graded search paths changed in UI")
        self.harvester.set_graded_source_search_paths(paths)
        self._update_ui_state()
        self.update_window_title()

    @pyqtSlot()
    def on_color_settings_changed(self):
        """Handles changes to color prep settings."""
        logger.debug("Color Prep settings changed in UI")
        settings = self.color_prep_tab.get_tab_settings()
        self.harvester.set_color_prep_handles(
            settings.get('color_prep_start_handles', 25),
            settings.get('color_prep_end_handles', 25)
        )
        self.harvester.set_color_prep_separator(settings.get('color_prep_separator', 0))
        self.harvester.set_split_gap_threshold(settings.get('split_gap_threshold_frames', -1))
        self._update_ui_state()
        self.update_window_title()

    @pyqtSlot()
    def on_online_settings_changed(self):
        """Handles changes to online prep settings."""
        logger.debug("Online Prep settings changed in UI")
        self._update_ui_state()
        self.update_window_title()

    def update_window_title(self):
        """Updates the window title based on project state."""
        is_dirty = self.harvester.is_project_dirty()
        base_title = "TimelineHarvester"
        proj_path = self.harvester.get_current_project_path()
        proj_name = os.path.basename(proj_path) if proj_path else "Untitled Project"
        dirty_indicator = " *" if is_dirty else ""
        self.setWindowTitle(f"{proj_name}{dirty_indicator} - {base_title}")
        # Also update save action enable state
        self.action_save_project.setEnabled(is_dirty and proj_path is not None)

    def _confirm_save_if_dirty(self) -> bool:
        """Checks facade's dirty state, prompts to save, returns True if okay to proceed."""
        if not self.harvester.is_project_dirty():
            return True

        reply = QMessageBox.question(self, "Unsaved Changes",
                                     "The current project has unsaved changes. Save before proceeding?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                     QMessageBox.Save)
        if reply == QMessageBox.Save:
            return self.save_project()
        elif reply == QMessageBox.Discard:
            return True
        else:  # Cancel
            return False

    # --- Project Actions Implementation ---

    @pyqtSlot()
    def new_project(self, confirm_save=True):
        """Creates a new project."""
        logger.info("Action: New Project")
        if confirm_save and not self._confirm_save_if_dirty():
            return

        self.harvester.new_project()
        self._update_ui_from_facade_state()
        self.status_manager.set_status("New project created.")
        self.update_window_title()
        self._update_ui_state()

    @pyqtSlot()
    def open_project(self):
        """Opens an existing project."""
        logger.info("Action: Open Project")
        if not self._confirm_save_if_dirty():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", self.last_project_dir,
            "Harvester Projects (*.thp *.json);;All Files (*)"
        )
        if not file_path:
            return

        self.last_project_dir = os.path.dirname(file_path)
        self.status_manager.set_busy(True, f"Loading project: {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            if not self.harvester.load_project(file_path):
                raise ValueError("Facade load_project returned False (check logs).")

            self._update_ui_from_facade_state()
            self.status_manager.set_status(f"Project '{os.path.basename(file_path)}' loaded.")
            self.save_settings()
        except Exception as e:
            logger.error(f"Failed to load project '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Load Project Error",
                                 f"Failed to load project:\n{e}\n\nCreating a new project.")
            self.harvester.new_project()
            self._update_ui_from_facade_state()
            self.status_manager.set_status("Failed to load project. New project started.")
        finally:
            self.status_manager.set_busy(False)
            self.update_window_title()
            self._update_ui_state()

    @pyqtSlot()
    def save_project(self) -> bool:
        """Saves the current project."""
        logger.info("Action: Save Project")
        current_path = self.harvester.get_current_project_path()
        if not current_path:
            return self.save_project_as()
        return self._save_project_to_path(current_path)

    @pyqtSlot()
    def save_project_as(self) -> bool:
        """Saves the current project to a new file."""
        logger.info("Action: Save Project As...")
        current_path = self.harvester.get_current_project_path()
        state = self.harvester.get_project_state_snapshot()
        suggested_name = os.path.basename(current_path or f"{state.settings.project_name or 'Untitled'}.thp")
        start_dir = os.path.dirname(current_path or self.last_project_dir)
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As",
            os.path.join(start_dir, suggested_name),
            "Harvester Projects (*.thp);;JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            return False

        # Ensure correct extension
        name, ext = os.path.splitext(file_path)
        if not ext.lower() in ['.thp', '.json']:
            file_path += ".thp"

        self.last_project_dir = os.path.dirname(file_path)
        return self._save_project_to_path(file_path)

    def _save_project_to_path(self, file_path: str) -> bool:
        """Internal helper for saving to a specific path."""
        self.status_manager.set_busy(True, f"Saving project to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            if not self.harvester.save_project(file_path):
                raise ValueError("Facade save_project returned False (check logs).")

            self.status_manager.set_status(f"Project saved: {os.path.basename(file_path)}.")
            self.save_settings()
            self.update_window_title()
            self._update_ui_state()
            return True
        except Exception as e:
            logger.error(f"Failed to save project to '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Save Project Error", f"Failed to save project:\n{e}")
            self.status_manager.set_status("Failed to save project.")
            self.update_window_title()
            self._update_ui_state()
            return False
        finally:
            self.status_manager.set_busy(False)

    # --- Settings Persistence ---

    def load_settings(self):
        """Loads application settings."""
        logger.info("Loading persistent application settings")
        settings = QSettings()
        try:
            geom = settings.value("window_geometry")
            if geom:
                self.restoreGeometry(geom)
            state = settings.value("window_state")
            if state:
                self.restoreState(state)
            self.last_project_dir = settings.value("last_project_dir", os.path.expanduser("~"))
            self.last_edit_file_dir = settings.value("last_edit_file_dir", self.last_project_dir)
            self.last_export_dir = settings.value("last_export_dir", self.last_project_dir)
        except Exception as e:
            logger.error(f"Error loading QSettings: {e}", exc_info=True)
        logger.info("Settings loading complete")

    def save_settings(self):
        """Saves application settings."""
        logger.info("Saving persistent application settings")
        settings = QSettings()
        settings.setValue("window_geometry", self.saveGeometry())
        settings.setValue("window_state", self.saveState())
        settings.setValue("last_project_dir", self.last_project_dir)
        settings.setValue("last_edit_file_dir", self.last_edit_file_dir)
        settings.setValue("last_export_dir", self.last_export_dir)
        logger.info("Window state and last directories saved")

    def closeEvent(self, event):
        """Handles window close event."""
        logger.debug("Close event triggered")
        if not self._confirm_save_if_dirty():
            event.ignore()
            return

        if self.worker_thread and self.worker_thread.isRunning():
            logger.warning("Closing while worker thread is running. Attempting to stop.")
            self.worker_thread.stop()

        self.save_settings()
        logger.info("Closing TimelineHarvester Application")
        event.accept()

    # --- UI State Management ---

    def _update_ui_state(self):
        """Updates the enabled state of all actions/buttons based on facade state."""
        is_busy = self.worker_thread is not None and self.worker_thread.isRunning()
        enabled = not is_busy

        # Get current state snapshot from facade
        state = self.harvester.get_project_state_snapshot()
        proj_path_exists = self.harvester.get_current_project_path() is not None

        # Determine capabilities based on state
        files_loaded = bool(state.edit_files)
        sources_paths_set = bool(state.settings.source_search_paths)
        analysis_done = bool(state.edit_shots)
        sources_found = analysis_done and any(s.lookup_status == 'found' for s in state.edit_shots)
        color_plan_calculated = state.color_transfer_batch is not None and bool(state.color_transfer_batch.segments)
        online_plan_calculated = state.online_transfer_batch is not None and bool(state.online_transfer_batch.segments)
        can_calc_online = enabled and sources_found and bool(state.settings.online_output_directory) and bool(
            state.settings.output_profiles)

        # Update Global Actions
        self.action_new_project.setEnabled(enabled)
        self.action_open_project.setEnabled(enabled)
        self.action_save_project.setEnabled(enabled and state.is_dirty and proj_path_exists)
        self.action_save_project_as.setEnabled(enabled)
        self.action_analyze.setEnabled(enabled and files_loaded and sources_paths_set)
        self.action_calculate_color.setEnabled(enabled and sources_found)
        self.action_export_for_color.setEnabled(enabled and color_plan_calculated)
        self.action_calculate_online.setEnabled(enabled and can_calc_online)
        self.action_transcode.setEnabled(enabled and online_plan_calculated)

        # Update Tab Buttons
        if self.color_prep_tab:
            self.color_prep_tab.update_button_states(
                can_analyze=enabled and files_loaded and sources_paths_set,
                can_calculate=enabled and sources_found,
                can_export=enabled and color_plan_calculated
            )
        if self.online_prep_tab:
            self.online_prep_tab.update_button_states(
                can_analyze=False,
                can_calculate=enabled and can_calc_online,
                can_transcode=enabled and online_plan_calculated
            )

        logger.debug(f"UI state updated (Busy: {is_busy})")

    def _is_worker_busy(self) -> bool:
        """Checks if the worker thread is active."""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "A background task is currently running. Please wait.")
            return True
        return False

    def _update_ui_from_facade_state(self):
        """Refreshes the entire UI based on the current facade/project state."""
        logger.info("Updating UI from facade state...")
        try:
            # Get the state object
            state = self.harvester.get_project_state_snapshot()

            # Update Project Panel
            if self.project_panel:
                self.project_panel.set_edit_files([f.path for f in state.edit_files])
                self.project_panel.set_original_search_paths(state.settings.source_search_paths)
                self.project_panel.set_graded_search_paths(state.settings.graded_source_search_paths)

            # Update Color Prep Tab
            if self.color_prep_tab:
                color_settings = {
                    'color_prep_start_handles': state.settings.color_prep_start_handles,
                    'color_prep_end_handles': state.settings.color_prep_end_handles,
                    'color_prep_same_handles': state.settings.color_prep_start_handles == state.settings.color_prep_end_handles,
                    'color_prep_separator': state.settings.color_prep_separator,
                    'split_gap_threshold_frames': state.settings.split_gap_threshold_frames,
                }
                self.color_prep_tab.load_tab_settings(color_settings)

                # Refresh results display
                analysis_summary = self.harvester.get_edit_shots_summary()
                self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
                color_plan_summary = self.harvester.get_transfer_segments_summary(stage='color')
                self.color_prep_tab.results_widget.display_plan_summary(color_plan_summary)
                unresolved_summary = self.harvester.get_unresolved_shots_summary()
                self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)

                # Update Online Prep Tab
                if self.online_prep_tab:
                    online_settings = {
                        'online_prep_handles': state.settings.online_prep_handles,
                        'output_profiles': [p.__dict__ for p in state.settings.output_profiles],
                        'online_output_directory': state.settings.online_output_directory,
                    }
                    self.online_prep_tab.load_tab_settings(online_settings)

                self.update_window_title()
                self._update_ui_state()
                logger.info("UI refreshed from facade state")
        except Exception as e:
            logger.error(f"Error updating UI from facade state: {e}", exc_info=True)
            QMessageBox.critical(self, "UI Update Error", f"Failed to refresh UI from project state:\n{e}")

    # --- Task Starting Slots ---

    @pyqtSlot()
    def start_analysis_task(self):
        """Starts the source analysis task."""
        if self._is_worker_busy():
            return

        state = self.harvester.get_project_state_snapshot()
        if not state.edit_files:
            QMessageBox.warning(self, "No Edit Files", "Please add edit files to the list.")
            return
        if not state.settings.source_search_paths:
            QMessageBox.warning(self, "Config Missing",
                                "Please add Original Source search paths in the Project Panel.")
            return

        self._start_worker('analyze', "Analyzing files & finding sources...", {})

    @pyqtSlot()
    def start_calculate_color_task(self):
        """Starts the calculate for color task."""
        if self._is_worker_busy():
            return

        state = self.harvester.get_project_state_snapshot()
        if not state.edit_shots or not any(s.lookup_status == 'found' for s in state.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete",
                                "Please run 'Analyze Sources' first and ensure original files were found.")
            return

        params = {'stage': 'color'}
        self._start_worker('calculate_plan', "Calculating segments for color prep...", params)

    @pyqtSlot()
    def start_export_for_color_task(self):
        """Starts the export for color task."""
        if self._is_worker_busy():
            return

        state = self.harvester.get_project_state_snapshot()
        batch = state.color_transfer_batch
        if not batch or not batch.segments:
            error_msg = "Calculate the plan for color first."
            if batch and batch.calculation_errors:
                error_msg = f"Cannot export: Calculation failed:\n{'; '.join(batch.calculation_errors)}"
            elif batch:
                error_msg = "Cannot export: The calculated plan for color is empty (no segments found)."
            QMessageBox.warning(self, "Export Error", error_msg)
            return

        proj_name = state.settings.project_name or "UntitledProject"
        default_name = f"{proj_name}_TRANSFER.aaf"
        start_dir = self.last_export_dir or os.path.dirname(
            self.harvester.get_current_project_path() or self.last_project_dir)

        file_filters = "AAF (*.aaf);;FCP XML (*.xml *.fcpxml);;CMX EDL (*.edl);;All Files (*)"

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Timeline for Color",
            os.path.join(start_dir, default_name),
            file_filters
        )
        if not file_path:
            return

        name_part, _ = os.path.splitext(file_path)
        if selected_filter.startswith("AAF") and not file_path.lower().endswith(".aaf"):
            file_path = name_part + ".aaf"
        elif selected_filter.startswith("FCP XML") and not (
                file_path.lower().endswith(".xml") or file_path.lower().endswith(".fcpxml")):
            file_path = name_part + ".xml"
        elif selected_filter.startswith("CMX EDL") and not file_path.lower().endswith(".edl"):
            file_path = name_part + ".edl"

        self.last_export_dir = os.path.dirname(file_path)
        self.status_manager.set_busy(True, f"Exporting to {os.path.basename(file_path)}...")
        QApplication.processEvents()

        try:
            success = self.harvester.run_export('color', file_path)
            if success:
                self.status_manager.set_status(f"Export successful: {os.path.basename(file_path)}", temporary=False)
                QMessageBox.information(self, "Export Successful", f"Timeline exported to:\n{file_path}")
                self.save_settings()
            else:
                self.status_manager.set_status("Export failed. Check logs.", temporary=False)
                QMessageBox.critical(self, "Export Failed",
                                     "Could not export timeline for color grading. Please check the application logs "
                                     "for details.")
        except Exception as e:
            logger.error(f"Unexpected error during color export task: {e}", exc_info=True)
            self.status_manager.set_status(f"Export Error: {e}", temporary=False)
            QMessageBox.critical(self, "Export Error", f"An unexpected error occurred during export:\n\n{e}")
        finally:
            self.status_manager.set_busy(False)

    @pyqtSlot()
    def start_calculate_online_task(self):
        """Starts the calculate for online task."""
        if self._is_worker_busy():
            return

        state = self.harvester.get_project_state_snapshot()
        if not state.edit_shots or not any(s.lookup_status == 'found' for s in state.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete", "Please run 'Analyze Sources' first.")
            return

        if not state.settings.online_output_directory:
            QMessageBox.warning(self, "Config Missing", "Please set the Online Output Directory.")
            return

        if not state.settings.output_profiles:
            QMessageBox.warning(self, "Config Missing", "Please configure Output Profiles for Online.")
            return

        params = {'stage': 'online'}
        self._start_worker('calculate_plan', "Calculating segments for online prep...", params)

    @pyqtSlot()
    def start_transcode_task(self):
        """Starts the transcode task."""
        if self._is_worker_busy():
            return

        state = self.harvester.get_project_state_snapshot()
        batch = state.online_transfer_batch

        if not batch or not batch.segments:
            error_msg = "Calculate the plan for online first."
            if batch and batch.calculation_errors:
                error_msg = f"Cannot transcode: Online calculation failed:\n{'; '.join(batch.calculation_errors)}"
            elif batch:
                error_msg = "Cannot transcode: The calculated online plan is empty."
            QMessageBox.warning(self, "Transcode Error", error_msg)
            return

        if not state.settings.online_output_directory:
            QMessageBox.critical(self, "Config Error", "Online output directory is not set.")
            return

        if not state.settings.output_profiles:
            QMessageBox.warning(self, "Config Missing", "No output profiles configured for online.")
            return

        segment_count = len(batch.segments)
        profile_count = len(state.settings.output_profiles)
        estimated_files = segment_count * profile_count
        output_dir = state.settings.online_output_directory

        reply = QMessageBox.question(
            self, "Confirm Transcode",
            f"Start transcoding approximately {estimated_files} file(s) for the online stage to:\n"
            f"{output_dir}\n\n"
            f"This process may take a significant amount of time.\nProceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._start_worker('transcode', f"Starting online transcoding...", {'stage': 'online'})
        else:
            self.status_manager.set_status("Online transcoding cancelled by user.")

    # --- Worker Thread Management ---

    def _start_worker(self, task_name: str, busy_message: str, params: Optional[Dict] = None):
        """Starts a worker thread to perform a background task."""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Another background task is already running.")
            return

        logger.info(f"Starting worker thread for task: {task_name}")
        self.status_manager.set_busy(True, busy_message)

        self.worker_thread = WorkerThread(self.harvester, task_name, params)
        # Connect signals
        self.worker_thread.analysis_finished.connect(self.on_analysis_complete)
        self.worker_thread.plan_finished.connect(self.on_plan_complete)
        self.worker_thread.transcode_finished.connect(self.on_transcode_complete)
        self.worker_thread.progress_update.connect(self.on_progress_update)
        self.worker_thread.error_occurred.connect(self.on_task_error)
        self.worker_thread.finished.connect(self.on_task_finished)

        # Start the thread
        self.worker_thread.start()
        self._update_ui_state()

    # --- Slots Handling Worker Thread Signals ---

    @pyqtSlot(list, list)
    def on_analysis_complete(self, analysis_summary: List[Dict], unresolved_summary: List[Dict]):
        """Handles completion of the analysis task."""
        logger.info(f"Analysis complete. Shots: {len(analysis_summary)}, Unresolved: {len(unresolved_summary)}")

        # Update results displays
        if self.color_prep_tab:
            self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)

        self.status_manager.set_status(
            f"Analysis complete. Found {sum(1 for s in analysis_summary if s['status'] == 'found')} original sources."
        )

    @pyqtSlot(list, list, str)
    def on_plan_complete(self, plan_summary: List[Dict], unresolved_summary: List[Dict], stage: str):
        """Handles completion of the calculation task."""
        logger.info(
            f"Plan complete for stage '{stage}'. Segments: {len(plan_summary)}, Unresolved: {len(unresolved_summary)}")

        # Update results display for the specific stage
        if stage == 'color' and self.color_prep_tab:
            self.color_prep_tab.results_widget.display_plan_summary(plan_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)

        self.status_manager.set_status(f"'{stage.capitalize()}' plan calculated ({len(plan_summary)} segments).")

    @pyqtSlot(bool, str)
    def on_transcode_complete(self, success: bool, message: str):
        """Handles completion of the transcode task."""
        logger.info(f"Transcode complete. Success: {success}, Message: {message}")

        if success:
            self.status_manager.set_status(message, temporary=False)
            QMessageBox.information(self, "Transcoding Complete", message)
        else:
            self.status_manager.set_status(f"Transcoding Failed: {message}. Check logs.", temporary=False)
            QMessageBox.critical(self, "Transcoding Failed",
                                 f"Transcoding process failed.\n{message}\n\nPlease check logs for details.")

    @pyqtSlot(int, str)
    def on_progress_update(self, percent: int, message: str):
        """Handles progress updates from the worker thread."""
        self.status_manager.show_progress(percent, 100, message)

    @pyqtSlot(str)
    def on_task_error(self, error_message: str):
        """Handles error signals from the worker thread."""
        logger.error(f"Worker thread error: {error_message}")
        self.status_manager.set_status(f"Error: {error_message}", temporary=False)
        QMessageBox.critical(self, "Background Task Error",
                             f"An error occurred during the background task:\n\n{error_message}\n\nPlease check logs for detailed information.")

    @pyqtSlot()
    def on_task_finished(self):
        """Handles the finished signal from the worker thread."""
        logger.info("Worker thread finished. Cleaning up UI.")
        self.status_manager.hide_progress()

        # Check if the final status message indicates an error or cancellation
        current_status = self.status_manager.status_label.text().lower()
        is_error_or_cancel = "error" in current_status or "fail" in current_status or "cancel" in current_status
        if not is_error_or_cancel:
            self.status_manager.set_status("Ready.")

        self.worker_thread = None
        self._update_ui_state()
        self._update_results_display()
        logger.info("Worker thread cleanup and UI update complete.")

    def _update_results_display(self):
        """Updates all result tabs in the UI."""
        logger.debug("Refreshing results display widgets...")
        try:
            # Use facade methods to get fresh summary data
            analysis_summary = self.harvester.get_edit_shots_summary()
            color_plan_summary = self.harvester.get_transfer_segments_summary(stage='color')
            unresolved_summary = self.harvester.get_unresolved_shots_summary()

            if self.color_prep_tab:
                self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
                self.color_prep_tab.results_widget.display_plan_summary(color_plan_summary)
                self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        except Exception as e:
            logger.error(f"Error refreshing results display: {e}", exc_info=True)

    # --- About Dialog ---

    def show_about_dialog(self):
        """Shows the about dialog."""
        QMessageBox.about(
            self, "About TimelineHarvester",
            f"<h2>TimelineHarvester</h2>"
            f"<p>Version {QCoreApplication.applicationVersion()}</p>"
            f"<p>Workflow tool for preparing media for color grading and online editing.</p>"
            f"<p>(Uses OpenTimelineIO and FFmpeg/FFprobe)</p>"
            f"<p>Qt Version: {Qt.QT_VERSION_STR}</p>"
        )

# gui/main_window.py
"""
Main Window Module - Refactored to use TimelineHarvesterFacade

Integrates ProjectPanel and Tab Widgets (ColorPrep, OnlinePrep).
Handles project state via the Facade, background tasks via WorkerThread,
and UI updates. Connects UI actions to the Facade.
"""

import logging
import os
from typing import List, Optional, Dict, Any  # Added Any for state snapshot

from PyQt5.QtCore import QSettings, QThread, pyqtSignal, pyqtSlot, Qt, QCoreApplication
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QVBoxLayout,
    QWidget, QTabWidget, QApplication
)

# Import the Facade instead of the old class
from core.timeline_harvester_facade import TimelineHarvesterFacade
# Import models only if directly needed (e.g., for type hints not covered by facade methods)
# from core.models import EditFileMetadata # Likely not needed directly now

# Import GUI components
from .color_prep_tab import ColorPrepTabWidget
from .online_prep_tab import OnlinePrepTabWidget
from .project_panel import ProjectPanel
from .status_bar import StatusBarManager

logger = logging.getLogger(__name__)


# --- Worker Thread Definition (Modified to accept Facade) ---
class WorkerThread(QThread):
    # Signals remain the same
    analysis_finished = pyqtSignal(list, list)  # Pass both analysis and unresolved summaries
    plan_finished = pyqtSignal(list, list, str)  # Pass plan, unresolved, and stage
    transcode_finished = pyqtSignal(bool, str)
    progress_update = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, harvester_facade: TimelineHarvesterFacade, task: str, params: Optional[Dict] = None):
        super().__init__()
        # Store the facade instance
        self.harvester = harvester_facade  # Rename internal variable for clarity
        self.task = task
        self.params = params if params else {}
        self._is_running = True
        logger.info(f"WorkerThread initialized with Facade for task: {self.task}")

    def stop(self):
        self._is_running = False
        logger.info(f"Stop requested for worker thread task: {self.task}")

    def run(self):
        logger.info(f"WorkerThread starting task: {self.task}")
        try:
            if self.task == 'analyze':
                # Call the single analysis method on the facade
                success = self.harvester.run_source_analysis()
                if not self._is_running: raise InterruptedError("Task stopped.")
                if not success: raise RuntimeError("Analysis process failed (check logs).")
                # Get summaries *after* analysis is complete
                analysis_summary = self.harvester.get_edit_shots_summary()
                unresolved_summary = self.harvester.get_unresolved_shots_summary()
                if self._is_running: self.analysis_finished.emit(analysis_summary, unresolved_summary)

            elif self.task == 'calculate_plan':  # Renamed for clarity
                stage = self.params.get('stage', 'color')
                logger.info(f"Worker calculating plan for stage: {stage}")
                # Call calculation method on the facade
                success = self.harvester.run_calculation(stage=stage)
                if not self._is_running: raise InterruptedError("Task stopped.")
                if not success: raise RuntimeError(f"Calculation process failed for stage {stage} (check logs).")
                # Get summaries *after* calculation
                segment_summary = self.harvester.get_transfer_segments_summary(stage=stage)
                unresolved_summary = self.harvester.get_unresolved_shots_summary()
                if self._is_running: self.plan_finished.emit(segment_summary, unresolved_summary, stage)

            elif self.task == 'transcode':
                stage = self.params.get('stage', 'online')
                if stage != 'online': raise ValueError("Transcoding implemented only for 'online' stage.")

                def progress_callback(current, total, message):
                    if not self._is_running: raise InterruptedError("Transcode stopped by user.")
                    percent = int((current / total) * 100) if total > 0 else 0
                    # Check thread running state again *before* emitting signal
                    if self._is_running:
                        self.progress_update.emit(percent, message)
                    else:  # If stopped during callback, raise error to stop FFmpeg loop potentially
                        raise InterruptedError("Transcode stopped during progress update.")

                # Call transcoding method on the facade
                self.harvester.run_online_transcoding(progress_callback)  # Facade handles errors internally or raises
                if self._is_running: self.transcode_finished.emit(True, "Online transcoding process completed.")
            else:
                raise ValueError(f"Unknown worker task: {self.task}")

            if self._is_running:
                logger.info(f"WorkerThread finished task '{self.task}' successfully.")

        except InterruptedError:
            logger.warning(f"WorkerThread task '{self.task}' cancelled by user.")
            # Don't emit error_occurred for user cancellation, just finish silently
            # self.error_occurred.emit(f"Task '{self.task}' cancelled.")
        except Exception as e:
            logger.error(f"WorkerThread error during task '{self.task}': {e}", exc_info=True)
            # Emit error signal only if the thread wasn't stopped externally
            if self._is_running:
                self.error_occurred.emit(f"Error during '{self.task}': {str(e)}")


# --- Main Window Class ---
class MainWindow(QMainWindow):
    """Main application window integrating ProjectPanel and workflow tabs."""

    # Signal for dirty state change (can be connected to Facade's signal later if needed)
    # projectDirtyStateChanged = pyqtSignal(bool)

    # *** CHANGE HERE: Constructor accepts Facade ***
    def __init__(self, harvester_facade: TimelineHarvesterFacade):
        super().__init__()
        self.harvester = harvester_facade  # Store facade instance
        self.worker_thread: Optional[WorkerThread] = None
        # Remove direct state tracking, rely on facade
        # self.current_project_path: Optional[str] = None -> Use self.harvester.get_current_project_path()
        # self.is_project_dirty: bool = False -> Use self.harvester.is_project_dirty()
        self.project_panel: Optional[ProjectPanel] = None
        self.tab_widget: Optional[QTabWidget] = None
        self.color_prep_tab: Optional[ColorPrepTabWidget] = None
        self.online_prep_tab: Optional[OnlinePrepTabWidget] = None
        self.status_manager: Optional[StatusBarManager] = None

        # Store last known directories
        self.last_project_dir = os.path.expanduser("~")
        self.last_edit_file_dir = os.path.expanduser("~")
        self.last_export_dir = os.path.expanduser("~")

        self.setWindowTitle("TimelineHarvester")  # Initial title
        self.setMinimumSize(1200, 800)
        self.init_ui()
        self.create_actions()
        self.create_menus()
        self.create_toolbar()
        self.connect_signals()
        self.load_settings()  # Load UI settings
        # Create a new project on startup using the facade method
        self.new_project(confirm_save=False)
        logger.info("MainWindow initialized with Facade.")

    # --- UI Creation Methods (No changes needed) ---
    def init_ui(self):
        self.status_manager = StatusBarManager(self.statusBar())
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        self.project_panel = ProjectPanel()
        main_layout.addWidget(self.project_panel)

        self.tab_widget = QTabWidget()
        self.tab_widget.setUsesScrollButtons(True)
        # Pass the *facade* to tabs if they need direct access (less ideal)
        # Or better, tabs emit signals, MainWindow calls facade
        self.color_prep_tab = ColorPrepTabWidget(self.harvester)  # Passing facade for now
        self.online_prep_tab = OnlinePrepTabWidget(self.harvester)  # Passing facade for now
        self.tab_widget.addTab(self.color_prep_tab, "1. Prepare for Color Grading")
        self.tab_widget.addTab(self.online_prep_tab, "2. Prepare for Online")
        main_layout.addWidget(self.tab_widget, 1)
        logger.debug("Main window UI layout created.")

    def create_actions(self):
        self.action_new_project = QAction("&New Project", self, shortcut="Ctrl+N", statusTip="Create a new project")
        self.action_open_project = QAction("&Open Project...", self, shortcut="Ctrl+O",
                                           statusTip="Open an existing project file (.thp)")
        self.action_save_project = QAction("&Save Project", self, shortcut="Ctrl+S",
                                           statusTip="Save the current project", enabled=False)
        self.action_save_project_as = QAction("Save Project &As...", self,
                                              statusTip="Save the current project to a new file")
        self.action_exit = QAction("E&xit", self, shortcut="Ctrl+Q", statusTip="Exit the application")
        # Process actions
        self.action_analyze = QAction("&Analyze Sources", self, shortcut="F5",
                                      statusTip="Parse edit files and find original sources", enabled=False)
        self.action_calculate_color = QAction("&Calculate for Color", self, shortcut="F6",
                                              statusTip="Calculate segments needed for color grading", enabled=False)
        self.action_export_for_color = QAction("Export EDL/XML for Color...", self,
                                               statusTip="Export list for color grading", enabled=False)
        self.action_calculate_online = QAction("Calculate for &Online", self, shortcut="F7",
                                               statusTip="Calculate segments needed for online", enabled=False)
        self.action_transcode = QAction("&Transcode for Online", self, shortcut="F8",
                                        statusTip="Transcode calculated segments for online", enabled=False)
        self.action_about = QAction("&About TimelineHarvester", self, statusTip="Show application information")
        logger.debug("UI Actions created.")

    def create_menus(self):
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
        logger.debug("UI Menus created.")

    def create_toolbar(self):
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.addAction(self.action_new_project)
        self.toolbar.addAction(self.action_open_project)
        self.toolbar.addAction(self.action_save_project)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_analyze)
        self.toolbar.addAction(self.action_calculate_color)
        self.toolbar.addAction(self.action_export_for_color)
        logger.debug("UI Toolbar created.")

    # --- Signal/Slot Connections ---
    def connect_signals(self):
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
        # ProjectPanel -> MainWindow (Connect to facade setters or specific handlers)
        self.project_panel.editFilesChanged.connect(self.on_edit_files_changed)
        self.project_panel.originalSourcePathsChanged.connect(self.on_original_paths_changed)
        self.project_panel.gradedSourcePathsChanged.connect(self.on_graded_paths_changed)
        # ColorPrepTab -> MainWindow
        self.color_prep_tab.settingsChanged.connect(self.on_color_settings_changed)  # Sync settings to facade
        self.color_prep_tab.analyzeSourcesClicked.connect(self.start_analysis_task)
        self.color_prep_tab.calculateSegmentsClicked.connect(self.start_calculate_color_task)
        self.color_prep_tab.exportEdlXmlClicked.connect(self.start_export_for_color_task)
        # OnlinePrepTab -> MainWindow (Placeholders)
        self.online_prep_tab.settingsChanged.connect(self.on_online_settings_changed)  # Sync settings
        self.online_prep_tab.calculateOnlineClicked.connect(self.start_calculate_online_task)
        self.online_prep_tab.transcodeClicked.connect(self.start_transcode_task)
        # Internal Dirty State -> Window Title (No longer needed if facade manages it)
        # self.projectDirtyStateChanged.connect(self.update_window_title)
        # We will call update_window_title manually when state changes
        logger.debug("UI Signals connected.")

    # --- Project State Management (Simplified using Facade) ---

    # Slot to handle changes from ProjectPanel edit files list
    @pyqtSlot(list)
    def on_edit_files_changed(self, paths: list):
        logger.debug("Edit files list changed in UI.")
        # Update facade state, which will mark dirty internally
        self.harvester.set_edit_file_paths(paths)
        self._update_ui_state()  # Update button enables etc.
        self.update_window_title()  # Update title based on facade's dirty state

    # Slot to handle changes from ProjectPanel original paths list
    @pyqtSlot(list)
    def on_original_paths_changed(self, paths: list):
        logger.debug("Original search paths changed in UI.")
        self.harvester.set_source_search_paths(paths)
        self._update_ui_state()
        self.update_window_title()

    # Slot to handle changes from ProjectPanel graded paths list
    @pyqtSlot(list)
    def on_graded_paths_changed(self, paths: list):
        logger.debug("Graded search paths changed in UI.")
        self.harvester.set_graded_source_search_paths(paths)
        self._update_ui_state()
        self.update_window_title()

    # Slot to handle changes from ColorPrepTab settings
    @pyqtSlot()
    def on_color_settings_changed(self):
        logger.debug("Color Prep settings changed in UI.")
        # Get settings from tab and update facade
        settings = self.color_prep_tab.get_tab_settings()
        self.harvester.set_color_prep_handles(
            settings.get('color_prep_start_handles', 24),
            settings.get('color_prep_end_handles', 24)  # Pass end handles correctly
        )
        self.harvester.set_color_prep_separator(settings.get('color_prep_separator', 0))
        self.harvester.set_split_gap_threshold(settings.get('split_gap_threshold_frames', -1))
        self._update_ui_state()
        self.update_window_title()

    # Slot to handle changes from OnlinePrepTab settings (Placeholder)
    @pyqtSlot()
    def on_online_settings_changed(self):
        logger.debug("Online Prep settings changed in UI.")
        settings = self.online_prep_tab.get_tab_settings()
        # Update facade with online settings when implemented
        # self.harvester.set_online_prep_handles(...)
        # self.harvester.set_online_output_directory(...)
        # self.harvester.set_output_profiles(...) # Facade needs this setter
        self._update_ui_state()
        self.update_window_title()

    # Update window title based on facade state
    def update_window_title(self):
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
        if not self.harvester.is_project_dirty(): return True  # No need to save if not dirty
        reply = QMessageBox.question(self, "Unsaved Changes",
                                     "The current project has unsaved changes. Save before proceeding?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if reply == QMessageBox.Save:
            return self.save_project()  # Call save method, which returns True/False
        elif reply == QMessageBox.Discard:
            return True  # Okay to proceed without saving
        else:  # Cancel
            return False  # Do not proceed

    # --- Project Actions Implementation (Using Facade) ---
    @pyqtSlot()
    def new_project(self, confirm_save=True):
        logger.info("Action: New Project")
        if confirm_save and not self._confirm_save_if_dirty(): return
        self.harvester.new_project()  # Facade handles clearing state
        self._update_ui_from_facade_state()  # Update UI from the new empty state
        self.status_manager.set_status("New project created.")
        # No need to manage dirty flag here, facade/manager does it
        self.update_window_title()
        self._update_ui_state()  # Update button states

    @pyqtSlot()
    def open_project(self):
        logger.info("Action: Open Project")
        if not self._confirm_save_if_dirty(): return
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Project", self.last_project_dir,
                                                   "Harvester Projects (*.thp *.json);;All Files (*)")
        if not file_path: return
        self.last_project_dir = os.path.dirname(file_path)
        self.status_manager.set_busy(True, f"Loading project: {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            # Call facade load method
            if not self.harvester.load_project(file_path):
                raise ValueError("Facade load_project returned False (check logs).")
            self._update_ui_from_facade_state()  # Refresh UI with loaded data
            self.status_manager.set_status(f"Project '{os.path.basename(file_path)}' loaded.")
            self.save_settings()  # Save last opened dir etc.
        except Exception as e:
            logger.error(f"Failed to load project '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Load Project Error", f"Failed to load project:\n{e}\n\nCreating a new project.")
            # Revert to a clean state on failure
            self.harvester.new_project()
            self._update_ui_from_facade_state()
            self.status_manager.set_status("Failed to load project. New project started.")
        finally:
            self.status_manager.set_busy(False)
            self.update_window_title()
            self._update_ui_state()

    @pyqtSlot()
    def save_project(self) -> bool:
        logger.info("Action: Save Project")
        current_path = self.harvester.get_current_project_path()
        if not current_path:
            return self.save_project_as()  # Trigger Save As if no path exists
        # No need to sync UI to facade explicitly, changes should already be in state via setters
        return self._save_project_to_path(current_path)

    @pyqtSlot()
    def save_project_as(self) -> bool:
        logger.info("Action: Save Project As...")
        current_path = self.harvester.get_current_project_path()
        state = self.harvester.get_project_state_snapshot()
        suggested_name = os.path.basename(current_path or f"{state.settings.project_name or 'Untitled'}.thp")
        start_dir = os.path.dirname(current_path or self.last_project_dir)
        file_path, selected_filter = QFileDialog.getSaveFileName(self, "Save Project As",
                                                                 os.path.join(start_dir, suggested_name),
                                                                 "Harvester Projects (*.thp);;JSON Files (*.json);;All Files (*)")
        if not file_path: return False
        # Ensure correct extension
        name, ext = os.path.splitext(file_path)
        if not ext.lower() in ['.thp', '.json']: file_path += ".thp"
        self.last_project_dir = os.path.dirname(file_path)
        return self._save_project_to_path(file_path)

    def _save_project_to_path(self, file_path: str) -> bool:
        """Internal helper: performs the actual save via facade."""
        self.status_manager.set_busy(True, f"Saving project to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            # Facade's save method handles setting name in state and saving
            if not self.harvester.save_project(file_path):
                raise ValueError("Facade save_project returned False (check logs).")
            # Update UI after successful save
            self.status_manager.set_status(f"Project saved: {os.path.basename(file_path)}.")
            self.save_settings()  # Save last used dir
            self.update_window_title()  # Title should now be clean
            self._update_ui_state()  # Update button states (Save should be disabled)
            return True
        except Exception as e:
            logger.error(f"Failed to save project to '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Save Project Error", f"Failed to save project:\n{e}")
            self.status_manager.set_status("Failed to save project.")
            # Keep project dirty on failure
            self.update_window_title()
            self._update_ui_state()
            return False
        finally:
            self.status_manager.set_busy(False)

    # --- Settings Persistence (Mostly unchanged, uses QSettings) ---
    def load_settings(self):
        logger.info("Loading persistent application settings...")
        # Use QCoreApplication attributes for QSettings
        settings = QSettings()  # Uses org/app names set earlier
        try:
            geom = settings.value("window_geometry")
            if geom: self.restoreGeometry(geom)
            state = settings.value("window_state")
            if state: self.restoreState(state)
            self.last_project_dir = settings.value("last_project_dir", os.path.expanduser("~"))
            self.last_edit_file_dir = settings.value("last_edit_file_dir", self.last_project_dir)
            self.last_export_dir = settings.value("last_export_dir", self.last_project_dir)
            # Load panel settings separately? Or handle through project load/new?
            # Project settings are now part of the .thp file.
            # UI-specific settings (like last dirs) are handled here.
            # We might still want to load *default* panel settings if no project is loaded.
            # panel_settings = settings.value("panel_settings", {}) # Keep if needed for defaults
            # if isinstance(panel_settings, dict): ... load into tabs ...

        except Exception as e:
            logger.error(f"Error loading QSettings: {e}", exc_info=True)
        logger.info("Settings loading complete.")

    def save_settings(self):
        logger.info("Saving persistent application settings...")
        settings = QSettings()  # Uses org/app names
        settings.setValue("window_geometry", self.saveGeometry())
        settings.setValue("window_state", self.saveState())
        settings.setValue("last_project_dir", self.last_project_dir)
        settings.setValue("last_edit_file_dir", self.last_edit_file_dir)
        settings.setValue("last_export_dir", self.last_export_dir)
        # Save panel specific UI settings *if they are not part of the project file*
        # settings.setValue("panel_settings", panel_settings) # Keep if needed
        logger.info("Window state and last directories saved.")

    # --- Window Event Handlers (Mostly unchanged) ---
    def closeEvent(self, event):
        logger.debug("Close event triggered.")
        if not self._confirm_save_if_dirty():
            event.ignore();
            return
        if self.worker_thread and self.worker_thread.isRunning():
            logger.warning("Closing while worker thread is running. Attempting to stop.")
            # Attempt graceful stop first
            self.worker_thread.stop()
            # Optionally wait a short time, but avoid blocking UI indefinitely
            # self.worker_thread.wait(500) # Wait 500ms
            # if self.worker_thread.isRunning(): # Force quit if still running
            #      logger.warning("Worker thread did not stop gracefully, terminating.")
            #      self.worker_thread.terminate()
            #      self.worker_thread.wait() # Wait for termination
        self.save_settings()
        logger.info("--- Closing TimelineHarvester Application ---")
        event.accept()

    # --- UI State Management (Using Facade and State) ---
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
        analysis_done = bool(state.edit_shots)  # If edit_shots list is populated
        sources_found = analysis_done and any(s.lookup_status == 'found' for s in state.edit_shots)
        color_plan_calculated = state.color_transfer_batch is not None and bool(state.color_transfer_batch.segments)
        online_plan_calculated = state.online_transfer_batch is not None and bool(state.online_transfer_batch.segments)
        can_calc_online = enabled and sources_found and bool(state.settings.online_output_directory) and bool(
            state.settings.output_profiles)  # Example check

        # Update Global Actions
        self.action_new_project.setEnabled(enabled)
        self.action_open_project.setEnabled(enabled)
        self.action_save_project.setEnabled(enabled and state.is_dirty and proj_path_exists)
        self.action_save_project_as.setEnabled(enabled)  # Always allow Save As
        self.action_analyze.setEnabled(enabled and files_loaded and sources_paths_set)
        self.action_calculate_color.setEnabled(enabled and sources_found)
        self.action_export_for_color.setEnabled(enabled and color_plan_calculated)
        self.action_calculate_online.setEnabled(enabled and can_calc_online)  # Use combined check
        self.action_transcode.setEnabled(enabled and online_plan_calculated)  # Requires calculated online plan

        # Update Tab Buttons
        if self.color_prep_tab:
            self.color_prep_tab.update_button_states(
                can_analyze=enabled and files_loaded and sources_paths_set,
                can_calculate=enabled and sources_found,
                can_export=enabled and color_plan_calculated
            )
        if self.online_prep_tab:
            # Update online tab buttons based on its specific pre-requisites
            self.online_prep_tab.update_button_states(
                can_analyze=False,  # Or analyze graded sources button state?
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
                # Update strategy combo if implemented in panel
                # self.project_panel.set_lookup_strategy(state.settings.source_lookup_strategy)

            # Update Color Prep Tab
            if self.color_prep_tab:
                color_settings = {
                    'color_prep_start_handles': state.settings.color_prep_start_handles,
                    'color_prep_end_handles': state.settings.color_prep_end_handles,
                    # Determine 'same handles' based on loaded values
                    'color_prep_same_handles': state.settings.color_prep_start_handles == state.settings.color_prep_end_handles,
                    'color_prep_separator': state.settings.color_prep_separator,
                    'split_gap_threshold_frames': state.settings.split_gap_threshold_frames,
                }
                self.color_prep_tab.load_tab_settings(color_settings)
                # Refresh results display using facade getter methods
                analysis_summary = self.harvester.get_edit_shots_summary()  # Pass time format if needed
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
                    # ... other online settings ...
                }
                self.online_prep_tab.load_tab_settings(online_settings)
                # TODO: Update online results display
                # analysis_summary = self.harvester.get_edit_shots_summary()
                # self.online_prep_tab.results_widget.display_analysis_summary(analysis_summary)
                # online_plan_summary = self.harvester.get_transfer_segments_summary(stage='online')
                # self.online_prep_tab.results_widget.display_plan_summary(online_plan_summary)
                # unresolved_summary = self.harvester.get_unresolved_shots_summary()
                # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)

            self.update_window_title()  # Update title reflecting loaded state
            self._update_ui_state()  # Update button enables based on new state
            logger.info("UI refreshed from facade state.")
        except Exception as e:
            logger.error(f"Error updating UI from facade state: {e}", exc_info=True)
            QMessageBox.critical(self, "UI Update Error", f"Failed to refresh UI from project state:\n{e}")

    # Syncing UI to Harvester state is now handled by individual signal slots (on_..._changed)

    # --- Task Starting Slots (Using Facade methods) ---
    @pyqtSlot()
    def start_analysis_task(self):
        if self._is_worker_busy(): return
        # Settings should already be in the facade's state via signals/slots
        state = self.harvester.get_project_state_snapshot()
        if not state.edit_files: QMessageBox.warning(self, "No Edit Files",
                                                     "Please add edit files to the list."); return
        if not state.settings.source_search_paths: QMessageBox.warning(self, "Config Missing",
                                                                       "Please add Original Source search paths in the Project Panel."); return

        # Worker now calls facade's run_source_analysis
        self._start_worker('analyze', "Analyzing files & finding sources...", {})
        # No need to mark dirty here, facade/processor handles it

    @pyqtSlot()
    def start_calculate_color_task(self):
        if self._is_worker_busy(): return
        # Settings are already in facade state
        state = self.harvester.get_project_state_snapshot()
        if not state.edit_shots or not any(s.lookup_status == 'found' for s in state.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete",
                                "Please run 'Analyze Sources' first and ensure original files were found.")
            return
        # Worker now calls facade's run_calculation
        params = {'stage': 'color'}
        self._start_worker('calculate_plan', "Calculating segments for color prep...", params)

    @pyqtSlot()
    def start_export_for_color_task(self):
        if self._is_worker_busy(): return
        # Settings are already in facade state
        state = self.harvester.get_project_state_snapshot()
        batch = state.color_transfer_batch
        if not batch or not batch.segments:
            # Provide more context if calculation failed
            error_msg = "Calculate the plan for color first."
            if batch and batch.calculation_errors:
                error_msg = f"Cannot export: Calculation failed:\n{'; '.join(batch.calculation_errors)}"
            elif batch:  # Batch exists but is empty
                error_msg = "Cannot export: The calculated plan for color is empty (no segments found)."
            QMessageBox.warning(self, "Export Error", error_msg);
            return

        proj_name = state.settings.project_name or "ColorTransfer"
        default_name = f"{proj_name}_ColorPrep.edl"
        start_dir = self.last_export_dir or os.path.dirname(
            self.harvester.get_current_project_path() or self.last_project_dir)
        file_path, selected_filter = QFileDialog.getSaveFileName(self, "Export Timeline for Color",
                                                                 os.path.join(start_dir, default_name),
                                                                 "CMX EDL (*.edl);;FCP XML (*.xml *.fcpxml);;All Files (*)")
        if not file_path: return
        self.last_export_dir = os.path.dirname(file_path)
        self.status_manager.set_busy(True, f"Exporting to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            # Call facade export method
            success = self.harvester.run_export('color', file_path)
            if success:
                self.status_manager.set_status(f"Export successful: {os.path.basename(file_path)}", temporary=False)
                QMessageBox.information(self, "Export Successful", f"Timeline exported to:\n{file_path}")
                self.save_settings()  # Save last export dir
            else:
                # Facade or exporter should have logged details
                self.status_manager.set_status("Export failed. Check logs.", temporary=False)
                QMessageBox.critical(self, "Export Failed",
                                     "Could not export timeline for color grading. Please check the application logs for details.")
        except Exception as e:
            logger.error(f"Unexpected error during color export task: {e}", exc_info=True)
            self.status_manager.set_status(f"Export Error: {e}", temporary=False)
            QMessageBox.critical(self, "Export Error", f"An unexpected error occurred during export:\n\n{e}")
        finally:
            self.status_manager.set_busy(False)

    @pyqtSlot()
    def start_calculate_online_task(self):
        if self._is_worker_busy(): return
        state = self.harvester.get_project_state_snapshot()
        # Add pre-flight checks based on facade state
        if not state.edit_shots or not any(s.lookup_status == 'found' for s in state.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete", "Please run 'Analyze Sources' first.")
            return
        if not state.settings.online_output_directory:
            QMessageBox.warning(self, "Config Missing", "Please set the Online Output Directory.");
            return
        if not state.settings.output_profiles:
            QMessageBox.warning(self, "Config Missing", "Please configure Output Profiles for Online.");
            return

        params = {'stage': 'online'}
        self._start_worker('calculate_plan', "Calculating segments for online prep...", params)

    @pyqtSlot()
    def start_transcode_task(self):
        if self._is_worker_busy(): return
        state = self.harvester.get_project_state_snapshot()
        batch = state.online_transfer_batch
        # Check if plan is ready
        if not batch or not batch.segments:
            error_msg = "Calculate the plan for online first."
            if batch and batch.calculation_errors:
                error_msg = f"Cannot transcode: Online calculation failed:\n{'; '.join(batch.calculation_errors)}"
            elif batch:
                error_msg = "Cannot transcode: The calculated online plan is empty."
            QMessageBox.warning(self, "Transcode Error", error_msg);
            return
        # Check essential settings (redundant with calculate check, but safe)
        if not state.settings.online_output_directory: QMessageBox.critical(self, "Config Error",
                                                                            "Online output directory is not set."); return
        if not state.settings.output_profiles: QMessageBox.warning(self, "Config Missing",
                                                                   "No output profiles configured for online."); return

        segment_count = len(batch.segments)
        # Calculate total files based on assigned targets (might be more accurate)
        # total_files = sum(len(seg.output_targets) for seg in batch.segments if seg.output_targets)
        # Or estimate based on profiles:
        profile_count = len(state.settings.output_profiles)
        estimated_files = segment_count * profile_count
        output_dir = state.settings.online_output_directory

        reply = QMessageBox.question(self, "Confirm Transcode",
                                     f"Start transcoding approximately {estimated_files} file(s) for the online stage to:\n"
                                     f"{output_dir}\n\n"
                                     f"This process may take a significant amount of time.\nProceed?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._start_worker('transcode', f"Starting online transcoding...", {'stage': 'online'})
        else:
            self.status_manager.set_status("Online transcoding cancelled by user.")

    # --- Worker Thread Management (Mostly unchanged, passes facade to Worker) ---
    def _start_worker(self, task_name: str, busy_message: str, params: Optional[Dict] = None):
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Another background task is already running.")
            return
        logger.info(f"Starting worker thread for task: {task_name}")
        self.status_manager.set_busy(True, busy_message)
        # *** CHANGE HERE: Pass the facade instance ***
        self.worker_thread = WorkerThread(self.harvester, task_name, params)
        # Connect signals
        self.worker_thread.analysis_finished.connect(self.on_analysis_complete)
        self.worker_thread.plan_finished.connect(self.on_plan_complete)
        self.worker_thread.transcode_finished.connect(self.on_transcode_complete)
        self.worker_thread.progress_update.connect(self.on_progress_update)
        self.worker_thread.error_occurred.connect(self.on_task_error)
        self.worker_thread.finished.connect(self.on_task_finished)  # Crucial for cleanup
        # Start the thread
        self.worker_thread.start()
        self._update_ui_state()  # Disable UI elements while worker runs

    # --- Slots Handling Worker Thread Signals (Update based on new signal args) ---
    @pyqtSlot(list, list)  # Updated signature: analysis_summary, unresolved_summary
    def on_analysis_complete(self, analysis_summary: List[Dict], unresolved_summary: List[Dict]):
        logger.info(
            f"Analysis complete signal received. Shots: {len(analysis_summary)}, Unresolved: {len(unresolved_summary)}")
        # Update results displays
        if self.color_prep_tab:
            self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        if self.online_prep_tab:
            # Update online tab results display if it shows analysis status
            # self.online_prep_tab.results_widget.display_analysis_summary(analysis_summary)
            # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
            pass
        self.status_manager.set_status(
            f"Analysis complete. Found {sum(1 for s in analysis_summary if s['status'] == 'found')} original sources.")
        # No need to set busy false here, on_task_finished handles it

    @pyqtSlot(list, list, str)  # Updated signature: plan_summary, unresolved_summary, stage
    def on_plan_complete(self, plan_summary: List[Dict], unresolved_summary: List[Dict], stage: str):
        logger.info(
            f"Plan complete signal for stage '{stage}'. Segments: {len(plan_summary)}, Unresolved: {len(unresolved_summary)}")
        # Update results display for the specific stage
        if stage == 'color' and self.color_prep_tab:
            self.color_prep_tab.results_widget.display_plan_summary(plan_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        elif stage == 'online' and self.online_prep_tab:
            # Update online tab results display
            # self.online_prep_tab.results_widget.display_plan_summary(plan_summary)
            # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
            pass
        self.status_manager.set_status(f"'{stage.capitalize()}' plan calculated ({len(plan_summary)} segments).")
        # on_task_finished handles busy state

    @pyqtSlot(bool, str)
    def on_transcode_complete(self, success: bool, message: str):
        logger.info(f"Transcode complete signal. Success: {success}, Message: {message}")
        # Update segment statuses in the UI based on the final state
        online_plan_summary = self.harvester.get_transfer_segments_summary(stage='online')
        if self.online_prep_tab:
            # self.online_prep_tab.results_widget.display_plan_summary(online_plan_summary) # Refresh online plan view
            pass

        if success:
            self.status_manager.set_status(message, temporary=False)
            QMessageBox.information(self, "Transcoding Complete", message)
        else:
            # Error should have been logged by TranscodeService or FFmpegRunner
            self.status_manager.set_status(f"Transcoding Failed: {message}. Check logs.", temporary=False)
            QMessageBox.critical(self, "Transcoding Failed",
                                 f"Transcoding process failed.\n{message}\n\nPlease check logs for details.")
        # on_task_finished handles busy state

    @pyqtSlot(int, str)
    def on_progress_update(self, percent: int, message: str):
        self.status_manager.show_progress(percent, 100, message)

    @pyqtSlot(str)
    def on_task_error(self, error_message: str):
        logger.error(f"Worker thread error signal received: {error_message}")
        self.status_manager.set_status(f"Error: {error_message}", temporary=False)
        # Display error without stack trace from worker, as worker already logged it
        QMessageBox.critical(self, "Background Task Error",
                             f"An error occurred during the background task:\n\n{error_message}\n\nPlease check logs for detailed information.")
        # on_task_finished will still be called to clean up UI state

    @pyqtSlot()
    def on_task_finished(self):
        """Called ALWAYS after worker finishes (success, error, or cancel)."""
        logger.info("Worker thread finished signal received. Cleaning up UI.")
        self.status_manager.hide_progress()
        # Check if the final status message indicates an error or cancellation
        current_status = self.status_manager.status_label.text().lower()
        is_error_or_cancel = "error" in current_status or "fail" in current_status or "cancel" in current_status
        if not is_error_or_cancel:
            # Only set to Ready if no error/cancel message is already shown
            self.status_manager.set_status("Ready.")

        self.worker_thread = None  # Clear thread reference IMPORTANT
        self._update_ui_state()  # Re-enable UI elements
        # Refresh results display one last time to show final state after task
        self._update_results_display()
        logger.info("Worker thread cleanup and UI update complete.")

    # --- Helper to refresh results ---
    def _update_results_display(self):
        """Updates all result tabs in the UI."""
        logger.debug("Refreshing results display widgets...")
        try:
            # Use facade methods to get fresh summary data
            # Pass the desired time format from UI if applicable
            time_disp_format = self.color_prep_tab.results_widget.time_format_combo.currentText() if self.color_prep_tab else "Timecode"

            analysis_summary = self.harvester.get_edit_shots_summary(time_format=time_disp_format)
            color_plan_summary = self.harvester.get_transfer_segments_summary(stage='color')
            online_plan_summary = self.harvester.get_transfer_segments_summary(stage='online')
            unresolved_summary = self.harvester.get_unresolved_shots_summary()

            if self.color_prep_tab:
                self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
                self.color_prep_tab.results_widget.display_plan_summary(color_plan_summary)
                self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
            if self.online_prep_tab:
                # self.online_prep_tab.results_widget.display_analysis_summary(analysis_summary)
                # self.online_prep_tab.results_widget.display_plan_summary(online_plan_summary)
                # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
                pass  # Update online results display
        except Exception as e:
            logger.error(f"Error refreshing results display: {e}", exc_info=True)

    # --- About Dialog (Unchanged) ---
    def show_about_dialog(self):
        QMessageBox.about(self, "About TimelineHarvester",
                          f"<h2>TimelineHarvester</h2>"
                          f"<p>Version {QCoreApplication.applicationVersion()}</p>"  # Use version from QCoreApplication
                          f"<p>Workflow tool for preparing media for color grading and online editing.</p>"
                          f"<p>(Uses OpenTimelineIO and FFmpeg/FFprobe)</p>"
                          f"<p>Qt Version: {Qt.QT_VERSION_STR}</p>")

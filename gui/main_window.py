# gui/main_window.py
"""
Main Window Module - Refactored with Tabs and Project Handling

Integrates ProjectPanel and Tab Widgets (ColorPrep, OnlinePrep).
Handles project state, background tasks via WorkerThread, and UI updates.
Connects UI actions to core TimelineHarvester logic.
"""

import logging
import os
from typing import List, Optional, Dict

from PyQt5.QtCore import QSettings, QThread, pyqtSignal, pyqtSlot, Qt
# --- PyQt5 Imports ---
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QVBoxLayout,
    QWidget, QTabWidget, QApplication
)

from core.models import EditFileMetadata
# --- Core Logic Imports ---
from core.timeline_harvester import TimelineHarvester
from .color_prep_tab import ColorPrepTabWidget
from .online_prep_tab import OnlinePrepTabWidget  # Import the placeholder
# --- GUI Component Imports (NEW STRUCTURE) ---
from .project_panel import ProjectPanel
from .status_bar import StatusBarManager

# ResultsDisplayWidget is now internal to the tab widgets
# Import models only if directly needed, e.g. for type hints
# from core.models import EditFileMetadata

logger = logging.getLogger(__name__)

# --- Worker Thread Definition (Remains the same logic as previously defined) ---
class WorkerThread(QThread):
    """Thread to run background tasks (analysis, plan, transcode) without freezing the GUI."""
    analysis_finished = pyqtSignal(list) # list of EditShot summary dicts
    plan_finished = pyqtSignal(list, str) # list of TransferSegment summary dicts, stage identifier
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
                # find_original_sources now returns tuple: (found, not_found, error)
                self.harvester.find_original_sources()
                if not self._is_running: raise InterruptedError("Task stopped.")
                summary = self.harvester.get_edit_shots_summary()
                if self._is_running: self.analysis_finished.emit(summary)

            elif self.task == 'create_plan':
                # Get parameters passed from MainWindow
                stage = self.params.get('stage', 'color')
                logger.info(f"Worker calculating plan for stage: {stage}")
                # Harvester's calculate_transfer method uses its internal state for handles etc.
                self.harvester.calculate_transfer(stage=stage) # Pass only stage
                if not self._is_running: raise InterruptedError("Task stopped.")
                # Get summary for the stage that was just calculated
                segment_summary = self.harvester.get_transfer_segments_summary(stage=stage)
                if self._is_running: self.plan_finished.emit(segment_summary, stage) # Emit summary and stage

            elif self.task == 'transcode': # Assumed Online for now
                stage = self.params.get('stage', 'online')
                if stage != 'online':
                     raise ValueError("Transcoding is currently only triggered for 'online' stage.")

                def progress_callback(current, total, message):
                    if not self._is_running:
                        # TODO: Need better way to interrupt FFmpeg process itself
                        raise InterruptedError("Transcode stopped by user request.")
                    percent = int((current / total) * 100) if total > 0 else 0
                    self.progress_update.emit(percent, message)

                # Call the specific transcoding method in harvester
                self.harvester.run_online_transcoding(progress_callback)
                if self._is_running:
                    self.transcode_finished.emit(True, "Online transcoding completed successfully.")
            else:
                raise ValueError(f"Unknown worker task: {self.task}")

            if self._is_running: logger.info(f"WorkerThread finished task: {self.task}")
        except InterruptedError:
             logger.warning(f"WorkerThread task '{self.task}' stopped by user request.")
             self.error_occurred.emit(f"Task '{self.task}' cancelled.")
        except Exception as e:
            logger.error(f"WorkerThread error during task '{self.task}': {e}", exc_info=True)
            if self._is_running:
                self.error_occurred.emit(f"Error during {self.task}: {str(e)}")


# --- Main Window Class ---
class MainWindow(QMainWindow):
    """Main application window integrating ProjectPanel and workflow tabs."""
    projectDirtyStateChanged = pyqtSignal(bool)

    def __init__(self, harvester: TimelineHarvester):
        super().__init__()
        self.harvester = harvester
        self.worker_thread: Optional[WorkerThread] = None
        # --- Project State ---
        self.current_project_path: Optional[str] = None
        self.is_project_dirty: bool = False
        # --- UI Component References ---
        self.project_panel: Optional[ProjectPanel] = None
        self.tab_widget: Optional[QTabWidget] = None
        self.color_prep_tab: Optional[ColorPrepTabWidget] = None
        self.online_prep_tab: Optional[OnlinePrepTabWidget] = None
        self.status_manager: Optional[StatusBarManager] = None
        # --- Load/Save Paths ---
        self.last_project_dir = os.path.expanduser("~")
        self.last_edit_file_dir = os.path.expanduser("~")
        self.last_export_dir = os.path.expanduser("~") # For EDL/XML export

        self.setWindowTitle("TimelineHarvester")
        self.setMinimumSize(1200, 800)

        self.init_ui()
        self.create_actions()
        self.create_menus()
        self.create_toolbar()
        self.connect_signals()

        self.load_settings() # Load persistent window/path/panel settings
        # Don't call new_project here, allow settings to potentially load a state?
        # Or call it to ensure clean start regardless of saved settings? Clean start is safer.
        self.new_project(confirm_save=False) # Start clean without prompt
        logger.info("MainWindow initialized.")

    # --- UI Creation Methods ---
    def init_ui(self):
        """Sets up the main window layout with Project Panel and Tabs."""
        self.status_manager = StatusBarManager(self.statusBar())
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5) # Consistent margins

        # 1. Project Panel (Top)
        self.project_panel = ProjectPanel()
        main_layout.addWidget(self.project_panel)

        # 2. Tab Widget (Main Area)
        self.tab_widget = QTabWidget()
        self.tab_widget.setUsesScrollButtons(True)

        # Create and add tab widgets
        self.color_prep_tab = ColorPrepTabWidget(self.harvester)
        self.online_prep_tab = OnlinePrepTabWidget(self.harvester) # Keep placeholder

        self.tab_widget.addTab(self.color_prep_tab, "1. Prepare for Color Grading")
        self.tab_widget.addTab(self.online_prep_tab, "2. Prepare for Online")
        # self.tab_widget.setTabEnabled(1, False) # Optionally disable Online tab

        main_layout.addWidget(self.tab_widget, 1) # Tabs stretch

        logger.debug("Main window UI layout created (Project Panel + Tabs).")

    def create_actions(self):
        """Creates QAction objects for menus and toolbars."""
        # Project Actions
        self.action_new_project = QAction("&New Project", self, shortcut="Ctrl+N", statusTip="Create a new project")
        self.action_open_project = QAction("&Open Project...", self, shortcut="Ctrl+O", statusTip="Open an existing project file (.thp)")
        self.action_save_project = QAction("&Save Project", self, shortcut="Ctrl+S", statusTip="Save the current project", enabled=False)
        self.action_save_project_as = QAction("Save Project &As...", self, statusTip="Save the current project to a new file")
        self.action_exit = QAction("E&xit", self, shortcut="Ctrl+Q", statusTip="Exit the application")

        # Process Actions
        self.action_analyze = QAction("&Analyze Sources", self, shortcut="F5", statusTip="Parse edit files and find original sources", enabled=False)
        self.action_calculate_color = QAction("&Calculate for Color", self, shortcut="F6", statusTip="Calculate segments needed for color grading", enabled=False)
        self.action_export_for_color = QAction("Export EDL/XML for Color...", self, statusTip="Export list for color grading", enabled=False)
        self.action_calculate_online = QAction("Calculate for &Online", self, shortcut="F7", statusTip="Calculate segments needed for online", enabled=False)
        self.action_transcode = QAction("&Transcode for Online", self, shortcut="F8", statusTip="Transcode calculated segments for online", enabled=False)

        # Help Actions
        self.action_about = QAction("&About TimelineHarvester", self)
        self.action_about.setStatusTip("Show application information")
        logger.debug("UI Actions created.")


    def create_menus(self):
        """Creates the main menu bar."""
        # File Menu
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.action_new_project)
        self.file_menu.addAction(self.action_open_project)
        self.file_menu.addAction(self.action_save_project)
        self.file_menu.addAction(self.action_save_project_as)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_exit)

        # Process Menu
        self.process_menu = self.menuBar().addMenu("&Process")
        color_menu = self.process_menu.addMenu("Color Grading Prep")
        color_menu.addAction(self.action_analyze)
        color_menu.addAction(self.action_calculate_color)
        color_menu.addAction(self.action_export_for_color)
        online_menu = self.process_menu.addMenu("Online Prep")
        # TODO: Add action for analyzing graded sources
        online_menu.addAction(self.action_calculate_online)
        online_menu.addAction(self.action_transcode)

        # Help Menu
        self.help_menu = self.menuBar().addMenu("&Help")
        self.help_menu.addAction(self.action_about)
        logger.debug("UI Menus created.")

    def create_toolbar(self):
        """Creates the main application toolbar."""
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.addAction(self.action_new_project)
        self.toolbar.addAction(self.action_open_project)
        self.toolbar.addAction(self.action_save_project)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_analyze)
        self.toolbar.addAction(self.action_calculate_color)
        self.toolbar.addAction(self.action_export_for_color)
        # self.toolbar.addAction(self.action_transcode) # Maybe less common
        logger.debug("UI Toolbar created.")

    # --- Signal/Slot Connections ---
    def connect_signals(self):
        """Connects signals and slots for UI interaction and project state."""
        # Project Actions
        self.action_new_project.triggered.connect(self.new_project)
        self.action_open_project.triggered.connect(self.open_project)
        self.action_save_project.triggered.connect(self.save_project)
        self.action_save_project_as.triggered.connect(self.save_project_as)
        self.action_exit.triggered.connect(self.close)
        self.action_about.triggered.connect(self.show_about_dialog)

        # Global Process Actions -> Slots in MainWindow
        self.action_analyze.triggered.connect(self.start_analysis_task)
        self.action_calculate_color.triggered.connect(self.start_calculate_color_task)
        self.action_export_for_color.triggered.connect(self.start_export_for_color_task)
        self.action_calculate_online.triggered.connect(self.start_calculate_online_task)
        self.action_transcode.triggered.connect(self.start_transcode_task)

        # Connect signals from ProjectPanel -> mark dirty AND update UI state
        self.project_panel.editFilesChanged.connect(self.on_project_panel_changed) # <<< FIXED: Added this connection
        self.project_panel.originalSourcePathsChanged.connect(self.on_project_panel_changed)
        self.project_panel.gradedSourcePathsChanged.connect(self.on_project_panel_changed)

        # Connect signals from Tab Widgets -> mark dirty & trigger actions from tab buttons
        self.color_prep_tab.settingsChanged.connect(self.mark_project_dirty)
        # Connect buttons inside the tab to the main window's task starters
        self.color_prep_tab.analyzeSourcesClicked.connect(self.start_analysis_task)
        self.color_prep_tab.calculateSegmentsClicked.connect(self.start_calculate_color_task)
        self.color_prep_tab.exportEdlXmlClicked.connect(self.start_export_for_color_task)

        # Connect signals from OnlinePrepTabWidget when implemented
        # self.online_prep_tab.settingsChanged.connect(self.mark_project_dirty)
        # self.online_prep_tab.analyzeGradedClicked.connect(self.start_analyze_graded_task)
        # self.online_prep_tab.calculateOnlineClicked.connect(self.start_calculate_online_task)
        # self.online_prep_tab.transcodeClicked.connect(self.start_transcode_task)

        # Internal dirty state signal -> update title/save action
        self.projectDirtyStateChanged.connect(self.update_window_title)

        logger.debug("UI Signals connected.")

    # --- Project State Management ---
    @pyqtSlot() # Mark as slot
    def mark_project_dirty(self):
        """Marks the current project as modified (unsaved changes)."""
        if not self.is_project_dirty:
            self.is_project_dirty = True
            self.projectDirtyStateChanged.emit(True)
            logger.debug("Project marked as dirty.")

    @pyqtSlot(list)
    def on_project_panel_changed(self, new_paths: list):
         """Handle path list changes from ProjectPanel - mark project dirty and update UI state."""
         # Syncing paths to harvester happens before processing, just mark dirty and update UI
         logger.debug("Project panel change detected, marking project dirty and updating UI state.")
         self.mark_project_dirty()
         self._update_ui_state() # <<< FIXED: Added call to update UI state

    @pyqtSlot(bool)
    def update_window_title(self, is_dirty: bool):
        """Updates the window title with project name and dirty indicator (*)."""
        base_title = "TimelineHarvester"
        project_name = os.path.basename(self.current_project_path) if self.current_project_path else "Untitled Project"
        dirty_indicator = " *" if is_dirty else ""
        self.setWindowTitle(f"{project_name}{dirty_indicator} - {base_title}")
        self.action_save_project.setEnabled(is_dirty) # Update Save action state


    def _confirm_save_if_dirty(self) -> bool:
        """Checks if project is dirty, prompts user to save, returns True if okay to proceed."""
        if not self.is_project_dirty:
            return True # Okay to proceed

        reply = QMessageBox.question(self, "Unsaved Changes",
                                     "The current project has unsaved changes.\n"
                                     "Do you want to save them before proceeding?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                     QMessageBox.Save) # Default to Save

        if reply == QMessageBox.Save:
            return self.save_project() # Returns True on success, False on failure/cancel
        elif reply == QMessageBox.Discard:
            logger.info("User chose to discard unsaved changes.")
            return True # Okay to proceed
        else: # Cancel
            logger.info("Operation cancelled by user (save prompt).")
            return False # User cancelled the operation

    # --- Project Actions Implementation ---
    @pyqtSlot()
    def new_project(self, confirm_save=True):
        """Clears state and starts a new project, optionally prompting to save."""
        logger.info("Action: New Project")
        if confirm_save and not self._confirm_save_if_dirty():
            logger.info("New project cancelled by user (did not save/discard).")
            return  # User cancelled save prompt

        # Clear the core logic state
        self.harvester.clear_state()
        # Reset project path info
        self.current_project_path = None
        # Reset UI elements to reflect the cleared state
        self._update_ui_from_harvester_state()  # This should call clear methods on panels

        # Set project state to clean and notify UI
        self.is_project_dirty = False
        self.projectDirtyStateChanged.emit(False)  # Emit clean state

        self.status_manager.set_status("New project created. Add edit files and configure paths.")
        logger.info("New project state initialized.")
        self._update_ui_state()  # Ensure buttons/actions reflect new state

    @pyqtSlot()
    def open_project(self):
        """Opens an existing project file (.thp/.json), prompting to save first."""
        logger.info("Action: Open Project")
        if not self._confirm_save_if_dirty():
            logger.info("Open project cancelled by user (did not save/discard).")
            return

        # --- File Dialog ---
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open TimelineHarvester Project", self.last_project_dir,
            "Harvester Projects (*.thp *.json);;All Files (*)"
        )
        if not file_path:
            self.status_manager.set_status("Open project cancelled.")
            return

        self.last_project_dir = os.path.dirname(file_path)  # Remember directory
        self.status_manager.set_busy(True, f"Loading project: {os.path.basename(file_path)}...")
        QApplication.processEvents()  # Update UI to show busy state

        # --- Load Project Logic ---
        try:
            loaded_ok = self.harvester.load_project(file_path)  # Use harvester's load method
            if not loaded_ok:
                # Error should have been logged by harvester.load_project
                raise ValueError("Harvester.load_project reported failure (check logs).")

            self.current_project_path = file_path
            # Refresh the entire UI based on the loaded harvester state
            self._update_ui_from_harvester_state()

            # Set project state to clean AFTER UI update and notify UI
            self.is_project_dirty = False
            self.projectDirtyStateChanged.emit(False)  # Emit clean state

            self.status_manager.set_status(f"Project '{os.path.basename(file_path)}' loaded.")
            logger.info(f"Successfully loaded project: {file_path}")
            self.save_settings()  # Save the updated last_project_dir

        except Exception as e:
            logger.error(f"Failed to load project file '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Load Project Error", f"Failed to load project:\n{e}")
            # Revert to a clean state after failed load
            self.new_project(confirm_save=False)  # Don't prompt again
            self.status_manager.set_status("Failed to load project.")
        finally:
            self.status_manager.set_busy(False)
            # Update UI state AFTER potential revert in case of error
            self._update_ui_state()

    @pyqtSlot()
    def save_project(self) -> bool:
        """Saves the current project. Prompts for filename if not set."""
        logger.info("Action: Save Project")
        if not self.current_project_path:
            # If project hasn't been saved before, act like Save As
            return self.save_project_as()
        else:
            # Sync UI state to harvester *before* saving
            if not self._sync_ui_to_harvester():
                logger.error("Save cancelled due to failure syncing UI state.")
                return False  # Prevent save if sync fails
            # Perform the save using the existing path
            return self._save_project_to_path(self.current_project_path)

    @pyqtSlot()
    def save_project_as(self) -> bool:
        """Prompts user for filename and saves the project."""
        logger.info("Action: Save Project As...")
        # Sync UI state to harvester *before* asking for path
        if not self._sync_ui_to_harvester():
            logger.error("Save As cancelled due to failure syncing UI state.")
            return False

        # Suggest filename and directory
        suggested_name = os.path.basename(
            self.current_project_path or f"{self.harvester.project_name or 'Untitled'}.thp")
        start_dir = os.path.dirname(self.current_project_path or self.last_project_dir)

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save TimelineHarvester Project As", os.path.join(start_dir, suggested_name),
            "Harvester Projects (*.thp);;JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            self.status_manager.set_status("Save project as cancelled.")
            return False

        # Ensure correct extension
        name, ext = os.path.splitext(file_path)
        if not ext.lower() in ['.thp', '.json']:
            if "(*.thp)" in selected_filter:
                file_path += ".thp"
            elif "(*.json)" in selected_filter:
                file_path += ".json"
            else:
                file_path += ".thp"  # Default to .thp

        self.last_project_dir = os.path.dirname(file_path)  # Update last dir used
        # Perform the save to the new path
        return self._save_project_to_path(file_path)

    def _save_project_to_path(self, file_path: str) -> bool:
        """Internal helper: performs the actual save using harvester."""
        self.status_manager.set_busy(True, f"Saving project to {os.path.basename(file_path)}...")
        QApplication.processEvents()  # Allow UI to show busy state
        try:
            # Update project name based on save filename before saving data
            # Harvester state should already be synced by save_project/save_project_as
            self.harvester.project_name = os.path.splitext(os.path.basename(file_path))[0]

            saved_ok = self.harvester.save_project(file_path)  # Call harvester's save method
            if not saved_ok:
                # Error should have been logged by harvester.save_project
                raise ValueError("Harvester.save_project reported failure (check logs).")

            self.current_project_path = file_path  # Update current path after successful save
            # Set state to clean and notify UI AFTER successful save
            self.is_project_dirty = False
            self.projectDirtyStateChanged.emit(False)

            self.status_manager.set_status(f"Project saved: {os.path.basename(file_path)}.")
            # Window title is updated automatically by the emitted signal connected to update_window_title
            logger.info(f"Project successfully saved to: {file_path}")
            self.save_settings()  # Save updated last_project_dir path to persistent settings
            return True

        except Exception as e:
            logger.error(f"Failed to save project to '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Save Project Error", f"Failed to save project:\n{e}")
            self.status_manager.set_status("Failed to save project.")
            # Should remain dirty if save failed
            self.mark_project_dirty()  # Use the slot to ensure dirty state is set correctly
            return False
        finally:
            self.status_manager.set_busy(False)
            self._update_ui_state()  # Update button states after save attempt

    # --- Settings Persistence ---
    def load_settings(self):
        """Loads persistent UI settings (window state, paths, last panel states)."""
        logger.info("Loading persistent application settings...")
        settings = QSettings("TimelineHarvesterOrg", "TimelineHarvester")
        try:
            # Restore window geometry and state
            geom = settings.value("window_geometry")
            if geom: self.restoreGeometry(geom)
            state = settings.value("window_state")
            if state: self.restoreState(state)

            # Restore last used directories
            self.last_project_dir = settings.value("last_project_dir", os.path.expanduser("~"))
            self.last_edit_file_dir = settings.value("last_edit_file_dir", self.last_project_dir)
            self.last_export_dir = settings.value("last_export_dir", self.last_project_dir)

            # Load settings into the Panel Widgets
            panel_settings_dict = settings.value("panel_settings", {})
            if isinstance(panel_settings_dict, dict):
                self.project_panel.load_panel_settings(panel_settings_dict.get("project_panel", {}))
                self.color_prep_tab.load_tab_settings(panel_settings_dict.get("color_prep_tab", {}))
                # self.online_prep_tab.load_tab_settings(panel_settings_dict.get("online_prep_tab", {})) # Uncomment later
                logger.info("Panel settings loaded from QSettings.")
            else:
                logger.warning("Could not load valid dictionary for panel_settings from QSettings.")
        except Exception as e:
             logger.error(f"Error loading persistent settings: {e}", exc_info=True)
        logger.info("Window settings loading complete.")


    def save_settings(self):
        """Saves persistent UI settings."""
        logger.info("Saving persistent application settings...")
        settings = QSettings("TimelineHarvesterOrg", "TimelineHarvester")
        settings.setValue("window_geometry", self.saveGeometry())
        settings.setValue("window_state", self.saveState())
        settings.setValue("last_project_dir", self.last_project_dir)
        settings.setValue("last_edit_file_dir", self.last_edit_file_dir)
        settings.setValue("last_export_dir", self.last_export_dir)

        try:
            panel_settings_dict = {
                "project_panel": self.project_panel.get_panel_settings(),
                "color_prep_tab": self.color_prep_tab.get_tab_settings(),
                # "online_prep_tab": self.online_prep_tab.get_tab_settings() # Uncomment later
            }
            settings.setValue("panel_settings", panel_settings_dict)
            logger.info("Window and panel settings saved.")
        except Exception as e:
             logger.error(f"Error retrieving settings from panels for saving: {e}", exc_info=True)


    # --- Window Event Handlers ---
    def closeEvent(self, event):
        """Handles the window close event."""
        logger.debug("Close event triggered.")
        if not self._confirm_save_if_dirty():
            event.ignore() # User cancelled, prevent closing
            return
        # If we are here, user either saved, discarded, or there were no changes
        # Proceed with closing
        if self.worker_thread and self.worker_thread.isRunning():
             logger.warning("Attempting to close application while worker thread is running.")
             self.worker_thread.stop() # Request stop
             # Give it a very short time to potentially finish current step cleanly
             # self.worker_thread.wait(200) # Don't wait long
        self.save_settings() # Save window state etc.
        logger.info("--- Closing TimelineHarvester Application ---")
        event.accept()


    # --- UI State Management ---
    def _update_ui_initial_state(self):
        """Sets the initial enabled state after startup or new project."""
        self.is_project_dirty = False # Start clean
        self.projectDirtyStateChanged.emit(False)
        self._update_ui_state()

    def _update_ui_state(self):
        """Updates the enabled state of all actions/buttons based on current project state."""
        is_busy = self.worker_thread is not None and self.worker_thread.isRunning()
        enabled = not is_busy

        # Get logical state from UI panels (before potential sync) and harvester results
        # Check UI panels directly for prerequisites of actions
        files_loaded = bool(self.project_panel.get_edit_files()) if self.project_panel else False
        sources_paths_set = bool(self.project_panel.get_original_search_paths()) if self.project_panel else False

        # Check harvester results for dependent actions
        analysis_done = bool(self.harvester.edit_shots)
        sources_found = analysis_done and any(s.lookup_status == 'found' for s in self.harvester.edit_shots)
        color_plan_calculated = self.harvester.color_transfer_batch is not None and bool(self.harvester.color_transfer_batch.segments)
        online_plan_calculated = self.harvester.online_transfer_batch is not None and bool(self.harvester.online_transfer_batch.segments)
        can_calc_online = enabled and sources_found # Placeholder: Needs check for graded sources analysis result

        # Update Global Actions
        self.action_new_project.setEnabled(enabled)
        self.action_open_project.setEnabled(enabled)
        self.action_save_project.setEnabled(enabled and self.is_project_dirty)
        self.action_save_project_as.setEnabled(enabled)
        self.action_analyze.setEnabled(enabled and files_loaded and sources_paths_set) # <<< FIXED: Use panel state
        self.action_calculate_color.setEnabled(enabled and sources_found)
        self.action_export_for_color.setEnabled(enabled and color_plan_calculated)
        self.action_calculate_online.setEnabled(enabled and can_calc_online) # Placeholder
        self.action_transcode.setEnabled(enabled and online_plan_calculated) # Placeholder

        # Delegate state updates to Tab Widgets (ensure they exist)
        if self.color_prep_tab:
            self.color_prep_tab.update_button_states(
                can_analyze=enabled and files_loaded and sources_paths_set, # <<< FIXED: Use panel state
                can_calculate=enabled and sources_found,
                can_export=enabled and color_plan_calculated
            )
        if self.online_prep_tab:
            self.online_prep_tab.update_button_states( # Update placeholder tab too
                can_analyze=False, # Placeholder logic
                can_calculate=enabled and can_calc_online, # Placeholder
                can_transcode=enabled and online_plan_calculated # Placeholder
            )
        logger.debug(f"UI actions/buttons state updated (Busy: {is_busy}, Files: {files_loaded}, Paths: {sources_paths_set}, Found: {sources_found}, ColorPlan: {color_plan_calculated})")


    def _is_worker_busy(self) -> bool:
        """Checks if the worker thread is active and shows a message."""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "A background task is currently running.\nPlease wait.")
            return True
        return False

    def _update_ui_from_harvester_state(self):
         """Refreshes the entire UI based on the current state of self.harvester after loading."""
         logger.info("Updating UI from harvester state...")
         try:
             # 1. Update Project Panel
             if self.project_panel:
                 self.project_panel.set_edit_files([f.path for f in self.harvester.edit_files])
                 self.project_panel.set_original_search_paths(self.harvester.source_search_paths)
                 self.project_panel.set_graded_search_paths(self.harvester.graded_source_search_paths)

             # 2. Update Color Prep Tab
             if self.color_prep_tab:
                 color_settings = {
                     'color_prep_start_handles': self.harvester.color_prep_start_handles,
                     'color_prep_end_handles': self.harvester.color_prep_end_handles,
                     # Infer checkbox state based on whether handles are equal
                     'color_prep_same_handles': self.harvester.color_prep_start_handles == self.harvester.color_prep_end_handles,
                     'color_prep_separator': self.harvester.color_prep_separator,
                     }
                 self.color_prep_tab.load_tab_settings(color_settings)
                 analysis_summary = self.harvester.get_edit_shots_summary()
                 self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
                 color_plan_summary = self.harvester.get_transfer_segments_summary(stage='color')
                 self.color_prep_tab.results_widget.display_plan_summary(color_plan_summary)
                 unresolved_summary = self.harvester.get_unresolved_shots_summary()
                 self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)

             # 3. Update Online Prep Tab (When implemented fully)
             if self.online_prep_tab:
                 online_settings = {
                     'online_prep_handles': self.harvester.online_prep_handles,
                     'output_profiles': [p.__dict__ for p in self.harvester.output_profiles],
                     'online_output_directory': self.harvester.online_output_directory,
                     'online_target_resolution': self.harvester.online_target_resolution,
                     'online_analyze_transforms': self.harvester.online_analyze_transforms
                 }
                 self.online_prep_tab.load_tab_settings(online_settings)
                 # TODO: Update online results display

             # 4. Update overall UI state and window title
             self._update_ui_state()
             self.update_window_title(self.is_project_dirty) # Reflect loaded dirty state (should be false)
             logger.info("UI refreshed from harvester state.")
         except Exception as e:
              logger.error(f"Error updating UI from harvester state: {e}", exc_info=True)
              QMessageBox.critical(self, "UI Update Error", f"Failed to refresh UI after loading project:\n{e}")


    def _sync_ui_to_harvester(self) -> bool:
        """Gathers current settings from UI panels and updates harvester's config attributes."""
        logger.debug("Syncing UI settings to harvester state...")
        if not self.project_panel or not self.color_prep_tab or not self.online_prep_tab:
             logger.error("Cannot sync UI to harvester: UI panels not initialized.")
             return False
        try:
             # Project Panel -> Harvester config
             proj_panel_settings = self.project_panel.get_panel_settings()
             # Update harvester's list of file paths (don't recreate EditFileMetadata objects here)
             self.harvester.edit_files = [EditFileMetadata(p) for p in proj_panel_settings.get("edit_files",[])]
             # Use setters for paths and strategy to potentially trigger finder reset
             self.harvester.set_source_search_paths(proj_panel_settings.get("original_search_paths", []))
             self.harvester.set_graded_source_search_paths(proj_panel_settings.get("graded_search_paths", []))
             # TODO: Get strategy from Project Panel UI if added
             # self.harvester.set_source_lookup_strategy(...)

             # Color Prep Tab -> Harvester config
             color_settings = self.color_prep_tab.get_tab_settings()
             self.harvester.set_color_prep_handles( # Use setters to handle logic
                 color_settings.get("color_prep_start_handles", 24),
                 color_settings.get("color_prep_end_handles", 24)
             )
             self.harvester.set_color_prep_separator(color_settings.get("color_prep_separator", 0))

             # Online Prep Tab -> Harvester config (When implemented)
             # online_settings = self.online_prep_tab.get_tab_settings()
             # self.harvester.set_online_prep_handles(...)
             # self.harvester.set_output_profiles(...)
             # self.harvester.set_online_output_directory(...)
             # ... other online settings ...

             logger.debug("Harvester state updated from UI settings.")
             return True
        except Exception as e:
             logger.error(f"Failed to sync UI settings to harvester: {e}", exc_info=True)
             QMessageBox.critical(self, "Internal Error", "Failed to gather current settings from UI panels.")
             return False


    # --- Task Starting Slots ---
    @pyqtSlot()
    def start_analysis_task(self):
        """Configures harvester from ProjectPanel and starts 'analyze' task."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return # Sync first

        # Check prerequisites again after sync
        if not self.harvester.edit_files:
            QMessageBox.warning(self, "No Edit Files", "Please add edit files in the Project Panel.")
            return
        if not self.harvester.source_search_paths:
            QMessageBox.warning(self, "Config Missing", "Please add Original Source Search Paths in the Project Panel.")
            return

        self._start_worker('analyze', "Analyzing files & finding sources...", {}) # Use the helper
        self.mark_project_dirty() # Analysis results change project state

    @pyqtSlot()
    def start_calculate_color_task(self):
        """Starts the 'create_plan' task specifically for color prep."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return # Sync first

        if not self.harvester.edit_shots or not any(s.lookup_status == 'found' for s in self.harvester.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete", "Run 'Analyze Sources' first & ensure originals were found.")
            return

        params = {'stage': 'color'} # Harvester uses its internal state for handles
        self._start_worker('create_plan', "Calculating segments for color prep...", params) # Use the helper
        self.mark_project_dirty()

    @pyqtSlot()
    def start_export_for_color_task(self):
        """Starts the export process for the color prep EDL/XML."""
        if self._is_worker_busy(): return
        # Sync needed? Probably not critical just for export, but safer.
        if not self._sync_ui_to_harvester(): return

        batch_to_export = self.harvester.color_transfer_batch
        if not batch_to_export or not batch_to_export.segments:
             QMessageBox.warning(self, "Export Error", "Calculate the transfer plan for color first.")
             return

        # Get separator value from harvester state (synced from UI)
        separator_frames = self.harvester.color_prep_separator

        # --- File Dialog ---
        proj_name_part = self.harvester.project_name or os.path.splitext(os.path.basename(self.current_project_path or "Untitled"))[0] or "ColorTransfer"
        default_filename = f"{proj_name_part}_ColorPrep.edl"
        start_dir = self.last_export_dir or os.path.dirname(self.current_project_path or os.path.expanduser("~"))
        default_path = os.path.join(start_dir, default_filename)

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Timeline for Color Grading", default_path,
            "CMX 3600 EDL (*.edl);;Final Cut Pro XML (*.xml *.fcpxml);;All Files (*)"
        )
        if not file_path: return

        self.last_export_dir = os.path.dirname(file_path)

        self.status_manager.set_busy(True, f"Exporting to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            from core.exporter import export_transfer_batch
            success = export_transfer_batch(
                batch_to_export, file_path, separator_frames=separator_frames
            )
            if success:
                self.status_manager.set_status(f"Export successful: {os.path.basename(file_path)}", temporary=False)
                QMessageBox.information(self, "Export Successful", f"Timeline exported to:\n{file_path}")
                self.save_settings() # Save updated last_export_dir
            else:
                self.status_manager.set_status("Export failed. Check logs.", temporary=False)
                QMessageBox.critical(self, "Export Failed", "Could not export the timeline. Check logs.")
        except Exception as e:
            logger.error(f"Unexpected error during export: {e}", exc_info=True)
            self.status_manager.set_status(f"Export Error: {e}", temporary=False)
            QMessageBox.critical(self, "Export Error", f"An unexpected error occurred during export:\n\n{e}")
        finally:
            self.status_manager.set_busy(False)


    @pyqtSlot()
    def start_calculate_online_task(self):
         """Placeholder for starting online calculation."""
         if self._is_worker_busy(): return
         # TODO: Sync UI, Check prerequisites (graded sources analyzed?)
         logger.warning("Calculate for Online functionality not implemented.")
         QMessageBox.information(self, "Not Implemented", "Calculating segments for online prep is not yet implemented.")
         # params = {'stage': 'online'}
         # self._start_worker('create_plan', "Calculating segments for online...", params)
         # self.mark_project_dirty()

    @pyqtSlot()
    def start_transcode_task(self):
        """Starts the 'transcode' task (Online prep) after confirmation."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return # Sync settings like profiles/output dir

        batch_to_run = self.harvester.online_transfer_batch
        if not batch_to_run or not batch_to_run.segments:
            QMessageBox.warning(self, "No Plan", "Calculate the ONLINE transfer plan first.")
            return
        if not batch_to_run.output_directory or not os.path.isdir(batch_to_run.output_directory):
            QMessageBox.critical(self, "Config Error", "Online output directory is invalid or not set.\nPlease configure it in the 'Online Prep' tab.")
            return
        if not batch_to_run.output_profiles_used:
            QMessageBox.warning(self, "Config Missing", "No output profiles are defined for the online batch.\nPlease configure them in the 'Online Prep' tab.")
            return

        # --- Confirmation dialog ---
        segment_count = len(batch_to_run.segments)
        profile_count = len(batch_to_run.output_profiles_used)
        total_files = segment_count * profile_count # This might be inaccurate if segments fail early
        output_dir = batch_to_run.output_directory
        reply = QMessageBox.question(self,"Confirm Transcode",
             f"This will start transcoding approximately {total_files} file(s) "
             f"using the online preparation plan.\n\n"
             f"Output Directory:\n{output_dir}\n\n"
             "Proceed?",
             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._start_worker('transcode', f"Starting online transcoding ({total_files} potential files)...", {'stage': 'online'}) # Use the helper
        else:
            self.status_manager.set_status("Online transcoding cancelled.")


    # --- Worker Thread Management ---

    def _start_worker(self, task_name: str, busy_message: str, params: Optional[Dict] = None):
        """Creates, configures, and starts the WorkerThread for a given task."""
        if self.worker_thread and self.worker_thread.isRunning():
            logger.warning(f"Attempted to start task '{task_name}' while another is running.")
            QMessageBox.warning(self, "Busy", "Another background task is already running.")
            return

        logger.info(f"Starting worker thread for task: {task_name}")
        self.status_manager.set_busy(True, busy_message)
        self.worker_thread = WorkerThread(self.harvester, task_name, params)

        # Connect signals from the thread to slots in MainWindow
        self.worker_thread.analysis_finished.connect(self.on_analysis_complete)
        self.worker_thread.plan_finished.connect(self.on_plan_complete)
        self.worker_thread.transcode_finished.connect(self.on_transcode_complete)
        self.worker_thread.progress_update.connect(self.on_progress_update)
        self.worker_thread.error_occurred.connect(self.on_task_error)
        self.worker_thread.finished.connect(self.on_task_finished) # Crucial for cleanup

        self.worker_thread.start()
        self._update_ui_state() # Disable UI elements while worker runs

    # --- Slots Handling Worker Thread Signals ---
    @pyqtSlot(list)
    def on_analysis_complete(self, analysis_summary: List[Dict]):
        """Handles successful completion of the 'analyze' task."""
        # Update results in the appropriate tab's display widget
        if self.color_prep_tab:
            self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
            unresolved_summary = self.harvester.get_unresolved_shots_summary() # Get latest from harvester
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        # TODO: Also update online_prep_tab results if needed
        found_count = len(analysis_summary) - len(unresolved_summary) if analysis_summary else 0
        logger.info(f"Analysis task completed signal received. Shots processed: {len(analysis_summary)}. Found: {found_count}")
        # Actual UI state update happens in on_task_finished

    @pyqtSlot(list, str) # Added stage argument
    def on_plan_complete(self, plan_summary: List[Dict], stage: str):
        """Handles successful completion of the 'create_plan' task."""
        logger.info(f"Plan calculation for stage '{stage}' completed signal received. Segments: {len(plan_summary)}")
        unresolved_summary = self.harvester.get_unresolved_shots_summary() # Get latest unresolved
        # Update the correct tab
        if stage == 'color' and self.color_prep_tab:
            self.color_prep_tab.results_widget.display_plan_summary(plan_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        elif stage == 'online' and self.online_prep_tab:
             # TODO: Update online tab results
             # self.online_prep_tab.results_widget.display_plan_summary(plan_summary)
             # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
             pass
        # Actual UI state update happens in on_task_finished

    @pyqtSlot(bool, str)
    def on_transcode_complete(self, success: bool, message: str):
        """Handles completion of 'transcode' task (Online Prep)."""
        logger.info(f"Transcoding task finished signal received. Success: {success}")
        if success:
            self.status_manager.set_status(message, temporary=False)
            QMessageBox.information(self, "Transcoding Complete", message)
        else:
            # Error should already be logged by runner, message contains summary
            self.status_manager.set_status(f"Transcoding Failed: {message}", temporary=False)
            QMessageBox.critical(self, "Transcoding Failed", f"Transcoding process failed.\nCheck logs for details.\n\nError summary: {message}")
        # TODO: Update status display in Online Prep Tab results
        # Actual UI state update happens in on_task_finished

    @pyqtSlot(int, str)
    def on_progress_update(self, percent: int, message: str):
        """Handles progress updates from worker."""
        self.status_manager.show_progress(percent, 100, message)

    @pyqtSlot(str)
    def on_task_error(self, error_message: str):
        """Handles unexpected errors propagated from the worker thread."""
        logger.error(f"Received error signal from worker thread: {error_message}")
        self.status_manager.set_status(f"Error: {error_message}", temporary=False)
        QMessageBox.critical(self, "Background Task Error", error_message)
        # Actual UI state update happens in on_task_finished

    @pyqtSlot()
    def on_task_finished(self):
        """Called ALWAYS after worker finishes. Cleans up and re-enables UI."""
        logger.info("Worker thread finished signal received. Cleaning up.")
        self.status_manager.hide_progress()
        # Check if status wasn't already set to a final state (error/success)
        current_status = self.status_manager.status_label.text()
        final_prefixes = ["Error:", "Failed:", "Completed", "cancelled", "complete", "exported", "Analysis complete", "Plan calculated", "Project saved", "Project loaded", "Task '"]
        is_final_status = any(current_status.startswith(prefix) for prefix in final_prefixes) or "cancelled" in current_status.lower()

        if not is_final_status:
             self.status_manager.set_status("Ready.") # Set "Ready" only if no specific result was shown

        self.worker_thread = None # <<< IMPORTANT: Clear the thread reference
        self._update_ui_state() # Re-enable/disable based on current state
        logger.info("Worker thread cleanup and UI state update complete.")


    # --- About Dialog ---
    def show_about_dialog(self):
        QMessageBox.about(self, "About TimelineHarvester",
                          "<h2>TimelineHarvester</h2>"
                          "<p>Version 1.1 (Tabs)</p>"
                          "<p>Workflow tool for preparing media for color grading and online editing.</p>"
                          "<p>(Uses OpenTimelineIO and FFmpeg/FFprobe)</p>")
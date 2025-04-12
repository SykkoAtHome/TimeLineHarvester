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
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QVBoxLayout,
    QWidget, QTabWidget, QApplication
)

from core.models import EditFileMetadata
from core.timeline_harvester import TimelineHarvester
from .color_prep_tab import ColorPrepTabWidget
from .online_prep_tab import OnlinePrepTabWidget
from .project_panel import ProjectPanel
from .status_bar import StatusBarManager

logger = logging.getLogger(__name__)

# --- Worker Thread Definition (No changes needed here) ---
class WorkerThread(QThread):
    analysis_finished = pyqtSignal(list)
    plan_finished = pyqtSignal(list, str)
    transcode_finished = pyqtSignal(bool, str)
    progress_update = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)
    # ... (init, stop, run methods as before) ...
    def __init__(self, harvester: TimelineHarvester, task: str, params: Optional[Dict] = None):
        super().__init__()
        self.harvester = harvester
        self.task = task
        self.params = params if params else {}
        self._is_running = True
        logger.info(f"WorkerThread initialized for task: {self.task}")

    def stop(self):
        self._is_running = False
        logger.info(f"Stop requested for worker thread task: {self.task}")

    def run(self):
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
                stage = self.params.get('stage', 'color')
                logger.info(f"Worker calculating plan for stage: {stage}")
                self.harvester.calculate_transfer(stage=stage) # Harvester uses internal state
                if not self._is_running: raise InterruptedError("Task stopped.")
                segment_summary = self.harvester.get_transfer_segments_summary(stage=stage)
                unresolved_summary = self.harvester.get_unresolved_shots_summary() # Also get unresolved
                # Emit both summaries? Or handle unresolved display differently?
                # For now, just emit plan summary, main thread can get unresolved if needed
                if self._is_running: self.plan_finished.emit(segment_summary, stage)
            elif self.task == 'transcode':
                stage = self.params.get('stage', 'online')
                if stage != 'online': raise ValueError("Transcoding only for 'online' stage.")
                def progress_callback(current, total, message):
                    if not self._is_running: raise InterruptedError("Transcode stopped.")
                    percent = int((current / total) * 100) if total > 0 else 0
                    self.progress_update.emit(percent, message)
                self.harvester.run_online_transcoding(progress_callback)
                if self._is_running: self.transcode_finished.emit(True, "Online transcoding completed.")
            else: raise ValueError(f"Unknown worker task: {self.task}")
            if self._is_running: logger.info(f"WorkerThread finished task: {self.task}")
        except InterruptedError:
             logger.warning(f"WorkerThread task '{self.task}' stopped by user.")
             self.error_occurred.emit(f"Task '{self.task}' cancelled.")
        except Exception as e:
            logger.error(f"WorkerThread error during task '{self.task}': {e}", exc_info=True)
            if self._is_running: self.error_occurred.emit(f"Error during {self.task}: {str(e)}")


# --- Main Window Class ---
class MainWindow(QMainWindow):
    """Main application window integrating ProjectPanel and workflow tabs."""
    projectDirtyStateChanged = pyqtSignal(bool)

    def __init__(self, harvester: TimelineHarvester):
        super().__init__()
        self.harvester = harvester
        self.worker_thread: Optional[WorkerThread] = None
        self.current_project_path: Optional[str] = None
        self.is_project_dirty: bool = False
        self.project_panel: Optional[ProjectPanel] = None
        self.tab_widget: Optional[QTabWidget] = None
        self.color_prep_tab: Optional[ColorPrepTabWidget] = None
        self.online_prep_tab: Optional[OnlinePrepTabWidget] = None
        self.status_manager: Optional[StatusBarManager] = None
        self.last_project_dir = os.path.expanduser("~")
        self.last_edit_file_dir = os.path.expanduser("~")
        self.last_export_dir = os.path.expanduser("~")

        self.setWindowTitle("TimelineHarvester")
        self.setMinimumSize(1200, 800)
        self.init_ui()
        self.create_actions()
        self.create_menus()
        self.create_toolbar()
        self.connect_signals()
        self.load_settings()
        self.new_project(confirm_save=False)
        logger.info("MainWindow initialized.")

    # --- UI Creation Methods ---
    def init_ui(self):
        """Sets up the main window layout with Project Panel and Tabs."""
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
        logger.debug("Main window UI layout created.")

    def create_actions(self):
        """Creates QAction objects for menus and toolbars."""
        self.action_new_project = QAction("&New Project", self, shortcut="Ctrl+N", statusTip="Create a new project")
        self.action_open_project = QAction("&Open Project...", self, shortcut="Ctrl+O", statusTip="Open an existing project file (.thp)")
        self.action_save_project = QAction("&Save Project", self, shortcut="Ctrl+S", statusTip="Save the current project", enabled=False)
        self.action_save_project_as = QAction("Save Project &As...", self, statusTip="Save the current project to a new file")
        self.action_exit = QAction("E&xit", self, shortcut="Ctrl+Q", statusTip="Exit the application")
        self.action_analyze = QAction("&Analyze Sources", self, shortcut="F5", statusTip="Parse edit files and find original sources", enabled=False)
        self.action_calculate_color = QAction("&Calculate for Color", self, shortcut="F6", statusTip="Calculate segments needed for color grading", enabled=False)
        self.action_export_for_color = QAction("Export EDL/XML for Color...", self, statusTip="Export list for color grading", enabled=False)
        self.action_calculate_online = QAction("Calculate for &Online", self, shortcut="F7", statusTip="Calculate segments needed for online", enabled=False)
        self.action_transcode = QAction("&Transcode for Online", self, shortcut="F8", statusTip="Transcode calculated segments for online", enabled=False)
        self.action_about = QAction("&About TimelineHarvester", self, statusTip="Show application information")
        logger.debug("UI Actions created.")

    def create_menus(self):
        """Creates the main menu bar."""
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
        # Global Process Actions
        self.action_analyze.triggered.connect(self.start_analysis_task)
        self.action_calculate_color.triggered.connect(self.start_calculate_color_task)
        self.action_export_for_color.triggered.connect(self.start_export_for_color_task)
        self.action_calculate_online.triggered.connect(self.start_calculate_online_task)
        self.action_transcode.triggered.connect(self.start_transcode_task)
        # ProjectPanel -> MainWindow
        self.project_panel.editFilesChanged.connect(self.on_project_panel_changed)
        self.project_panel.originalSourcePathsChanged.connect(self.on_project_panel_changed)
        self.project_panel.gradedSourcePathsChanged.connect(self.on_project_panel_changed)
        # ColorPrepTab -> MainWindow
        self.color_prep_tab.settingsChanged.connect(self.mark_project_dirty)
        self.color_prep_tab.analyzeSourcesClicked.connect(self.start_analysis_task)
        self.color_prep_tab.calculateSegmentsClicked.connect(self.start_calculate_color_task)
        self.color_prep_tab.exportEdlXmlClicked.connect(self.start_export_for_color_task)
        # OnlinePrepTab -> MainWindow (Placeholders)
        # self.online_prep_tab.settingsChanged.connect(self.mark_project_dirty)
        # ... connect other online tab signals ...
        # Internal Dirty State -> Window Title
        self.projectDirtyStateChanged.connect(self.update_window_title)
        logger.debug("UI Signals connected.")

    # --- Project State Management ---
    @pyqtSlot()
    def mark_project_dirty(self):
        """Marks the current project as modified."""
        if not self.is_project_dirty:
            self.is_project_dirty = True
            self.projectDirtyStateChanged.emit(True)
            logger.debug("Project marked as dirty.")

    @pyqtSlot(list)
    def on_project_panel_changed(self, new_paths: list):
         """Handles path list changes from ProjectPanel."""
         logger.debug("Project panel change detected, marking dirty & updating UI state.")
         self.mark_project_dirty()
         self._update_ui_state()

    @pyqtSlot(bool)
    def update_window_title(self, is_dirty: bool):
        """Updates the window title with project name and dirty indicator."""
        base_title = "TimelineHarvester"
        project_name = os.path.basename(self.current_project_path) if self.current_project_path else "Untitled Project"
        dirty_indicator = " *" if is_dirty else ""
        self.setWindowTitle(f"{project_name}{dirty_indicator} - {base_title}")
        self.action_save_project.setEnabled(is_dirty)

    def _confirm_save_if_dirty(self) -> bool:
        """Checks if dirty, prompts to save, returns True if okay to proceed."""
        if not self.is_project_dirty: return True
        reply = QMessageBox.question(self, "Unsaved Changes", "Save changes before proceeding?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if reply == QMessageBox.Save: return self.save_project()
        elif reply == QMessageBox.Discard: return True
        else: return False # Cancel

    # --- Project Actions Implementation ---
    @pyqtSlot()
    def new_project(self, confirm_save=True):
        """Starts a new project."""
        logger.info("Action: New Project")
        if confirm_save and not self._confirm_save_if_dirty(): return
        self.harvester.clear_state()
        self.current_project_path = None
        self._update_ui_from_harvester_state() # Clears panels via harvester state
        self.is_project_dirty = False
        self.projectDirtyStateChanged.emit(False)
        self.status_manager.set_status("New project created.")
        self._update_ui_state()

    @pyqtSlot()
    def open_project(self):
        """Opens an existing project file."""
        logger.info("Action: Open Project")
        if not self._confirm_save_if_dirty(): return
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Project", self.last_project_dir, "Harvester Projects (*.thp *.json);;All Files (*)")
        if not file_path: return
        self.last_project_dir = os.path.dirname(file_path)
        self.status_manager.set_busy(True, f"Loading project: {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            if not self.harvester.load_project(file_path):
                 raise ValueError("Harvester load_project failed (check logs).")
            self.current_project_path = file_path
            self._update_ui_from_harvester_state()
            self.is_project_dirty = False
            self.projectDirtyStateChanged.emit(False)
            self.status_manager.set_status(f"Project '{os.path.basename(file_path)}' loaded.")
            self.save_settings()
        except Exception as e:
            logger.error(f"Failed to load project '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Load Project Error", f"Failed to load project:\n{e}")
            self.new_project(confirm_save=False) # Revert to clean state
            self.status_manager.set_status("Failed to load project.")
        finally:
            self.status_manager.set_busy(False)
            self._update_ui_state()

    @pyqtSlot()
    def save_project(self) -> bool:
        """Saves the current project."""
        logger.info("Action: Save Project")
        if not self.current_project_path: return self.save_project_as()
        if not self._sync_ui_to_harvester(): return False
        return self._save_project_to_path(self.current_project_path)

    @pyqtSlot()
    def save_project_as(self) -> bool:
        """Prompts for filename and saves the project."""
        logger.info("Action: Save Project As...")
        if not self._sync_ui_to_harvester(): return False
        suggested_name = os.path.basename(self.current_project_path or f"{self.harvester.project_name or 'Untitled'}.thp")
        start_dir = os.path.dirname(self.current_project_path or self.last_project_dir)
        file_path, selected_filter = QFileDialog.getSaveFileName(self, "Save Project As", os.path.join(start_dir, suggested_name), "Harvester Projects (*.thp);;JSON Files (*.json);;All Files (*)")
        if not file_path: return False
        name, ext = os.path.splitext(file_path)
        if not ext.lower() in ['.thp', '.json']: file_path += ".thp" # Default extension
        self.last_project_dir = os.path.dirname(file_path)
        return self._save_project_to_path(file_path)

    def _save_project_to_path(self, file_path: str) -> bool:
        """Internal helper: performs the actual save."""
        self.status_manager.set_busy(True, f"Saving project to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            self.harvester.project_name = os.path.splitext(os.path.basename(file_path))[0]
            if not self.harvester.save_project(file_path):
                 raise ValueError("Harvester save_project failed (check logs).")
            self.current_project_path = file_path
            self.is_project_dirty = False
            self.projectDirtyStateChanged.emit(False)
            self.status_manager.set_status(f"Project saved: {os.path.basename(file_path)}.")
            self.save_settings()
            return True
        except Exception as e:
            logger.error(f"Failed to save project to '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Save Project Error", f"Failed to save project:\n{e}")
            self.status_manager.set_status("Failed to save project.")
            self.mark_project_dirty() # Remain dirty
            return False
        finally:
            self.status_manager.set_busy(False)
            self._update_ui_state()

    # --- Settings Persistence ---
    def load_settings(self):
        """Loads persistent UI settings."""
        logger.info("Loading persistent application settings...")
        settings = QSettings("TimelineHarvesterOrg", "TimelineHarvester")
        try:
            geom = settings.value("window_geometry")
            if geom: self.restoreGeometry(geom)
            state = settings.value("window_state")
            if state: self.restoreState(state)
            self.last_project_dir = settings.value("last_project_dir", os.path.expanduser("~"))
            self.last_edit_file_dir = settings.value("last_edit_file_dir", self.last_project_dir)
            self.last_export_dir = settings.value("last_export_dir", self.last_project_dir)
            panel_settings = settings.value("panel_settings", {})
            if isinstance(panel_settings, dict):
                 if self.project_panel: self.project_panel.load_panel_settings(panel_settings.get("project_panel", {}))
                 if self.color_prep_tab: self.color_prep_tab.load_tab_settings(panel_settings.get("color_prep_tab", {}))
                 if self.online_prep_tab: self.online_prep_tab.load_tab_settings(panel_settings.get("online_prep_tab", {})) # Placeholder
                 logger.info("Panel settings loaded from QSettings.")
            else: logger.warning("Could not load valid panel_settings dict.")
        except Exception as e: logger.error(f"Error loading settings: {e}", exc_info=True)
        logger.info("Settings loading complete.")

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
            panel_settings = {}
            if self.project_panel: panel_settings["project_panel"] = self.project_panel.get_panel_settings()
            if self.color_prep_tab: panel_settings["color_prep_tab"] = self.color_prep_tab.get_tab_settings()
            if self.online_prep_tab: panel_settings["online_prep_tab"] = self.online_prep_tab.get_tab_settings() # Placeholder
            settings.setValue("panel_settings", panel_settings)
            logger.info("Window and panel settings saved.")
        except Exception as e: logger.error(f"Error getting panel settings for saving: {e}", exc_info=True)

    # --- Window Event Handlers ---
    def closeEvent(self, event):
        """Handles the window close event."""
        logger.debug("Close event triggered.")
        if not self._confirm_save_if_dirty():
            event.ignore(); return
        if self.worker_thread and self.worker_thread.isRunning():
             logger.warning("Closing while worker thread is running.")
             self.worker_thread.stop()
        self.save_settings()
        logger.info("--- Closing TimelineHarvester Application ---")
        event.accept()

    # --- UI State Management ---
    def _update_ui_state(self):
        """Updates the enabled state of all actions/buttons."""
        is_busy = self.worker_thread is not None and self.worker_thread.isRunning()
        enabled = not is_busy
        files_loaded = bool(self.project_panel.get_edit_files()) if self.project_panel else False
        sources_paths_set = bool(self.project_panel.get_original_search_paths()) if self.project_panel else False
        analysis_done = bool(self.harvester.edit_shots)
        sources_found = analysis_done and any(s.lookup_status == 'found' for s in self.harvester.edit_shots)
        color_plan_calculated = self.harvester.color_transfer_batch is not None and bool(self.harvester.color_transfer_batch.segments)
        online_plan_calculated = self.harvester.online_transfer_batch is not None and bool(self.harvester.online_transfer_batch.segments)
        can_calc_online = enabled and sources_found # Placeholder

        # Update Global Actions
        self.action_new_project.setEnabled(enabled)
        self.action_open_project.setEnabled(enabled)
        self.action_save_project.setEnabled(enabled and self.is_project_dirty)
        self.action_save_project_as.setEnabled(enabled)
        self.action_analyze.setEnabled(enabled and files_loaded and sources_paths_set)
        self.action_calculate_color.setEnabled(enabled and sources_found)
        self.action_export_for_color.setEnabled(enabled and color_plan_calculated)
        self.action_calculate_online.setEnabled(enabled and can_calc_online)
        self.action_transcode.setEnabled(enabled and online_plan_calculated)
        # Update Tab Buttons
        if self.color_prep_tab: self.color_prep_tab.update_button_states(enabled and files_loaded and sources_paths_set, enabled and sources_found, enabled and color_plan_calculated)
        if self.online_prep_tab: self.online_prep_tab.update_button_states(False, enabled and can_calc_online, enabled and online_plan_calculated) # Placeholder
        logger.debug(f"UI state updated (Busy: {is_busy})")

    def _is_worker_busy(self) -> bool:
        """Checks if the worker thread is active."""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "A background task is currently running.")
            return True
        return False

    def _update_ui_from_harvester_state(self):
         """Refreshes the entire UI based on the current harvester state."""
         logger.info("Updating UI from harvester state...")
         try:
             # Update Project Panel
             if self.project_panel:
                 self.project_panel.set_edit_files([f.path for f in self.harvester.edit_files])
                 self.project_panel.set_original_search_paths(self.harvester.source_search_paths)
                 self.project_panel.set_graded_search_paths(self.harvester.graded_source_search_paths)
             # Update Color Prep Tab
             if self.color_prep_tab:
                 color_settings = {
                     'color_prep_start_handles': self.harvester.color_prep_start_handles,
                     'color_prep_end_handles': self.harvester.color_prep_end_handles,
                     'color_prep_same_handles': self.harvester.color_prep_start_handles == self.harvester.color_prep_end_handles,
                     'color_prep_separator': self.harvester.color_prep_separator,
                     'split_gap_threshold_frames': self.harvester.split_gap_threshold_frames, # Update threshold
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
                 online_settings = { # Placeholder
                     'online_prep_handles': self.harvester.online_prep_handles,
                     'output_profiles': [p.__dict__ for p in self.harvester.output_profiles],
                     'online_output_directory': self.harvester.online_output_directory,
                     # ... other settings
                 }
                 self.online_prep_tab.load_tab_settings(online_settings)
                 # TODO: Update online results display

             self._update_ui_state() # Update button states
             self.update_window_title(self.is_project_dirty) # Update title reflecting loaded state
             logger.info("UI refreshed from harvester state.")
         except Exception as e:
              logger.error(f"Error updating UI from harvester state: {e}", exc_info=True)
              QMessageBox.critical(self, "UI Update Error", f"Failed to refresh UI:\n{e}")

    def _sync_ui_to_harvester(self) -> bool:
        """Gathers current settings from UI panels and updates harvester."""
        logger.debug("Syncing UI settings to harvester state...")
        if not self.project_panel or not self.color_prep_tab or not self.online_prep_tab:
             logger.error("Cannot sync UI: panels not initialized.")
             return False
        try:
             # Project Panel
             proj_settings = self.project_panel.get_panel_settings()
             self.harvester.edit_files = [EditFileMetadata(p) for p in proj_settings.get("edit_files",[])]
             self.harvester.set_source_search_paths(proj_settings.get("original_search_paths", []))
             self.harvester.set_graded_source_search_paths(proj_settings.get("graded_search_paths", []))
             # TODO: Sync strategy if UI is added
             # Color Prep Tab
             color_settings = self.color_prep_tab.get_tab_settings()
             self.harvester.set_color_prep_handles(color_settings.get("color_prep_start_handles", 24), color_settings.get("color_prep_end_handles", 24) )
             self.harvester.set_color_prep_separator(color_settings.get("color_prep_separator", 0))
             self.harvester.set_split_gap_threshold(color_settings.get("split_gap_threshold_frames", -1)) # Sync threshold
             # Online Prep Tab (Placeholder)
             # online_settings = self.online_prep_tab.get_tab_settings()
             # ... sync online settings ...
             logger.debug("Harvester state updated from UI.")
             return True
        except Exception as e:
             logger.error(f"Failed to sync UI settings to harvester: {e}", exc_info=True)
             QMessageBox.critical(self, "Internal Error", "Failed to gather settings from UI.")
             return False

    # --- Task Starting Slots ---
    @pyqtSlot()
    def start_analysis_task(self):
        """Configures harvester, clears previous results, and starts 'analyze' task."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return
        if not self.harvester.edit_files: QMessageBox.warning(self, "No Edit Files", "Add edit files."); return
        if not self.harvester.source_search_paths: QMessageBox.warning(self, "Config Missing",
                                                                       "Add Original Source Paths."); return

        # --- <<< NEW: Clear previous calculation results >>> ---
        logger.info("Clearing previous calculation results before starting new analysis.")
        self.harvester.color_transfer_batch = None  # Clear core batch data
        self.harvester.online_transfer_batch = None  # Clear core batch data
        if self.color_prep_tab:  # Clear GUI table for calculated segments
            self.color_prep_tab.results_widget.segments_table.setRowCount(0)
        if self.online_prep_tab:  # Clear online tab results if needed
            # self.online_prep_tab.results_widget.segments_table.setRowCount(0) # Or similar clearing
            pass
        # Reset button states related to calculation/export
        self._update_ui_state()
        QApplication.processEvents()  # Allow UI to update
        # --- <<< End Clearing >>> ---

        self._start_worker('analyze', "Analyzing files & finding sources...", {})
        self.mark_project_dirty()  # New analysis makes project dirty

    @pyqtSlot()
    def start_calculate_color_task(self):
        """Starts the 'create_plan' task for color prep."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return # Syncs handles, threshold etc.
        if not self.harvester.edit_shots or not any(s.lookup_status == 'found' for s in self.harvester.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete", "Run 'Analyze Sources' first & ensure originals were found.")
            return
        params = {'stage': 'color'}
        self._start_worker('create_plan', "Calculating segments for color prep...", params)
        self.mark_project_dirty()

    @pyqtSlot()
    def start_export_for_color_task(self):
        """Exports the color prep EDL/XML."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return # Sync separator value
        batch = self.harvester.color_transfer_batch
        if not batch or not batch.segments: QMessageBox.warning(self, "Export Error", "Calculate plan for color first."); return
        separator = self.harvester.color_prep_separator
        proj_name = self.harvester.project_name or "ColorTransfer"
        default_name = f"{proj_name}_ColorPrep.edl"
        start_dir = self.last_export_dir or os.path.dirname(self.current_project_path or self.last_project_dir)
        file_path, selected_filter = QFileDialog.getSaveFileName(self, "Export Timeline for Color", os.path.join(start_dir, default_name), "CMX EDL (*.edl);;FCP XML (*.xml *.fcpxml);;All Files (*)")
        if not file_path: return
        self.last_export_dir = os.path.dirname(file_path)
        self.status_manager.set_busy(True, f"Exporting to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            from core.exporter import export_transfer_batch # Local import
            success = export_transfer_batch(batch, file_path, separator_frames=separator)
            if success:
                self.status_manager.set_status(f"Export successful: {os.path.basename(file_path)}", temporary=False)
                QMessageBox.information(self, "Export Successful", f"Timeline exported to:\n{file_path}")
                self.save_settings()
            else:
                 self.status_manager.set_status("Export failed. Check logs.", temporary=False)
                 QMessageBox.critical(self, "Export Failed", "Could not export timeline. Check logs.")
        except Exception as e:
            logger.error(f"Unexpected export error: {e}", exc_info=True)
            self.status_manager.set_status(f"Export Error: {e}", temporary=False)
            QMessageBox.critical(self, "Export Error", f"An unexpected error occurred:\n\n{e}")
        finally: self.status_manager.set_busy(False)

    @pyqtSlot()
    def start_calculate_online_task(self):
         """Placeholder for starting online calculation."""
         if self._is_worker_busy(): return
         QMessageBox.information(self, "Not Implemented", "Calculating segments for online prep is not yet implemented.")

    @pyqtSlot()
    def start_transcode_task(self):
        """Starts the 'transcode' task after confirmation."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return
        batch = self.harvester.online_transfer_batch
        if not batch or not batch.segments: QMessageBox.warning(self, "No Plan", "Calculate the ONLINE plan first."); return
        if not batch.output_directory or not os.path.isdir(batch.output_directory): QMessageBox.critical(self, "Config Error", "Online output directory invalid."); return
        if not batch.output_profiles_used: QMessageBox.warning(self, "Config Missing", "No output profiles for online."); return
        segment_count = len(batch.segments)
        profile_count = len(batch.output_profiles_used)
        total_files = segment_count * profile_count
        output_dir = batch.output_directory
        reply = QMessageBox.question(self,"Confirm Transcode", f"Start transcoding ~{total_files} file(s) for online to:\n{output_dir}\n\nProceed?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes: self._start_worker('transcode', f"Starting online transcoding...", {'stage': 'online'})
        else: self.status_manager.set_status("Online transcoding cancelled.")

    # --- Worker Thread Management ---
    def _start_worker(self, task_name: str, busy_message: str, params: Optional[Dict] = None):
        """Creates, configures, and starts the WorkerThread."""
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
        self.worker_thread.start()
        self._update_ui_state() # Disable UI

    # --- Slots Handling Worker Thread Signals ---
    @pyqtSlot(list)
    def on_analysis_complete(self, analysis_summary: List[Dict]):
        """Handles successful completion of the 'analyze' task."""
        if self.color_prep_tab: # Update results display
            self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
            unresolved_summary = self.harvester.get_unresolved_shots_summary()
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        # TODO: Update online tab if needed
        found_count = sum(1 for s in analysis_summary if s['status'] == 'found')
        logger.info(f"Analysis complete signal. Shots: {len(analysis_summary)}, Found: {found_count}")

    @pyqtSlot(list, str)
    def on_plan_complete(self, plan_summary: List[Dict], stage: str):
        """Handles successful completion of the 'create_plan' task."""
        logger.info(f"Plan complete signal for stage '{stage}'. Segments: {len(plan_summary)}")
        unresolved_summary = self.harvester.get_unresolved_shots_summary()
        if stage == 'color' and self.color_prep_tab:
            self.color_prep_tab.results_widget.display_plan_summary(plan_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        elif stage == 'online' and self.online_prep_tab:
            # self.online_prep_tab.results_widget.display_plan_summary(plan_summary)
            # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
            pass # Update online tab results later

    @pyqtSlot(bool, str)
    def on_transcode_complete(self, success: bool, message: str):
        """Handles completion of 'transcode' task."""
        logger.info(f"Transcode complete signal. Success: {success}")
        if success:
            self.status_manager.set_status(message, temporary=False)
            QMessageBox.information(self, "Transcoding Complete", message)
        else:
            self.status_manager.set_status(f"Transcoding Failed: {message}", temporary=False)
            QMessageBox.critical(self, "Transcoding Failed", f"Transcoding failed.\nCheck logs.\n\nSummary: {message}")
        # TODO: Update online tab results status

    @pyqtSlot(int, str)
    def on_progress_update(self, percent: int, message: str):
        """Handles progress updates from worker."""
        self.status_manager.show_progress(percent, 100, message)

    @pyqtSlot(str)
    def on_task_error(self, error_message: str):
        """Handles unexpected errors from the worker thread."""
        logger.error(f"Worker thread error signal: {error_message}")
        self.status_manager.set_status(f"Error: {error_message}", temporary=False)
        QMessageBox.critical(self, "Background Task Error", error_message)

    @pyqtSlot()
    def on_task_finished(self):
        """Called ALWAYS after worker finishes. Cleans up and re-enables UI."""
        logger.info("Worker thread finished signal received. Cleaning up.")
        self.status_manager.hide_progress()
        current_status = self.status_manager.status_label.text()
        final_prefixes = ["Error:", "Failed:", "Completed", "cancelled", "complete", "exported", "Analysis complete", "Plan calculated", "Project saved", "Project loaded", "Task '"]
        is_final = any(current_status.startswith(p) for p in final_prefixes) or "cancelled" in current_status.lower()
        if not is_final: self.status_manager.set_status("Ready.")
        self.worker_thread = None # Clear thread reference
        self._update_ui_state() # Re-enable UI
        logger.info("Worker thread cleanup and UI update complete.")

    # --- About Dialog ---
    def show_about_dialog(self):
        QMessageBox.about(self, "About TimelineHarvester",
                          "<h2>TimelineHarvester</h2>"
                          "<p>Version 1.1 (Tabs)</p>" # TODO: Update version dynamically
                          "<p>Workflow tool for preparing media for color grading and online editing.</p>"
                          "<p>(Uses OpenTimelineIO and FFmpeg/FFprobe)</p>")
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

from PyQt5.QtCore import QSettings, QThread, pyqtSignal, pyqtSlot
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

# No direct model imports needed here usually

logger = logging.getLogger(__name__)


# --- Worker Thread Definition (Same as before) ---
class WorkerThread(QThread):
    """Thread to run background tasks (analysis, plan, transcode) without freezing the GUI."""
    analysis_finished = pyqtSignal(list)
    plan_finished = pyqtSignal(list, str)  # Added stage identifier
    transcode_finished = pyqtSignal(bool, str)
    progress_update = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)

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
                # Assume harvester config (paths, strategy) is set before starting
                self.harvester.parse_added_edit_files()
                if not self._is_running: raise InterruptedError("Task stopped.")
                self.harvester.find_original_sources()
                if not self._is_running: raise InterruptedError("Task stopped.")
                summary = self.harvester.get_edit_shots_summary()
                if self._is_running: self.analysis_finished.emit(summary)

            elif self.task == 'create_plan':
                handles = self.params.get('handles', 0)
                output_dir = self.params.get('output_dir')  # May be None for color
                stage = self.params.get('stage', 'color')
                logger.info(f"Worker calculating plan for stage: {stage}")
                # Harvester method calculates and stores internally
                self.harvester.calculate_transfer(handles, output_dir, stage=stage)
                if not self._is_running: raise InterruptedError("Task stopped.")
                # Get summary for the stage that was just calculated
                segment_summary = self.harvester.get_transfer_segments_summary(stage=stage)
                if self._is_running: self.plan_finished.emit(segment_summary, stage)  # Emit stage

            elif self.task == 'transcode':  # Assumed Online for now
                stage = self.params.get('stage', 'online')  # Get stage context
                if stage != 'online':
                    raise ValueError("Transcoding is currently only implemented for 'online' stage.")

                def progress_callback(current, total, message):
                    if not self._is_running: raise InterruptedError("Transcode stopped.")
                    percent = int((current / total) * 100) if total > 0 else 0
                    self.progress_update.emit(percent, message)

                self.harvester.run_online_transcoding(progress_callback)  # Specific method
                if self._is_running: self.transcode_finished.emit(True, "Online transcoding completed.")
            else:
                raise ValueError(f"Unknown worker task: {self.task}")

            if self._is_running: logger.info(f"WorkerThread finished task: {self.task}")
        except InterruptedError:
            logger.warning(f"WorkerThread task '{self.task}' stopped by user request.")
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
        # UI Component References
        self.project_panel: Optional[ProjectPanel] = None
        self.tab_widget: Optional[QTabWidget] = None
        self.color_prep_tab: Optional[ColorPrepTabWidget] = None
        self.online_prep_tab: Optional[OnlinePrepTabWidget] = None
        self.status_manager: Optional[StatusBarManager] = None
        # Load/Save Paths - Initialize with home directory
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

        self.load_settings()  # Load persistent window/path/panel settings
        self.new_project(confirm_save=False)  # Start clean without prompt
        logger.info("MainWindow initialized and started with a new project.")

    # --- UI Creation Methods ---
    def init_ui(self):
        """Sets up the main window layout with Project Panel and Tabs."""
        self.status_manager = StatusBarManager(self.statusBar())
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # 1. Project Panel (Top)
        self.project_panel = ProjectPanel()
        main_layout.addWidget(self.project_panel)  # Add it first, let it take natural height

        # 2. Tab Widget (Main Area)
        self.tab_widget = QTabWidget()
        self.tab_widget.setUsesScrollButtons(True)

        # Create and add tab widgets
        self.color_prep_tab = ColorPrepTabWidget(self.harvester)
        self.online_prep_tab = OnlinePrepTabWidget(self.harvester)  # Create placeholder instance

        self.tab_widget.addTab(self.color_prep_tab, "1. Prepare for Color Grading")
        self.tab_widget.addTab(self.online_prep_tab, "2. Prepare for Online")
        # Optionally disable online tab initially if not implemented
        # self.tab_widget.setTabEnabled(1, False)

        main_layout.addWidget(self.tab_widget, 1)  # Make tabs stretch vertically
        logger.debug("Main window UI layout created (Project Panel + Tabs).")

    def create_actions(self):
        """Creates QAction objects for menus and toolbars."""
        # Project Actions
        self.action_new_project = QAction("&New Project", self, shortcut="Ctrl+N", statusTip="Create a new project")
        self.action_open_project = QAction("&Open Project...", self, shortcut="Ctrl+O",
                                           statusTip="Open an existing project file (.thp)")
        self.action_save_project = QAction("&Save Project", self, shortcut="Ctrl+S",
                                           statusTip="Save the current project", enabled=False)
        self.action_save_project_as = QAction("Save Project &As...", self,
                                              statusTip="Save the current project to a new file")
        self.action_exit = QAction("E&xit", self, shortcut="Ctrl+Q", statusTip="Exit the application")

        # Process Actions
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

        # Connect signals from ProjectPanel -> mark dirty
        self.project_panel.editFilesChanged.connect(self.on_project_panel_changed)
        self.project_panel.originalSourcePathsChanged.connect(self.on_project_panel_changed)
        self.project_panel.gradedSourcePathsChanged.connect(self.on_project_panel_changed)

        # Connect signals from Tab Widgets -> mark dirty & trigger actions from tab buttons
        # Color Prep Tab
        self.color_prep_tab.settingsChanged.connect(self.mark_project_dirty)
        self.color_prep_tab.analyzeSourcesClicked.connect(self.start_analysis_task)
        self.color_prep_tab.calculateSegmentsClicked.connect(self.start_calculate_color_task)
        self.color_prep_tab.exportEdlXmlClicked.connect(self.start_export_for_color_task)

        # Online Prep Tab (Connect when implemented)
        # self.online_prep_tab.settingsChanged.connect(self.mark_project_dirty)
        # ... connect other signals ...

        # Internal dirty state signal -> update title/save action
        self.projectDirtyStateChanged.connect(self.update_window_title)

        logger.debug("UI Signals connected.")

    # --- Project State Management ---
    @pyqtSlot()
    def mark_project_dirty(self):
        """Marks the current project as modified (dirty=True)."""
        if not self.is_project_dirty:
            self.is_project_dirty = True
            self.projectDirtyStateChanged.emit(True)
            logger.debug("Project marked as dirty.")

    @pyqtSlot(list)
    def on_project_panel_changed(self, new_paths: list):
        """Handle path list changes from ProjectPanel - mark project dirty."""
        # Syncing to harvester happens just before save/process
        logger.debug("Project panel change detected, marking project dirty.")
        self.mark_project_dirty()

    @pyqtSlot(bool)
    def update_window_title(self, is_dirty: bool):
        """Updates the window title with project name and dirty indicator (*)."""
        base_title = "TimelineHarvester"
        project_name = os.path.basename(self.current_project_path) if self.current_project_path else "Untitled Project"
        dirty_indicator = " *" if is_dirty else ""
        self.setWindowTitle(f"{project_name}{dirty_indicator} - {base_title}")
        self.action_save_project.setEnabled(is_dirty)  # Enable Save only if dirty

    def _confirm_save_if_dirty(self) -> bool:
        """Checks if project is dirty, prompts user to save, returns True if okay to proceed."""
        if not self.is_project_dirty: return True
        reply = QMessageBox.question(self, "Unsaved Changes",
                                     "The current project has unsaved changes.\n"
                                     "Do you want to save them before proceeding?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                     QMessageBox.Save)
        if reply == QMessageBox.Save:
            return self.save_project()
        elif reply == QMessageBox.Discard:
            logger.info("User discarded unsaved changes.");
            return True
        else:
            logger.info("User cancelled operation due to unsaved changes.");
            return False  # Cancel

    # --- Project Actions Implementation ---
    @pyqtSlot()
    def new_project(self, confirm_save=True):
        """Clears state and starts a new project, optionally prompting to save."""
        logger.info("Action: New Project")
        if confirm_save and not self._confirm_save_if_dirty():
            logger.info("New project cancelled by user.")
            return

        self.harvester.clear_state()
        self.current_project_path = None
        self._update_ui_from_harvester_state()  # Refresh UI to reflect cleared state
        self.is_project_dirty = False
        self.projectDirtyStateChanged.emit(False)
        self.status_manager.set_status("New project created. Add edit files and configure paths.")
        self._update_ui_state()  # Update UI which includes save button state
        logger.info("New project state initialized.")

    @pyqtSlot()
    def open_project(self):
        """Opens an existing project file (.thp/.json), prompting to save first."""
        logger.info("Action: Open Project")
        if not self._confirm_save_if_dirty(): return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open TimelineHarvester Project", self.last_project_dir,
            "Harvester Projects (*.thp *.json);;All Files (*)"
        )
        if not file_path: self.status_manager.set_status("Open project cancelled."); return

        self.last_project_dir = os.path.dirname(file_path)
        self.status_manager.set_busy(True, f"Loading project: {os.path.basename(file_path)}...")
        QApplication.processEvents()

        try:
            loaded_ok = self.harvester.load_project(file_path)
            if not loaded_ok: raise ValueError("Harvester.load_project reported failure.")

            self.current_project_path = file_path
            self._update_ui_from_harvester_state()  # Refresh UI with loaded data
            self.is_project_dirty = False
            self.projectDirtyStateChanged.emit(False)
            self.status_manager.set_status(f"Project '{os.path.basename(file_path)}' loaded.")
            logger.info(f"Successfully loaded project: {file_path}")
            self.save_settings()  # Save the updated last_project_dir

        except Exception as e:
            logger.error(f"Failed to load project file '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Load Project Error", f"Failed to load project:\n{e}")
            self.new_project(confirm_save=False)  # Revert to clean state
            self.status_manager.set_status("Failed to load project.")
        finally:
            self.status_manager.set_busy(False)
            self._update_ui_state()

    @pyqtSlot()
    def save_project(self) -> bool:
        """Saves the current project. Prompts for filename if not set."""
        logger.info("Action: Save Project")
        if not self.current_project_path:
            return self.save_project_as()
        else:
            if not self._sync_ui_to_harvester(): return False  # Sync before saving
            return self._save_project_to_path(self.current_project_path)

    @pyqtSlot()
    def save_project_as(self) -> bool:
        """Prompts user for filename and saves the project."""
        logger.info("Action: Save Project As...")
        if not self._sync_ui_to_harvester(): return False  # Sync before asking path

        suggested_name = os.path.basename(
            self.current_project_path or f"{self.harvester.project_name or 'Untitled'}.thp")
        start_dir = os.path.dirname(self.current_project_path or self.last_project_dir)

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save TimelineHarvester Project As", os.path.join(start_dir, suggested_name),
            "Harvester Projects (*.thp);;JSON Files (*.json);;All Files (*)"
        )
        if not file_path: self.status_manager.set_status("Save project as cancelled."); return False

        name, ext = os.path.splitext(file_path)
        if not ext.lower() in ['.thp', '.json']:
            if "(*.thp)" in selected_filter:
                file_path += ".thp"
            elif "(*.json)" in selected_filter:
                file_path += ".json"
            else:
                file_path += ".thp"

        self.last_project_dir = os.path.dirname(file_path)
        return self._save_project_to_path(file_path)

    def _save_project_to_path(self, file_path: str) -> bool:
        """Internal helper: performs the actual save using harvester."""
        self.status_manager.set_busy(True, f"Saving project to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            # Project name sync happens in _sync_ui_to_harvester or harvester.get_project_data...
            self.harvester.project_name = os.path.splitext(os.path.basename(file_path))[0]
            saved_ok = self.harvester.save_project(file_path)
            if not saved_ok: raise ValueError("Harvester.save_project reported failure.")

            self.current_project_path = file_path
            self.is_project_dirty = False
            self.projectDirtyStateChanged.emit(False)
            self.status_manager.set_status(f"Project saved: {os.path.basename(file_path)}.")
            logger.info(f"Project successfully saved to: {file_path}")
            self.save_settings()  # Save updated last_project_dir
            return True

        except Exception as e:
            logger.error(f"Failed to save project to '{file_path}': {e}", exc_info=True)
            QMessageBox.critical(self, "Save Project Error", f"Failed to save project:\n{e}")
            self.status_manager.set_status("Failed to save project.")
            self.mark_project_dirty(True)  # Still dirty if save failed
            return False
        finally:
            self.status_manager.set_busy(False)

    # --- Settings Persistence ---
    def load_settings(self):
        """Loads persistent UI settings (window state, paths, last panel states)."""
        logger.info("Loading persistent application settings...")
        settings = QSettings("TimelineHarvesterOrg", "TimelineHarvester")
        self.restoreGeometry(settings.value("window_geometry", self.saveGeometry()))
        self.restoreState(settings.value("window_state", self.saveState()))
        self.last_project_dir = settings.value("last_project_dir", os.path.expanduser("~"))
        self.last_edit_file_dir = settings.value("last_edit_file_dir", self.last_project_dir)
        self.last_export_dir = settings.value("last_export_dir", self.last_project_dir)

        panel_settings_dict = settings.value("panel_settings", {})
        if isinstance(panel_settings_dict, dict):
            try:
                self.project_panel.load_panel_settings(panel_settings_dict.get("project_panel", {}))
                self.color_prep_tab.load_tab_settings(panel_settings_dict.get("color_prep_tab", {}))
                # self.online_prep_tab.load_tab_settings(panel_settings_dict.get("online_prep_tab", {}))
                logger.info("Panel settings loaded from QSettings.")
            except Exception as e:
                logger.error(f"Error applying loaded settings to panels: {e}", exc_info=True)
        else:
            logger.warning("Could not load valid dictionary for panel_settings from QSettings.")
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

        panel_settings_dict = {
            "project_panel": self.project_panel.get_panel_settings(),
            "color_prep_tab": self.color_prep_tab.get_tab_settings(),
            # "online_prep_tab": self.online_prep_tab.get_tab_settings()
        }
        settings.setValue("panel_settings", panel_settings_dict)
        logger.info("Window and panel settings saved.")

    # --- UI State Management ---
    def _update_ui_initial_state(self):
        """Sets the initial enabled state after startup or new project."""
        self.mark_project_dirty(False)
        self._update_ui_state()

    def _update_ui_state(self):
        """Updates the enabled state of actions/buttons based on project state."""
        is_busy = self.worker_thread is not None and self.worker_thread.isRunning()
        enabled = not is_busy

        # Get logical state from harvester
        files_loaded = bool(self.harvester.edit_files)
        analysis_done = bool(self.harvester.edit_shots)  # Basic check if parsing happened
        sources_found = analysis_done and any(s.lookup_status == 'found' for s in self.harvester.edit_shots)
        color_plan_calculated = self.harvester.color_transfer_batch is not None and bool(
            self.harvester.color_transfer_batch.segments)
        online_plan_calculated = self.harvester.online_transfer_batch is not None and bool(
            self.harvester.online_transfer_batch.segments)
        # TODO: Add more specific checks for online stage prerequisites
        can_calc_online = enabled and sources_found  # Placeholder: Needs check for graded sources analysis

        # Update Global Actions
        self.action_new_project.setEnabled(enabled)
        self.action_open_project.setEnabled(enabled)
        self.action_save_project.setEnabled(enabled and self.is_project_dirty)
        self.action_save_project_as.setEnabled(enabled)  # Always possible to save as
        self.action_analyze.setEnabled(enabled and files_loaded)
        self.action_calculate_color.setEnabled(enabled and sources_found)
        self.action_export_for_color.setEnabled(enabled and color_plan_calculated)
        self.action_calculate_online.setEnabled(enabled and can_calc_online)
        self.action_transcode.setEnabled(enabled and online_plan_calculated)

        # Delegate state updates to Tab Widgets
        self.color_prep_tab.update_button_states(
            can_analyze=enabled and files_loaded,
            can_calculate=enabled and sources_found,
            can_export=enabled and color_plan_calculated
        )
        # self.online_prep_tab.update_button_states(...) # Uncomment when implemented

        logger.debug(f"UI actions/buttons state updated (Busy: {is_busy})")

    def _is_worker_busy(self) -> bool:
        """Checks if the worker thread is active and shows a message."""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Busy",
                                "A background task is currently running.\nPlease wait for it to complete.")
            return True
        return False

    def _update_ui_from_harvester_state(self):
        """Refreshes the entire UI based on the current state of self.harvester."""
        logger.info("Updating UI from harvester state...")
        try:
            # Update Project Panel (paths, edit files)
            self.project_panel.set_edit_files([f.path for f in self.harvester.edit_files])
            self.project_panel.set_original_search_paths(self.harvester.source_search_paths)
            self.project_panel.set_graded_search_paths(self.harvester.graded_source_search_paths)

            # Update Color Prep Tab (settings and results)
            color_settings = {'color_prep_handles': self.harvester.color_prep_handles}
            self.color_prep_tab.load_tab_settings(color_settings)
            analysis_summary = self.harvester.get_edit_shots_summary()
            self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
            color_plan_summary = self.harvester.get_transfer_segments_summary(stage='color')
            self.color_prep_tab.results_widget.display_plan_summary(color_plan_summary)
            unresolved_summary = self.harvester.get_unresolved_shots_summary()
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)

            # Update Online Prep Tab (when implemented)
            # online_settings = { ... }
            # self.online_prep_tab.load_tab_settings(online_settings)
            # ... update online results ...

            # Update overall UI state (button enables etc.) and window title
            self._update_ui_state()
            self.update_window_title(self.is_project_dirty)  # Reflect loaded dirty state (should be false)
            logger.info("UI refreshed from harvester state.")
        except Exception as e:
            logger.error(f"Error updating UI from harvester state: {e}", exc_info=True)
            QMessageBox.critical(self, "UI Update Error", f"Failed to refresh UI after loading project:\n{e}")

    def _sync_ui_to_harvester(self) -> bool:
        """Gathers current settings from UI panels and updates the harvester's config attributes."""
        logger.debug("Syncing UI settings to harvester state...")
        try:
            # Project Panel -> Harvester config
            proj_panel_settings = self.project_panel.get_panel_settings()
            # Only update paths if they changed? No, harvester needs the current list.
            self.harvester.edit_files = [EditFileMetadata(p) for p in proj_panel_settings.get("edit_files", [])]
            self.harvester.source_search_paths = proj_panel_settings.get("original_search_paths", [])
            self.harvester.graded_source_search_paths = proj_panel_settings.get("graded_search_paths", [])

            # Color Prep Tab -> Harvester config
            color_settings = self.color_prep_tab.get_tab_settings()
            self.harvester.color_prep_handles = color_settings.get("color_prep_handles", 24)

            # Online Prep Tab -> Harvester config (When implemented)
            # online_settings = self.online_prep_tab.get_tab_settings()
            # self.harvester.online_prep_handles = online_settings.get("online_prep_handles", 12)
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
        if not self._sync_ui_to_harvester(): return  # Sync settings first

        if not self.harvester.edit_files:
            QMessageBox.warning(self, "No Files", "Please add edit files via the Project Panel first.")
            return
        if not self.harvester.source_search_paths:
            QMessageBox.warning(self, "Configuration Missing",
                                "Please add Original Source Search Paths in the Project Panel.")
            return

        self._start_worker('analyze', "Analyzing files & finding sources...", {})
        # Mark dirty because analysis results are part of the project state
        self.mark_project_dirty()

    @pyqtSlot()
    def start_calculate_color_task(self):
        """Starts the 'create_plan' task specifically for color prep."""
        if self._is_worker_busy(): return
        if not self._sync_ui_to_harvester(): return  # Sync settings first

        if not self.harvester.edit_shots or not any(s.lookup_status == 'found' for s in self.harvester.edit_shots):
            QMessageBox.warning(self, "Analysis Incomplete",
                                "Please run 'Analyze Sources' first and ensure originals were found.")
            return

        params = {
            'handles': self.harvester.color_prep_handles,  # Use value from harvester state
            'output_dir': None,  # Not needed for color calculation
            'stage': 'color'  # Provide context
        }
        self._start_worker('create_plan', "Calculating segments for color prep...", params)
        self.mark_project_dirty()  # Calculation result is a project change

    @pyqtSlot()
    def start_export_for_color_task(self):
        """Starts the export process for the color prep EDL/XML."""
        if self._is_worker_busy(): return
        batch_to_export = self.harvester.color_transfer_batch
        if not batch_to_export or not batch_to_export.segments:
            QMessageBox.warning(self, "Export Error", "Please calculate the transfer plan for color first.")
            return

        proj_name_part = self.harvester.project_name or \
                         os.path.splitext(os.path.basename(self.current_project_path or "Untitled"))[
                             0] or "ColorTransfer"
        default_filename = f"{proj_name_part}_ColorPrep.edl"
        start_dir = self.last_export_dir or os.path.dirname(self.current_project_path or os.path.expanduser("~"))
        default_path = os.path.join(start_dir, default_filename)

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Timeline for Color Grading", default_path,
            "CMX 3600 EDL (*.edl);;Final Cut Pro XML (*.xml *.fcpxml);;All Files (*)"
        )
        if not file_path: self.status_manager.set_status("Export cancelled."); return

        self.last_export_dir = os.path.dirname(file_path)

        self.status_manager.set_busy(True, f"Exporting to {os.path.basename(file_path)}...")
        QApplication.processEvents()
        try:
            from core.exporter import export_transfer_batch
            # Pass the specific color batch
            success = export_transfer_batch(batch_to_export, file_path)
            if success:
                self.status_manager.set_status(f"Export successful: {os.path.basename(file_path)}", temporary=False)
                QMessageBox.information(self, "Export Successful", f"Timeline exported successfully to:\n{file_path}")
                self.save_settings()  # Save updated last_export_dir path
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
        # TODO: Sync UI
        # TODO: Check prerequisites (graded sources analyzed?)
        logger.warning("Calculate for Online functionality not implemented.")
        QMessageBox.information(self, "Not Implemented", "Calculating segments for online prep is not yet implemented.")
        # params = {'stage': 'online', ... }
        # self._start_worker('create_plan', "Calculating segments for online...", params)
        # self.mark_project_dirty()

    @pyqtSlot()
    def start_transcode_task(self):
        """Starts the 'transcode' task (assumed for Online prep) after confirmation."""
        if self._is_worker_busy(): return
        # TODO: Check if online plan is calculated
        batch_to_run = self.harvester.online_transfer_batch
        if not batch_to_run or not batch_to_run.segments:
            QMessageBox.warning(self, "No Plan", "Please calculate the ONLINE transfer plan first.")
            return
        if not batch_to_run.output_directory or not os.path.isdir(batch_to_run.output_directory):
            QMessageBox.critical(self, "Configuration Error", "Online output directory is not set or invalid.")
            return
        if not batch_to_run.output_profiles_used:
            QMessageBox.warning(self, "Configuration Missing", "No output profiles configured for the online plan.")
            return

        segment_count = len(batch_to_run.segments)
        profile_count = len(batch_to_run.output_profiles_used)
        total_files = segment_count * profile_count
        output_dir = batch_to_run.output_directory

        reply = QMessageBox.question(self, "Confirm Online Transcode",
                                     f"Start transcoding {total_files} file(s) for online?\n"
                                     f"({segment_count} segments x {profile_count} profiles)\n\n"
                                     f"Output Directory:\n'{output_dir}'\n\n"
                                     f"(Ensure FFmpeg is accessible)",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._start_worker('transcode', f"Starting online transcoding ({total_files} files)...",
                               {'stage': 'online'})
        else:
            self.status_manager.set_status("Online transcoding cancelled.")

    def _start_worker(self, task_name: str, busy_message: str, params: Dict):
        """Helper to create, connect signals, start, and manage worker thread."""
        # Double-check it's not already busy, though the calling methods should also check
        if self._is_worker_busy(): return

        logger.info(f"Starting worker task: {task_name} with params: {params}")
        self.status_manager.set_busy(True, busy_message)
        # Call the correct method to update UI state (which will disable elements because worker is running)
        self._update_ui_state()  # Update UI to reflect busy state

        # Create the worker thread instance
        self.worker_thread = WorkerThread(self.harvester, task_name, params)

        # Connect signals FROM this specific worker thread instance TO slots in MainWindow (self)
        self.worker_thread.analysis_finished.connect(self.on_analysis_complete)
        self.worker_thread.plan_finished.connect(self.on_plan_complete)
        self.worker_thread.transcode_finished.connect(self.on_transcode_complete)
        self.worker_thread.progress_update.connect(self.on_progress_update)
        self.worker_thread.error_occurred.connect(self.on_task_error)
        # Connect the built-in finished signal (emitted always) to our cleanup slot
        self.worker_thread.finished.connect(self.on_task_finished)

        # Start thread execution (calls the run() method in the background)
        self.worker_thread.start()

    # --- Slots Handling Worker Thread Signals ---
    @pyqtSlot(list)
    def on_analysis_complete(self, analysis_summary: List[Dict]):
        """Handles successful completion of the 'analyze' task."""
        # Update the results display within the Color Prep Tab's results widget
        self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
        # Update unresolved list in BOTH tabs? Or just active one? Update both for consistency.
        unresolved_summary = [s for s in analysis_summary if s['status'] != 'found']
        self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        # TODO: Also update unresolved in online_prep_tab.results_widget if it exists
        found_count = sum(1 for s in analysis_summary if s['status'] == 'found')
        logger.info(f"Analysis task completed. Sources found for {found_count}/{len(analysis_summary)} clips.")
        # Status bar/actions updated in on_task_finished

    @pyqtSlot(list, str)  # Added stage argument
    def on_plan_complete(self, plan_summary: List[Dict], stage: str):
        """Handles successful completion of the 'create_plan' task."""
        unresolved_summary = self.harvester.get_unresolved_shots_summary()
        errors = []
        batch = self.harvester.color_transfer_batch if stage == 'color' else self.harvester.online_transfer_batch
        if batch: errors = batch.calculation_errors

        status_msg = f"Plan calculation for '{stage}' complete: {len(plan_summary)} segments."
        if errors: status_msg += f" ({len(errors)} calc errors)."
        logger.info(status_msg)

        # Update results in the appropriate tab
        if stage == 'color':
            self.color_prep_tab.results_widget.display_plan_summary(plan_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        elif stage == 'online':
            # TODO: Update online_prep_tab results display
            # self.online_prep_tab.results_widget.display_plan_summary(plan_summary)
            # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
            pass  # Placeholder
        # Status bar/actions updated in on_task_finished

    @pyqtSlot(bool, str)
    def on_transcode_complete(self, success: bool, message: str):
        """Handles completion of 'transcode' task (Online Prep)."""
        if success:
            self.status_manager.set_status(message, temporary=False)
            QMessageBox.information(self, "Transcoding Complete", message)
        else:
            self.status_manager.set_status(f"Transcoding Failed: {message}", temporary=False)
            QMessageBox.critical(self, "Transcoding Failed", message)
        logger.info(f"Transcoding task signal received. Success: {success}")
        # TODO: Update status in the Online Prep Tab results view
        # Status bar/actions updated in on_task_finished

    @pyqtSlot(int, str)
    def on_progress_update(self, percent: int, message: str):
        """Handles progress updates during tasks like transcoding."""
        self.status_manager.show_progress(percent, 100, message)

    @pyqtSlot(str)
    def on_task_error(self, error_message: str):
        """Handles unexpected errors propagated from the worker thread's run() method."""
        logger.error(f"Received error signal from worker thread: {error_message}")
        self.status_manager.set_status(f"Error: {error_message}", temporary=False)
        QMessageBox.critical(self, "Background Task Error", error_message)
        # Status bar/actions updated in on_task_finished

    @pyqtSlot()
    def on_task_finished(self):
        """
        Slot connected to QThread.finished signal.
        Called ALWAYS after the worker thread's run() method completes,
        regardless of success or failure. Cleans up and re-enables UI.
        """
        logger.info("Worker thread finished signal received.")
        self.status_manager.hide_progress()  # Ensure progress bar is hidden

        # Set final status message *if* no specific error/completion msg was set by handler
        # Get the current message *before* setting potentially to "Ready."
        current_status = self.status_manager.status_label.text()
        # List of prefixes indicating a task ended with a specific status message
        final_message_prefixes = [
            "Error:", "Failed:", "Completed", "cancelled", "complete",
            "exported", "Analysis complete", "Plan calculated", "Project saved",
            "Project loaded", "Task '",  # Added for cancellation message
        ]
        # If the current message doesn't already indicate a final state, set to "Ready."
        if not any(current_status.startswith(prefix) for prefix in final_message_prefixes):
            self.status_manager.set_status("Ready.")  # Default idle message

        # CRUCIAL: Re-enable UI elements based on the *current* application state
        # Now that the worker is no longer busy
        self._update_ui_state()

        # Clear the reference to the finished thread object to allow garbage collection
        # and indicate no worker is currently active
        self.worker_thread = None
        logger.info("Worker thread cleanup and UI state update complete.")

    # --- Placeholder Methods for Save/Export/Report ---
    def save_transfer_plan(self):  # Method remains but points to project save
        logger.warning("Save Transfer Plan action is likely obsolete. Use Save Project.")
        QMessageBox.information(self, "Save Project",
                                "Use File > Save Project (Ctrl+S) to save the current state, including calculated plans.")

    def export_segments(self):  # Could export a simple CSV/Text list
        logger.warning("Export Segments function not implemented.")
        QMessageBox.information(self, "Not Implemented", "Exporting segment lists (e.g., CSV) is not yet implemented.")
        # TODO: Iterate through active batch (color or online) and write segment info to file

    def generate_report(self):
        logger.warning("Generate Report function not implemented.")
        QMessageBox.information(self, "Not Implemented", "Generating a summary report is not yet implemented.")
        # TODO: Gather data from harvester and format a report string/file

    # --- About Dialog ---
    def show_about_dialog(self):
        QMessageBox.about(self, "About TimelineHarvester",
                          "<h2>TimelineHarvester</h2>"
                          "<p>Version 1.1 (Tabs)</p>"
                          "<p>Analyzes edit files, finds original sources, calculates needed segments, "
                          "and prepares timelines/media for color grading and online finishing.</p>"
                          "<p>(Uses OpenTimelineIO and FFmpeg/FFprobe)</p>")

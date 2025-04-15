# gui2/controllers/application_controller.py
"""
Application Controller for TimelineHarvester

Serves as the central coordinator between the UI and the application logic,
managing the overall application flow and lifecycle.
"""

import logging
import os
from typing import Optional, Dict, Any

from PyQt5.QtCore import QObject, QSettings

# Import our services and models
from ..services.event_bus_service import EventBusService, EventType, EventData
from ..models.ui_state_model import UIStateModel

# Import the facade from core (adjust import path as needed)
from core.timeline_harvester_facade import TimelineHarvesterFacade

logger = logging.getLogger(__name__)


class ApplicationController(QObject):
    """
    Central controller that coordinates the application.

    Responsibilities:
    - Initializing and connecting core components
    - Managing application lifecycle (startup, shutdown)
    - Coordinating between UI components and the business logic
    - Handling global application state
    """

    def __init__(self, facade: TimelineHarvesterFacade, event_bus: EventBusService,
                 ui_state: UIStateModel):
        """
        Initialize with required services.

        Args:
            facade: The TimelineHarvesterFacade instance
            event_bus: The EventBusService for app-wide communication
            ui_state: The UIStateModel for tracking UI state
        """
        super().__init__()
        self.facade = facade
        self.event_bus = event_bus
        self.ui_state = ui_state

        # Store common paths
        self.last_project_dir = os.path.expanduser("~")
        self.last_edit_file_dir = os.path.expanduser("~")
        self.last_export_dir = os.path.expanduser("~")

        # Connect to events
        self._setup_event_handlers()
        logger.info("ApplicationController initialized")

    def _setup_event_handlers(self):
        """Subscribe to relevant application events."""
        # Application lifecycle events
        self.event_bus.subscribe(EventType.APP_READY, self._on_app_ready)
        self.event_bus.subscribe(EventType.APP_CLOSING, self._on_app_closing)

        # Project events will be handled by the ProjectController
        # Workflow events will be handled by the WorkflowController

        # This controller will still respond to high-level UI changes
        self.event_bus.subscribe(EventType.SETTINGS_CHANGED, self._on_settings_changed)

    def _on_app_ready(self, event_data: EventData):
        """Handler for APP_READY event."""
        logger.info("Application ready event received")
        # Load application settings
        self.load_settings()

        # Create a new project on startup
        self.facade.new_project()

        # Update UI state
        self._update_ui_state_from_facade()

        # Publish event that the application is fully initialized
        self.event_bus.publish(EventData(
            EventType.PROJECT_LOADED,
            project_path=None,
            is_new=True
        ))

    def _on_app_closing(self, event_data: EventData):
        """Handler for APP_CLOSING event."""
        logger.info("Application closing event received")
        # Save application settings
        self.save_settings()

    def _on_settings_changed(self, event_data: EventData):
        """Handler for SETTINGS_CHANGED event."""
        logger.debug(f"Settings changed: {event_data}")
        # Mark project as dirty
        self.facade.mark_project_dirty()
        # Update UI state
        self._update_ui_state_from_facade()

    def load_settings(self):
        """Load application settings from QSettings."""
        logger.info("Loading application settings")
        settings = QSettings()

        # Load path settings
        self.last_project_dir = settings.value("last_project_dir", os.path.expanduser("~"))
        self.last_edit_file_dir = settings.value("last_edit_file_dir", self.last_project_dir)
        self.last_export_dir = settings.value("last_export_dir", self.last_project_dir)

        # Other application settings can be loaded here

        logger.info("Application settings loaded")

    def save_settings(self):
        """Save application settings to QSettings."""
        logger.info("Saving application settings")
        settings = QSettings()

        # Save path settings
        settings.setValue("last_project_dir", self.last_project_dir)
        settings.setValue("last_edit_file_dir", self.last_edit_file_dir)
        settings.setValue("last_export_dir", self.last_export_dir)

        # Other application settings can be saved here

        logger.info("Application settings saved")

    def _update_ui_state_from_facade(self):
        """
        Update the UI state model based on current facade state.
        Called after operations that may change the application state.
        """
        # Get the current state snapshot from the facade
        state = self.facade.get_project_state_snapshot()

        # Update project state
        self.ui_state.update({
            'current_project_path': self.facade.get_current_project_path(),
            'project_dirty': self.facade.is_project_dirty(),

            # Project panel state
            'edit_files': [f.path for f in state.edit_files],
            'source_search_paths': state.settings.source_search_paths,
            'graded_source_paths': state.settings.graded_source_search_paths,

            # Color prep state
            'color_handle_frames': state.settings.color_prep_start_handles,
            'color_separator_frames': state.settings.color_prep_separator,
            'color_split_threshold': state.settings.split_gap_threshold_frames,

            # Online prep state
            'online_output_directory': state.settings.online_output_directory or '',
            'online_handle_frames': state.settings.online_prep_handles,

            # Results state
            'has_analysis_results': bool(state.edit_shots),
            'has_color_segments': state.color_transfer_batch is not None and bool(state.color_transfer_batch.segments),
            'has_online_segments': state.online_transfer_batch is not None and bool(
                state.online_transfer_batch.segments),
        })

        # Update workflow capability flags
        self._update_workflow_capabilities(state)

    def _update_workflow_capabilities(self, state):
        """Update UI state with workflow capabilities based on current state."""
        # Determine what actions are possible
        files_loaded = bool(state.edit_files)
        sources_paths_set = bool(state.settings.source_search_paths)
        analysis_done = bool(state.edit_shots)
        sources_found = analysis_done and any(s.lookup_status == 'found' for s in state.edit_shots)
        color_plan_calculated = state.color_transfer_batch is not None and bool(state.color_transfer_batch.segments)
        online_plan_calculated = state.online_transfer_batch is not None and bool(state.online_transfer_batch.segments)
        can_calc_online = sources_found and bool(state.settings.online_output_directory) and bool(
            state.settings.output_profiles)

        # Update UI state
        self.ui_state.update({
            'color_prep_can_analyze': files_loaded and sources_paths_set,
            'color_prep_can_calculate': sources_found,
            'color_prep_can_export': color_plan_calculated,
            'online_prep_can_calculate': can_calc_online,
            'online_prep_can_transcode': online_plan_calculated,
        })

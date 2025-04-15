# gui2/controllers/project_controller.py
"""
Project Controller for TimelineHarvester

Manages project operations like loading, saving, and creating new projects.
Coordinates between the UI state, event bus, and core facade.
"""

import logging
import os
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSlot

from core.timeline_harvester_facade import TimelineHarvesterFacade
from ..models.ui_state_model import UIStateModel
from ..services.event_bus_service import EventBusService, EventType, EventData
from ..services.state_update_service import StateUpdateService

logger = logging.getLogger(__name__)


class ProjectController(QObject):
    """
    Controller for project operations.

    Responsibilities:
    - Create new projects
    - Load projects from files
    - Save projects to files
    - Manage project state via the core facade
    """

    def __init__(
            self,
            facade: TimelineHarvesterFacade,
            ui_state: UIStateModel,
            event_bus: EventBusService,
            state_update: StateUpdateService
    ):
        """
        Initialize with required dependencies.

        Args:
            facade: Core facade for business logic
            ui_state: UI state model for tracking UI state
            event_bus: Event bus for communication
            state_update: Service for updating UI state from core state
        """
        super().__init__()

        self.facade = facade
        self.ui_state = ui_state
        self.event_bus = event_bus
        self.state_update = state_update

        # Last used directories for file dialogs
        self.last_project_dir = os.path.expanduser("~")

        # Connect to events
        self._connect_to_events()

        logger.debug("ProjectController initialized")

    def _connect_to_events(self):
        """Connect to relevant events from the event bus."""
        self.event_bus.subscribe(EventType.SETTINGS_CHANGED, self._on_settings_changed)

    def new_project(self) -> bool:
        """
        Create a new project.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Creating new project")

        try:
            # Call facade to create new project
            self.facade.new_project()

            # Update UI state
            self.state_update.update_from_facade()

            # Publish event
            self.event_bus.publish(EventData(
                EventType.PROJECT_LOADED,
                project_path=None,
                is_new=True
            ))

            return True

        except Exception as e:
            logger.error(f"Error creating new project: {e}", exc_info=True)
            return False

    def load_project(self, file_path: str) -> bool:
        """
        Load a project from a file.

        Args:
            file_path: Path to the project file

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Loading project from {file_path}")

        try:
            # Update last used directory
            self.last_project_dir = os.path.dirname(file_path)

            # Set UI to busy state
            self.ui_state.set_busy("project_loading", True)

            # Call facade to load project
            if self.facade.load_project(file_path):
                # Update UI state
                self.state_update.update_from_facade()

                # Explicitly update analysis results and segments data
                self.state_update.update_edit_shots_data()
                self.state_update.update_unresolved_shots_data()

                # Get state for debugging
                state = self.facade.get_project_state_snapshot()

                # Log color transfer batch info
                if state.color_transfer_batch:
                    num_segments = len(state.color_transfer_batch.segments)
                    logger.debug(f"Color transfer batch has {num_segments} segments")

                    # Add more detailed logging about segments
                    if num_segments > 0:
                        for i, segment in enumerate(state.color_transfer_batch.segments):
                            source_verified = "verified" if (
                                        segment.original_source and segment.original_source.is_verified) else "not verified"
                            segment_id = segment.segment_id or f"Segment {i}"
                            logger.debug(
                                f"  Segment {i}: ID={segment_id}, Status={segment.status}, Source={source_verified}")

                    # If there are really no segments, log this as a warning
                    if num_segments == 0:
                        logger.warning(
                            "No color segments found in loaded project. Check serialization/deserialization.")
                else:
                    logger.debug("No color transfer batch found in project")

                # Update transfer segments data regardless of whether we think there are segments
                # This ensures UI is updated even if segments exist but were not detected
                self.state_update.update_transfer_segments_data('color')
                self.state_update.update_transfer_segments_data('online')

                # Publish event
                self.event_bus.publish(EventData(
                    EventType.PROJECT_LOADED,
                    project_path=file_path,
                    is_new=False
                ))

                return True
            else:
                logger.error(f"Facade load_project returned False for {file_path}")
                return False

        except Exception as e:
            logger.error(f"Error loading project {file_path}: {e}", exc_info=True)
            return False
        finally:
            # Reset busy state
            self.ui_state.set_busy("project_loading", False)

    def save_project(self, file_path: str) -> bool:
        """
        Save the current project to a file.

        Args:
            file_path: Path where to save the project

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Saving project to {file_path}")

        try:
            # Update last used directory
            self.last_project_dir = os.path.dirname(file_path)

            # Set UI to busy state
            self.ui_state.set_busy("project_saving", True)

            # Call facade to save project
            if self.facade.save_project(file_path):
                # Update UI state
                self.ui_state.set('current_project_path', file_path)
                self.ui_state.set('project_dirty', False)

                # Publish event
                self.event_bus.publish(EventData(
                    EventType.PROJECT_SAVED,
                    project_path=file_path
                ))

                return True
            else:
                logger.error(f"Facade save_project returned False for {file_path}")
                return False

        except Exception as e:
            logger.error(f"Error saving project {file_path}: {e}", exc_info=True)
            return False
        finally:
            # Reset busy state
            self.ui_state.set_busy("project_saving", False)

    @pyqtSlot(EventData)
    def _on_settings_changed(self, event_data: EventData):
        """
        Handle settings changed events.

        Updates the facade and marks the project as dirty.
        """
        setting = event_data.setting
        value = event_data.value

        logger.debug(f"Setting changed: {setting}")

        try:
            # Dispatch based on setting type
            if setting == "edit_files":
                self.facade.set_edit_file_paths(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "source_search_paths":
                self.facade.set_source_search_paths(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "graded_source_paths":
                self.facade.set_graded_source_search_paths(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "source_lookup_strategy":
                self.facade.set_source_lookup_strategy(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "color_prep_handles":
                # Assuming value is a tuple of (start, end)
                if isinstance(value, tuple) and len(value) == 2:
                    self.facade.set_color_prep_handles(value[0], value[1])
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "color_prep_separator":
                self.facade.set_color_prep_separator(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "split_gap_threshold":
                self.facade.set_split_gap_threshold(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "output_profiles":
                self.facade.set_output_profiles(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()
            elif setting == "online_output_directory":
                self.facade.set_online_output_directory(value)
                # Update UI state after facade update
                self.state_update.update_from_facade()

            # Mark project as dirty since a setting changed
            self.ui_state.set('project_dirty', True)

        except Exception as e:
            logger.error(f"Error updating setting {setting}: {e}", exc_info=True)

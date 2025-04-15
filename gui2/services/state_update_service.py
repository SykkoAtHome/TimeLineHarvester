# gui2/services/state_update_service.py
"""
State Update Service for TimelineHarvester

Synchronizes the UI state model with the core application state.
Ensures consistent state representation across the UI.
"""

import logging
import os
from typing import Optional

from core.timeline_harvester_facade import TimelineHarvesterFacade
from ..models.ui_state_model import UIStateModel

logger = logging.getLogger(__name__)


class StateUpdateService:
    """
    Service for updating UI state from the core application state.

    Responsibilities:
    - Synchronize UI state with core state
    - Update UI model when core state changes
    - Provide centralized state mapping logic
    """

    def __init__(self, facade: TimelineHarvesterFacade, ui_state: UIStateModel):
        """
        Initialize the state update service.

        Args:
            facade: Core facade for accessing application state
            ui_state: UI state model to update
        """
        self.facade = facade
        self.ui_state = ui_state

        logger.debug("StateUpdateService initialized")

    def update_from_facade(self):
        """
        Update the UI state model from the current facade state.

        This is called after operations that may change the application state,
        such as loading a project or running analysis.
        """
        logger.debug("Updating UI state from facade")

        try:
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
                'color_same_handles': state.settings.color_prep_start_handles == state.settings.color_prep_end_handles,
                'color_end_handle_frames': state.settings.color_prep_end_handles,
                'color_separator_frames': state.settings.color_prep_separator,
                'color_split_threshold': state.settings.split_gap_threshold_frames,

                # Online prep state
                'online_output_directory': state.settings.online_output_directory or '',
                'online_handle_frames': state.settings.online_prep_handles,
                'output_profiles': [p.__dict__ for p in state.settings.output_profiles],

                # Results state
                'has_analysis_results': bool(state.edit_shots),
                'has_color_segments': state.color_transfer_batch is not None and bool(
                    state.color_transfer_batch.segments),
                'has_online_segments': state.online_transfer_batch is not None and bool(
                    state.online_transfer_batch.segments),
            })

            # Update workflow capability flags
            self._update_workflow_capabilities(state)

            logger.debug("UI state updated from facade")

        except Exception as e:
            logger.error(f"Error updating UI state from facade: {e}", exc_info=True)

    def _update_workflow_capabilities(self, state):
        """
        Update UI state with workflow capabilities based on current state.

        Args:
            state: The current project state from the facade
        """
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

    def update_edit_shots_data(self):
        """
        Update edit shots data in UI state.

        Called after source analysis to update the UI with analysis results.
        """
        try:
            # Get analysis summary from facade
            analysis_summary = self.facade.get_edit_shots_summary()

            # Update UI state
            self.ui_state.set('analysis_data', analysis_summary)
            self.ui_state.set('has_analysis_results', bool(analysis_summary))

            # Update workflow capabilities
            state = self.facade.get_project_state_snapshot()
            self._update_workflow_capabilities(state)

            logger.debug(f"Updated edit shots data ({len(analysis_summary)} shots)")

        except Exception as e:
            logger.error(f"Error updating edit shots data: {e}", exc_info=True)

    def update_transfer_segments_data(self, stage='color'):
        """
        Update transfer segments data in UI state.

        Called after segment calculation to update the UI with results.

        Args:
            stage: 'color' or 'online'
        """
        try:
            # Get segments summary from facade
            segments_summary = self.facade.get_transfer_segments_summary(stage=stage)

            # Log the actual number of segments returned
            logger.debug(f"Received {len(segments_summary)} {stage} segments from facade")

            # Update UI state
            if stage == 'color':
                self.ui_state.set('color_segments_data', segments_summary)
                self.ui_state.set('has_color_segments', bool(segments_summary))
            else:
                self.ui_state.set('online_segments_data', segments_summary)
                self.ui_state.set('has_online_segments', bool(segments_summary))

            # Update workflow capabilities
            state = self.facade.get_project_state_snapshot()
            self._update_workflow_capabilities(state)

            logger.debug(f"Updated {stage} segments data ({len(segments_summary)} segments)")

        except Exception as e:
            logger.error(f"Error updating {stage} segments data: {e}", exc_info=True)

    def update_unresolved_shots_data(self):
        """
        Update unresolved shots data in UI state.

        Called after source analysis or segment calculation to update the UI
        with information about unresolved shots.
        """
        try:
            # Get unresolved summary from facade
            unresolved_summary = self.facade.get_unresolved_shots_summary()

            # Update UI state
            self.ui_state.set('unresolved_data', unresolved_summary)

            logger.debug(f"Updated unresolved shots data ({len(unresolved_summary)} items)")

        except Exception as e:
            logger.error(f"Error updating unresolved shots data: {e}", exc_info=True)
            
# core/processing/calculation_service.py
"""
Service responsible for calculating TransferBatch objects for different
workflow stages (color, online) based on the current ProjectState.
"""

import logging
from typing import List, Optional

# Import state, models, and the calculator module
from ..project_state import ProjectState
from ..models import TransferBatch, EditShot
from .. import calculator as transfer_calculator  # Import the calculator module

logger = logging.getLogger(__name__)


class CalculationService:
    """Calculates TransferBatches and updates the project state."""

    def __init__(self, state: ProjectState):
        """
        Initializes the service with the project state.

        Args:
            state: The ProjectState object to read from and update.
        """
        if not isinstance(state, ProjectState):
            raise TypeError("CalculationService requires a valid ProjectState instance.")
        self.state = state
        logger.debug("CalculationService initialized.")

    def calculate_transfer_batch(self, stage: str) -> bool:
        """
        Calculates the TransferBatch for the specified stage ('color' or 'online')
        and updates the ProjectState.

        Args:
            stage: The target stage ('color' or 'online').

        Returns:
            True if calculation was attempted (even if it resulted in an empty batch
            or errors stored within the batch), False if stage is invalid or a
            critical prerequisite (like settings) is missing before calculation.
        """
        logger.info(f"Starting transfer batch calculation for stage: '{stage}'...")

        # Clear previous results for the target stage in the state
        if stage == 'color':
            self.state.color_transfer_batch = None
        elif stage == 'online':
            self.state.online_transfer_batch = None
        else:
            logger.error(f"Invalid stage specified: '{stage}'. Cannot calculate.")
            return False

        # Gather necessary settings and data from the state
        settings = self.state.settings
        all_shots = self.state.edit_shots

        # Determine settings based on the stage
        if stage == 'color':
            handles_to_use = settings.color_prep_start_handles  # Using start handle symmetrically
            shots_to_process = [s for s in all_shots if s.lookup_status == 'found']
            split_threshold = settings.split_gap_threshold_frames
            profiles_for_stage = []  # Not directly used in color calculation logic
            output_dir_for_stage = None
            batch_name = f"{settings.project_name or 'Project'}_ColorPrep"

        elif stage == 'online':
            handles_to_use = settings.online_prep_handles
            # TODO: Implement graded source finding logic if needed. Using originals for now.
            shots_to_process = [s for s in all_shots if s.lookup_status == 'found']
            split_threshold = -1  # Default: no splitting for online
            profiles_for_stage = settings.output_profiles
            output_dir_for_stage = settings.online_output_directory
            batch_name = f"{settings.project_name or 'Project'}_OnlinePrep"

            # Pre-flight checks for online stage
            if not output_dir_for_stage:
                logger.error("Cannot calculate for Online: Output directory not set in settings.")
                # Create an empty batch with error state
                batch = TransferBatch(handle_frames=handles_to_use, batch_name=f"{batch_name}_Error")
                batch.calculation_errors.append("Online output directory not set.")
                self.state.online_transfer_batch = batch
                return True  # Calculation was "attempted" but failed pre-flight
            if not profiles_for_stage:
                logger.error("Cannot calculate for Online: Output profiles not set in settings.")
                batch = TransferBatch(handle_frames=handles_to_use, batch_name=f"{batch_name}_Error")
                batch.calculation_errors.append("Online output profiles not set.")
                self.state.online_transfer_batch = batch
                return True  # Calculation was "attempted" but failed pre-flight
        else:
            # This case is already handled, but defensively return False
            return False

        # --- Perform Calculation ---
        batch: Optional[TransferBatch] = None
        if not shots_to_process:
            logger.warning(f"[{stage}] No valid shots (status='found') available to calculate segments.")
            # Create an empty batch, but mark it as calculated
            batch = TransferBatch(
                handle_frames=handles_to_use,
                output_directory=output_dir_for_stage,
                batch_name=batch_name,
                output_profiles_used=profiles_for_stage  # Store profiles even if no segments
            )
            # Populate unresolved shots from the main list
            batch.unresolved_shots = [s for s in all_shots if s.lookup_status != 'found']

        else:
            try:
                # Call the core calculator function
                logger.info(
                    f"Calling transfer_calculator for {len(shots_to_process)} shots, stage '{stage}', handles={handles_to_use}f, split_gap={split_threshold}f.")
                calculated_batch = transfer_calculator.calculate_transfer_batch(
                    edit_shots=shots_to_process,
                    handle_frames=handles_to_use,
                    split_gap_threshold_frames=split_threshold
                )
                batch = calculated_batch  # Assign the successfully calculated batch

                # Post-process the calculated batch with project context
                # Add any remaining unresolved shots from the main list
                batch.unresolved_shots.extend(
                    [s for s in all_shots if s.lookup_status != 'found' and s not in batch.unresolved_shots]
                )
                batch.source_edit_files = self.state.edit_files  # Link to edit files from state
                batch.batch_name = batch_name  # Ensure correct batch name
                batch.output_directory = output_dir_for_stage  # Store output dir
                batch.output_profiles_used = profiles_for_stage  # Store profiles used
                batch.handle_frames = handles_to_use  # Store handles used

            except Exception as e:
                logger.error(f"Fatal error during transfer calculation for stage '{stage}': {e}", exc_info=True)
                # Create an error batch state
                batch = TransferBatch(
                    handle_frames=handles_to_use,
                    output_directory=output_dir_for_stage,
                    batch_name=f"{batch_name}_Error",
                    output_profiles_used=profiles_for_stage
                )
                batch.calculation_errors.append(f"Fatal calculation error: {str(e)}")
                batch.unresolved_shots = all_shots  # Mark all as unresolved in this error case

        # --- Update Project State ---
        if stage == 'color':
            self.state.color_transfer_batch = batch
            logger.info(f"Color batch calculation complete. Segments: {len(batch.segments if batch else 0)}")
        elif stage == 'online':
            self.state.online_transfer_batch = batch
            logger.info(f"Online batch calculation complete. Segments: {len(batch.segments if batch else 0)}")

        # Log final batch status summary
        if batch:
            log_msg = f"[{stage}] Batch Summary -> Segments: {len(batch.segments)}, " \
                      f"Unresolved: {len(batch.unresolved_shots)}, " \
                      f"Errors: {len(batch.calculation_errors)}"
            if batch.calculation_errors:
                logger.warning(log_msg)
            else:
                logger.info(log_msg)

        return True  # Indicate calculation process was run

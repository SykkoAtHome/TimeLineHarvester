# core/processing/transcode_service.py
"""
Service responsible for managing and executing the transcoding process
for the 'online' stage using the calculated TransferBatch and FFmpegRunner.
"""

import logging
import os
from typing import Optional, Callable, List, Dict, Tuple

# Import state, models, and the ffmpeg runner module
from ..project_state import ProjectState
from ..models import TransferBatch, OutputProfile
from .. import ffmpeg as ffmpeg_module  # Import the ffmpeg module

logger = logging.getLogger(__name__)


class TranscodeService:
    """Handles the online transcoding workflow."""

    def __init__(self, state: ProjectState):
        """
        Initializes the service with the project state.

        Args:
            state: The ProjectState object containing the data and settings.
        """
        if not isinstance(state, ProjectState):
            raise TypeError("TranscodeService requires a valid ProjectState instance.")
        self.state = state
        # Initialize the FFmpeg runner instance when the service is created
        # This allows checking for ffmpeg executable early, if desired.
        self._ffmpeg_runner: Optional[ffmpeg_module.FFmpegRunner] = None
        try:
            self._ffmpeg_runner = ffmpeg_module.FFmpegRunner()
            if not self._ffmpeg_runner.ffmpeg_path:
                logger.error("FFmpeg executable not found. Transcoding will not be possible.")
                # Keep the runner instance as None to indicate failure
                self._ffmpeg_runner = None
        except Exception as e:
            logger.error(f"Failed to initialize FFmpegRunner: {e}", exc_info=True)
            self._ffmpeg_runner = None

        logger.debug("TranscodeService initialized.")

    def _assign_output_targets(self, batch: TransferBatch) -> Tuple[int, List[str]]:
        """
        Assigns output file paths to each segment based on profiles.
        Updates segment.output_targets in place.

        Args:
            batch: The TransferBatch to process.

        Returns:
            Tuple: (total_tasks_count, list_of_errors)
        """
        if not batch.output_directory:
            return 0, ["Output directory is not set in the batch."]
        if not batch.output_profiles_used:
            return 0, ["No output profiles are assigned to the batch."]

        logger.info("Assigning output target paths for transcoding batch...")
        assign_errors: List[str] = []
        total_tasks = 0
        segment_count = len(batch.segments)

        for index, segment in enumerate(batch.segments):
            segment.output_targets = {}  # Clear previous targets just in case
            segment.status = "pending"  # Reset status before assignment
            segment.error_message = None

            if not segment.original_source or not segment.original_source.path:
                msg = f"Segment {index}/{segment_count} missing original source path information."
                logger.error(msg)
                assign_errors.append(msg)
                segment.status = "failed"
                segment.error_message = msg
                continue  # Skip profiles for this segment

            try:
                original_basename = os.path.splitext(os.path.basename(segment.original_source.path))[0]
            except Exception as path_err:
                msg = f"Segment {index}/{segment_count}: Error processing source path '{segment.original_source.path}': {path_err}"
                logger.error(msg)
                assign_errors.append(msg)
                segment.status = "failed"
                segment.error_message = msg
                continue

            for profile in batch.output_profiles_used:
                try:
                    # Construct filename: <OriginalName>_<ProfileName>_<SegmentIndex>.<ProfileExt>
                    # Using 4-digit padding for index ensures reasonable sorting
                    output_filename = f"{original_basename}_{profile.name}_{index:04d}.{profile.extension}"
                    # Ensure filename is valid for the OS (basic sanitization might be needed)
                    # output_filename = sanitize_filename(output_filename) # Add if needed
                    output_path = os.path.join(batch.output_directory, output_filename)

                    segment.output_targets[profile.name] = output_path
                    total_tasks += 1
                    # logger.debug(f"  Assigned target for seg {index}, profile '{profile.name}': {output_path}")

                except Exception as name_err:
                    msg = f"Segment {index}/{segment_count}: Error creating output name for profile '{profile.name}': {name_err}"
                    logger.error(msg, exc_info=True)  # Log traceback for naming errors
                    assign_errors.append(msg)
                    segment.status = "failed"
                    segment.error_message = msg
                    # Stop processing profiles for this segment if naming fails for one
                    break

        if assign_errors:
            logger.error(f"Errors occurred during output target assignment: {len(assign_errors)}")
        else:
            logger.info(f"Successfully assigned {total_tasks} output targets.")

        return total_tasks, assign_errors

    def run_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """
        Executes the transcoding process for the online TransferBatch stored in the state.

        Args:
            progress_callback: Optional function to receive progress updates.

        Raises:
            RuntimeError: If FFmpeg runner is not available.
            ValueError: If the online batch is not ready for transcoding (not calculated,
                        no segments, missing settings, or assignment errors).
        """
        logger.info("Attempting to start online transcoding process via TranscodeService...")

        if not self._ffmpeg_runner:
            raise RuntimeError("FFmpeg runner is not available. Cannot start transcoding.")

        batch_to_run = self.state.online_transfer_batch
        settings = self.state.settings

        # --- Pre-flight Checks ---
        if not batch_to_run:
            raise ValueError("Online transfer batch has not been calculated yet.")
        if not batch_to_run.segments:
            if batch_to_run.calculation_errors:
                raise ValueError(
                    f"Cannot transcode: Online calculation failed with errors: {'; '.join(batch_to_run.calculation_errors)}")
            else:
                raise ValueError("Cannot transcode: Online batch contains no segments.")
        if not settings.online_output_directory:  # Check settings directly
            raise ValueError("Cannot transcode: Online output directory not configured in project settings.")
        if not settings.output_profiles:  # Check settings directly
            raise ValueError("Cannot transcode: No output profiles configured in project settings.")

        # Ensure the batch object has the correct settings assigned (redundant if CalculationService did it)
        batch_to_run.output_directory = settings.online_output_directory
        batch_to_run.output_profiles_used = settings.output_profiles

        # --- Assign Output Targets ---
        # This step generates the `segment.output_targets` dict needed by the FFmpegRunner
        total_tasks, assignment_errors = self._assign_output_targets(batch_to_run)

        if assignment_errors:
            error_summary = "; ".join(assignment_errors)
            raise ValueError(f"Cannot transcode due to errors assigning output targets: {error_summary}")
        if total_tasks == 0:
            raise ValueError("Cannot transcode: No output tasks were generated after assigning targets.")

        # --- Ensure Output Directory Exists ---
        try:
            os.makedirs(settings.online_output_directory, exist_ok=True)
            logger.info(f"Ensured online output directory exists: {settings.online_output_directory}")
        except OSError as e:
            raise OSError(f"Cannot create online output directory '{settings.online_output_directory}': {e}") from e

        # --- Execute Transcoding ---
        try:
            logger.info(
                f"Executing FFmpeg runner for ONLINE batch: {len(batch_to_run.segments)} segments, {total_tasks} total tasks.")
            # The runner will update the status of segments within the batch_to_run object directly
            self._ffmpeg_runner.run_batch(batch_to_run, progress_callback)
            logger.info("Transcoding process finished by FFmpeg runner.")
            # Note: The ProjectState is implicitly updated because the runner modified
            # the TransferBatch object held within the state.
        except Exception as e:
            # Log the error and re-raise to be handled by the caller (e.g., WorkerThread)
            logger.error(f"Online transcoding run failed within TranscodeService: {e}", exc_info=True)
            raise RuntimeError(f"Transcoding execution failed: {str(e)}") from e

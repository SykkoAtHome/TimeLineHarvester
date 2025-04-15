# -*- coding: utf-8 -*-
"""
core/ffmpeg.py

Handles FFmpeg command generation and execution for transcoding tasks.
"""

import logging
import os
import subprocess
from typing import Callable, List, Optional

# Use absolute imports for clarity and robustness
from utils import find_executable
from .models import OutputProfile, TransferBatch, TransferSegment

logger = logging.getLogger(__name__)

# --- Constants ---
# Default timeout for FFmpeg process communication (in seconds)
DEFAULT_FFMPEG_TIMEOUT = 3600  # 1 hour


# --- FFmpeg Command Generation ---

def generate_ffmpeg_command(
        segment: TransferSegment,
        profile: OutputProfile,
        output_path: str,
        ffmpeg_exe_path: str) -> Optional[List[str]]:
    """
    Generates the FFmpeg command arguments as a list for a single segment and profile.

    This currently creates a basic command focusing on input trimming (-ss, -i, -t).
    More complex options like codec settings, filters, metadata mapping, and
    timecode handling should be incorporated by defining them within the
    OutputProfile or handled via more sophisticated logic here.

    Args:
        segment: The TransferSegment containing source file info and time range.
        profile: The OutputProfile defining the target format characteristics.
                 (Currently only uses profile.extension, expects detailed options elsewhere).
        output_path: The full destination path for the transcoded file.
        ffmpeg_exe_path: The full path to the FFmpeg executable.

    Returns:
        A list of strings representing the command and arguments for subprocess,
        or None if essential information is missing or invalid.
    """
    if not ffmpeg_exe_path or not os.path.exists(ffmpeg_exe_path):
        logger.error("FFmpeg executable not found at '%s'. Cannot generate command.", ffmpeg_exe_path)
        return None

    if not segment.original_source or not os.path.exists(segment.original_source.path):
        source_path = segment.original_source.path if segment.original_source else "None"
        logger.error(
            "Original source file '%s' for segment not found or segment has no source. Cannot generate command for '%s'.",
            source_path, os.path.basename(output_path)
        )
        return None

    if not segment.transfer_source_range or segment.transfer_source_range.duration.value <= 0:
        logger.error(
            "Invalid time range duration (<= 0) for segment from source '%s'. Cannot generate command for '%s'.",
            segment.original_source.path if segment.original_source else "N/A",
            os.path.basename(output_path)
        )
        return None

    # Extract time range information
    input_file = segment.original_source.path
    start_time_sec = segment.transfer_source_range.start_time.to_seconds()
    duration_sec = segment.transfer_source_range.duration.to_seconds()

    # Basic command structure: ffmpeg -y -ss [start] -i [input] -t [duration] ... [output]
    command = [
        ffmpeg_exe_path,
        '-y',  # Overwrite output files without asking
        '-ss', f"{start_time_sec:.6f}",  # Input seeking (accurate for many formats)
        '-i', input_file,
        '-t', f"{duration_sec:.6f}",  # Duration of the segment to encode
        # '-nostdin', # Prevent ffmpeg from reading from stdin, useful in some contexts
    ]

    # --- TODO: Add Profile-Specific Options ---
    # This is where options from the `OutputProfile` should be inserted.
    # For example: profile.codec_options, profile.filter_options etc.
    # Example placeholder:
    # if profile.video_codec:
    #     command.extend(['-c:v', profile.video_codec])
    # if profile.audio_codec:
    #     command.extend(['-c:a', profile.audio_codec])
    # Placeholder: Currently, no options from profile are used besides extension.
    # command.extend(profile.ffmpeg_options) # Assumes profile has an 'ffmpeg_options' list attribute

    # --- TODO: Add Metadata/Timecode Handling ---
    # Options like '-map_metadata', '-timecode' should be added here based
    # on requirements and source file properties.

    # Add the output path
    command.append(output_path)

    # logger.debug(f"Generated FFmpeg command: {' '.join(command)}")
    return command


# --- FFmpeg Runner Class ---

class FFmpegRunner:
    """
    Manages the execution of FFmpeg commands for transcoding batches.

    Finds the FFmpeg executable upon initialization and provides a method
    to run transcoding tasks sequentially for a given TransferBatch.
    Includes basic error handling and progress reporting via a callback.
    """

    def __init__(self, ffmpeg_path: Optional[str] = None):
        """
        Initializes the FFmpegRunner.

        Args:
            ffmpeg_path: Optional path to the FFmpeg executable. If None,
                         it attempts to find it using `find_executable`.
        """
        if ffmpeg_path and os.path.exists(ffmpeg_path):
            self.ffmpeg_path = ffmpeg_path
        else:
            self.ffmpeg_path = find_executable("ffmpeg")

        if not self.ffmpeg_path:
            logger.critical(
                "FFmpeg executable not found. Transcoding operations will fail. "
                "Please ensure FFmpeg is installed and in the system's PATH "
                "or provide the path during initialization."
            )
            # Note: We don't raise an error here to allow the application
            # to potentially run other non-transcoding tasks, but run_batch will fail.
        else:
            logger.info("FFmpegRunner initialized. Using FFmpeg at: %s", self.ffmpeg_path)

    def run_batch(self,
                  batch: TransferBatch,
                  progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """
        Executes FFmpeg sequentially for all valid segments and profiles in the batch.

        Updates the status and error_message attributes of each TransferSegment
        based on the outcome of its associated transcoding tasks.

        Args:
            batch: The TransferBatch containing segments and output targets.
            progress_callback: An optional function to report progress. It should
                               accept (completed_tasks, total_tasks, message).

        Raises:
            RuntimeError: If FFmpeg executable was not found during initialization.
                          or if essential batch configuration is missing.
        """
        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg executable was not found. Cannot run batch.")

        if not batch.output_profiles_used:
            logger.error("Cannot run batch: No output profiles defined in the batch.")
            # Mark all processable segments as failed
            for segment in batch.segments:
                if segment.status != "failed":  # Avoid overwriting previous specific errors
                    segment.status = "failed"
                    segment.error_message = "Batch has no defined output profiles."
            if progress_callback:
                progress_callback(0, 0, "Error: Batch has no output profiles.")
            return  # Cannot proceed

        if not batch.output_directory:
            logger.error("Cannot run batch: Output directory not defined in the batch.")
            for segment in batch.segments:
                if segment.status != "failed":
                    segment.status = "failed"
                    segment.error_message = "Batch has no defined output directory."
            if progress_callback:
                progress_callback(0, 0, "Error: Batch has no output directory.")
            return  # Cannot proceed

        # Filter segments that might have failed during calculation phase
        segments_to_process = [s for s in batch.segments if s.status != "failed"]
        total_tasks = sum(len(s.output_targets) for s in segments_to_process)
        completed_tasks = sum(
            len(s.output_targets) for s in batch.segments if s.status == "failed")  # Count pre-failed tasks

        if total_tasks == 0 and completed_tasks > 0:
            logger.warning("FFmpeg batch run: All tasks were already marked as failed before execution.")
        elif total_tasks == 0:
            logger.warning("FFmpeg batch run: No tasks to execute.")
            if progress_callback: progress_callback(0, 0, "No tasks to execute.")
            return
        else:
            logger.info("Starting FFmpeg batch run for %d tasks.", total_tasks)

        if progress_callback:
            progress_callback(completed_tasks, total_tasks + completed_tasks,
                              "Starting FFmpeg batch...")  # Initial report

        for segment in segments_to_process:
            segment.status = "pending"  # Reset status before processing profiles
            segment.error_message = None  # Clear previous non-fatal errors if any

            segment_failed = False
            for profile_name, output_path in segment.output_targets.items():
                # Ensure output directory exists
                output_dir = os.path.dirname(output_path)
                try:
                    if not os.path.exists(output_dir):
                        os.makedirs(output_dir)
                        logger.info("Created output directory: %s", output_dir)
                except OSError as e:
                    msg = f"Failed to create output directory '{output_dir}': {e}"
                    logger.error(msg)
                    segment.status = "failed"
                    segment.error_message = msg
                    segment_failed = True
                    # Increment completed tasks count for all remaining targets in this segment
                    remaining_tasks_in_segment = len(segment.output_targets) - completed_tasks % len(
                        segment.output_targets)
                    completed_tasks += remaining_tasks_in_segment
                    break  # Stop processing profiles for this segment

                # Find the corresponding OutputProfile definition
                profile = next((p for p in batch.output_profiles_used if p.name == profile_name), None)
                if not profile:
                    msg = f"OutputProfile '{profile_name}' not found in batch definition. Cannot transcode target '{os.path.basename(output_path)}'."
                    logger.error(msg)
                    segment.status = "failed"
                    segment.error_message = msg
                    segment_failed = True
                    completed_tasks += 1  # Count this failed task
                    break  # Stop processing other profiles for this segment

                # Generate the FFmpeg command
                command = generate_ffmpeg_command(segment, profile, output_path, self.ffmpeg_path)
                if not command:
                    # Error already logged by generate_ffmpeg_command
                    msg = f"Command generation failed for '{os.path.basename(output_path)}'."
                    segment.status = "failed"
                    # Check if generate_ffmpeg_command already set an error, otherwise use generic one
                    segment.error_message = segment.error_message or msg
                    segment_failed = True
                    completed_tasks += 1  # Count this failed task
                    break  # Stop processing other profiles for this segment

                # --- Execute FFmpeg ---
                segment.status = "running"  # Status applies to the segment being processed
                task_message = f"Transcoding: {os.path.basename(output_path)}"
                logger.info(task_message)
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks + completed_tasks, task_message)

                process = None  # Ensure process variable is defined
                try:
                    # Execute the command - this is a blocking call
                    logger.debug("Executing FFmpeg command: %s", ' '.join(command))
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,  # Decode stdout/stderr as text
                        encoding='utf-8',
                        errors='ignore',  # Ignore decoding errors in FFmpeg output
                        # Hide console window on Windows
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    # Wait for the process to complete, capture output
                    stdout, stderr = process.communicate(timeout=DEFAULT_FFMPEG_TIMEOUT)

                    if process.returncode == 0:
                        logger.info("FFmpeg SUCCESS for: %s", output_path)
                        # Status remains 'running' or 'pending' until all profiles for segment are done
                    else:
                        msg = f"FFmpeg FAILED (code {process.returncode}) for: '{os.path.basename(output_path)}'"
                        logger.error(msg)
                        # Log the last part of stderr for debugging, avoiding excessively large logs
                        if stderr:
                            logger.error("FFmpeg stderr (last 1000 chars):\n%s", stderr[-1000:])
                        segment.status = "failed"
                        segment.error_message = f"{msg} (Code {process.returncode})"
                        segment_failed = True
                        completed_tasks += 1  # Count this failed task
                        break  # Stop processing other profiles for this segment on failure

                except subprocess.TimeoutExpired:
                    msg = f"FFmpeg TIMEOUT ({DEFAULT_FFMPEG_TIMEOUT}s) for: '{os.path.basename(output_path)}'"
                    logger.error(msg)
                    segment.status = "failed"
                    segment.error_message = msg
                    segment_failed = True
                    if process:
                        try:
                            process.kill()  # Terminate the runaway process
                            process.communicate()  # Clean up resources
                        except Exception as kill_err:
                            logger.warning("Error trying to kill timed-out FFmpeg process: %s", kill_err)
                    completed_tasks += 1  # Count this failed task
                    break  # Stop processing other profiles for this segment

                except Exception as e:
                    msg = f"Unexpected error running FFmpeg for '{os.path.basename(output_path)}': {e}"
                    logger.error(msg, exc_info=True)  # Include traceback for unexpected errors
                    segment.status = "failed"
                    segment.error_message = msg
                    segment_failed = True
                    completed_tasks += 1  # Count this failed task
                    break  # Stop processing other profiles for this segment

                finally:
                    # Always count the task completion, successful or not (unless loop broken early)
                    if not segment_failed:
                        completed_tasks += 1
                    # Update overall progress after each task attempt
                    if progress_callback:
                        final_task_msg = f"Failed: {os.path.basename(output_path)}" if segment_failed else f"Done: {os.path.basename(output_path)}"
                        progress_callback(completed_tasks, total_tasks + completed_tasks, final_task_msg)

            # After processing all profiles for a segment:
            if not segment_failed:
                segment.status = "completed"  # Mark segment completed only if all profiles succeeded

        final_total_tasks = total_tasks + completed_tasks  # Recalculate based on actual completed count
        logger.info("FFmpeg batch run finished processing all segments.")
        # Final progress update
        if progress_callback:
            progress_callback(final_total_tasks, final_total_tasks, "Batch finished.")

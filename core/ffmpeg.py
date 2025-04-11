# core/ffmpeg.py
"""
Manages FFmpeg command generation and execution for transcoding.
(Basic implementation - primarily placeholder for now)
"""

import logging
import subprocess
import os
from typing import List, Optional, Callable, Dict

# Import necessary models
from .models import TransferSegment, OutputProfile, TransferBatch
# Import executable finder utility
from utils import find_executable  # Use absolute import

logger = logging.getLogger(__name__)


# --- FFmpeg Command Generation ---
def generate_ffmpeg_command(
        segment: TransferSegment,
        profile: OutputProfile,
        output_path: str,
        ffmpeg_exe_path: str) -> Optional[List[str]]:
    """
    Generates an FFmpeg command list for a single segment and profile.
    (Basic implementation - needs more options for metadata, timecode etc.)

    Args:
        segment: The TransferSegment to transcode.
        profile: The OutputProfile defining the target format.
        output_path: The full path for the output file.
        ffmpeg_exe_path: The full path to the ffmpeg executable.

    Returns:
        A list of strings representing the command and its arguments, or None on error.
    """
    if not ffmpeg_exe_path or not os.path.exists(ffmpeg_exe_path):
        logger.error("Cannot generate command: FFmpeg executable path is invalid or missing.")
        return None
    if not segment.original_source or not os.path.exists(segment.original_source.path):
        logger.error(
            f"Cannot generate command for '{os.path.basename(output_path)}': Original source file not found at '{segment.original_source.path}'")
        return None
    if not segment.transfer_source_range or segment.transfer_source_range.duration.value <= 0:
        logger.error(f"Cannot generate command for '{os.path.basename(output_path)}': Invalid segment duration.")
        return None

    input_file = segment.original_source.path
    start_time_sec = segment.transfer_source_range.start_time.to_seconds()
    duration_sec = segment.transfer_source_range.duration.to_seconds()

    # Basic command structure
    command = [
        ffmpeg_exe_path,
        '-y',  # Overwrite output without asking
        '-ss', f"{start_time_sec:.6f}",
        '-i', input_file,
        '-t', f"{duration_sec:.6f}",
        # Basic handling for audio/video only profiles
        # Assumes profile options include -an or -vn if needed
        # '-vn' if '-an' in profile.ffmpeg_options else '', # Re-evaluate if needed
        # '-an' if '-vn' in profile.ffmpeg_options else '',
    ]
    # command = [arg for arg in command if arg] # Filter empty strings

    # Add profile-specific options
    command.extend(profile.ffmpeg_options)

    # TODO: Add metadata/timecode options here later

    # Add output path
    command.append(output_path)

    logger.debug(f"Generated FFmpeg command: {' '.join(command)}")
    return command


# --- FFmpeg Runner Class ---
class FFmpegRunner:
    """
    Executes FFmpeg commands.
    (Basic implementation - runs sequentially, no progress parsing yet)
    """

    def __init__(self):
        # Find ffmpeg executable path during initialization
        self.ffmpeg_path = find_executable("ffmpeg")
        if not self.ffmpeg_path:
            logger.critical("FFmpeg executable not found. Transcoding will not function.")
            # Consider raising an error here if FFmpeg is essential?
            # raise FileNotFoundError("FFmpeg executable not found.")
        else:
            logger.info(f"FFmpegRunner initialized. Using FFmpeg at: {self.ffmpeg_path}")

    def run_batch(self,
                  batch: TransferBatch,
                  progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """
        Runs FFmpeg sequentially for all segments and profiles in the batch.

        Args:
            batch: The TransferBatch containing segments and targets.
            progress_callback: Optional function called with (completed_tasks, total_tasks, message).
        """
        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg executable not found. Cannot run batch.")

        # Check if batch has necessary info
        if not batch.output_profiles_used:
            logger.error("Cannot run batch: No output profiles associated with the batch.")
            # Mark all segments as failed?
            for segment in batch.segments: segment.status = "failed"; segment.error_message = "No output profiles defined for batch."
            return
        if not batch.output_directory:
            logger.error("Cannot run batch: No output directory defined for the batch.")
            for segment in batch.segments: segment.status = "failed"; segment.error_message = "No output directory defined for batch."
            return

        total_tasks = sum(
            len(seg.output_targets) for seg in batch.segments if seg.status != 'failed')  # Count only tasks to be run
        completed_tasks = 0
        logger.info(f"Starting FFmpeg batch run for {total_tasks} tasks.")

        if progress_callback:
            progress_callback(completed_tasks, total_tasks, f"Starting FFmpeg batch...")

        for segment in batch.segments:
            # Skip segments already marked as failed during calculation
            if segment.status == "failed":
                logger.warning(
                    f"Skipping segment for '{os.path.basename(segment.original_source.path)}' due to previous error.")
                # Ensure we count the implied tasks as "complete" for progress
                completed_tasks += len(segment.output_targets)
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, f"Skipped segment (prev error)")
                continue

            # Reset status before processing this segment's profiles
            segment.status = "pending"
            segment.error_message = None  # Clear previous error message if any

            for profile_name, output_path in segment.output_targets.items():
                # Find the profile definition
                profile = next((p for p in batch.output_profiles_used if p.name == profile_name), None)
                if not profile:
                    msg = f"Profile '{profile_name}' not found for target '{output_path}'."
                    logger.error(msg)
                    segment.status = "failed"
                    segment.error_message = msg
                    break  # Fail the whole segment if a profile is missing

                # Generate command
                command = generate_ffmpeg_command(segment, profile, output_path, self.ffmpeg_path)
                if not command:
                    msg = f"CmdGen failed for '{os.path.basename(output_path)}'."
                    logger.error(msg)
                    segment.status = "failed"
                    segment.error_message = msg
                    break  # Fail the segment

                # --- Execute FFmpeg ---
                segment.status = "running"
                task_message = f"Transcoding: {os.path.basename(output_path)}"
                logger.info(task_message)
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, task_message)

                try:
                    # Execute blocking call (replace with non-blocking later)
                    logger.debug(f"Executing: {' '.join(command)}")
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding='utf-8', errors='ignore',
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        # Hide console window on Windows
                    )
                    stdout, stderr = process.communicate(timeout=3600)  # Add generous timeout (1 hour)

                    if process.returncode == 0:
                        logger.info(f"FFmpeg SUCCESS for: {output_path}")
                        # Status remains 'running' until all profiles for segment are done
                    else:
                        msg = f"FFmpeg FAILED (code {process.returncode}) for: '{os.path.basename(output_path)}'"
                        logger.error(msg)
                        logger.error(f"Stderr (last 1k): ...\n{stderr[-1000:]}")
                        segment.status = "failed"
                        segment.error_message = msg + f" (Code {process.returncode})"
                        break  # Stop processing other profiles for this segment on failure

                except subprocess.TimeoutExpired:
                    msg = f"FFmpeg TIMEOUT for: '{os.path.basename(output_path)}'"
                    logger.error(msg)
                    segment.status = "failed"
                    segment.error_message = msg
                    # Try to kill the process
                    try:
                        process.kill(); process.communicate()
                    except:
                        pass
                    break
                except Exception as e:
                    msg = f"Unexpected error running FFmpeg for '{os.path.basename(output_path)}': {e}"
                    logger.error(msg, exc_info=True)
                    segment.status = "failed"
                    segment.error_message = msg
                    break  # Stop processing this segment
                finally:
                    completed_tasks += 1
                    # Update overall progress after each task attempt
                    if progress_callback:
                        final_task_msg = f"Done: {os.path.basename(output_path)}" if segment.status != "failed" else f"Failed: {os.path.basename(output_path)}"
                        progress_callback(completed_tasks, total_tasks, final_task_msg)

            # After processing all profiles for a segment:
            if segment.status != "failed":
                segment.status = "completed"  # Mark segment as completed only if all profiles succeeded

        logger.info("FFmpeg batch run finished processing all segments.")
        # Final progress update
        if progress_callback:
            progress_callback(total_tasks, total_tasks, "Batch finished.")

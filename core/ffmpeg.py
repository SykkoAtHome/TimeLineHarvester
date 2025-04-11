# core/ffmpeg.py
"""
Manages FFmpeg command generation and execution for transcoding TransferSegments.

Assumes ffmpeg and ffprobe executables might need to be located dynamically,
not necessarily rely on the system PATH.
"""

import logging
import subprocess
import os
import sys  # Needed for sys._MEIPASS later
import shutil  # For shutil.which fallback
from typing import List, Optional, Callable, Dict

# Import necessary models
from .models import TransferSegment, OutputProfile, TransferBatch

logger = logging.getLogger(__name__)


# --- Helper Function to find Executables (Needs Improvement for Bundling) ---
def find_executable(name: str) -> Optional[str]:
    """
    Attempts to find an executable (ffmpeg or ffprobe).
    Placeholder: Checks PATH first, needs update for bundled apps.

    Args:
        name: Name of the executable (e.g., "ffmpeg", "ffprobe").

    Returns:
        Absolute path to the executable or None if not found.
    """
    # TODO: Implement robust finding for bundled executables (PyInstaller)
    # Check if running in a PyInstaller bundle
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # If bundled, executable should be in the same directory as the main executable
        # or potentially a subfolder depending on bundling settings.
        bundle_dir = sys._MEIPASS
        exe_path = os.path.join(bundle_dir, f"{name}.exe" if os.name == 'nt' else name)
        if os.path.exists(exe_path):
            logger.info(f"Found bundled executable: {exe_path}")
            return exe_path
        else:
            # Maybe it's in a specific subfolder? Adjust as needed.
            # e.g., exe_path = os.path.join(bundle_dir, 'bin', f"{name}.exe"...)
            logger.warning(f"Could not find '{name}' in PyInstaller bundle directory: {bundle_dir}")
            # Fall through to check PATH as a last resort? Or fail? Failing is safer.
            # return shutil.which(name) # Fallback to PATH (optional)
            return None  # Fail if not found in bundle


    # If not bundled, check system PATH as a fallback
    else:
        logger.debug(f"Not running in PyInstaller bundle, checking PATH for '{name}'.")
        exe_path = shutil.which(name)
        if exe_path:
            logger.info(f"Found executable in PATH: {exe_path}")
            return exe_path
        else:
            logger.error(f"Executable '{name}' not found in system PATH.")
            return None


# --- FFmpeg Command Generation ---
def generate_ffmpeg_command(
        segment: TransferSegment,
        profile: OutputProfile,
        output_path: str,
        ffmpeg_exe_path: str) -> Optional[List[str]]:
    """
    Generates an FFmpeg command list for a single segment and profile.

    Args:
        segment: The TransferSegment to transcode.
        profile: The OutputProfile defining the target format.
        output_path: The full path for the output file.
        ffmpeg_exe_path: The full path to the ffmpeg executable.

    Returns:
        A list of strings representing the command and its arguments, or None on error.
    """
    if not os.path.exists(segment.original_source.path):
        logger.error(
            f"Cannot generate command for '{output_path}': Original source file not found at '{segment.original_source.path}'")
        return None

    # Input file path needs careful handling for quoting/escaping if names are complex
    input_file = segment.original_source.path

    # Time range conversion (RationalTime to seconds)
    if not segment.transfer_source_range:
        logger.error(f"Cannot generate command for '{output_path}': Segment has no transfer range.")
        return None

    start_time = segment.transfer_source_range.start_time
    duration = segment.transfer_source_range.duration

    if duration.value <= 0:
        logger.error(f"Cannot generate command for '{output_path}': Segment duration is zero or negative ({duration}).")
        return None

    # Use floating point seconds for -ss and -t for better precision
    start_time_sec = start_time.to_seconds()
    duration_sec = duration.to_seconds()

    # Basic FFmpeg command structure
    command = [
        ffmpeg_exe_path,
        '-y',  # Overwrite output files without asking
        # Input options - specify start time BEFORE input for faster seeking
        '-ss', f"{start_time_sec:.6f}",  # Use high precision for start time
        '-i', input_file,  # Input file path
        # Output options - specify duration AFTER input
        '-t', f"{duration_sec:.6f}",  # Duration to process, high precision
        # '-to', f"{start_time_sec + duration_sec:.6f}", # Alternative to -t
        '-vn' if '-an' in profile.ffmpeg_options else '',  # Add -vn if only audio specified
        '-an' if '-vn' in profile.ffmpeg_options else '',  # Add -an if only video specified
    ]
    # Filter out empty strings from -vn/-an logic
    command = [arg for arg in command if arg]

    # Add profile-specific options from the OutputProfile model
    command.extend(profile.ffmpeg_options)

    # --- Metadata and Timecode Handling (Optional but Recommended) ---
    # TODO: Add options to preserve or set timecode if needed.
    # Example: Map source timecode using -map_metadata and -timecode
    # if segment.original_source.start_timecode:
    #     start_tc_str = segment.transfer_source_range.start_time.to_timecode(
    #         rate=segment.original_source.frame_rate,
    #         start_time=segment.original_source.start_timecode # Use original start TC as base
    #     )
    #     command.extend(['-timecode', start_tc_str])
    # command.extend(['-map_metadata', '0']) # Copy global metadata from input

    # Add output path (needs careful handling if paths contain spaces/special chars)
    command.append(output_path)

    logger.debug(f"Generated FFmpeg command for '{os.path.basename(output_path)}': {' '.join(command)}")
    return command


# --- FFmpeg Runner Class ---
class FFmpegRunner:
    """
    Executes FFmpeg commands for a TransferBatch, managing processes.
    """

    def __init__(self):
        self.ffmpeg_path = find_executable("ffmpeg")
        self.active_processes = []  # Could be used for parallel execution later
        if not self.ffmpeg_path:
            logger.critical("FFmpeg executable not found. Transcoding will fail.")
            # Optionally raise an error here to prevent proceeding

    def run_batch(self,
                  batch: TransferBatch,
                  progress_callback: Optional[Callable[[int, int, str], None]] = None):
        # Progress callback now takes (current_task, total_tasks, message)
        """
        Runs FFmpeg sequentially for all segments and profiles in the batch.

        Args:
            batch: The TransferBatch containing segments and targets.
            progress_callback: Optional function called with (completed_tasks, total_tasks, message).
        """
        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg executable not found. Cannot run batch.")

        total_tasks = sum(len(seg.output_targets) for seg in batch.segments)
        completed_tasks = 0
        logger.info(f"Starting FFmpeg batch run for {total_tasks} tasks.")

        if progress_callback:
            progress_callback(completed_tasks, total_tasks, f"Starting batch ({total_tasks} tasks)...")

        for segment in batch.segments:
            # Reset status only if it wasn't already failed during calculation
            if segment.status != "failed":
                segment.status = "pending"

            # Skip segments already marked as failed during calculation
            if segment.status == "failed":
                logger.warning(
                    f"Skipping segment for {segment.original_source.path} due to previous calculation error: {segment.error_message}")
                # Count failed calculation as a 'completed' task for progress
                completed_tasks += len(segment.output_targets)
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, f"Skipped segment (calculation error)")
                continue

            for profile_name, output_path in segment.output_targets.items():
                # Find the corresponding profile object from the batch config
                profile = next((p for p in batch.output_profiles_used if p.name == profile_name), None)

                if not profile:
                    msg = f"Output profile '{profile_name}' definition not found in batch for segment target '{output_path}'. Skipping."
                    logger.error(msg)
                    segment.status = "failed"  # Mark the whole segment as failed if profile is missing
                    segment.error_message = segment.error_message + f"; {msg}" if segment.error_message else msg
                    # Break inner loop? Or just skip this profile? Skipping profile is safer.
                    completed_tasks += 1  # Count this skipped task
                    if progress_callback:
                        progress_callback(completed_tasks, total_tasks, f"Skipped task (profile missing)")
                    continue  # Skip this profile target

                # Generate the command
                command = generate_ffmpeg_command(segment, profile, output_path, self.ffmpeg_path)

                if not command:
                    msg = f"Failed to generate FFmpeg command for '{output_path}'."
                    logger.error(msg)
                    segment.status = "failed"
                    segment.error_message = segment.error_message + f"; {msg}" if segment.error_message else msg
                    # Break inner loop if command generation fails for one profile? Probably yes.
                    break  # Stop processing other profiles for this segment

                # --- Execute FFmpeg Command ---
                segment.status = "running"
                task_message = f"Processing: {os.path.basename(output_path)}"
                logger.info(task_message)
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, task_message)

                try:
                    # Run FFmpeg process - This is blocking!
                    # TODO: Implement non-blocking execution with threading/asyncio
                    #       and stderr parsing for real-time progress within a single task.
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    stdout, stderr = process.communicate()  # Wait for completion

                    if process.returncode == 0:
                        logger.info(f"FFmpeg successfully finished for: {output_path}")
                        # Status will be set to 'completed' after the outer loop for the segment
                    else:
                        msg = f"FFmpeg failed for '{output_path}'. Exit code: {process.returncode}"
                        logger.error(msg)
                        logger.error(f"FFmpeg stderr (last 1000 chars):\n{stderr[-1000:]}")
                        segment.status = "failed"
                        segment.error_message = segment.error_message + f"; {msg}" if segment.error_message else msg
                        # Optional: Break inner loop on first profile failure for a segment?
                        # break

                except FileNotFoundError:
                    # Should be caught by initial check, but handle again just in case
                    msg = f"FFmpeg command '{self.ffmpeg_path}' not found during execution."
                    logger.critical(msg)
                    segment.status = "failed"
                    segment.error_message = segment.error_message + f"; {msg}" if segment.error_message else msg
                    raise RuntimeError(msg) from None  # Stop the whole batch
                except Exception as e:
                    msg = f"Unexpected error running FFmpeg for '{output_path}': {e}"
                    logger.error(msg, exc_info=True)
                    segment.status = "failed"
                    segment.error_message = segment.error_message + f"; {msg}" if segment.error_message else msg
                    # Optional: Break inner loop?
                    # break
                finally:
                    completed_tasks += 1
                    # Update progress after each profile is processed or skipped/failed
                    if progress_callback:
                        # Use a message reflecting the last action's outcome
                        final_task_msg = f"Finished: {os.path.basename(output_path)}" if segment.status != "failed" else f"Failed: {os.path.basename(output_path)}"
                        progress_callback(completed_tasks, total_tasks, final_task_msg)

            # After processing all profiles for a segment:
            if segment.status != "failed":
                segment.status = "completed"  # Mark as completed only if all profiles succeeded

        logger.info("FFmpeg batch run finished.")
        # Final progress update
        if progress_callback:
            progress_callback(total_tasks, total_tasks, "Batch complete.")

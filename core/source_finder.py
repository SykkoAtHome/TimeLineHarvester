# core/source_finder.py
"""
Finds and verifies original source media files based on information
extracted from edit timelines (EditShot objects).

Relies on external tools like ffprobe for verification.
Handles finding bundled executables.
"""

import json
import logging
import os
import subprocess
from typing import List, Optional, Dict

from opentimelineio import opentime  # Explicit import for time objects

# Import necessary models
from .models import EditShot, OriginalSourceFile

# Import the consolidated executable finder from utils
from utils import find_executable

# Note: time_utils are not directly used here anymore, but handle_utils might be needed by calculator
# from utils import time_utils

logger = logging.getLogger(__name__)  # Use module-specific logger

# --- SourceFinder Class ---
class SourceFinder:
    """
    Locates and verifies original source files corresponding to EditShots.
    Manages a cache of verified source files to minimize ffprobe calls.
    """

    def __init__(self, search_paths: List[str], strategy: str = "basic_name_match"):
        """
        Initializes the SourceFinder.

        Args:
            search_paths: A list of directory paths where original source media might be found.
            strategy: The method to use for finding file candidates (e.g., 'basic_name_match').
        """
        # Normalize and filter search paths
        self.search_paths = []
        for p in search_paths:
            abs_p = os.path.abspath(p)
            if os.path.isdir(abs_p):
                self.search_paths.append(abs_p)
            else:
                logger.warning(f"Ignoring invalid search path (not a directory): {p}")

        self.strategy = strategy
        # Cache verified sources {absolute_path: OriginalSourceFile}
        self.verified_cache: Dict[str, OriginalSourceFile] = {}
        # Find ffprobe executable path once during initialization using the imported function
        self.ffprobe_path = find_executable("ffprobe")

        if not self.search_paths:
            logger.warning("SourceFinder initialized with no valid search paths.")
        logger.info(f"SourceFinder initialized. Strategy: '{self.strategy}'. Search paths: {len(self.search_paths)}")
        if not self.ffprobe_path:
            logger.error("ffprobe executable not found. Source file verification will not be available.")

    def find_source(self, edit_shot: EditShot) -> Optional[OriginalSourceFile]:
        """
        Attempts to find and verify the original source file for a given EditShot.
        Checks cache first, then finds a candidate path, then verifies with ffprobe.

        Args:
            edit_shot: The EditShot containing information about the edit media.

        Returns:
            An OriginalSourceFile object if found and verified, otherwise None.
        """
        logger.debug(f"Finding source for EditShot: '{edit_shot.clip_name}' (Edit media: {edit_shot.edit_media_path})")

        # Cannot proceed without ffprobe for verification
        if not self.ffprobe_path:
            logger.error(
                f"Cannot find/verify source for '{os.path.basename(edit_shot.edit_media_path)}': ffprobe not available.")
            return None

        # --- Step 1: Find a potential candidate path based on strategy ---
        candidate_path = self._find_candidate_path(edit_shot)

        if not candidate_path:
            # Log warning only if lookup was attempted (i.e., search paths exist)
            if self.search_paths:
                logger.warning(
                    f"No candidate original source path found for '{os.path.basename(edit_shot.edit_media_path)}' using strategy '{self.strategy}'.")
            else:
                logger.debug("No candidate path found because no search paths are set.")
            return None

        # Ensure candidate path is absolute for consistent caching/comparison
        abs_candidate_path = os.path.abspath(candidate_path)

        # --- Step 2: Check Cache ---
        if abs_candidate_path in self.verified_cache:
            logger.debug(f"Found verified source in cache: {abs_candidate_path}")
            return self.verified_cache[abs_candidate_path]

        # --- Step 3: Verify the candidate file using ffprobe ---
        logger.debug(f"Verifying candidate path: {abs_candidate_path}")
        verified_info = self._verify_source_with_ffprobe(abs_candidate_path)

        if verified_info:
            logger.info(f"Successfully verified original source file: {abs_candidate_path}")
            # Create the OriginalSourceFile object using verified data
            original_source = OriginalSourceFile(
                path=abs_candidate_path,  # Use the absolute path
                duration=verified_info.get('duration'),
                frame_rate=verified_info.get('frame_rate'),
                start_timecode=verified_info.get('start_timecode'),
                is_verified=True,  # Mark as verified
                metadata=verified_info.get('metadata', {})
            )
            # Add the newly verified source to the cache BEFORE returning
            self.verified_cache[abs_candidate_path] = original_source
            return original_source
        else:
            # Verification failed (ffprobe error, file invalid, etc.)
            logger.error(f"Verification failed for candidate source file: {abs_candidate_path}")
            # Do not add failed verifications to cache
            return None

    def _find_candidate_path(self, edit_shot: EditShot) -> Optional[str]:
        """
        Implements the chosen strategy to find a potential original file path.

        Args:
            edit_shot: The EditShot providing the proxy path and potentially metadata.

        Returns:
            An absolute path string if a candidate is found, otherwise None.
        """
        if not self.search_paths:
            # logger.warning("Cannot find candidate path: No search paths configured.") # Logged by caller
            return None

        # --- Basic Name Matching Strategy ---
        if self.strategy == "basic_name_match":
            proxy_basename = os.path.basename(edit_shot.edit_media_path)
            # Handle potential multiple extensions like .proxy.mov or .LTO.mxf
            proxy_name_stem = proxy_basename.split('.')[0]
            if not proxy_name_stem:
                logger.warning(f"Could not extract base name stem from proxy path: {edit_shot.edit_media_path}")
                return None

            logger.debug(f"Searching for original source matching stem: '{proxy_name_stem}'")

            for search_dir in self.search_paths:
                # logger.debug(f"Checking directory: {search_dir}") # Can be very verbose
                try:
                    # TODO: Implement optional recursive search using os.walk
                    for item_name in os.listdir(search_dir):
                        item_path = os.path.join(search_dir, item_name)
                        # Optimization: Check if it's likely a file before splitting name
                        if os.path.isfile(item_path):
                            item_stem = item_name.split('.')[0]
                            # Case-insensitive comparison is generally safer across OS
                            if item_stem.lower() == proxy_name_stem.lower():
                                # Found a potential match based on stem
                                logger.info(
                                    f"Found potential original source match for '{proxy_basename}': {item_path}")
                                return os.path.abspath(item_path)  # Return absolute path of first match
                except OSError as e:
                    logger.warning(f"Could not access or list directory '{search_dir}': {e}")
                except Exception as e:
                    logger.error(f"Unexpected error searching directory '{search_dir}': {e}", exc_info=True)

            logger.debug(f"No match found for stem '{proxy_name_stem}' in configured search paths.")
            return None  # No match found in any search path

        # --- Placeholder for other strategies ---
        # elif self.strategy == "tape_name":
        #     # ... implementation using edit_shot.edit_metadata ...
        #     logger.warning(f"'{self.strategy}' lookup strategy not fully implemented.")
        #     return None
        else:
            logger.error(f"Unknown or unimplemented source finding strategy specified: '{self.strategy}'")
            return None

    def _verify_source_with_ffprobe(self, file_path: str) -> Optional[Dict]:
        """
        Uses ffprobe (if found) to get duration, fps, start_tc, and basic metadata.
        Includes robust parsing for time values.

        Args:
            file_path: Absolute path to the candidate media file.

        Returns:
            A dictionary with 'duration', 'frame_rate', 'start_timecode' (as OTIO time objects),
            and 'metadata' (dict with codec, width, height) if successful, otherwise None.
        """
        # ffprobe_path should be checked by the caller (find_source)
        if not self.ffprobe_path:
            # This log might be redundant if find_source already logged it, but safe to keep
            logger.error("Cannot verify source: ffprobe path is not configured or not found.")
            return None

        if not os.path.exists(file_path):
            logger.error(f"Verification failed: File does not exist at path: {file_path}")
            return None

        try:
            logger.info(f"Running ffprobe on: {os.path.basename(file_path)}")
            command = [
                self.ffprobe_path,
                '-v', 'error',
                '-select_streams', 'v:0',  # Analyze the first video stream
                '-show_entries',
                'stream=duration,r_frame_rate,avg_frame_rate,start_time,codec_name,width,height:stream_tags=timecode:format=duration,start_time',
                '-of', 'json',
                '-sexagesimal',  # Request H:M:S.ms format where applicable
                file_path
            ]

            # Execute ffprobe with a timeout
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,  # Check return code manually
                encoding='utf-8',
                errors='ignore',
                timeout=30  # seconds timeout
            )

            # Check ffprobe's return code
            if result.returncode != 0:
                logger.error(
                    f"ffprobe failed for '{os.path.basename(file_path)}'. Exit code: {result.returncode}\nStderr: {result.stderr.strip()}")
                return None

            # Parse the JSON output from ffprobe
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as json_err:
                logger.error(
                    f"Failed to parse ffprobe JSON output for '{os.path.basename(file_path)}': {json_err}\nOutput (first 500 chars): {result.stdout[:500]}")
                return None

            # Check for essential 'streams' data
            if not data or 'streams' not in data or not data['streams']:
                logger.error(f"ffprobe output lacks valid 'streams' data for '{os.path.basename(file_path)}'.")
                return None

            # --- Extract data ---
            stream = data['streams'][0]  # Assume first video stream
            format_data = data.get('format', {})  # Get format data if available
            info = {'metadata': {}}  # Initialize result dictionary

            # --- 1. Extract Frame Rate (Mandatory) ---
            rate_str = stream.get('r_frame_rate') or stream.get('avg_frame_rate')
            if not rate_str or '/' not in rate_str:
                logger.error(
                    f"Could not determine valid frame rate for '{os.path.basename(file_path)}'. Found: '{rate_str}'")
                return None
            try:
                num_str, den_str = rate_str.split('/')
                num, den = float(num_str), float(den_str)
                if den <= 0: raise ValueError("Denominator must be positive")
                info['frame_rate'] = num / den
                logger.debug(f"  Extracted frame_rate: {info['frame_rate']:.3f} fps")
            except (ValueError, TypeError) as e:
                logger.error(f"Error parsing frame rate string '{rate_str}' for '{os.path.basename(file_path)}': {e}")
                return None
            frame_rate = info['frame_rate']  # Convenience variable

            # --- 2. Extract Duration (Mandatory) ---
            duration_str = stream.get('duration') or format_data.get('duration')
            if duration_str:
                try:
                    # *** CORRECTED PARSING USING from_time_string ***
                    # This handles both seconds ("43.52") and H:M:S.ms ("0:00:43.520000")
                    duration_rt = opentime.from_time_string(duration_str, frame_rate)

                    if duration_rt.value > 0:
                        info['duration'] = duration_rt  # Store as RationalTime
                        logger.debug(f"  Extracted duration: {info['duration']} (from string '{duration_str}')")
                    else:
                        # Handle cases where ffprobe might report 0 or negative (e.g., single image frame)
                        logger.warning(
                            f"ffprobe reported non-positive duration '{duration_str}' for '{os.path.basename(file_path)}'. Assuming 1 frame.")
                        info['duration'] = opentime.RationalTime(value=1, rate=frame_rate)  # Treat as 1 frame duration
                except (ValueError, TypeError) as e:
                    logger.error(
                        f"Error parsing duration string '{duration_str}' using from_time_string for '{os.path.basename(file_path)}': {e}")
                    return None  # Duration is mandatory, fail if parsing error
            else:
                logger.error(f"Could not determine duration from ffprobe output for '{os.path.basename(file_path)}'.")
                return None  # Duration is mandatory

            # --- 3. Extract Start Timecode (Optional, defaults to 0) ---
            start_tc_str = stream.get('tags', {}).get('timecode') or stream.get('start_time') or format_data.get(
                'start_time')
            start_timecode = opentime.RationalTime(0, frame_rate)  # Default to zero at correct rate
            if start_tc_str:
                try:
                    # Use from_time_string here as well, it's more robust than from_timecode
                    start_timecode = opentime.from_time_string(start_tc_str, frame_rate)
                    logger.debug(
                        f"  Extracted start timecode (from_time_string): {start_timecode} (from string '{start_tc_str}')")
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"Could not parse start time/timecode string '{start_tc_str}' using from_time_string for '{os.path.basename(file_path)}'. Assuming 0. Error: {e}")
                    # Keep default zero timecode
            else:
                logger.warning(
                    f"No start time/timecode found in ffprobe output for '{os.path.basename(file_path)}'. Assuming 0.")
                # Keep default zero timecode
            info['start_timecode'] = start_timecode

            # --- 4. Extract Basic Metadata (Optional) ---
            info['metadata']['codec'] = stream.get('codec_name', 'unknown')
            info['metadata']['width'] = stream.get('width')
            info['metadata']['height'] = stream.get('height')
            logger.debug(
                f"  Extracted metadata: Codec={info['metadata']['codec']}, Res={info['metadata']['width']}x{info['metadata']['height']}")

            # Final check (duration and rate are already checked upon extraction failure)
            # No extra check needed here if the logic above returns None on failure

            return info  # Return the dictionary with extracted info

        except FileNotFoundError:
            # This case should be unlikely if self.ffprobe_path was set, but handle defensively
            logger.critical(f"ffprobe command '{self.ffprobe_path}' was not found during execution.")
            self.ffprobe_path = None  # Prevent further attempts
            return None
        except subprocess.TimeoutExpired:
            logger.error(f"ffprobe command timed out after 30 seconds for file: {file_path}")
            return None
        except Exception as e:
            # Catch any other unexpected errors during the process
            logger.error(f"Unexpected error during ffprobe verification for '{os.path.basename(file_path)}': {e}",
                         exc_info=True)
            return None

    def clear_cache(self):
        """Clears the internal cache of verified source files."""
        self.verified_cache = {}
        logger.info("SourceFinder verified cache cleared.")
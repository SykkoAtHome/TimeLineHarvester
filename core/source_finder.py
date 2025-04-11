# core/source_finder.py
"""
Finds and verifies original source media files based on information
extracted from edit timelines (EditShot objects).

Relies on external tools like ffprobe for verification.
"""

import json  # To parse ffprobe JSON output
import logging
import os
import subprocess  # To run ffprobe
from typing import List, Optional, Dict

import opentimelineio as otio

# Import necessary models and utils
from .models import EditShot, OriginalSourceFile

logger = logging.getLogger(__name__)


# --- Helper Function to find ffprobe (Placeholder) ---
# We will improve this later to find the bundled executable
def find_ffprobe_path() -> Optional[str]:
    """
    Placeholder: Attempts to find the ffprobe executable.
    Currently assumes it's in the system PATH.

    Returns:
        The path to ffprobe or None if not found.
    """
    # TODO: Implement robust searching, especially for bundled executables
    #       using sys._MEIPASS for PyInstaller etc.
    import shutil
    ffprobe_exe = shutil.which("ffprobe")  # Checks PATH
    if ffprobe_exe:
        logger.debug(f"Found ffprobe executable at: {ffprobe_exe}")
        return ffprobe_exe
    else:
        logger.error("ffprobe command not found in system PATH. Verification will fail.")
        return None


# --- SourceFinder Class ---
class SourceFinder:
    """
    Locates and verifies original source files corresponding to EditShots.
    Manages a cache of verified source files.
    """

    def __init__(self, search_paths: List[str], strategy: str = "basic_name_match"):
        """
        Initializes the SourceFinder.

        Args:
            search_paths: A list of directory paths where original source media might be found.
            strategy: The method to use for finding file candidates.
        """
        self.search_paths = [os.path.abspath(p) for p in search_paths if os.path.isdir(p)]
        self.strategy = strategy
        # Cache verified sources to avoid redundant ffprobe calls {path: OriginalSourceFile}
        self.verified_cache: Dict[str, OriginalSourceFile] = {}
        self.ffprobe_path = find_ffprobe_path()  # Find ffprobe once on init

        if not self.search_paths:
            logger.warning("SourceFinder initialized with no valid search paths.")
        logger.info(f"SourceFinder initialized. Strategy: '{self.strategy}'. Search paths: {len(self.search_paths)}")
        if not self.ffprobe_path:
            logger.error("ffprobe not found. Source file verification will not work.")

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

        if not self.ffprobe_path:
            logger.error("Cannot verify source: ffprobe path is not set.")
            return None  # Cannot proceed without ffprobe

        # --- Step 1: Find a potential candidate path based on strategy ---
        candidate_path = self._find_candidate_path(edit_shot)

        if not candidate_path:
            logger.warning(
                f"No candidate original source path found for '{edit_shot.edit_media_path}' using strategy '{self.strategy}'.")
            return None

        # --- Step 2: Check Cache ---
        if candidate_path in self.verified_cache:
            logger.debug(f"Found verified source in cache: {candidate_path}")
            return self.verified_cache[candidate_path]

        # --- Step 3: Verify the candidate file using ffprobe ---
        logger.debug(f"Verifying candidate path: {candidate_path}")
        verified_info = self._verify_source_with_ffprobe(candidate_path)

        if verified_info:
            logger.info(f"Successfully verified original source file: {candidate_path}")
            original_source = OriginalSourceFile(
                path=candidate_path,
                duration=verified_info.get('duration'),
                frame_rate=verified_info.get('frame_rate'),
                start_timecode=verified_info.get('start_timecode'),
                is_verified=True,
                metadata=verified_info.get('metadata', {})
            )
            # Add the newly verified source to the cache
            self.verified_cache[candidate_path] = original_source
            return original_source
        else:
            # Verification failed (ffprobe error, file invalid, etc.)
            logger.error(f"Verification failed for candidate source file: {candidate_path}")
            # Do not add to cache if verification failed
            return None

    def _find_candidate_path(self, edit_shot: EditShot) -> Optional[str]:
        """
        Implements the chosen strategy to find a potential original file path.

        Currently implements only 'basic_name_match'. Needs expansion.

        Returns:
            An absolute path string if a candidate is found, otherwise None.
        """
        if not self.search_paths:
            logger.warning("Cannot find candidate path: No search paths configured.")
            return None

        # --- Basic Name Matching Strategy ---
        if self.strategy == "basic_name_match":
            proxy_basename = os.path.basename(edit_shot.edit_media_path)
            # Extract name without extension(s) - handle potential double extensions like .tar.gz
            proxy_name_stem = proxy_basename.split('.')[0]
            if not proxy_name_stem:
                logger.warning(f"Could not extract base name from proxy path: {edit_shot.edit_media_path}")
                return None

            logger.debug(f"Searching for original source matching stem: '{proxy_name_stem}'")

            for search_dir in self.search_paths:
                logger.debug(f"Checking directory: {search_dir}")
                try:
                    # Walk directory recursively? For now, just top level.
                    # TODO: Consider adding recursive search option.
                    for item_name in os.listdir(search_dir):
                        item_path = os.path.join(search_dir, item_name)
                        if os.path.isfile(item_path):
                            item_stem = item_name.split('.')[0]
                            # Case-insensitive comparison might be useful depending on OS/workflow
                            if item_stem.lower() == proxy_name_stem.lower():
                                logger.info(f"Found potential original source match: {item_path}")
                                return os.path.abspath(item_path)  # Return absolute path of first match
                except OSError as e:
                    logger.warning(f"Could not access or list directory '{search_dir}': {e}")
                except Exception as e:
                    logger.error(f"Unexpected error searching directory '{search_dir}': {e}", exc_info=True)

            logger.debug(f"No match found for stem '{proxy_name_stem}' in search paths.")
            return None  # No match found in any search path

        # --- Other Strategies (Placeholders) ---
        elif self.strategy == "tape_name":
            # TODO: Implement search based on edit_shot.edit_metadata.get("Tape Name") etc.
            logger.warning(f"'{self.strategy}' lookup strategy is not implemented.")
            return None
        elif self.strategy == "match_metadata_field":
            # TODO: Implement search based on a custom metadata field
            logger.warning(f"'{self.strategy}' lookup strategy is not implemented.")
            return None
        else:
            logger.error(f"Unknown source finding strategy specified: '{self.strategy}'")
            return None

    def _verify_source_with_ffprobe(self, file_path: str) -> Optional[Dict]:
        """
        Uses ffprobe (if found) to get duration, fps, start_tc of a media file.

        Args:
            file_path: Absolute path to the candidate media file.

        Returns:
            A dictionary with 'duration', 'frame_rate', 'start_timecode', 'metadata'
            (containing codec, width, height) if successful, otherwise None.
        """
        if not self.ffprobe_path:
            logger.error("Cannot verify source: ffprobe path is not configured or not found.")
            return None

        if not os.path.exists(file_path):
            logger.error(f"Verification failed: File does not exist at path: {file_path}")
            return None

        try:
            logger.debug(f"Running ffprobe command on: {file_path}")
            command = [
                self.ffprobe_path,
                '-v', 'error',  # Only show errors
                '-select_streams', 'v:0',  # Analyze the first video stream
                '-show_entries',  # Specify entries to show
                'stream=duration,r_frame_rate,avg_frame_rate,start_time,codec_name,width,height:stream_tags=timecode',
                # Get common fields and TC tag
                '-of', 'json',  # Output as JSON
                file_path
            ]

            # Execute ffprobe
            result = subprocess.run(command,
                                    capture_output=True,
                                    text=True,  # Decode stdout/stderr as text
                                    check=False,  # Don't raise exception on non-zero exit, check manually
                                    encoding='utf-8',  # Specify encoding
                                    errors='ignore')  # Ignore decoding errors if any

            # Check ffprobe exit code
            if result.returncode != 0:
                logger.error(f"ffprobe failed for '{file_path}'. Exit code: {result.returncode}")
                logger.error(f"ffprobe stderr: {result.stderr.strip()}")
                return None

            # Parse JSON output
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to parse ffprobe JSON output for '{file_path}': {json_err}")
                logger.debug(f"ffprobe stdout was:\n{result.stdout}")
                return None

            # Check if video stream data is present
            if not data or 'streams' not in data or not data['streams']:
                logger.error(f"ffprobe found no video streams in '{file_path}'.")
                return None

            stream = data['streams'][0]  # Assume first video stream is the one we want
            info = {'metadata': {}}

            # --- Extract Frame Rate ---
            # Prefer r_frame_rate (real base rate), fallback to avg_frame_rate
            rate_str = stream.get('r_frame_rate') or stream.get('avg_frame_rate')
            if not rate_str or '/' not in rate_str:
                logger.error(
                    f"Could not determine valid frame rate from ffprobe for '{file_path}'. Found: '{rate_str}'")
                return None
            try:
                num, den = map(float, rate_str.split('/'))
                if den <= 0: raise ValueError("Denominator must be positive")
                info['frame_rate'] = num / den
            except ValueError as e:
                logger.error(f"Error parsing frame rate '{rate_str}' for '{file_path}': {e}")
                return None

            frame_rate = info['frame_rate']  # Convenience

            # --- Extract Duration ---
            duration_str = stream.get('duration')
            if duration_str:
                try:
                    duration_sec = float(duration_str)
                    if duration_sec > 0:
                        # Use the extracted frame rate for conversion
                        info['duration'] = otio.opentime.RationalTime(duration_sec * frame_rate, frame_rate)
                    else:
                        logger.warning(
                            f"ffprobe reported non-positive duration '{duration_str}' for '{file_path}'. Treating as invalid.")
                        # If duration is 0 or negative, maybe it's a single frame or invalid file?
                        # Consider if a single frame should have duration 1/rate.
                        # For now, fail verification if duration is invalid/missing.
                        return None
                except ValueError as e:
                    logger.error(f"Error parsing duration '{duration_str}' for '{file_path}': {e}")
                    return None
            else:
                # If duration is missing, can we infer it? (e.g., for image sequences later)
                # For now, require duration for video files.
                logger.error(f"ffprobe did not report a duration for '{file_path}'.")
                return None

            # --- Extract Start Timecode ---
            # Prefer tagged timecode, fallback to stream start_time
            start_tc_str = stream.get('tags', {}).get('timecode') or stream.get('start_time')
            start_timecode = otio.opentime.RationalTime(0, frame_rate)  # Default to zero
            if start_tc_str:
                try:
                    # Try standard timecode format first (HH:MM:SS:FF or HH:MM:SS;FF)
                    start_timecode = otio.opentime.from_timecode(start_tc_str, frame_rate)
                except ValueError:
                    try:
                        # Fallback to parsing as seconds float
                        start_sec = float(start_tc_str)
                        start_timecode = otio.opentime.RationalTime(start_sec * frame_rate, frame_rate)
                    except ValueError:
                        logger.warning(
                            f"Could not parse start time/timecode string '{start_tc_str}' from ffprobe for '{file_path}'. Assuming 0.")
                        # Keep default of 0
            else:
                logger.warning(f"No start timecode or start_time found for '{file_path}'. Assuming 0.")
                # Keep default of 0
            info['start_timecode'] = start_timecode

            # --- Extract Basic Metadata ---
            info['metadata']['codec'] = stream.get('codec_name', 'unknown')
            info['metadata']['width'] = stream.get('width')
            info['metadata']['height'] = stream.get('height')

            # Log extracted info for debugging
            logger.debug(f"Verified Info for {os.path.basename(file_path)}: "
                         f"FPS={info['frame_rate']:.3f}, "
                         f"Duration={info['duration']}, "
                         f"StartTC={info['start_timecode']}, "
                         f"Codec={info['metadata']['codec']}, "
                         f"Res={info['metadata']['width']}x{info['metadata']['height']}")

            return info

        except FileNotFoundError:
            # This case should be caught by the initial check, but handle defensively
            logger.critical(
                f"ffprobe command '{self.ffprobe_path}' not found during execution. Is it installed and path correct?")
            # No point continuing if ffprobe isn't there
            self.ffprobe_path = None  # Prevent further attempts
            return None
        except subprocess.TimeoutExpired:
            logger.error(f"ffprobe command timed out for file: {file_path}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error running or parsing ffprobe for '{file_path}': {e}", exc_info=True)
            return None


def clear_cache(self):
    """Clears the internal cache of verified source files."""
    self.verified_cache = {}
    logger.info("SourceFinder verified cache cleared.")

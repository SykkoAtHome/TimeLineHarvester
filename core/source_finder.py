# -*- coding: utf-8 -*-
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
import shlex  # Use shlex for safer command construction if needed, though not strictly required here
from typing import List, Optional, Dict, Any

from opentimelineio import opentime

from .models import EditShot, OriginalSourceFile
from utils import find_executable

logger = logging.getLogger(__name__)


class SourceFinder:
    """
    Locates and verifies original source files corresponding to EditShots.
    Manages a cache of verified source files to minimize redundant checks.
    """

    def __init__(self, search_paths: List[str], strategy: str = "basic_name_match"):
        """
        Initializes the SourceFinder.

        Args:
            search_paths: A list of directory paths to search for source files.
            strategy: The strategy to use for finding candidate files.
                      Currently supports "basic_name_match".
        """
        self.search_paths: List[str] = []
        for p in search_paths:
            abs_p = os.path.abspath(p)
            if os.path.isdir(abs_p):
                self.search_paths.append(abs_p)
            else:
                logger.warning(f"Ignoring invalid search path (not a directory): {p}")

        self.strategy = strategy
        self.verified_cache: Dict[str, OriginalSourceFile] = {}
        self.ffprobe_path: Optional[str] = find_executable("ffprobe")

        if not self.search_paths:
            logger.warning("SourceFinder initialized with no valid search paths.")
        if not self.ffprobe_path:
            logger.error("ffprobe executable not found. Source file verification is disabled.")
        else:
            logger.info(f"SourceFinder initialized. Strategy: '{self.strategy}'. "
                        f"Search paths: {len(self.search_paths)}. ffprobe found: {self.ffprobe_path}")

    def find_source(self, edit_shot: EditShot) -> Optional[OriginalSourceFile]:
        """
        Finds and verifies the original source file for a given EditShot.

        Args:
            edit_shot: The EditShot object representing a clip from an edit timeline.

        Returns:
            An OriginalSourceFile object if found and verified, otherwise None.
        """
        # Use the most specific path available, falling back to clip name
        identifier = edit_shot.edit_media_path or edit_shot.clip_name
        if not identifier:
            logger.warning(f"Cannot find source for EditShot (Clip: {edit_shot.clip_name}): "
                           f"Missing identifier (edit_media_path or clip_name).")
            return None

        if not self.ffprobe_path:
            # Logged during init, maybe log less verbosely here or remove?
            # Keeping a specific error here might be useful if it fails later.
            logger.error(f"Cannot verify source for identifier '{identifier}': ffprobe is not available.")
            return None

        candidate_path = self._find_candidate_path(identifier)
        if not candidate_path:
            # Only warn if search paths were provided but no match was found
            if self.search_paths:
                logger.warning(
                    f"No candidate path found for identifier '{identifier}' using strategy '{self.strategy}'.")
            return None

        abs_candidate_path = os.path.abspath(candidate_path)

        # Check cache first
        if abs_candidate_path in self.verified_cache:
            return self.verified_cache[abs_candidate_path]

        # Verify the candidate file
        verified_info = self._verify_source_with_ffprobe(abs_candidate_path)

        if verified_info:
            logger.info(f"Successfully verified original source file: {abs_candidate_path}")
            original_source = OriginalSourceFile(
                path=abs_candidate_path,
                is_verified=True,
                **verified_info  # Unpack duration, frame_rate, start_timecode, metadata
            )
            self.verified_cache[abs_candidate_path] = original_source
            return original_source
        else:
            # Verification failure already logged in _verify_source_with_ffprobe
            logger.error(f"Verification failed for candidate source file: {abs_candidate_path}")
            return None

    def _find_candidate_path(self, identifier: str) -> Optional[str]:
        """
        Searches for a candidate file path based on the identifier and strategy.

        Args:
            identifier: The identifier string (e.g., filename or path) to search for.

        Returns:
            The absolute path to a candidate file, or None if not found.
        """
        if not self.search_paths or not identifier:
            return None

        if self.strategy == "basic_name_match":
            # Extract the base name without extension
            base_name = os.path.basename(identifier)
            name_stem, _ = os.path.splitext(base_name)
            if not name_stem:
                logger.warning(f"Could not extract base name stem from identifier: {identifier}")
                return None

            # logger.debug(f"Searching for original source matching stem: '{name_stem}'") # Too verbose
            for search_dir in self.search_paths:
                try:
                    for item_name in os.listdir(search_dir):
                        item_path = os.path.join(search_dir, item_name)
                        # Basic check if it's a file before getting stem
                        if os.path.isfile(item_path):
                            item_stem, _ = os.path.splitext(item_name)
                            # Case-insensitive comparison
                            if item_stem.lower() == name_stem.lower():
                                logger.info(f"Found potential source match for '{identifier}': {item_path}")
                                return os.path.abspath(item_path)
                except OSError as e:
                    logger.warning(f"Could not access directory '{search_dir}': {e}")
                except Exception as e:
                    # Catch unexpected errors during search
                    logger.error(f"Error searching directory '{search_dir}': {e}", exc_info=True)

            # logger.debug(f"No match found for stem '{name_stem}' in search paths.") # Too verbose
            return None
        else:
            logger.error(f"Unknown source finding strategy: '{self.strategy}'")
            return None

    def _verify_source_with_ffprobe(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Verifies a file using ffprobe and extracts essential metadata.

        Args:
            file_path: The absolute path to the file to verify.

        Returns:
            A dictionary containing verified information ('duration', 'frame_rate',
            'start_timecode', 'metadata') or None if verification fails.
        """
        if not self.ffprobe_path:  # Should have been checked before calling, but double-check
            logger.error(f"ffprobe path is not set, cannot verify {file_path}")
            return None
        if not os.path.exists(file_path):
            logger.error(f"File not found for ffprobe verification: {file_path}")
            return None

        try:
            base_filename = os.path.basename(file_path)
            logger.info(f"Running ffprobe verification on: {base_filename}")
            command = [
                self.ffprobe_path,
                '-v', 'error',  # Only show errors
                '-select_streams', 'v:0',  # Select first video stream
                '-show_entries',
                'stream=duration,r_frame_rate,avg_frame_rate,start_time,codec_name,width,height:stream_tags=timecode:format=duration,start_time',
                '-of', 'json',  # Output format JSON
                '-sexagesimal',  # Use H:M:S:F format for timecodes/durations
                file_path
            ]

            # Increased timeout for potentially slow network drives or large files
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,  # Don't raise exception on non-zero exit
                encoding='utf-8',
                errors='ignore',  # Ignore potential decoding errors in ffprobe output
                timeout=60  # Increased timeout
            )

            if result.returncode != 0:
                logger.error(
                    f"ffprobe failed for '{base_filename}' (Code: {result.returncode}). Stderr: {result.stderr.strip()}")
                return None

            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse ffprobe JSON output for '{base_filename}'.")
                return None

            if not data or 'streams' not in data or not data['streams']:
                logger.error(f"ffprobe output missing 'streams' data for '{base_filename}'.")
                return None

            stream = data['streams'][0]
            format_data = data.get('format', {})
            verified_info = {'metadata': {}}  # Dictionary to hold extracted info

            # --- Frame Rate ---
            rate_str = stream.get('r_frame_rate') or stream.get('avg_frame_rate')
            if not rate_str or '/' not in rate_str:
                logger.error(f"Invalid or missing frame rate string ('{rate_str}') for {base_filename}.")
                return None
            try:
                num, den = map(float, rate_str.split('/'))
                if den <= 0:
                    raise ValueError("Frame rate denominator must be positive")
                frame_rate = num / den
                verified_info['frame_rate'] = frame_rate
            except Exception as e:
                logger.error(f"Error parsing frame rate '{rate_str}' for {base_filename}: {e}")
                return None

            # --- Duration ---
            # Prefer stream duration, fallback to format duration
            duration_str = stream.get('duration') or format_data.get('duration')
            if duration_str:
                try:
                    # OTIO handles various time string formats including sexagesimal
                    duration_rt = opentime.from_time_string(duration_str, frame_rate)
                    # Ensure duration is at least one frame if parsing results in zero
                    verified_info['duration'] = duration_rt if duration_rt.value > 0 else opentime.RationalTime(1,
                                                                                                                frame_rate)
                except Exception as e:
                    logger.error(f"Error parsing duration string '{duration_str}' for {base_filename}: {e}")
                    return None  # Cannot proceed without duration
            else:
                logger.error(f"Missing duration information for {base_filename}.")
                return None  # Cannot proceed without duration

            # --- Start Timecode ---
            start_timecode_rt = opentime.RationalTime(0, frame_rate)  # Default to 0
            parsed_successfully = False
            source_for_timecode = "default (00:00:00:00)"  # Descriptive source for logging

            # Attempt 1: Use 'timecode' tag with from_timecode (most reliable)
            tag_timecode_str = stream.get('tags', {}).get('timecode')
            if tag_timecode_str:
                source_for_timecode = f"stream 'tags.timecode' ('{tag_timecode_str}')"
                try:
                    start_timecode_rt = opentime.from_timecode(tag_timecode_str, frame_rate)
                    parsed_successfully = True
                except ValueError:  # Handles format errors in from_timecode
                    # Attempt 2: Fallback using from_time_string for non-standard timecode tags
                    try:
                        start_timecode_rt = opentime.from_time_string(tag_timecode_str, frame_rate)
                        logger.warning(
                            f"Parsed '{tag_timecode_str}' using from_time_string fallback for {base_filename}.")
                        parsed_successfully = True
                        source_for_timecode += " [parsed via from_time_string fallback]"
                    except ValueError as e_str:
                        logger.warning(
                            f"Could not parse timecode tag '{tag_timecode_str}' using from_timecode or from_time_string for {base_filename}: {e_str}")
                        source_for_timecode += " [parsing failed]"
                    except Exception as e_fallback:
                        logger.error(
                            f"Unexpected error parsing timecode tag '{tag_timecode_str}' with from_time_string for {base_filename}: {e_fallback}",
                            exc_info=False)
                        source_for_timecode += " [parsing error]"
                except Exception as e_tcode:
                    logger.error(
                        f"Unexpected error parsing timecode tag '{tag_timecode_str}' with from_timecode for {base_filename}: {e_tcode}",
                        exc_info=False)
                    source_for_timecode += " [parsing error]"

            # Attempt 3: If tag parsing failed, try stream 'start_time' field
            if not parsed_successfully:
                start_time_str = stream.get('start_time') or format_data.get('start_time')  # Check format too
                if start_time_str:
                    # Often 'start_time' is float seconds, sometimes sexagesimal
                    source_for_timecode = f"stream/format 'start_time' ('{start_time_str}')"
                    try:
                        # from_time_string handles both float seconds and H:M:S formats
                        start_timecode_rt = opentime.from_time_string(start_time_str, frame_rate)
                        parsed_successfully = True
                    except ValueError as e_start:
                        logger.warning(
                            f"Could not parse 'start_time' string '{start_time_str}' using from_time_string for {base_filename}: {e_start}")
                        source_for_timecode += " [parsing failed]"
                    except Exception as e_start_other:
                        logger.error(
                            f"Unexpected error parsing 'start_time' {start_time_str} for {base_filename}: {e_start_other}",
                            exc_info=False)
                        source_for_timecode += " [parsing error]"

            if not parsed_successfully and (tag_timecode_str or start_time_str):
                # Log only if fields were present but failed parsing
                logger.warning(
                    f"Failed to parse start timecode from available fields for {base_filename}. Using default 0.")
            elif not tag_timecode_str and not start_time_str:
                # Log if no relevant fields were found
                logger.info(f"No explicit start timecode or start_time found for {base_filename}. Using default 0.")

            verified_info['start_timecode'] = start_timecode_rt
            logger.info(
                f"  Determined start_timecode for {base_filename}: {opentime.to_timecode(start_timecode_rt)} (Source: {source_for_timecode})")

            # --- Metadata ---
            verified_info['metadata']['codec'] = stream.get('codec_name', 'unknown')
            verified_info['metadata']['width'] = stream.get('width')
            verified_info['metadata']['height'] = stream.get('height')

            return verified_info  # Return dict with 'duration', 'frame_rate', 'start_timecode', 'metadata'

        except FileNotFoundError:
            # This should only happen if ffprobe was found initially but removed later
            logger.critical(
                f"ffprobe command failed: executable not found at '{self.ffprobe_path}'. Disabling further checks.")
            self.ffprobe_path = None  # Prevent further attempts
            return None
        except subprocess.TimeoutExpired:
            logger.error(f"ffprobe timed out after {command.timeout} seconds for {file_path}")
            return None
        except Exception as e:
            logger.error(
                f"An unexpected error occurred during ffprobe verification for {os.path.basename(file_path)}: {e}",
                exc_info=True)
            return None

    def clear_cache(self):
        """Clears the internal cache of verified source files."""
        count = len(self.verified_cache)
        self.verified_cache = {}
        logger.info(f"SourceFinder verified cache cleared ({count} items).")

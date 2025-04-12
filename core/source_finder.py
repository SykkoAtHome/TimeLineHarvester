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

from opentimelineio import opentime  # Explicit import

from .models import EditShot, OriginalSourceFile
from utils import find_executable  # Use the one from utils

logger = logging.getLogger(__name__)


class SourceFinder:
    """
    Locates and verifies original source files corresponding to EditShots.
    Manages a cache of verified source files to minimize ffprobe calls.
    """

    def __init__(self, search_paths: List[str], strategy: str = "basic_name_match"):
        self.search_paths = []
        for p in search_paths:
            abs_p = os.path.abspath(p)
            if os.path.isdir(abs_p):
                self.search_paths.append(abs_p)
            else:
                logger.warning(f"Ignoring invalid search path (not a directory): {p}")
        self.strategy = strategy
        self.verified_cache: Dict[str, OriginalSourceFile] = {}
        self.ffprobe_path = find_executable("ffprobe")
        if not self.search_paths: logger.warning("SourceFinder initialized with no valid search paths.")
        logger.info(f"SourceFinder initialized. Strategy: '{self.strategy}'. Search paths: {len(self.search_paths)}")
        if not self.ffprobe_path: logger.error(
            "ffprobe executable not found. Source file verification will not be available.")

    def find_source(self, edit_shot: EditShot) -> Optional[OriginalSourceFile]:
        # Use the identifier stored in edit_media_path by the parser
        identifier = edit_shot.edit_media_path or edit_shot.clip_name
        if not identifier:
            logger.warning("Cannot find source: EditShot lacks a usable identifier.")
            return None
        logger.debug(f"Finding source for EditShot: Clip='{edit_shot.clip_name}', Identifier='{identifier}'")
        if not self.ffprobe_path:
            logger.error(f"Cannot find/verify source for identifier '{identifier}': ffprobe not available.")
            return None
        candidate_path = self._find_candidate_path(identifier)
        if not candidate_path:
            if self.search_paths:
                logger.warning(
                    f"No candidate path found for identifier '{identifier}' using strategy '{self.strategy}'.")
            else:
                logger.debug("No candidate path found (no search paths).")
            return None
        abs_candidate_path = os.path.abspath(candidate_path)
        if abs_candidate_path in self.verified_cache:
            logger.debug(f"Found verified source in cache: {abs_candidate_path}")
            return self.verified_cache[abs_candidate_path]
        logger.debug(f"Verifying candidate path: {abs_candidate_path}")
        verified_info = self._verify_source_with_ffprobe(abs_candidate_path)
        if verified_info:
            logger.info(f"Successfully verified original source file: {abs_candidate_path}")
            # Use dictionary unpacking for cleaner assignment from verified_info
            original_source = OriginalSourceFile(path=abs_candidate_path, **verified_info)
            original_source.is_verified = True  # Explicitly set verified flag
            self.verified_cache[abs_candidate_path] = original_source
            return original_source
        else:
            logger.error(f"Verification failed for candidate source file: {abs_candidate_path}")
            return None

    def _find_candidate_path(self, identifier: str) -> Optional[str]:
        if not self.search_paths or not identifier: return None
        if self.strategy == "basic_name_match":
            base_name = os.path.basename(identifier)
            name_stem = base_name.split('.')[0]
            if not name_stem:
                logger.warning(f"Could not extract base name stem from identifier: {identifier}")
                return None
            logger.debug(f"Searching for original source matching stem: '{name_stem}' (from identifier '{identifier}')")
            for search_dir in self.search_paths:
                try:
                    for item_name in os.listdir(search_dir):
                        item_path = os.path.join(search_dir, item_name)
                        if os.path.isfile(item_path):
                            item_stem = item_name.split('.')[0]
                            if item_stem.lower() == name_stem.lower():
                                logger.info(f"Found potential original source match for '{identifier}': {item_path}")
                                return os.path.abspath(item_path)
                except OSError as e:
                    logger.warning(f"Could not access directory '{search_dir}': {e}")
                except Exception as e:
                    logger.error(f"Error searching directory '{search_dir}': {e}", exc_info=True)
            logger.debug(f"No match found for stem '{name_stem}' in search paths.")
            return None
        else:
            logger.error(f"Unknown source finding strategy: '{self.strategy}'")
            return None

    def _verify_source_with_ffprobe(self, file_path: str) -> Optional[Dict]:
        """Verifies file with ffprobe, parsing timecode correctly."""
        if not self.ffprobe_path or not os.path.exists(file_path): return None

        try:
            logger.info(f"Running ffprobe on: {os.path.basename(file_path)}")
            command = [self.ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
                       '-show_entries',
                       'stream=duration,r_frame_rate,avg_frame_rate,start_time,codec_name,width,height:stream_tags=timecode:format=duration,start_time',
                       '-of', 'json', '-sexagesimal', file_path]
            result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8',
                                    errors='ignore', timeout=30)

            if result.returncode != 0:
                logger.error(
                    f"ffprobe failed for '{os.path.basename(file_path)}'. Code: {result.returncode}\nStderr: {result.stderr.strip()}")
                return None
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.error(f"Failed ffprobe JSON parse for '{os.path.basename(file_path)}'"); return None
            if not data or 'streams' not in data or not data['streams']: logger.error(
                f"ffprobe missing 'streams' for '{os.path.basename(file_path)}'."); return None

            stream = data['streams'][0]
            format_data = data.get('format', {})
            info = {'metadata': {}}  # Dictionary to be returned

            # --- Frame Rate ---
            rate_str = stream.get('r_frame_rate') or stream.get('avg_frame_rate')
            if not rate_str or '/' not in rate_str: logger.error(
                f"Invalid frame rate string '{rate_str}' for {os.path.basename(file_path)}"); return None
            try:
                n, d = map(float, rate_str.split('/'))
                if d <= 0: raise ValueError("Rate denominator zero/negative")
                frame_rate = n / d
                info['frame_rate'] = frame_rate  # Store in info dict
            except Exception as e:
                logger.error(f"Error parsing frame rate '{rate_str}': {e}"); return None

            # --- Duration ---
            duration_str = stream.get('duration') or format_data.get('duration')
            if duration_str:
                try:
                    duration_rt = opentime.from_time_string(duration_str, frame_rate)
                    info['duration'] = duration_rt if duration_rt.value > 0 else opentime.RationalTime(1,
                                                                                                       frame_rate)  # Store in info dict
                except Exception as e:
                    logger.error(f"Error parsing duration '{duration_str}': {e}"); return None
            else:
                logger.error(f"Missing duration for {os.path.basename(file_path)}"); return None

            # --- Start Timecode (FIXED PARSING LOGIC) ---
            start_timecode_rt = opentime.RationalTime(0, frame_rate)
            parsed_successfully = False
            source_for_timecode = "default (0)"

            tag_timecode_str = stream.get('tags', {}).get('timecode')
            if tag_timecode_str:
                source_for_timecode = f"'tags.timecode' ('{tag_timecode_str}')"
                logger.debug(f"  Attempting to parse {source_for_timecode} with rate {frame_rate}")
                try:  # Attempt 1: from_timecode
                    start_timecode_rt = opentime.from_timecode(tag_timecode_str, frame_rate)
                    logger.debug(f"    Successfully parsed using from_timecode: {start_timecode_rt}")
                    parsed_successfully = True
                except ValueError as e_tcode:  # Catch only ValueError here
                    logger.warning(
                        f"    from_timecode failed for '{tag_timecode_str}' (Rate: {frame_rate}): {e_tcode}. Trying fallback.")
                    try:  # Attempt 2: from_time_string fallback
                        start_timecode_rt = opentime.from_time_string(tag_timecode_str, frame_rate)
                        logger.debug(f"    Successfully parsed using from_time_string fallback: {start_timecode_rt}")
                        parsed_successfully = True
                        source_for_timecode += " [parsed via from_time_string fallback]"
                    except ValueError as e_str:  # Catch only ValueError
                        logger.warning(f"    from_time_string also failed for '{tag_timecode_str}': {e_str}")
                        source_for_timecode += " [parsing failed]"
                    except Exception as e_fallback:  # Catch other errors during fallback
                        logger.error(f"    Unexpected error during from_time_string fallback: {e_fallback}",
                                     exc_info=False)  # Log less verbosely
                        source_for_timecode += " [parsing error]"
                except Exception as e_tcode_other:  # Catch other errors during from_timecode
                    logger.error(f"    Unexpected error parsing 'tags.timecode' with from_timecode: {e_tcode_other}",
                                 exc_info=False)
                    source_for_timecode += " [parsing error]"

            if not parsed_successfully:  # Try 'start_time' field if tag parsing failed
                start_time_str = stream.get('start_time') or format_data.get('start_time')
                if start_time_str:
                    source_for_timecode = f"'start_time' field ('{start_time_str}')"
                    logger.debug(
                        f"  Attempting to parse {source_for_timecode} using from_time_string (Rate: {frame_rate})")
                    try:
                        start_timecode_rt = opentime.from_time_string(start_time_str, frame_rate)
                        logger.debug(f"    Successfully parsed using from_time_string: {start_timecode_rt}")
                        parsed_successfully = True
                    except ValueError as e_start:
                        logger.warning(
                            f"    Could not parse 'start_time' string '{start_time_str}' using from_time_string: {e_start}")
                        source_for_timecode += " [parsing failed]"
                    except Exception as e_start_other:
                        logger.error(f"    Unexpected error parsing 'start_time': {e_start_other}", exc_info=False)
                        source_for_timecode += " [parsing error]"

            if not parsed_successfully:  # Final log if all failed
                logger.warning(f"  No valid start time/timecode parsed from available fields. Assuming 0.")
                start_timecode_rt = opentime.RationalTime(0, frame_rate)

            info['start_timecode'] = start_timecode_rt  # Store in info dict
            logger.info(f"  Final start_timecode set to: {start_timecode_rt} (Source: {source_for_timecode})")
            # --- End Start Timecode ---

            # --- Metadata ---
            info['metadata']['codec'] = stream.get('codec_name', 'unknown')
            info['metadata']['width'] = stream.get('width')
            info['metadata']['height'] = stream.get('height')
            # logger.debug(f"  Extracted metadata: Codec={info['metadata']['codec']}, Res={info['metadata']['width']}x{info['metadata']['height']}")

            # Return the dictionary with parsed info (excluding 'is_verified')
            return info

        except FileNotFoundError:
            logger.critical(f"ffprobe not found at '{self.ffprobe_path}'"); self.ffprobe_path = None; return None
        except subprocess.TimeoutExpired:
            logger.error(f"ffprobe timed out for {file_path}"); return None
        except Exception as e:
            logger.error(f"Error during ffprobe verification for {os.path.basename(file_path)}: {e}",
                         exc_info=True); return None

    def clear_cache(self):
        """Clears the internal cache of verified source files."""
        self.verified_cache = {}
        logger.info("SourceFinder verified cache cleared.")

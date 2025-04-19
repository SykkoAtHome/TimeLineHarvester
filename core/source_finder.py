# core/source_finder.py
"""
Finds and verifies original source media files based on information
extracted from edit timelines (EditShot objects).

Relies on FFProbeAnalyzer for verification and media type detection.
"""
import logging
import os
from typing import List, Optional, Dict

from opentimelineio import opentime  # Explicit import

from .models import EditShot, OriginalSourceFile, MediaType
from .ffprobe_analyzer import FFProbeAnalyzer, FFProbeAnalyzerError, FFProbeResult
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

        # Initialize the FFProbeAnalyzer
        self.analyzer = None
        if self.ffprobe_path:
            try:
                self.analyzer = FFProbeAnalyzer(self.ffprobe_path)
            except Exception as e:
                logger.error(f"Failed to initialize FFProbeAnalyzer: {e}", exc_info=True)

        if not self.search_paths:
            logger.warning("SourceFinder initialized with no valid search paths.")
        logger.info(f"SourceFinder initialized. Strategy: '{self.strategy}'. Search paths: {len(self.search_paths)}")
        if not self.ffprobe_path:
            logger.error("ffprobe executable not found. Source file verification will not be available.")

    def find_source(self, edit_shot: EditShot) -> Optional[OriginalSourceFile]:
        """
        Finds and verifies the original source file for an EditShot.

        Uses FFProbeAnalyzer to detect media type and properties.
        Falls back to legacy method if analyzer fails.
        """
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

        # First try using FFProbeAnalyzer if available
        if self.analyzer:
            try:
                original_source = self._verify_with_analyzer(abs_candidate_path)
                if original_source:
                    self.verified_cache[abs_candidate_path] = original_source
                    return original_source
                else:
                    logger.warning(f"FFProbeAnalyzer failed to verify: {abs_candidate_path}")
            except Exception as e:
                logger.warning(f"Error using FFProbeAnalyzer: {e}. Falling back to legacy method.")

        # Fall back to legacy verification method if analyzer failed or isn't available
        info = self._verify_source_with_ffprobe(abs_candidate_path)
        if info:
            original_source = self._create_original_source(abs_candidate_path, info)
            if original_source:
                logger.info(f"Successfully verified original source file: {abs_candidate_path}")
                self.verified_cache[abs_candidate_path] = original_source
                return original_source

        logger.error(f"Verification failed for candidate source file: {abs_candidate_path}")
        return None

    def _verify_with_analyzer(self, file_path: str) -> Optional[OriginalSourceFile]:
        """
        Verifies a source file using the FFProbeAnalyzer.

        Returns:
            An OriginalSourceFile object if verification succeeds, None otherwise.
        """
        try:
            analysis_result = self.analyzer.analyze(file_path)
            if not analysis_result:
                logger.warning(f"FFProbeAnalyzer returned no result for: {file_path}")
                return None

            # Validate essential information
            if not analysis_result.frame_rate or analysis_result.frame_rate <= 0:
                logger.warning(f"Invalid frame rate ({analysis_result.frame_rate}) from analyzer for {file_path}")
                return None

            if not isinstance(analysis_result.duration, opentime.RationalTime) or analysis_result.duration.value <= 0:
                logger.warning(f"Invalid duration from analyzer for {file_path}")
                return None

            if not isinstance(analysis_result.start_timecode, opentime.RationalTime):
                logger.warning(f"Invalid start timecode from analyzer for {file_path}")
                return None

            # Create OriginalSourceFile from analysis results
            source = OriginalSourceFile(
                path=file_path,
                media_type=analysis_result.media_type,
                duration=analysis_result.duration,
                frame_rate=analysis_result.frame_rate,
                start_timecode=analysis_result.start_timecode,
                is_verified=True,
                metadata=analysis_result.video_stream_info.copy() if analysis_result.video_stream_info else {},
                sequence_pattern=analysis_result.sequence_pattern,
                sequence_frame_range=analysis_result.sequence_frame_range
            )

            # Add audio stream info to metadata if available
            if analysis_result.audio_stream_info:
                source.metadata['audio_streams'] = analysis_result.audio_stream_info

            logger.info(f"Successfully verified original source file with analyzer: {file_path}")
            return source

        except FFProbeAnalyzerError as e:
            logger.error(f"FFProbeAnalyzer error for {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during verification with analyzer: {e}", exc_info=True)
            return None

    def _verify_source_with_ffprobe(self, file_path: str) -> Optional[Dict]:
        """
        Directly verifies a media file using ffprobe.

        Returns:
            A dictionary with metadata information if verification succeeds, None otherwise.
        """
        if not self.ffprobe_path or not os.path.exists(file_path):
            return None

        try:
            # Import required modules
            import subprocess
            import json
            import opentimelineio as otio  # Add this import explicitly

            # Choose the appropriate command based on file type
            is_mxf = file_path.lower().endswith('.mxf')

            if is_mxf:
                # MXF-specific command that works correctly
                command = [
                    self.ffprobe_path, '-v', 'error',
                    '-select_streams', 'v:0',  # First video stream
                    '-show_entries',
                    'stream=index,codec_type,codec_name,duration,r_frame_rate,avg_frame_rate,start_time,width,height:stream_tags=timecode:format=duration',
                    '-of', 'json',
                    file_path
                ]
            else:
                # Standard command for other file types
                command = [
                    self.ffprobe_path, '-v', 'error',
                    '-show_entries',
                    'stream=index,codec_type,codec_name,duration,r_frame_rate,avg_frame_rate,start_time,nb_frames,width,height,channels,channel_layout,sample_rate:stream_tags=timecode:format=duration,start_time',
                    '-of', 'json', '-sexagesimal',
                    file_path
                ]

            logger.debug(f"Running ffprobe command: {' '.join(command)}")

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                encoding='utf-8',
                errors='ignore',
                timeout=30
            )

            if result.returncode != 0:
                stderr_snippet = result.stderr.strip()[-500:] if result.stderr else "No stderr output"
                logger.error(
                    f"ffprobe failed for '{os.path.basename(file_path)}'. Code: {result.returncode}. Stderr: {stderr_snippet}")
                return None

            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse ffprobe JSON output: {e}")
                return None

            # Prepare result dictionary
            info = {'metadata': {}}

            if not data or 'streams' not in data or not data['streams']:
                logger.warning(f"No streams found in ffprobe output for '{file_path}'")
                return None

            # Find video stream
            video_stream = None
            for stream in data['streams']:
                if stream.get('codec_type') == 'video':
                    video_stream = stream
                    break

            if not video_stream:
                logger.warning(f"No video stream found in '{file_path}'")
                return None

            # Extract frame rate
            rate_str = video_stream.get('r_frame_rate') or video_stream.get('avg_frame_rate')
            current_rate = None
            if rate_str and '/' in rate_str:
                try:
                    n, d = map(float, rate_str.split('/'))
                    if d > 0:
                        current_rate = n / d
                        info['frame_rate'] = current_rate
                    else:
                        logger.warning(f"Invalid frame rate denominator in '{rate_str}'")
                        return None
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse frame rate string: {rate_str}")
                    return None
            else:
                logger.warning(f"No valid frame rate found for '{file_path}'")
                return None

            # Extract format_data before using it
            format_data = data.get('format', {})

            # Extract duration
            duration_str = video_stream.get('duration') or format_data.get('duration')

            if duration_str:
                try:
                    # Improved duration parsing - handles both formats
                    duration_rt = None

                    if isinstance(duration_str, str):
                        if ':' in duration_str:
                            # Format could be hh:mm:ss:ff (standard timecode) or hh:mm:ss.fraction
                            parts = duration_str.split(':')

                            # Check if we have hh:mm:ss.fraction format
                            if len(parts) == 3 and '.' in parts[2]:
                                # Format is like "0:01:24.800000" (decimal seconds)
                                hours, minutes, seconds_with_fraction = parts
                                total_seconds = (int(hours) * 3600) + (int(minutes) * 60) + float(seconds_with_fraction)
                                duration_rt = otio.opentime.RationalTime(total_seconds * current_rate, current_rate)
                            else:
                                # Try standard timecode parsing first
                                try:
                                    duration_rt = otio.opentime.from_timecode(duration_str, current_rate)
                                except ValueError:
                                    # If that fails, try more flexible parsing
                                    try:
                                        duration_rt = otio.opentime.from_time_string(duration_str, current_rate)
                                    except Exception as inner_e:
                                        logger.warning(f"Failed to parse time string '{duration_str}': {inner_e}")
                                        # Try the last method below
                        else:
                            # Could be numeric (seconds)
                            try:
                                duration_secs = float(duration_str)
                                duration_rt = otio.opentime.RationalTime(duration_secs * current_rate, current_rate)
                            except ValueError as ve:
                                logger.warning(f"Could not parse duration as float: {duration_str}: {ve}")
                                return None
                    else:
                        # Might already be a number (float/int)
                        try:
                            duration_secs = float(duration_str)
                            duration_rt = otio.opentime.RationalTime(duration_secs * current_rate, current_rate)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Could not convert duration to float: {duration_str}: {e}")
                            return None

                    if duration_rt:
                        info['duration'] = duration_rt
                    else:
                        logger.warning(f"Could not parse duration '{duration_str}' in any supported format")
                        return None
                except Exception as e:
                    logger.warning(f"Error parsing duration '{duration_str}': {e}")
                    return None
            else:
                logger.warning(f"No duration found for '{file_path}'")
                return None

            # Extract timecode
            tag_timecode_str = video_stream.get('tags', {}).get('timecode')
            if tag_timecode_str:
                try:
                    # First try standard timecode format
                    start_timecode_rt = otio.opentime.from_timecode(tag_timecode_str, current_rate)
                    info['start_timecode'] = start_timecode_rt
                except ValueError:
                    try:
                        # Fallback to more flexible parsing
                        start_timecode_rt = otio.opentime.from_time_string(tag_timecode_str, current_rate)
                        info['start_timecode'] = start_timecode_rt
                    except Exception as e:
                        logger.warning(f"Could not parse timecode '{tag_timecode_str}': {e}")
                        # Default to zero if parsing fails
                        info['start_timecode'] = otio.opentime.RationalTime(0, current_rate)
                except Exception as e:
                    logger.warning(f"Error parsing timecode '{tag_timecode_str}': {e}")
                    # Default to zero if parsing fails
                    info['start_timecode'] = otio.opentime.RationalTime(0, current_rate)
            else:
                # No timecode found, default to zero
                info['start_timecode'] = otio.opentime.RationalTime(0, current_rate)

            # Save additional metadata
            for key in ['width', 'height', 'codec_name']:
                if key in video_stream:
                    info['metadata'][key] = video_stream[key]

            if 'tags' in video_stream:
                info['metadata']['tags'] = video_stream['tags']

            return info

        except Exception as e:
            logger.error(f"Error during ffprobe verification for {os.path.basename(file_path)}: {e}",
                         exc_info=True)
            return None

    def _create_original_source(self, file_path: str, info: Dict) -> Optional[OriginalSourceFile]:
        """Creates an OriginalSourceFile from the parsed ffprobe information."""
        try:
            # Determine media type based on file extension and codec
            media_type = MediaType.UNKNOWN
            file_ext = os.path.splitext(file_path)[1].lower()

            # Check codec name for classification
            codec_name = info.get('metadata', {}).get('codec_name', '').lower()

            video_extensions = {'.mp4', '.mov', '.mxf', '.avi', '.mkv', '.mpg', '.mpeg', '.dv', '.m4v', '.mts', '.m2ts'}
            image_extensions = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.dpx', '.exr', '.bmp', '.gif', '.webp'}
            audio_extensions = {'.wav', '.mp3', '.aac', '.flac', '.m4a', '.ogg', '.wma'}

            if 'audio_streams' in info['metadata'] and not codec_name:
                media_type = MediaType.AUDIO
            elif file_ext in image_extensions or codec_name in ['mjpeg', 'png', 'jpeg', 'tiff', 'dpx', 'exr']:
                media_type = MediaType.IMAGE
            elif file_ext in video_extensions or codec_name:
                media_type = MediaType.VIDEO
            elif file_ext in audio_extensions:
                media_type = MediaType.AUDIO

            # Create and return the OriginalSourceFile
            source = OriginalSourceFile(
                path=file_path,
                media_type=media_type,
                duration=info.get('duration'),
                frame_rate=info.get('frame_rate'),
                start_timecode=info.get('start_timecode'),
                is_verified=True,
                metadata=info.get('metadata', {}),
                sequence_pattern=None,  # Legacy method doesn't detect sequences
                sequence_frame_range=None
            )

            return source
        except Exception as e:
            logger.error(f"Error creating OriginalSourceFile from info: {e}", exc_info=True)
            return None

    def _find_candidate_path(self, identifier: str) -> Optional[str]:
        """
        Finds a candidate path for the source file using the specified strategy.

        Searches recursively through all subdirectories of the search paths.

        Args:
            identifier: The identifier string to match against file names.

        Returns:
            The absolute path to the found file, or None if no match was found.
        """
        if not self.search_paths or not identifier:
            return None

        if self.strategy == "basic_name_match":
            base_name = os.path.basename(identifier)
            name_stem = base_name.split('.')[0]
            if not name_stem:
                logger.warning(f"Could not extract base name stem from identifier: {identifier}")
                return None

            logger.debug(
                f"Searching recursively for original source matching stem: '{name_stem}' (from identifier '{identifier}')")

            for search_dir in self.search_paths:
                try:
                    # Walk through the directory tree recursively
                    for root, dirs, files in os.walk(search_dir):
                        for file_name in files:
                            file_stem = file_name.split('.')[0]
                            if file_stem.lower() == name_stem.lower():
                                file_path = os.path.join(root, file_name)
                                logger.info(f"Found potential original source match for '{identifier}': {file_path}")
                                return os.path.abspath(file_path)
                except OSError as e:
                    logger.warning(f"Could not access directory '{search_dir}': {e}")
                except Exception as e:
                    logger.error(f"Error searching directory '{search_dir}': {e}", exc_info=True)

            logger.debug(f"No match found for stem '{name_stem}' in search paths (including subdirectories).")
            return None
        else:
            logger.error(f"Unknown source finding strategy: '{self.strategy}'")
            return None

    def clear_cache(self):
        """Clears the internal cache of verified source files."""
        self.verified_cache = {}
        logger.info("SourceFinder verified cache cleared.")

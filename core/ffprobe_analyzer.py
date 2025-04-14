# core/ffprobe_analyzer.py

import json
import logging
import os
import re  # For sequence pattern detection
import subprocess
from pathlib import Path  # Use pathlib for path operations
from typing import Optional, Dict, Any, Tuple, List, Set

import opentimelineio as otio

# Import MediaType enum from models
from .models import MediaType

logger = logging.getLogger(__name__)

# Known video codec names that might appear for single images
# Add more as needed based on ffprobe output for different image formats
KNOWN_IMAGE_CODEC_NAMES: Set[str] = {
    "mjpeg", "png", "tiff", "tiff_pipe", "dpx", "dpx_pipe", "exr", "exr_pipe",
    "webp", "bmp", "gif", "jpeg2000", "targa", "pcx", "pgx"
    # Consider adding variations if ffprobe reports them differently
}


class FFProbeAnalyzerError(Exception):
    """Custom exception for errors during ffprobe analysis."""
    pass


class FFProbeResult:
    """Data class to hold structured results from ffprobe analysis."""

    def __init__(self):
        self.media_type: MediaType = MediaType.UNKNOWN
        self.duration: Optional[otio.opentime.RationalTime] = None
        self.frame_rate: Optional[float] = None
        self.start_timecode: Optional[otio.opentime.RationalTime] = None
        self.video_stream_info: Dict[str, Any] = {}  # Codec, width, height etc.
        self.audio_stream_info: List[Dict[str, Any]] = []  # Info for audio streams
        self.is_sequence: bool = False
        self.sequence_pattern: Optional[str] = None
        self.sequence_frame_range: Optional[Tuple[int, int]] = None
        self.raw_ffprobe_data: Optional[Dict] = None  # Store raw json for debugging


class FFProbeAnalyzer:
    """
    Analyzes media files and sequences using ffprobe to determine
    type, duration, frame rate, timecode, and other metadata.
    """

    def __init__(self, ffprobe_path: str):
        """
        Initializes the analyzer.

        Args:
            ffprobe_path: The full path to the ffprobe executable.

        Raises:
            FileNotFoundError: If the ffprobe executable is not found.
        """
        if not ffprobe_path or not os.path.exists(ffprobe_path):
            raise FileNotFoundError(f"FFProbe executable not found at: {ffprobe_path}")
        self.ffprobe_path = ffprobe_path
        logger.info(f"FFProbeAnalyzer initialized with ffprobe: {self.ffprobe_path}")

    def analyze(self, file_path: str) -> FFProbeResult:
        """
        Analyzes a given file path to determine media type and properties.
        Handles single files, images, and attempts to detect image sequences.

        Args:
            file_path: The absolute path to the media file.

        Returns:
            An FFProbeResult object containing the analysis results.

        Raises:
            FFProbeAnalyzerError: If analysis fails.
        """
        if not os.path.exists(file_path):
            raise FFProbeAnalyzerError(f"File not found for analysis: {file_path}")

        result = FFProbeResult()
        logger.info(f"Analyzing file: {os.path.basename(file_path)}")

        try:
            # Check if file is MXF to choose appropriate command
            is_mxf = file_path.lower().endswith(".mxf")
            command_type = "mxf" if is_mxf else "standard"

            # 1. Analyze the single file provided
            single_file_data = self._run_ffprobe(file_path, command_type=command_type)
            if not single_file_data:
                # Error already logged by _run_ffprobe
                result.media_type = MediaType.UNKNOWN
                return result  # Return unknown if basic ffprobe fails

            result.raw_ffprobe_data = single_file_data  # Store raw data
            parsed_data = self._parse_ffprobe_output(single_file_data)

            # Extract common info (will be overwritten for sequences if detected)
            result.frame_rate = parsed_data.get('frame_rate')
            result.duration = parsed_data.get('duration')
            result.start_timecode = parsed_data.get('start_timecode')
            result.video_stream_info = parsed_data.get('video_stream', {})
            result.audio_stream_info = parsed_data.get('audio_streams', [])

            # 2. Classify based on single file analysis
            preliminary_type = self._classify_media(parsed_data)
            result.media_type = preliminary_type  # Set preliminary type

            # 3. If it looks like an image, try to detect a sequence
            if preliminary_type == MediaType.IMAGE:
                logger.debug(
                    f"'{os.path.basename(file_path)}' classified as potential image/sequence frame. Detecting sequence...")
                is_seq, pattern, frame_range, _ = self._detect_sequence(file_path)

                if is_seq and pattern and frame_range:
                    logger.info(
                        f"Detected image sequence pattern: {pattern} (Frames: {frame_range[0]}-{frame_range[1]})")
                    result.is_sequence = True
                    result.media_type = MediaType.IMAGE_SEQUENCE
                    result.sequence_pattern = pattern
                    result.sequence_frame_range = frame_range

                    # 4. Analyze the *entire* sequence (optional but recommended for duration)
                    # Use default frame rate (25) for sequence unless overridden later
                    sequence_frame_rate = result.frame_rate or 25.0
                    try:
                        seq_data = self._run_ffprobe(
                            pattern,
                            is_sequence=True,
                            sequence_options={
                                'start_number': frame_range[0],
                                'framerate': sequence_frame_rate  # Tell ffprobe the rate
                            }
                        )
                        if seq_data:
                            parsed_seq_data = self._parse_ffprobe_output(seq_data, default_rate=sequence_frame_rate)
                            # Update duration and potentially other fields based on full sequence analysis
                            result.duration = parsed_seq_data.get('duration', result.duration)
                            # Keep frame rate as determined from sequence analysis or override
                            result.frame_rate = parsed_seq_data.get('frame_rate', result.frame_rate)
                            # Start timecode usually comes from the first frame's metadata
                            result.start_timecode = parsed_data.get('start_timecode', result.start_timecode)
                            logger.info(f"Sequence analysis successful. Duration: {result.duration}")
                        else:
                            logger.warning(f"FFprobe analysis failed for the full sequence pattern: {pattern}")
                    except Exception as seq_err:
                        logger.error(f"Error analyzing full sequence '{pattern}': {seq_err}", exc_info=True)

            # Final logging based on type
            if result.media_type == MediaType.IMAGE_SEQUENCE:
                logger.info(
                    f"Final classification: IMAGE_SEQUENCE. Path: {file_path}, Pattern: {result.sequence_pattern}, Duration: {result.duration}")
            elif result.media_type == MediaType.IMAGE:
                logger.info(f"Final classification: IMAGE. Path: {file_path}")
            elif result.media_type == MediaType.VIDEO:
                logger.info(f"Final classification: VIDEO. Path: {file_path}, Duration: {result.duration}")
            elif result.media_type == MediaType.AUDIO:
                logger.info(f"Final classification: AUDIO. Path: {file_path}, Duration: {result.duration}")
            else:
                logger.info(f"Final classification: UNKNOWN. Path: {file_path}")


        except Exception as e:
            logger.error(f"Unexpected error during analysis of '{file_path}': {e}", exc_info=True)
            raise FFProbeAnalyzerError(f"Analysis failed for {file_path}: {e}") from e

        return result

    def _run_ffprobe(self, file_path_or_pattern: str, is_sequence: bool = False,
                     sequence_options: Optional[Dict] = None, command_type: str = "standard") -> Optional[Dict]:
        """Runs the ffprobe command and returns the parsed JSON data."""
        command = [self.ffprobe_path, '-v', 'error']

        if is_sequence:
            command.extend(['-f', 'image2'])
            if sequence_options:
                if 'start_number' in sequence_options:
                    command.extend(['-start_number', str(sequence_options['start_number'])])
                if 'framerate' in sequence_options:
                    # Add framerate input option *before* -i
                    command.extend(['-framerate', str(sequence_options['framerate'])])
            # Assuming pattern_type sequence for now, adjust if needed
            command.extend(['-pattern_type', 'sequence'])
        elif command_type == "mxf":
            # Specialized command for MXF files (tested and working)
            command.extend([
                '-select_streams', 'v:0',  # First video stream only
                '-show_entries',
                'stream=index,codec_type,codec_name,duration,r_frame_rate,avg_frame_rate,start_time,width,height:stream_tags=timecode:format=duration',
                '-of', 'json'
            ])
        else:
            # Standard command for other file types
            command.extend([
                '-select_streams', 'v:0',  # First video stream
                '-select_streams', 'a',  # All audio streams
                '-show_entries',
                'stream=index,codec_type,codec_name,duration,r_frame_rate,avg_frame_rate,start_time,nb_frames,width,height,channels,channel_layout,sample_rate:stream_tags=timecode:format=duration,start_time',
                '-of', 'json',
                '-sexagesimal'
            ])

        # Add the file path
        command.append(file_path_or_pattern)

        logger.debug(f"Running ffprobe command: {' '.join(command)}")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,  # Don't raise exception on non-zero exit code
                encoding='utf-8',
                errors='ignore',
                timeout=30  # Add a timeout
            )

            if result.returncode != 0:
                # Log specific error from ffprobe stderr if possible
                stderr_snippet = result.stderr.strip()[-500:]  # Log last part of stderr
                logger.error(
                    f"ffprobe failed for '{os.path.basename(file_path_or_pattern)}'. Code: {result.returncode}. Stderr: {stderr_snippet}")
                return None

            try:
                data = json.loads(result.stdout)
                return data
            except json.JSONDecodeError as json_err:
                logger.error(
                    f"Failed to parse ffprobe JSON output for '{os.path.basename(file_path_or_pattern)}': {json_err}")
                logger.debug(
                    f"FFprobe raw output causing parse error:\n{result.stdout[:1000]}...")  # Log beginning of output
                return None

        except subprocess.TimeoutExpired:
            logger.error(f"ffprobe command timed out for '{os.path.basename(file_path_or_pattern)}'.")
            return None
        except FileNotFoundError:
            # This shouldn't happen if constructor check passed, but handle defensively
            logger.critical(f"ffprobe executable not found at '{self.ffprobe_path}' during run.")
            # Potentially re-raise or handle differently?
            raise FFProbeAnalyzerError(f"FFprobe not found at {self.ffprobe_path}")
        except Exception as e:
            logger.error(f"Unexpected error running ffprobe for '{os.path.basename(file_path_or_pattern)}': {e}",
                         exc_info=True)
            return None

    def _parse_ffprobe_output(self, data: Dict, default_rate: float = 25.0) -> Dict:
        """Parses the raw JSON data from ffprobe into a structured dictionary."""
        parsed = {
            'video_stream': None,
            'audio_streams': [],
            'frame_rate': None,
            'duration': None,
            'start_timecode': None,
        }
        if not data or 'streams' not in data:
            logger.warning("No 'streams' key found in ffprobe output.")
            # For simple commands, format data might still have useful information
            format_data = data.get('format', {})
            if format_data:
                # Try to get duration from format section
                duration_str = format_data.get('duration')
                if duration_str:
                    try:
                        # Try to parse as sexagesimal time format (HH:MM:SS.mmm)
                        if ':' in duration_str:
                            duration_rt = otio.opentime.from_timecode(duration_str, default_rate)
                        else:
                            # Parse as floating point seconds
                            duration_secs = float(duration_str)
                            duration_rt = otio.opentime.RationalTime(
                                duration_secs * default_rate, default_rate)

                        if duration_rt.value > 0:
                            parsed['duration'] = duration_rt
                            logger.debug(f"Using format duration: {duration_str} at {default_rate}fps")
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Could not parse format duration: {duration_str}: {e}")
            return parsed

        format_data = data.get('format', {})

        # Find first video stream and all audio streams
        for stream in data['streams']:
            codec_type = stream.get('codec_type')
            if codec_type == 'video' and not parsed['video_stream']:  # Take first video stream
                parsed['video_stream'] = stream
            elif codec_type == 'audio':
                parsed['audio_streams'].append(stream)

        # --- Process Video Stream (if found) ---
        video_stream = parsed['video_stream']
        if video_stream:
            # Frame Rate
            rate_str = video_stream.get('r_frame_rate') or video_stream.get('avg_frame_rate')
            if rate_str and '/' in rate_str:
                try:
                    n, d = map(float, rate_str.split('/'))
                    if d > 0:
                        parsed['frame_rate'] = n / d
                except ValueError:
                    logger.warning(f"Could not parse frame rate string: {rate_str}")
            if not parsed['frame_rate']:
                parsed['frame_rate'] = default_rate  # Use default if not found/parsed
                logger.debug(f"Using default frame rate {default_rate} for video stream.")

            current_rate = parsed['frame_rate']

            # Duration
            duration_str = video_stream.get('duration') or format_data.get('duration')
            if duration_str:
                try:
                    # Try to handle different duration formats (sexagesimal or numeric)
                    if ':' in duration_str:  # Looks like sexagesimal (HH:MM:SS.mmm)
                        duration_rt = otio.opentime.from_timecode(duration_str, current_rate)
                    else:  # Assume numeric seconds
                        duration_secs = float(duration_str)
                        duration_rt = otio.opentime.RationalTime(duration_secs * current_rate, current_rate)

                    # Ensure duration is positive, min 1 frame if needed
                    if duration_rt.value <= 0:
                        logger.warning(f"Parsed duration {duration_rt} is zero or negative, setting to 1 frame.")
                        parsed['duration'] = otio.opentime.RationalTime(1, current_rate)
                    else:
                        parsed['duration'] = duration_rt
                except Exception as e:
                    logger.warning(f"Could not parse duration string '{duration_str}': {e}")
            if not parsed['duration']:
                # Try nb_frames as fallback ONLY if duration failed
                nb_frames = video_stream.get('nb_frames')
                try:
                    num_frames = int(nb_frames)
                    if num_frames > 0:
                        parsed['duration'] = otio.opentime.RationalTime(num_frames, current_rate)
                        logger.debug(f"Used nb_frames ({num_frames}) as fallback for duration.")
                except (ValueError, TypeError, AttributeError):
                    logger.warning("Could not determine duration from ffprobe output.")

            # Start Timecode / Start Time
            start_timecode_rt = None
            parsed_successfully = False
            source_for_timecode = "default (0)"
            tag_timecode_str = video_stream.get('tags', {}).get('timecode')

            if tag_timecode_str:
                source_for_timecode = f"'tags.timecode' ('{tag_timecode_str}')"
                try:  # Attempt 1: from_timecode (strict TC format)
                    start_timecode_rt = otio.opentime.from_timecode(tag_timecode_str, current_rate)
                    parsed_successfully = True
                except ValueError:
                    try:  # Attempt 2: from_time_string (more flexible)
                        start_timecode_rt = otio.opentime.from_time_string(tag_timecode_str, current_rate)
                        parsed_successfully = True
                        source_for_timecode += " [parsed via from_time_string fallback]"
                    except ValueError as e_str:
                        logger.warning(
                            f"Could not parse timecode string '{tag_timecode_str}' using from_timecode or from_time_string: {e_str}")
                    except Exception as e_fallback:
                        logger.error(
                            f"Unexpected error parsing timecode '{tag_timecode_str}' with from_time_string: {e_fallback}")
                except Exception as e_tcode_other:
                    logger.error(f"Unexpected error parsing 'tags.timecode' with from_timecode: {e_tcode_other}")

            # Attempt 3: 'start_time' field if tag parsing failed or tag missing
            if not parsed_successfully:
                start_time_str = video_stream.get('start_time') or format_data.get('start_time')
                if start_time_str:
                    source_for_timecode = f"'start_time' field ('{start_time_str}')"
                    try:
                        # Handle different formats of start_time
                        if ':' in start_time_str:  # Looks like timecode format
                            start_timecode_rt = otio.opentime.from_timecode(start_time_str, current_rate)
                        else:  # Assume numeric seconds
                            start_secs = float(start_time_str)
                            start_timecode_rt = otio.opentime.RationalTime(start_secs * current_rate, current_rate)
                        parsed_successfully = True
                    except ValueError as e_start:
                        logger.warning(f"Could not parse 'start_time' string '{start_time_str}': {e_start}")
                    except Exception as e_start_other:
                        logger.error(f"Unexpected error parsing 'start_time': {e_start_other}")

            # Set final start timecode (default to 0 if all parsing failed)
            if start_timecode_rt is None:
                start_timecode_rt = otio.opentime.RationalTime(0, current_rate)
                source_for_timecode = "default (0)"

            parsed['start_timecode'] = start_timecode_rt
            logger.debug(f"Parsed start_timecode: {start_timecode_rt} (Source: {source_for_timecode})")

        # --- Process Audio Streams (if any) ---
        # Additional audio processing could be added here if needed

        return parsed

    def _classify_media(self, parsed_data: Dict) -> MediaType:
        """Classifies the media type based on parsed ffprobe data (single file)."""
        video_stream = parsed_data.get('video_stream')
        audio_streams = parsed_data.get('audio_streams', [])

        if video_stream:
            codec_name = video_stream.get('codec_name', '').lower()
            nb_frames_str = video_stream.get('nb_frames')

            is_image_codec = codec_name in KNOWN_IMAGE_CODEC_NAMES

            # Check if nb_frames suggests a single frame
            is_single_frame = False
            if nb_frames_str:
                try:
                    if int(nb_frames_str) == 1:
                        is_single_frame = True
                except (ValueError, TypeError):
                    pass  # Ignore if nb_frames is not a valid integer string

            # Also check duration as nb_frames can be unreliable
            duration_rt = parsed_data.get('duration')
            rate = parsed_data.get('frame_rate')
            is_short_duration = False
            if isinstance(duration_rt, otio.opentime.RationalTime) and rate and rate > 0:
                # Consider it short if duration is <= 1 frame
                one_frame_duration = otio.opentime.RationalTime(1, rate)
                if duration_rt <= one_frame_duration:
                    is_short_duration = True

            if is_image_codec and (is_single_frame or is_short_duration):
                # Likely a single image or a frame from a sequence
                return MediaType.IMAGE
            else:
                # Otherwise, assume video
                return MediaType.VIDEO
        elif audio_streams:
            # If no video but audio exists
            return MediaType.AUDIO
        else:
            # No recognizable video or audio streams
            return MediaType.UNKNOWN

    def _detect_sequence(self, file_path_str: str) -> Tuple[
        bool, Optional[str], Optional[Tuple[int, int]], Optional[int]]:
        """
        Attempts to detect if a file is part of an image sequence based on filename.

        Args:
            file_path_str: The absolute path to the file potentially being part of a sequence.

        Returns:
            A tuple: (is_sequence, pattern, frame_range, padding)
            is_sequence: True if a sequence pattern was detected and neighbours exist.
            pattern: The detected sequence pattern (e.g., "file.%04d.ext").
            frame_range: Tuple of (start_frame, end_frame) of the sequence found on disk.
            padding: The detected zero-padding length (e.g., 4 for %04d).
        """
        try:
            file_path = Path(file_path_str)
            directory = file_path.parent
            filename = file_path.name
            suffix = file_path.suffix.lower()  # Ensure lowercase suffix for matching

            # Regex to find potential frame numbers at the end, before the extension
            # Looks for one or more digits preceded by a common separator (., _, -) or none
            # Example: name.1234.ext, name_1234.ext, name-1234.ext, name1234.ext
            match = re.search(r'([._-]?)(\d+)$', file_path.stem)

            if not match:
                logger.debug(f"No sequence pattern (numeric suffix) found in '{filename}'.")
                return False, None, None, None

            separator = match.group(1)  # The separator before the number (or empty)
            number_str = match.group(2)  # The numeric part as a string
            padding = len(number_str)  # Detected padding
            frame_number = int(number_str)

            # Construct the base name and the glob pattern
            base_name = file_path.stem[:-len(match.group(0))]  # Name before separator and number
            glob_pattern = f"{base_name}{separator}{'?' * padding}{suffix}"  # Pattern for globbing files
            # Construct ffprobe/printf pattern
            printf_pattern = f"{base_name}{separator}%0{padding}d{suffix}"

            logger.debug(
                f"Potential sequence pattern found: Base='{base_name}', Separator='{separator}', Padding={padding}, Pattern='{printf_pattern}'")

            # Find all matching files in the directory using glob
            matching_files = []
            min_frame = float('inf')
            max_frame = float('-inf')

            for item in directory.glob(glob_pattern):
                if item.is_file() and item.suffix.lower() == suffix:
                    # Extract number again from the found file to be sure it matches
                    inner_match = re.search(r'(\d+)$', item.stem)
                    if inner_match:
                        try:
                            num = int(inner_match.group(1))
                            # Check if length matches padding (prevents matching name_1.ext with name_10.ext if padding=1)
                            if len(inner_match.group(1)) == padding:
                                matching_files.append(num)
                                min_frame = min(min_frame, num)
                                max_frame = max(max_frame, num)
                        except (ValueError, TypeError):
                            continue  # Ignore if not a valid number

            if len(matching_files) > 1:  # Need more than one file to confirm a sequence
                logger.debug(f"Found {len(matching_files)} files matching pattern. Range: {min_frame}-{max_frame}")
                # Optional: Check for frame continuity (more robust)
                # matching_files.sort()
                # is_continuous = all(matching_files[i] == matching_files[0] + i for i in range(len(matching_files)))
                # if not is_continuous:
                #     logger.warning(f"Detected sequence '{printf_pattern}' has missing frames.")
                #     # Decide if you want to treat discontinuous sequences as valid

                return True, str(directory / printf_pattern), (min_frame, max_frame), padding
            else:
                logger.debug(f"Only one file found matching pattern '{glob_pattern}'. Treating as single image.")
                return False, None, None, None

        except Exception as e:
            logger.error(f"Error during sequence detection for '{file_path_str}': {e}", exc_info=True)
            return False, None, None, None  # Return False on any error

"""
Timeline I/O Module

This module provides functionality for reading, writing, and manipulating timeline files
(EDL, AAF, XML) using OpenTimelineIO (OTIO).
"""

import os
import logging
from typing import Optional, Dict, Any, Tuple, List

import opentimelineio as otio

# Configure logging
logger = logging.getLogger(__name__)

# Mapping of file extensions to OTIO adapter names
FORMAT_MAP = {
    '.edl': 'edl',
    '.xml': 'xml',  # Generic XML (OTIO will try to determine the specific format)
    '.fcpxml': 'fcpxml',  # Final Cut Pro XML
    '.aaf': 'aaf',
    # Add other formats as needed
}


def detect_format(file_path: str) -> Optional[str]:
    """
    Detect the format of a timeline file based on its extension.

    Args:
        file_path: Path to the timeline file

    Returns:
        String representing the OTIO adapter name, or None if format is unknown
    """
    ext = os.path.splitext(file_path)[1].lower()
    format_name = FORMAT_MAP.get(ext)

    if not format_name:
        logger.warning(f"Unknown file extension: {ext}. Format detection may fail.")

    return format_name


def read_timeline(file_path: str, fps: Optional[float] = None,
                  adapter_options: Optional[Dict[str, Any]] = None) -> otio.schema.Timeline:
    """
    Read a timeline file, auto-detecting its format.

    Args:
        file_path: Path to the timeline file
        fps: Frames per second to use if not specified in the file
        adapter_options: Additional options to pass to the OTIO adapter

    Returns:
        OTIO Timeline object

    Raises:
        ValueError: If the file cannot be read or the format is not supported
    """
    if not os.path.exists(file_path):
        raise ValueError(f"File not found: {file_path}")

    # Detect format based on file extension
    format_name = detect_format(file_path)

    # Prepare adapter options
    if adapter_options is None:
        adapter_options = {}

    # Set up fps in adapter options if specified
    if fps:
        adapter_options.setdefault('rate', fps)

    try:
        logger.info(f"Reading timeline file: {file_path} (format: {format_name or 'auto-detect'})")

        # If format is known, use specific adapter, otherwise let OTIO try to detect
        if format_name:
            timeline = otio.adapters.read_from_file(
                file_path,
                adapter_name=format_name,
                **adapter_options
            )
        else:
            timeline = otio.adapters.read_from_file(file_path, **adapter_options)

        logger.info(f"Successfully parsed timeline: {timeline.name} with {len(timeline.tracks)} tracks")
        return timeline

    except Exception as e:
        logger.error(f"Failed to parse timeline: {str(e)}")
        raise ValueError(f"Failed to parse timeline file {file_path}: {str(e)}")


def get_timeline_clips(timeline: otio.schema.Timeline) -> List[otio.schema.Clip]:
    """
    Extract all clips from a timeline.

    Args:
        timeline: OTIO Timeline object

    Returns:
        List of all clips in the timeline
    """
    clips = []

    # Iterate through all tracks and extract clips
    for track in timeline.tracks:
        for item in track:
            if isinstance(item, otio.schema.Clip):
                clips.append(item)
            elif isinstance(item, otio.schema.Stack) or isinstance(item, otio.schema.Track):
                # Handle nested compositions recursively
                for child_item in item:
                    if isinstance(child_item, otio.schema.Clip):
                        clips.append(child_item)

    logger.info(f"Found {len(clips)} clips in timeline")
    return clips


def get_clip_source_info(clip: otio.schema.Clip) -> Dict[str, Any]:
    """
    Extract source information from a clip.

    Args:
        clip: OTIO Clip object

    Returns:
        Dictionary containing source file information and timecode ranges
    """
    source_info = {
        'name': clip.name,
        'source_file': None,
        'source_start': None,
        'source_end': None,
        'timeline_start': None,
        'timeline_end': None,
    }

    # Extract media reference information if available
    if hasattr(clip, 'media_reference') and clip.media_reference:
        if isinstance(clip.media_reference, otio.schema.ExternalReference):
            source_info['source_file'] = clip.media_reference.target_url

    # Extract source range information
    if clip.source_range:
        source_info['source_start'] = clip.source_range.start_time
        source_info['source_end'] = clip.source_range.end_time_exclusive()

    # Extract timeline range
    if clip.range_in_parent():
        source_info['timeline_start'] = clip.range_in_parent().start_time
        source_info['timeline_end'] = clip.range_in_parent().end_time_exclusive()

    return source_info


def create_consolidated_timeline(source_clips: List[Dict[str, Any]],
                                 timeline_name: str = "Consolidated Timeline") -> otio.schema.Timeline:
    """
    Create a new timeline containing consolidated clips.

    Args:
        source_clips: List of clip information dictionaries with consolidated ranges
        timeline_name: Name for the new timeline

    Returns:
        New OTIO Timeline object with consolidated clips
    """
    timeline = otio.schema.Timeline(name=timeline_name)

    # Create a video track
    video_track = otio.schema.Track(name="Video", kind="Video")
    timeline.tracks.append(video_track)

    current_time = otio.opentime.RationalTime(0, 24)  # Starting at time 0, default 24fps

    # Add each consolidated clip to the timeline
    for clip_info in source_clips:
        # Create a media reference
        media_ref = otio.schema.ExternalReference(
            target_url=clip_info['source_file']
        )

        # Create source range
        source_range = otio.opentime.TimeRange(
            start_time=clip_info['source_start'],
            duration=clip_info['source_end'] - clip_info['source_start']
        )

        # Create the clip
        clip = otio.schema.Clip(
            name=clip_info['name'],
            media_reference=media_ref,
            source_range=source_range
        )

        # Add to track at current time
        video_track.append(clip)

        # Update current time for next clip
        current_time += source_range.duration

    logger.info(f"Created consolidated timeline with {len(source_clips)} clips")
    return timeline


def write_timeline(timeline: otio.schema.Timeline, output_path: str,
                   format_name: Optional[str] = None,
                   adapter_options: Optional[Dict[str, Any]] = None) -> str:
    """
    Write a timeline to a file.

    Args:
        timeline: OTIO Timeline object
        output_path: Path where the timeline file should be written
        format_name: Format to write (if None, will be detected from output_path extension)
        adapter_options: Additional options to pass to the OTIO adapter

    Returns:
        Path to the written file

    Raises:
        ValueError: If the timeline cannot be written or the format is not supported
    """
    # Detect format from output path if not specified
    if not format_name:
        format_name = detect_format(output_path)
        if not format_name:
            raise ValueError(f"Could not determine format for {output_path}")

    # Prepare adapter options
    if adapter_options is None:
        adapter_options = {}

    try:
        logger.info(f"Writing timeline to: {output_path} (format: {format_name})")

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Write the timeline
        otio.adapters.write_to_file(timeline, output_path, adapter_name=format_name, **adapter_options)

        logger.info(f"Successfully wrote timeline to: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Failed to write timeline: {str(e)}")
        raise ValueError(f"Failed to write timeline to {output_path}: {str(e)}")
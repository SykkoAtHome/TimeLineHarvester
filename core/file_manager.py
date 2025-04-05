"""
File Manager Module

This module handles loading and saving timeline files (EDL, AAF, XML) using OpenTimelineIO.
It provides the necessary functions to read timeline files and convert them to the
system's internal models, as well as exporting results.
"""

import os
import logging
from typing import Dict, List, Optional, Union, Any

import opentimelineio as otio

from .models import Timeline, TransferPlan, TransferSegment

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


class FileManager:
    """
    Handles reading and writing timeline files in various formats using OpenTimelineIO.
    """

    @staticmethod
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

    @staticmethod
    def read_otio_timeline(file_path: str, fps: Optional[float] = None,
                           adapter_options: Optional[Dict[str, Any]] = None) -> otio.schema.Timeline:
        """
        Read a timeline file using OTIO, auto-detecting its format.

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
        format_name = FileManager.detect_format(file_path)

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

            logger.info(f"Successfully parsed OTIO timeline: {timeline.name} with {len(timeline.tracks)} tracks")
            return timeline

        except Exception as e:
            logger.error(f"Failed to parse timeline: {str(e)}")
            raise ValueError(f"Failed to parse timeline file {file_path}: {str(e)}")

    @staticmethod
    def read_timeline(file_path: str, fps: Optional[float] = None,
                      adapter_options: Optional[Dict[str, Any]] = None,
                      source_clips: Optional[Dict[str, Any]] = None) -> Timeline:
        """
        Read a timeline file and convert it to our Timeline model.

        Args:
            file_path: Path to the timeline file
            fps: Frames per second to use if not specified in the file
            adapter_options: Additional options to pass to the OTIO adapter
            source_clips: Optional dictionary of existing source clips to reuse

        Returns:
            Timeline object containing the parsed timeline data
        """
        # Read the OTIO timeline
        otio_timeline = FileManager.read_otio_timeline(file_path, fps, adapter_options)

        # Convert to our Timeline model
        timeline = Timeline.from_otio_timeline(otio_timeline, source_clips)

        logger.info(f"Converted OTIO timeline to Timeline model: {timeline.name} with {len(timeline.clips)} clips")
        return timeline

    @staticmethod
    def read_multiple_timelines(file_paths: List[str], fps: Optional[float] = None,
                                adapter_options: Optional[Dict[str, Any]] = None) -> List[Timeline]:
        """
        Read multiple timeline files and convert them to our Timeline models.

        Ensures source clips are shared across timelines.

        Args:
            file_paths: List of paths to timeline files
            fps: Frames per second to use if not specified in the files
            adapter_options: Additional options to pass to the OTIO adapter

        Returns:
            List of Timeline objects
        """
        timelines = []
        source_clips = {}  # Shared source clips dictionary

        for file_path in file_paths:
            timeline = FileManager.read_timeline(file_path, fps, adapter_options, source_clips)
            timelines.append(timeline)

            # Update the shared source clips with new sources from this timeline
            for source_path, source_clip in timeline.sources.items():
                if source_path not in source_clips:
                    source_clips[source_path] = source_clip

        logger.info(f"Read {len(timelines)} timelines with {len(source_clips)} unique source clips")
        return timelines

    @staticmethod
    def write_otio_timeline(otio_timeline: otio.schema.Timeline, output_path: str,
                            format_name: Optional[str] = None,
                            adapter_options: Optional[Dict[str, Any]] = None) -> str:
        """
        Write an OTIO Timeline to a file.

        Args:
            otio_timeline: OTIO Timeline object
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
            format_name = FileManager.detect_format(output_path)
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
            otio.adapters.write_to_file(otio_timeline, output_path, adapter_name=format_name, **adapter_options)

            logger.info(f"Successfully wrote timeline to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to write timeline: {str(e)}")
            raise ValueError(f"Failed to write timeline to {output_path}: {str(e)}")

    @staticmethod
    def write_timeline(timeline: Timeline, output_path: str,
                       format_name: Optional[str] = None,
                       adapter_options: Optional[Dict[str, Any]] = None) -> str:
        """
        Write a Timeline model to a file.

        Args:
            timeline: Timeline object
            output_path: Path where the timeline file should be written
            format_name: Format to write (if None, will be detected from output_path extension)
            adapter_options: Additional options to pass to the OTIO adapter

        Returns:
            Path to the written file
        """
        # Convert our Timeline to OTIO timeline
        otio_timeline = timeline.get_otio_timeline()

        # Write using the OTIO adapter
        return FileManager.write_otio_timeline(otio_timeline, output_path, format_name, adapter_options)

    @staticmethod
    def write_transfer_plan(transfer_plan: TransferPlan, output_path: str,
                            format_name: Optional[str] = None,
                            adapter_options: Optional[Dict[str, Any]] = None) -> str:
        """
        Write a TransferPlan to a consolidated timeline file.

        Args:
            transfer_plan: TransferPlan object
            output_path: Path where the timeline file should be written
            format_name: Format to write (if None, will be detected from output_path extension)
            adapter_options: Additional options to pass to the OTIO adapter

        Returns:
            Path to the written file
        """
        # Get the consolidated timeline from the transfer plan
        otio_timeline = transfer_plan.get_consolidated_timeline()

        # Write using the OTIO adapter
        return FileManager.write_otio_timeline(otio_timeline, output_path, format_name, adapter_options)

    @staticmethod
    def write_segments_batch(segments: List[TransferSegment], output_dir: str,
                             format_name: Optional[str] = None,
                             filename_pattern: str = "{name}.{ext}",
                             adapter_options: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Write multiple segments as individual timeline files.

        Args:
            segments: List of TransferSegment objects
            output_dir: Directory where to write the files
            format_name: Format to write (if None, will be detected from extension in pattern)
            filename_pattern: Pattern for generating filenames
            adapter_options: Additional options to pass to the OTIO adapter

        Returns:
            List of paths to the written files
        """
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Default extension if format specified
        ext = format_name or "edl"

        output_paths = []
        for segment in segments:
            # Generate filename
            filename = filename_pattern.format(
                name=segment.name,
                source=os.path.basename(segment.source_file),
                ext=ext
            )
            output_path = os.path.join(output_dir, filename)

            # Create a simple timeline with just this segment
            timeline = otio.schema.Timeline(name=segment.name)
            video_track = otio.schema.Track(name="Video", kind="Video")
            timeline.tracks.append(video_track)
            video_track.append(segment.get_otio_clip())

            # Write the timeline
            FileManager.write_otio_timeline(timeline, output_path, format_name, adapter_options)
            output_paths.append(output_path)

        logger.info(f"Wrote {len(output_paths)} segment files to {output_dir}")
        return output_paths
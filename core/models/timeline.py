"""
Timeline Module

This module defines the Timeline class, which represents an editing timeline
containing multiple clips with timing information.
"""

import os
import logging
from typing import Optional, Dict, List, Any, Union, Set
from collections import defaultdict
import opentimelineio as otio

from .timeline_clip import TimelineClip
from .source_clip import SourceClip

# Configure logging
logger = logging.getLogger(__name__)


class Timeline:
    """
    Represents an editing timeline containing multiple clips.

    This class maintains a collection of TimelineClip objects, along with
    metadata about the timeline itself.
    """

    def __init__(self,
                 name: str,
                 fps: Optional[float] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a Timeline instance.

        Args:
            name: Name of the timeline
            fps: Frames per second of the timeline
            metadata: Additional metadata associated with the timeline
        """
        self.name = name
        self.fps = fps
        self.metadata = metadata or {}
        self.clips = []
        self.sources = {}  # Map of source path to SourceClip

        # Original OTIO timeline if created from one
        self._otio_timeline = None

    def __str__(self) -> str:
        """String representation of the timeline."""
        return f"Timeline('{self.name}', {len(self.clips)} clips)"

    def __repr__(self) -> str:
        """Detailed representation of the timeline."""
        return (f"Timeline(name='{self.name}', "
                f"fps={self.fps}, "
                f"clips_count={len(self.clips)})")

    @property
    def duration(self) -> Optional[otio.opentime.RationalTime]:
        """
        Get the duration of the timeline.

        Returns:
            Total timeline duration based on the latest clip end time
        """
        if not self.clips:
            return None

        # Initialize to earliest possible value
        latest_end_time = None

        for clip in self.clips:
            if clip.timeline_end:
                if latest_end_time is None or clip.timeline_end > latest_end_time:
                    latest_end_time = clip.timeline_end

        if latest_end_time is None:
            return None

        # Assuming timeline starts at 0
        return latest_end_time

    def add_clip(self, clip: TimelineClip) -> None:
        """
        Add a TimelineClip to the timeline.

        Args:
            clip: TimelineClip to add
        """
        self.clips.append(clip)

        # Add its source to our sources dictionary if not already present
        if clip.source_clip:
            source_path = clip.source_clip.source_path
            if source_path not in self.sources:
                self.sources[source_path] = clip.source_clip

    def get_clips(self) -> List[TimelineClip]:
        """
        Get all clips in the timeline.

        Returns:
            List of TimelineClip objects
        """
        return self.clips

    def get_sources(self) -> List[SourceClip]:
        """
        Get all unique source clips used in the timeline.

        Returns:
            List of unique SourceClip objects
        """
        return list(self.sources.values())

    def get_source_usage(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get detailed information about how each source is used.

        Returns:
            Dictionary mapping source file paths to lists of usage information
        """
        source_usage = defaultdict(list)

        for clip in self.clips:
            if not clip.source_clip:
                continue

            source_path = clip.source_clip.source_path

            # Skip clips without source file information
            if not source_path:
                logger.warning(f"Clip '{clip.name}' has no source file reference - skipping")
                continue

            # Record this usage of the source file
            source_usage[source_path].append({
                'name': clip.name,
                'source_start': clip.source_start,
                'source_end': clip.source_end,
                'timeline_start': clip.timeline_start,
                'timeline_end': clip.timeline_end,
                'timeline_name': self.name
            })

        return dict(source_usage)

    def get_otio_timeline(self) -> otio.schema.Timeline:
        """
        Get an OTIO representation of this timeline.

        Returns:
            OTIO Timeline object
        """
        if self._otio_timeline:
            return self._otio_timeline

        # Create a new OTIO timeline
        timeline = otio.schema.Timeline(name=self.name)

        # Create a video track
        video_track = otio.schema.Track(name="Video", kind="Video")
        timeline.tracks.append(video_track)

        # Sort clips by timeline start time
        sorted_clips = sorted(
            [c for c in self.clips if c.timeline_start],
            key=lambda c: c.timeline_start.value
        )

        # Add each clip to the track
        for clip in sorted_clips:
            if not clip.source_clip:
                continue

            # Create a media reference
            media_ref = otio.schema.ExternalReference(
                target_url=clip.source_clip.source_path
            )

            # Create source range if available
            source_range = None
            if clip.source_start and clip.source_duration:
                source_range = otio.opentime.TimeRange(
                    start_time=clip.source_start,
                    duration=clip.source_duration
                )

            # Create the OTIO clip
            otio_clip = otio.schema.Clip(
                name=clip.name,
                media_reference=media_ref,
                source_range=source_range
            )

            # Add to track
            video_track.append(otio_clip)

        return timeline

    @classmethod
    def from_otio_timeline(cls, otio_timeline: otio.schema.Timeline,
                           source_clips: Optional[Dict[str, SourceClip]] = None) -> 'Timeline':
        """
        Create a Timeline from an OTIO Timeline object.

        Args:
            otio_timeline: OTIO Timeline object
            source_clips: Optional dictionary mapping source paths to existing SourceClip objects
                        to reuse rather than creating new ones

        Returns:
            New Timeline instance
        """
        # Extract basic timeline info
        name = otio_timeline.name

        # Try to extract fps from the timeline
        fps = None
        if (hasattr(otio_timeline, 'global_start_time') and
                otio_timeline.global_start_time and
                hasattr(otio_timeline.global_start_time, 'rate')):
            fps = otio_timeline.global_start_time.rate

        # Extract metadata
        metadata = {}
        if hasattr(otio_timeline, 'metadata') and otio_timeline.metadata:
            metadata = dict(otio_timeline.metadata)

        # Create the timeline
        timeline = cls(name=name, fps=fps, metadata=metadata)
        timeline._otio_timeline = otio_timeline

        # Initialize source clips dictionary if not provided
        if source_clips is None:
            source_clips = {}

        # Extract all clips from the OTIO timeline
        otio_clips = []

        # Helper function to recursively extract clips
        def extract_clips(item):
            if isinstance(item, otio.schema.Clip):
                otio_clips.append(item)
            elif hasattr(item, '__iter__'):
                for child in item:
                    extract_clips(child)

        # Extract clips from all tracks
        for track in otio_timeline.tracks:
            extract_clips(track)

        # Create TimelineClip objects for each OTIO clip
        for otio_clip in otio_clips:
            # Skip clips without media reference
            if not hasattr(otio_clip, 'media_reference') or not otio_clip.media_reference:
                logger.warning(f"Skipping clip '{otio_clip.name}' with no media reference")
                continue

            # Skip non-external references
            if not isinstance(otio_clip.media_reference, otio.schema.ExternalReference):
                logger.warning(f"Skipping clip '{otio_clip.name}' with non-external media reference")
                continue

            source_path = otio_clip.media_reference.target_url

            # Get or create source clip
            if source_path in source_clips:
                source_clip = source_clips[source_path]
            else:
                source_clip = SourceClip.from_otio_media_reference(
                    otio_clip.media_reference,
                    name=os.path.basename(source_path)
                )
                source_clips[source_path] = source_clip

            # Create timeline clip
            timeline_clip = TimelineClip.from_otio_clip(otio_clip, source_clip)

            # Add to timeline
            timeline.add_clip(timeline_clip)

        logger.info(f"Created Timeline '{name}' with {len(timeline.clips)} clips from OTIO timeline")
        return timeline
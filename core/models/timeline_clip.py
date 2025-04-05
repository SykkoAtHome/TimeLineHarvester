"""
Timeline Clip Module

This module defines the TimelineClip class, which represents a clip placed on a timeline
with timing information relative to both the source and the timeline.
"""

import logging
from typing import Optional, Dict, Any, Union
import opentimelineio as otio

# Configure logging
logger = logging.getLogger(__name__)


class TimelineClip:
    """
    Represents a clip placed on a timeline.

    This class maintains information about a clip's position and timing on a timeline,
    as well as its relation to the source media.
    """

    def __init__(self,
                 name: str,
                 source_clip,  # Avoid direct import to prevent circular imports
                 source_start: Optional[otio.opentime.RationalTime] = None,
                 source_end: Optional[otio.opentime.RationalTime] = None,
                 timeline_start: Optional[otio.opentime.RationalTime] = None,
                 timeline_end: Optional[otio.opentime.RationalTime] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a TimelineClip instance.

        Args:
            name: Name of the clip on the timeline
            source_clip: SourceClip instance this timeline clip references
            source_start: Start time in the source media
            source_end: End time in the source media
            timeline_start: Start time on the timeline
            timeline_end: End time on the timeline
            metadata: Additional metadata associated with the clip
        """
        self.name = name
        self.source_clip = source_clip
        self.source_start = source_start
        self.source_end = source_end
        self.timeline_start = timeline_start
        self.timeline_end = timeline_end
        self.metadata = metadata or {}

        # Register this timeline clip with its source clip
        if source_clip:
            source_clip.add_timeline_clip(self)

    def __str__(self) -> str:
        """String representation of the timeline clip."""
        return f"TimelineClip('{self.name}', source='{self.source_clip.name if self.source_clip else 'None'}')"

    def __repr__(self) -> str:
        """Detailed representation of the timeline clip."""
        return (f"TimelineClip(name='{self.name}', "
                f"source_clip={self.source_clip}, "
                f"source_range={self.source_start}-{self.source_end}, "
                f"timeline_range={self.timeline_start}-{self.timeline_end})")

    @property
    def source_duration(self) -> Optional[otio.opentime.RationalTime]:
        """Get the duration of the clip in source time."""
        if self.source_start and self.source_end:
            return self.source_end - self.source_start
        return None

    @property
    def timeline_duration(self) -> Optional[otio.opentime.RationalTime]:
        """Get the duration of the clip on the timeline."""
        if self.timeline_start and self.timeline_end:
            return self.timeline_end - self.timeline_start
        return None

    def get_source_range(self) -> Optional[otio.opentime.TimeRange]:
        """Get the source time range."""
        if self.source_start and self.source_duration:
            return otio.opentime.TimeRange(self.source_start, self.source_duration)
        return None

    def get_timeline_range(self) -> Optional[otio.opentime.TimeRange]:
        """Get the timeline time range."""
        if self.timeline_start and self.timeline_duration:
            return otio.opentime.TimeRange(self.timeline_start, self.timeline_duration)
        return None

    def overlaps_source_range(self, start_time: otio.opentime.RationalTime,
                              end_time: otio.opentime.RationalTime) -> bool:
        """
        Check if this clip overlaps with a given source time range.

        Args:
            start_time: Start time to check
            end_time: End time to check

        Returns:
            True if this clip overlaps with the given range, False otherwise
        """
        if not self.source_start or not self.source_end:
            return False

        # Ensure we're comparing times with the same rate
        if start_time.rate != self.source_start.rate:
            start_time = start_time.rescaled_to(self.source_start.rate)
        if end_time.rate != self.source_end.rate:
            end_time = end_time.rescaled_to(self.source_end.rate)

        # Check for overlap
        return not (end_time <= self.source_start or start_time >= self.source_end)

    @classmethod
    def from_otio_clip(cls, otio_clip: otio.schema.Clip,
                       source_clip,
                       metadata: Optional[Dict[str, Any]] = None) -> 'TimelineClip':
        """
        Create a TimelineClip from an OTIO Clip object.

        Args:
            otio_clip: OTIO Clip object
            source_clip: SourceClip this TimelineClip references
            metadata: Additional metadata to store

        Returns:
            New TimelineClip instance
        """
        # Extract source range information
        source_start = None
        source_end = None
        if otio_clip.source_range:
            source_start = otio_clip.source_range.start_time
            source_end = otio_clip.source_range.end_time_exclusive()

        # Extract timeline range
        timeline_start = None
        timeline_end = None
        if otio_clip.range_in_parent():
            timeline_start = otio_clip.range_in_parent().start_time
            timeline_end = otio_clip.range_in_parent().end_time_exclusive()

        # Combine metadata from OTIO clip and provided metadata
        combined_metadata = {}
        if hasattr(otio_clip, 'metadata') and otio_clip.metadata:
            combined_metadata.update(otio_clip.metadata)
        if metadata:
            combined_metadata.update(metadata)

        return cls(
            name=otio_clip.name,
            source_clip=source_clip,
            source_start=source_start,
            source_end=source_end,
            timeline_start=timeline_start,
            timeline_end=timeline_end,
            metadata=combined_metadata
        )
"""
Transfer Segment Module

This module defines the TransferSegment class, which represents a consolidated
segment of source media that needs to be transferred, potentially spanning
multiple timeline clips.
"""

import os
import logging
from typing import Optional, Dict, List, Any, Set
import opentimelineio as otio

from .timeline_clip import TimelineClip

# Configure logging
logger = logging.getLogger(__name__)


class TransferSegment:
    """
    Represents a consolidated segment of source media for transfer.

    This class defines a continuous segment of source media that needs to be
    transferred, potentially spanning multiple timeline clips. It includes
    optimized start and end points to minimize transfer size while covering
    all required media.
    """

    def __init__(self,
                 name: str,
                 source_file: str,
                 source_start: otio.opentime.RationalTime,
                 source_end: otio.opentime.RationalTime,
                 timeline_clips: Optional[List[TimelineClip]] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a TransferSegment instance.

        Args:
            name: Name of the transfer segment
            source_file: Path to the source file
            source_start: Start time in the source
            source_end: End time in the source
            timeline_clips: List of TimelineClip objects covered by this segment
            metadata: Additional metadata
        """
        self.name = name
        self.source_file = source_file
        self.source_start = source_start
        self.source_end = source_end
        self.timeline_clips = timeline_clips or []
        self.metadata = metadata or {}

    def __str__(self) -> str:
        """String representation of the transfer segment."""
        return f"TransferSegment('{self.name}', covers {len(self.timeline_clips)} clips)"

    def __repr__(self) -> str:
        """Detailed representation of the transfer segment."""
        return (f"TransferSegment(name='{self.name}', "
                f"source_file='{self.source_file}', "
                f"source_range={self.source_start}-{self.source_end}, "
                f"clips_count={len(self.timeline_clips)})")

    @property
    def duration(self) -> otio.opentime.RationalTime:
        """Get the duration of this transfer segment."""
        return self.source_end - self.source_start

    @property
    def filename(self) -> str:
        """Get the base filename without directory path."""
        return os.path.basename(self.source_file)

    def get_duration_seconds(self) -> float:
        """Get the duration in seconds."""
        return self.duration.value / self.duration.rate

    def add_timeline_clip(self, clip: TimelineClip) -> None:
        """
        Add a TimelineClip to the list of clips covered by this segment.

        Args:
            clip: TimelineClip that is covered by this segment
        """
        if clip not in self.timeline_clips:
            self.timeline_clips.append(clip)

    def covers_clip(self, clip: TimelineClip) -> bool:
        """
        Check if this segment fully covers a timeline clip.

        Args:
            clip: TimelineClip to check

        Returns:
            True if this segment covers the entire source range of the clip
        """
        if not clip.source_start or not clip.source_end:
            return False

        # Ensure we're comparing times with the same rate
        start = clip.source_start
        end = clip.source_end

        if start.rate != self.source_start.rate:
            start = start.rescaled_to(self.source_start.rate)
        if end.rate != self.source_end.rate:
            end = end.rescaled_to(self.source_end.rate)

        # Check if this segment fully contains the clip
        return start >= self.source_start and end <= self.source_end

    def partially_covers_clip(self, clip: TimelineClip) -> bool:
        """
        Check if this segment partially covers a timeline clip.

        Args:
            clip: TimelineClip to check

        Returns:
            True if this segment at least partially covers the source range of the clip
        """
        if not clip.source_start or not clip.source_end:
            return False

        # Ensure we're comparing times with the same rate
        start = clip.source_start
        end = clip.source_end

        if start.rate != self.source_start.rate:
            start = start.rescaled_to(self.source_start.rate)
        if end.rate != self.source_end.rate:
            end = end.rescaled_to(self.source_end.rate)

        # Check for overlap
        return not (end <= self.source_start or start >= self.source_end)

    def get_otio_clip(self) -> otio.schema.Clip:
        """
        Create an OTIO clip representing this transfer segment.

        Returns:
            OTIO Clip object
        """
        # Create a media reference
        media_ref = otio.schema.ExternalReference(
            target_url=self.source_file
        )

        # Create source range
        source_range = otio.opentime.TimeRange(
            start_time=self.source_start,
            duration=self.duration
        )

        # Create the clip
        clip = otio.schema.Clip(
            name=self.name,
            media_reference=media_ref,
            source_range=source_range
        )

        return clip

    @classmethod
    def from_dict(cls, segment_dict: Dict[str, Any]) -> 'TransferSegment':
        """
        Create a TransferSegment from a dictionary.

        Args:
            segment_dict: Dictionary with segment information

        Returns:
            New TransferSegment instance
        """
        name = segment_dict.get('name', 'Unnamed Segment')
        source_file = segment_dict.get('source_file', '')
        source_start = segment_dict.get('source_start')
        source_end = segment_dict.get('source_end')

        # Extract metadata excluding the main fields
        metadata = {k: v for k, v in segment_dict.items()
                    if k not in ['name', 'source_file', 'source_start', 'source_end', 'original_segments']}

        segment = cls(
            name=name,
            source_file=source_file,
            source_start=source_start,
            source_end=source_end,
            metadata=metadata
        )

        return segment
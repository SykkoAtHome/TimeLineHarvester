"""
Source Clip Module

This module defines the SourceClip class, which represents a source media file
and its properties. It serves as a foundation for tracking media usage across
timelines.
"""

import os
from typing import Optional, Union, Dict, Any
import opentimelineio as otio


class SourceClip:
    """
    Represents a source media file and its metadata.

    This class maintains information about a source media file including its path,
    format, metadata, and any relevant timing information.
    """

    def __init__(self,
                 source_path: str,
                 name: Optional[str] = None,
                 frame_rate: Optional[float] = None,
                 duration: Optional[Union[float, otio.opentime.RationalTime]] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a SourceClip instance.

        Args:
            source_path: Path to the source media file
            name: Name of the source clip (defaults to base filename if not provided)
            frame_rate: Frame rate of the source media (frames per second)
            duration: Duration of the source media (in seconds or as RationalTime)
            metadata: Additional metadata associated with the source
        """
        self.source_path = source_path
        self.name = name if name else os.path.basename(source_path)
        self.frame_rate = frame_rate
        self.metadata = metadata or {}

        # Convert duration to RationalTime if provided as a float
        if duration is not None:
            if isinstance(duration, float):
                # If frame_rate is not provided, default to 24fps for conversion
                rate = frame_rate if frame_rate is not None else 24
                self.duration = otio.opentime.RationalTime(duration * rate, rate)
            else:
                self.duration = duration
        else:
            self.duration = None

        # Dictionary to track timeline clips that use this source
        self.timeline_clips = {}

    def __str__(self) -> str:
        """String representation of the source clip."""
        return f"SourceClip('{self.name}', path='{self.source_path}')"

    def __repr__(self) -> str:
        """Detailed representation of the source clip."""
        return (f"SourceClip(source_path='{self.source_path}', "
                f"name='{self.name}', "
                f"frame_rate={self.frame_rate}, "
                f"duration={self.duration})")

    @property
    def extension(self) -> str:
        """Get the file extension of the source file."""
        return os.path.splitext(self.source_path)[1].lower()

    @property
    def filename(self) -> str:
        """Get the base filename without directory path."""
        return os.path.basename(self.source_path)

    @property
    def directory(self) -> str:
        """Get the directory containing the source file."""
        return os.path.dirname(self.source_path)

    def get_duration_seconds(self) -> Optional[float]:
        """Get the duration in seconds, if available."""
        if self.duration:
            return self.duration.value / self.duration.rate
        return None

    def add_timeline_clip(self, timeline_clip) -> None:
        """
        Associate a TimelineClip with this source.

        Args:
            timeline_clip: The TimelineClip that uses this source
        """
        # Use timeline clip ID as key to avoid duplicates
        self.timeline_clips[id(timeline_clip)] = timeline_clip

    def get_timeline_clips(self) -> list:
        """
        Get all TimelineClips that use this source.

        Returns:
            List of TimelineClip objects that reference this source
        """
        return list(self.timeline_clips.values())

    @classmethod
    def from_otio_media_reference(cls, media_ref: otio.schema.ExternalReference,
                                  name: Optional[str] = None) -> 'SourceClip':
        """
        Create a SourceClip from an OTIO ExternalReference.

        Args:
            media_ref: OTIO ExternalReference object
            name: Optional name for the source clip

        Returns:
            New SourceClip instance
        """
        # Extract source path from the media reference
        source_path = media_ref.target_url

        # Extract any available metadata
        metadata = {}
        if hasattr(media_ref, 'metadata') and media_ref.metadata:
            metadata = dict(media_ref.metadata)

        # Try to extract frame rate from metadata if available
        frame_rate = None
        if (hasattr(media_ref, 'available_range') and
                media_ref.available_range and
                hasattr(media_ref.available_range.start_time, 'rate')):
            frame_rate = media_ref.available_range.start_time.rate

        # Try to extract duration from available_range if available
        duration = None
        if hasattr(media_ref, 'available_range') and media_ref.available_range:
            duration = media_ref.available_range.duration

        return cls(
            source_path=source_path,
            name=name,
            frame_rate=frame_rate,
            duration=duration,
            metadata=metadata
        )
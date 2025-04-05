"""
Transfer Plan Module

This module defines the TransferPlan class, which represents a comprehensive plan
for transferring optimized media segments from source files used in one or more timelines.
"""

import os
import logging
from typing import Optional, Dict, List, Any, Set, Union
from datetime import datetime
import opentimelineio as otio

from .timeline import Timeline
from .transfer_segment import TransferSegment

# Configure logging
logger = logging.getLogger(__name__)


class TransferPlan:
    """
    Represents a plan for transferring optimized media segments.

    This class maintains a collection of TransferSegment objects, along with
    metadata about the transfer plan itself, including optimization parameters.
    """

    def __init__(self,
                 name: Optional[str] = None,
                 min_gap_duration: float = 0.0,
                 start_handles: int = 0,
                 end_handles: Optional[int] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a TransferPlan instance.

        Args:
            name: Name of the transfer plan
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        (If None, will use the same value as start_handles)
            metadata: Additional metadata
        """
        # Generate a default name if not provided
        if name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"TransferPlan_{timestamp}"

        self.name = name
        self.min_gap_duration = min_gap_duration
        self.start_handles = start_handles
        self.end_handles = end_handles if end_handles is not None else start_handles
        self.metadata = metadata or {}

        # Collection of segments in this plan
        self.segments = []

        # Timelines this plan is based on
        self.timelines = []

        # Calculated statistics
        self.statistics = {}

    def __str__(self) -> str:
        """String representation of the transfer plan."""
        return f"TransferPlan('{self.name}', {len(self.segments)} segments)"

    def __repr__(self) -> str:
        """Detailed representation of the transfer plan."""
        return (f"TransferPlan(name='{self.name}', "
                f"segments_count={len(self.segments)}, "
                f"min_gap_duration={self.min_gap_duration}, "
                f"handles={self.start_handles}/{self.end_handles})")

    def add_segment(self, segment: TransferSegment) -> None:
        """
        Add a TransferSegment to the plan.

        Args:
            segment: TransferSegment to add
        """
        self.segments.append(segment)

    def add_timeline(self, timeline: Timeline) -> None:
        """
        Add a Timeline to the list of timelines this plan is based on.

        Args:
            timeline: Timeline that this plan covers
        """
        if timeline not in self.timelines:
            self.timelines.append(timeline)

    def get_segments(self) -> List[TransferSegment]:
        """
        Get all segments in the plan.

        Returns:
            List of TransferSegment objects
        """
        return self.segments

    def get_segment_by_source(self, source_file: str) -> List[TransferSegment]:
        """
        Get all segments for a specific source file.

        Args:
            source_file: Path to the source file

        Returns:
            List of TransferSegment objects for the source file
        """
        return [s for s in self.segments if s.source_file == source_file]

    def get_consolidated_timeline(self) -> otio.schema.Timeline:
        """
        Create a new timeline containing all consolidated segments.

        Returns:
            OTIO Timeline object with all segments arranged sequentially
        """
        # Create a new OTIO timeline
        timeline = otio.schema.Timeline(name=f"{self.name}_consolidated")

        # Create a video track
        video_track = otio.schema.Track(name="Video", kind="Video")
        timeline.tracks.append(video_track)

        # Current position in the timeline
        current_time = otio.opentime.RationalTime(0, 24)  # Starting at time 0, default 24fps

        # Add each segment as a clip to the timeline
        for segment in self.segments:
            # Create the OTIO clip
            otio_clip = segment.get_otio_clip()

            # Add to track
            video_track.append(otio_clip)

            # Update current time for next clip
            current_time += segment.duration

        logger.info(f"Created consolidated timeline with {len(self.segments)} segments")
        return timeline

    def calculate_statistics(self) -> Dict[str, Any]:
        """
        Calculate statistics about the transfer plan.

        Returns:
            Dictionary with various statistics
        """
        # Calculate total duration of all segments
        total_duration = otio.opentime.RationalTime(0, 24)
        for segment in self.segments:
            # Ensure consistent rate
            duration = segment.duration
            if duration.rate != total_duration.rate:
                duration = duration.rescaled_to(total_duration.rate)
            total_duration += duration

        # Count unique source files
        unique_sources = set(segment.source_file for segment in self.segments)

        # Calculate statistics by source
        segments_by_source = {}
        duration_by_source = {}

        for source in unique_sources:
            source_segments = self.get_segment_by_source(source)
            segments_by_source[source] = len(source_segments)

            source_duration = otio.opentime.RationalTime(0, 24)
            for segment in source_segments:
                duration = segment.duration
                if duration.rate != source_duration.rate:
                    duration = duration.rescaled_to(source_duration.rate)
                source_duration += duration

            duration_by_source[source] = source_duration

        # Create statistics dictionary
        stats = {
            'timeline_count': len(self.timelines),
            'segment_count': len(self.segments),
            'unique_sources': len(unique_sources),
            'total_duration': total_duration,
            'segments_by_source': segments_by_source,
            'duration_by_source': duration_by_source,
            'min_gap_duration': self.min_gap_duration,
            'start_handles': self.start_handles,
            'end_handles': self.end_handles,
        }

        # Store statistics
        self.statistics = stats

        return stats

    def estimate_savings(self,
                         original_durations: Optional[Dict[str, Union[float, otio.opentime.RationalTime]]] = None) -> \
    Dict[str, Any]:
        """
        Estimate the savings of this transfer plan.

        Args:
            original_durations: Optional dictionary mapping source files to their original durations.
                              If not provided, will make a rough estimate based on segments.

        Returns:
            Dictionary with savings information
        """
        if not self.statistics:
            self.calculate_statistics()

        # Calculate original and optimized durations
        original_duration = otio.opentime.RationalTime(0, 24)
        optimized_duration = self.statistics['total_duration']

        # If original durations are provided
        if original_durations:
            for source, duration in original_durations.items():
                # Convert to RationalTime if needed
                if isinstance(duration, float):
                    # Default to 24fps if we don't know better
                    duration = otio.opentime.RationalTime(duration * 24, 24)

                # Ensure consistent rate
                if duration.rate != original_duration.rate:
                    duration = duration.rescaled_to(original_duration.rate)

                original_duration += duration
        else:
            # Rough estimate: Find earliest and latest points in each source
            earliest_latest_by_source = {}

            for segment in self.segments:
                source = segment.source_file

                if source not in earliest_latest_by_source:
                    earliest_latest_by_source[source] = {
                        'earliest': segment.source_start,
                        'latest': segment.source_end
                    }
                else:
                    if segment.source_start < earliest_latest_by_source[source]['earliest']:
                        earliest_latest_by_source[source]['earliest'] = segment.source_start
                    if segment.source_end > earliest_latest_by_source[source]['latest']:
                        earliest_latest_by_source[source]['latest'] = segment.source_end

            # Sum up original durations (from earliest to latest point used)
            for source, times in earliest_latest_by_source.items():
                source_duration = times['latest'] - times['earliest']

                # Ensure consistent rate
                if source_duration.rate != original_duration.rate:
                    source_duration = source_duration.rescaled_to(original_duration.rate)

                original_duration += source_duration

        # Calculate savings
        savings = {
            'original_duration': original_duration,
            'optimized_duration': optimized_duration,
        }

        # Calculate percentage savings if original duration > 0
        if original_duration.value > 0:
            savings_percentage = (1 - (optimized_duration.value / original_duration.value)) * 100
            savings['savings_percentage'] = savings_percentage

        return savings

    @classmethod
    def from_dict(cls, plan_dict: Dict[str, Any]) -> 'TransferPlan':
        """
        Create a TransferPlan from a dictionary.

        Args:
            plan_dict: Dictionary with transfer plan information

        Returns:
            New TransferPlan instance
        """
        # Extract basic parameters
        name = plan_dict.get('name', f"ImportedPlan_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        min_gap_duration = plan_dict.get('min_gap_duration', 0.0)
        start_handles = plan_dict.get('start_handles', 0)
        end_handles = plan_dict.get('end_handles', start_handles)

        # Extract metadata excluding known fields
        metadata = {k: v for k, v in plan_dict.items()
                    if k not in ['name', 'min_gap_duration', 'start_handles', 'end_handles',
                                 'optimized_segments', 'statistics']}

        # Create the plan
        plan = cls(
            name=name,
            min_gap_duration=min_gap_duration,
            start_handles=start_handles,
            end_handles=end_handles,
            metadata=metadata
        )

        # Add segments if present
        segments_data = plan_dict.get('optimized_segments', [])
        for segment_data in segments_data:
            segment = TransferSegment.from_dict(segment_data)
            plan.add_segment(segment)

        # Add statistics if present
        if 'statistics' in plan_dict:
            plan.statistics = plan_dict['statistics']

        return plan
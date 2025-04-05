"""
Gap Detector Module

This module identifies unused regions ("gaps") in source files based on
the portions used in an editing timeline. It helps to optimize media transfers
by identifying parts of source files that can be skipped.

This version works with the model-based Timeline and Clip classes.
"""

import logging
import os
from typing import Dict, List, Optional, Any, Union

import opentimelineio as otio

from ..models import TimelineClip, Timeline, TransferSegment
from ..utils import (
    ensure_rational_time,
    ensure_non_negative_time,
    normalize_handles,
    apply_handles_to_range, rescale_time
)

# Configure logging
logger = logging.getLogger(__name__)


class GapDetector:
    """
    Detects and manages gaps (unused regions) in source media files.
    Works with the model-based Timeline and Clip classes.
    """

    def __init__(self, timeline_or_clips: Union[Timeline, List[TimelineClip], Dict[str, List[TimelineClip]]]):
        """
        Initialize the gap detector with timeline or clip information.

        Args:
            timeline_or_clips: Either a Timeline object, a list of TimelineClip objects,
                            or a dictionary mapping source files to lists of TimelineClip objects
        """
        # Dictionary to hold all clips by source file
        self.clips_by_source = {}

        # Process different input types
        if isinstance(timeline_or_clips, Timeline):
            # If given a Timeline, extract clips and group by source
            for clip in timeline_or_clips.get_clips():
                if not clip.source_clip:
                    continue
                source_path = clip.source_clip.source_path
                if source_path not in self.clips_by_source:
                    self.clips_by_source[source_path] = []
                self.clips_by_source[source_path].append(clip)

        elif isinstance(timeline_or_clips, list):
            # If given a list of clips, group by source
            for clip in timeline_or_clips:
                if not clip.source_clip:
                    continue
                source_path = clip.source_clip.source_path
                if source_path not in self.clips_by_source:
                    self.clips_by_source[source_path] = []
                self.clips_by_source[source_path].append(clip)

        elif isinstance(timeline_or_clips, dict):
            # If already grouped by source
            self.clips_by_source = timeline_or_clips

        else:
            raise TypeError("timeline_or_clips must be a Timeline, a list of TimelineClip objects, "
                            "or a dictionary mapping source files to TimelineClip lists")

    def find_gaps(self, source_file: str,
                  min_gap_duration: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Find gaps (unused regions) in a source file.

        Args:
            source_file: Path to the source file
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            List of dictionaries describing gaps in the source file
        """
        # Get all clips for this source
        clips = self.clips_by_source.get(source_file, [])
        if not clips:
            logger.warning(f"No usage found for source: {source_file}")
            return []

        # Sort clips by source start time
        sorted_clips = sorted(
            [c for c in clips if c.source_start],
            key=lambda c: c.source_start.value
        )

        if not sorted_clips:
            logger.warning(f"No clips with source timing for: {source_file}")
            return []

        # Find gaps between clips
        gaps = []
        for i in range(len(sorted_clips) - 1):
            current_end = sorted_clips[i].source_end
            next_start = sorted_clips[i + 1].source_start

            # If there's a gap between these clips
            if next_start > current_end:
                gap_duration = next_start - current_end

                # Skip if gap is smaller than minimum threshold
                if min_gap_duration is not None:
                    # Convert gap_duration to seconds for comparison
                    gap_seconds = gap_duration.value / gap_duration.rate
                    if gap_seconds < min_gap_duration:
                        continue

                # Record the gap
                gap = {
                    'source_file': source_file,
                    'gap_start': current_end,
                    'gap_end': next_start,
                    'duration': gap_duration
                }
                gaps.append(gap)

        logger.info(f"Found {len(gaps)} significant gaps in {source_file}")
        return gaps

    def find_all_gaps(self, min_gap_duration: Optional[float] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find gaps in all source files.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            Dictionary mapping source files to lists of gaps
        """
        all_gaps = {}

        for source_file in self.clips_by_source:
            gaps = self.find_gaps(source_file, min_gap_duration)
            if gaps:
                all_gaps[source_file] = gaps

        return all_gaps

    def calculate_gap_savings(self, min_gap_duration: Optional[float] = None) -> Dict[str, Any]:
        """
        Calculate potential savings from skipping gaps.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            Dictionary with statistics about potential savings
        """
        all_gaps = self.find_all_gaps(min_gap_duration)

        total_gaps = 0
        total_gap_duration = otio.opentime.RationalTime(0, 24)  # Default to 24fps
        savings_by_source = {}

        for source_file, gaps in all_gaps.items():
            source_gap_duration = otio.opentime.RationalTime(0, 24)

            for gap in gaps:
                total_gaps += 1
                duration = gap['duration']

                # Ensure we're using a consistent rate
                duration = rescale_time(duration, total_gap_duration.rate)
                total_gap_duration += duration
                source_gap_duration += duration

            savings_by_source[source_file] = {
                'num_gaps': len(gaps),
                'total_gap_duration': source_gap_duration
            }

        return {
            'total_gaps': total_gaps,
            'total_gap_duration': total_gap_duration,
            'savings_by_source': savings_by_source
        }

    def optimize_segments(self, source_file: str, min_gap_duration: float,
                          start_handles: int = 0, end_handles: Optional[int] = None) -> List[TransferSegment]:
        """
        Create optimized segments for a source file by splitting at significant gaps.

        Args:
            source_file: Path to the source file
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of TransferSegment objects with optimized source ranges
        """
        # Normalize handle values
        start_handles, end_handles = normalize_handles(start_handles, end_handles)

        # Get all clips for this source
        clips = self.clips_by_source.get(source_file, [])
        if not clips:
            logger.warning(f"No usage found for source: {source_file}")
            return []

        # Find gaps that are large enough to split at
        gaps = self.find_gaps(source_file, min_gap_duration)

        # Sort clips by source start time
        sorted_clips = sorted(
            [c for c in clips if c.source_start],
            key=lambda c: c.source_start.value
        )

        # If no clips with source_start, return empty list
        if not sorted_clips:
            logger.warning(f"No clips with source timing for: {source_file}")
            return []

        # Determine the frame rate to use for handles
        frame_rate = None
        for clip in sorted_clips:
            if clip.source_start and hasattr(clip.source_start, 'rate'):
                frame_rate = clip.source_start.rate
                break

        # Default to 24fps if we couldn't determine a rate
        if frame_rate is None:
            frame_rate = 24

        # If no significant gaps, merge all clips into one range
        if not gaps:
            # Create a single range covering all clips
            range_start, range_end = apply_handles_to_range(
                sorted_clips[0].source_start,
                sorted_clips[-1].source_end,
                start_handles,
                end_handles
            )

            segment_name = f"{os.path.basename(source_file)}_consolidated"
            segment = TransferSegment(
                name=segment_name,
                source_file=source_file,
                source_start=range_start,
                source_end=range_end,
                timeline_clips=sorted_clips  # No need to copy, we're not modifying the list
            )

            return [segment]

        # Sort gaps by start time
        sorted_gaps = sorted(gaps, key=lambda g: g['gap_start'].value)

        # Group clips separated by significant gaps
        optimized_segments = []
        current_group = []

        for i, clip in enumerate(sorted_clips):
            current_group.append(clip)

            # If this is the last clip or the next clip is after a significant gap
            is_last_clip = (i == len(sorted_clips) - 1)
            is_before_gap = False

            if not is_last_clip:
                next_clip = sorted_clips[i + 1]
                clip_end = clip.source_end
                next_start = next_clip.source_start

                # Check if this clip and the next are separated by a gap
                for gap in sorted_gaps:
                    if (gap['gap_start'] == clip_end and
                            gap['gap_end'] == next_start):
                        is_before_gap = True
                        break

            # If we've reached a boundary, create a consolidated range
            if is_last_clip or is_before_gap:
                if current_group:
                    range_start, range_end = apply_handles_to_range(
                        current_group[0].source_start,
                        current_group[-1].source_end,
                        start_handles,
                        end_handles
                    )

                    segment_name = f"{os.path.basename(source_file)}_opt_{len(optimized_segments) + 1}"
                    segment = TransferSegment(
                        name=segment_name,
                        source_file=source_file,
                        source_start=range_start,
                        source_end=range_end,
                        timeline_clips=current_group  # Pass the current group directly
                    )
                    optimized_segments.append(segment)
                    current_group = []  # Reset for next group

        logger.info(f"Created {len(optimized_segments)} optimized segments for {source_file} "
                    f"based on {len(gaps)} significant gaps")
        return optimized_segments

    def optimize_all_segments(self, min_gap_duration: float,
                              start_handles: int = 0, end_handles: Optional[int] = None) -> List[TransferSegment]:
        """
        Create optimized segments for all source files.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of TransferSegment objects with optimized source ranges for all sources
        """
        # Normalize handle values
        start_handles, end_handles = normalize_handles(start_handles, end_handles)

        all_optimized = []

        for source_file in self.clips_by_source:
            optimized = self.optimize_segments(source_file, min_gap_duration, start_handles, end_handles)
            all_optimized.extend(optimized)

        return all_optimized
"""
Timeline Analyzer Module

This module analyzes one or multiple timelines (EDL/AAF/XML) to identify source file usage,
detect gaps, and generate optimized transfer plans. It leverages the model classes for
better object-oriented design and cleaner code.
"""

import logging
import os
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from collections import defaultdict

import opentimelineio as otio

from ..timeline_io import read_timeline
from ..models import SourceClip, TimelineClip, Timeline, TransferSegment, TransferPlan
from .gap_detector import GapDetector

# Configure logging
logger = logging.getLogger(__name__)


class TimelineAnalyzer:
    """
    Analyzes timelines to identify source usage patterns and optimize media transfers.
    Can work with a single timeline or multiple timelines.
    """

    def __init__(self, timeline: Optional[Union[otio.schema.Timeline, Timeline]] = None):
        """
        Initialize the analyzer with an optional timeline.

        Args:
            timeline: An optional Timeline or OTIO Timeline object to analyze
        """
        self.timelines = []  # List of Timeline objects
        self.source_clips = {}  # Dictionary mapping source paths to SourceClip objects

        # Add the initial timeline if provided
        if timeline:
            self.add_timeline(timeline)

    def add_timeline(self, timeline_or_path: Union[str, otio.schema.Timeline, Timeline],
                     fps: Optional[float] = None) -> Timeline:
        """
        Add a timeline to the analysis.

        Args:
            timeline_or_path: Either a Timeline object, an OTIO Timeline, or a path to a timeline file
            fps: Frames per second to use if not specified in the file (when path is provided)

        Returns:
            The added Timeline object
        """
        # Handle different input types
        if isinstance(timeline_or_path, str):
            # Read OTIO timeline from file
            otio_timeline = read_timeline(timeline_or_path, fps)
            # Convert to our Timeline model
            timeline = Timeline.from_otio_timeline(otio_timeline, self.source_clips)
            logger.info(f"Added timeline from file: {timeline_or_path}")

        elif isinstance(timeline_or_path, otio.schema.Timeline):
            # Convert OTIO timeline to our Timeline model
            timeline = Timeline.from_otio_timeline(timeline_or_path, self.source_clips)
            logger.info(f"Added OTIO timeline: {timeline.name}")

        elif isinstance(timeline_or_path, Timeline):
            # Already a Timeline object
            timeline = timeline_or_path
            logger.info(f"Added Timeline object: {timeline.name}")

        else:
            raise TypeError("timeline_or_path must be a path, an OTIO Timeline, or a Timeline object")

        # Add timeline to our list
        self.timelines.append(timeline)

        # Update our source clips dictionary
        for source_path, source_clip in timeline.sources.items():
            if source_path not in self.source_clips:
                self.source_clips[source_path] = source_clip

        logger.info(f"Added timeline '{timeline.name}' to analysis. "
                    f"Total timelines: {len(self.timelines)}")

        return timeline

    def add_timelines(self, timeline_paths: List[str], fps: Optional[float] = None) -> List[Timeline]:
        """
        Add multiple timelines to the analysis.

        Args:
            timeline_paths: List of paths to timeline files
            fps: Frames per second to use if not specified in the files

        Returns:
            List of added Timeline objects
        """
        return [self.add_timeline(path, fps) for path in timeline_paths]

    def get_unique_sources(self) -> List[str]:
        """
        Get a list of all unique source files used across all analyzed timelines.

        Returns:
            List of source file paths
        """
        return list(self.source_clips.keys())

    def get_source_usage(self, source_file: Optional[str] = None) -> Dict:
        """
        Get usage information for source files.

        Args:
            source_file: Optional specific source file to get info for.
                         If None, returns info for all sources.

        Returns:
            Dictionary mapping source files to their usage ranges,
            or a list of usage ranges for a specific source file
        """
        source_usage = defaultdict(list)

        # Iterate through all timelines and their clips
        for timeline in self.timelines:
            for clip in timeline.clips:
                if not clip.source_clip:
                    continue

                source_path = clip.source_clip.source_path

                # If looking for a specific source and this isn't it, skip
                if source_file and source_path != source_file:
                    continue

                # Record this usage of the source file
                source_usage[source_path].append({
                    'name': clip.name,
                    'source_start': clip.source_start,
                    'source_end': clip.source_end,
                    'timeline_start': clip.timeline_start,
                    'timeline_end': clip.timeline_end,
                    'timeline_name': timeline.name
                })

        # If a specific source was requested, return just its usages
        if source_file:
            return source_usage.get(source_file, [])

        return dict(source_usage)

    def _get_clips_by_source(self) -> Dict[str, List[TimelineClip]]:
        """
        Helper method to organize timeline clips by source file.
        This is used to create a GapDetector with our clips.

        Returns:
            Dictionary mapping source file paths to lists of TimelineClip objects
        """
        clips_by_source = defaultdict(list)

        for source_path, source_clip in self.source_clips.items():
            clips_by_source[source_path] = source_clip.get_timeline_clips()

        return dict(clips_by_source)

    def find_gaps(self, source_file: str,
                  min_gap_duration: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Find gaps (unused regions) in a source file.

        Uses GapDetector to avoid code duplication.

        Args:
            source_file: Path to the source file
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            List of dictionaries describing gaps in the source file
        """
        # Create a gap detector with our clips
        gap_detector = GapDetector(self._get_clips_by_source())
        return gap_detector.find_gaps(source_file, min_gap_duration)

    def find_all_gaps(self, min_gap_duration: Optional[float] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find gaps in all source files.

        Uses GapDetector to avoid code duplication.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            Dictionary mapping source files to lists of gaps
        """
        # Create a gap detector with our clips
        gap_detector = GapDetector(self._get_clips_by_source())
        return gap_detector.find_all_gaps(min_gap_duration)

    def calculate_gap_savings(self, min_gap_duration: Optional[float] = None) -> Dict[str, Any]:
        """
        Calculate potential savings from skipping gaps.

        Uses GapDetector to avoid code duplication.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            Dictionary with statistics about potential savings
        """
        # Create a gap detector with our clips
        gap_detector = GapDetector(self._get_clips_by_source())
        return gap_detector.calculate_gap_savings(min_gap_duration)

    def get_consolidated_ranges(self, source_file: str,
                                start_handles: int = 0,
                                end_handles: Optional[int] = None) -> List[TransferSegment]:
        """
        Get consolidated time ranges for a source file, merging overlapping segments.

        Args:
            source_file: Path to the source file
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of TransferSegment objects with consolidated source ranges
        """
        # If end_handles is not specified, use the same value as start_handles
        if end_handles is None:
            end_handles = start_handles

        # Get the source clip
        source_clip = self.source_clips.get(source_file)
        if not source_clip:
            logger.warning(f"No source clip found for path: {source_file}")
            return []

        # Get all timeline clips that use this source
        timeline_clips = source_clip.get_timeline_clips()

        # Skip if no timeline clips use this source
        if not timeline_clips:
            logger.warning(f"No usage found for source: {source_file}")
            return []

        # Determine the frame rate to use for handles
        frame_rate = None
        for clip in timeline_clips:
            if clip.source_start and hasattr(clip.source_start, 'rate'):
                frame_rate = clip.source_start.rate
                break

        # Default to 24fps if we couldn't determine a rate
        if frame_rate is None:
            frame_rate = 24

        # Convert handles to time units
        start_handle_time = otio.opentime.RationalTime(start_handles, frame_rate)
        end_handle_time = otio.opentime.RationalTime(end_handles, frame_rate)

        # Sort clips by source start time
        sorted_clips = sorted(
            [c for c in timeline_clips if c.source_start],
            key=lambda c: c.source_start.value
        )

        # Merge overlapping segments
        consolidated_segments = []

        if sorted_clips:
            # Start with the first clip
            current_start = sorted_clips[0].source_start - start_handle_time
            current_end = sorted_clips[0].source_end + end_handle_time
            current_clips = [sorted_clips[0]]

            # Ensure start time is not negative
            if current_start.value < 0:
                current_start = otio.opentime.RationalTime(0, current_start.rate)

            # Process remaining clips
            for clip in sorted_clips[1:]:
                clip_start = clip.source_start - start_handle_time
                clip_end = clip.source_end + end_handle_time

                # Ensure clip_start is not negative
                if clip_start.value < 0:
                    clip_start = otio.opentime.RationalTime(0, clip_start.rate)

                # If this clip overlaps with the current segment, extend it
                if clip_start <= current_end:
                    if clip_end > current_end:
                        current_end = clip_end
                    current_clips.append(clip)
                else:
                    # No overlap, create a new segment
                    segment_name = f"{os.path.basename(source_file)}_consolidated_{len(consolidated_segments) + 1}"
                    segment = TransferSegment(
                        name=segment_name,
                        source_file=source_file,
                        source_start=current_start,
                        source_end=current_end,
                        timeline_clips=current_clips  # Pass directly, no need for .copy()
                    )
                    consolidated_segments.append(segment)

                    # Start a new segment
                    current_start = clip_start
                    current_end = clip_end
                    current_clips = [clip]

            # Add the final segment
            segment_name = f"{os.path.basename(source_file)}_consolidated_{len(consolidated_segments) + 1}"
            segment = TransferSegment(
                name=segment_name,
                source_file=source_file,
                source_start=current_start,
                source_end=current_end,
                timeline_clips=current_clips  # Pass directly, no need for .copy()
            )
            consolidated_segments.append(segment)

        logger.info(
            f"Consolidated {len(sorted_clips)} clips into {len(consolidated_segments)} ranges for {source_file}")
        return consolidated_segments

    def get_all_consolidated_ranges(self, start_handles: int = 0,
                                    end_handles: Optional[int] = None) -> List[TransferSegment]:
        """
        Get consolidated time ranges for all source files.

        Args:
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of TransferSegment objects with consolidated source ranges for all sources
        """
        all_consolidated = []

        for source_path in self.source_clips:
            consolidated = self.get_consolidated_ranges(source_path, start_handles, end_handles)
            all_consolidated.extend(consolidated)

        return all_consolidated

    def optimize_segments(self, source_file: str, min_gap_duration: float,
                          start_handles: int = 0, end_handles: Optional[int] = None) -> List[TransferSegment]:
        """
        Create optimized segments for a source file by splitting at significant gaps.

        Uses GapDetector to avoid code duplication.

        Args:
            source_file: Path to the source file
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of TransferSegment objects with optimized source ranges
        """
        # Validate the min_gap_duration parameter
        if min_gap_duration < 0:
            logger.warning(f"min_gap_duration should be non-negative, got {min_gap_duration}. "
                           f"Treating as 0.")
            min_gap_duration = 0

        # If no significant gaps needed, just return consolidated ranges
        if min_gap_duration == 0:
            return self.get_consolidated_ranges(source_file, start_handles, end_handles)

        # Create a gap detector with our clips
        gap_detector = GapDetector(self._get_clips_by_source())
        return gap_detector.optimize_segments(source_file, min_gap_duration, start_handles, end_handles)

    def optimize_all_segments(self, min_gap_duration: float,
                              start_handles: int = 0, end_handles: Optional[int] = None) -> List[TransferSegment]:
        """
        Create optimized segments for all source files.

        Uses GapDetector to avoid code duplication.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of TransferSegment objects with optimized source ranges for all sources
        """
        # Create a gap detector with our clips
        gap_detector = GapDetector(self._get_clips_by_source())
        return gap_detector.optimize_all_segments(min_gap_duration, start_handles, end_handles)

    def get_timeline_statistics(self) -> Dict[str, Any]:
        """
        Generate statistics about the timeline(s) and source usage.

        Returns:
            Dictionary with various statistics
        """
        total_clips = 0
        unique_sources = len(self.source_clips)
        timeline_names = []

        # Calculate total duration of all used segments and gaps
        total_used_duration = otio.opentime.RationalTime(0, 24)

        # Process each timeline to collect clips and durations
        for timeline in self.timelines:
            timeline_names.append(timeline.name)

            # Count clips in this timeline
            clips = timeline.get_clips()
            total_clips += len(clips)

            # Get timeline duration if available
            timeline_duration = timeline.duration
            if timeline_duration:
                # Ensure consistent rate
                if timeline_duration.rate != total_used_duration.rate:
                    timeline_duration = timeline_duration.rescaled_to(total_used_duration.rate)
                total_used_duration += timeline_duration

        # Calculate usage and gap statistics
        gap_stats = self.calculate_gap_savings()

        stats = {
            'timeline_count': len(self.timelines),
            'timeline_names': timeline_names,
            'total_clips': total_clips,
            'unique_sources': unique_sources,
            'total_used_duration': total_used_duration,
            'gap_statistics': gap_stats
        }

        return stats

    def create_transfer_plan(self, min_gap_duration: float = 0,
                             start_handles: int = 0, end_handles: Optional[int] = None) -> TransferPlan:
        """
        Create a comprehensive transfer plan based on all analyzed timelines.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            TransferPlan object with all optimized segments
        """
        # Validate end_handles
        if end_handles is not None and not isinstance(end_handles, int):
            logger.warning(f"end_handles should be an integer, got {type(end_handles)}. "
                           f"Using start_handles value ({start_handles}).")
            end_handles = start_handles

        # Create a new transfer plan
        plan_name = f"TransferPlan_{len(self.timelines)}_timelines"
        transfer_plan = TransferPlan(
            name=plan_name,
            min_gap_duration=min_gap_duration,
            start_handles=start_handles,
            end_handles=end_handles
        )

        # Add all timelines to the plan
        for timeline in self.timelines:
            transfer_plan.add_timeline(timeline)

        # Get optimized segments and add them to the plan
        optimized_segments = self.optimize_all_segments(min_gap_duration, start_handles, end_handles)
        for segment in optimized_segments:
            transfer_plan.add_segment(segment)

        # Calculate statistics
        transfer_plan.calculate_statistics()

        # Estimate savings
        transfer_plan.estimate_savings()

        logger.info(f"Created transfer plan for {len(self.timelines)} timelines with "
                    f"{len(optimized_segments)} optimized segments.")

        return transfer_plan
"""
Timeline Analyzer Module

This module analyzes one or multiple timelines (EDL/AAF/XML) to identify source file usage,
detect gaps, and generate optimized transfer plans. It can work with a single timeline
or combine analysis from multiple timelines into a unified view.
"""

import logging
import os
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from collections import defaultdict

import opentimelineio as otio

from ..timeline_io import read_timeline, get_timeline_clips, get_clip_source_info

# Configure logging
logger = logging.getLogger(__name__)


class TimelineAnalyzer:
    """
    Analyzes timelines to identify source usage patterns and optimize media transfers.
    Can work with a single timeline or multiple timelines.
    """

    def __init__(self, timeline: Optional[otio.schema.Timeline] = None):
        """
        Initialize the analyzer with an optional timeline.

        Args:
            timeline: An optional OTIO Timeline object to analyze
        """
        self.timelines = []  # List of all timelines
        self.source_usage = defaultdict(list)  # Maps source files to their usage ranges

        # Add the initial timeline if provided
        if timeline:
            self.add_timeline(timeline)

    def add_timeline(self, timeline_or_path: Union[str, otio.schema.Timeline],
                     fps: Optional[float] = None) -> None:
        """
        Add a timeline to the analysis.

        Args:
            timeline_or_path: Either an OTIO Timeline object or a path to a timeline file
            fps: Frames per second to use if not specified in the file (when path is provided)
        """
        # If a path is provided, read the timeline
        if isinstance(timeline_or_path, str):
            try:
                timeline = read_timeline(timeline_or_path, fps)
                logger.info(f"Successfully read timeline from: {timeline_or_path}")
            except Exception as e:
                logger.error(f"Failed to read timeline from {timeline_or_path}: {str(e)}")
                raise
        else:
            timeline = timeline_or_path

        # Add to our list of timelines
        self.timelines.append(timeline)

        # Extract clips and update source usage
        self._analyze_timeline(timeline)

        logger.info(f"Added timeline '{timeline.name}' to analysis. "
                    f"Total timelines: {len(self.timelines)}")

    def add_timelines(self, timeline_paths: List[str], fps: Optional[float] = None) -> None:
        """
        Add multiple timelines to the analysis.

        Args:
            timeline_paths: List of paths to timeline files
            fps: Frames per second to use if not specified in the files
        """
        for path in timeline_paths:
            self.add_timeline(path, fps)

    def _analyze_timeline(self, timeline: otio.schema.Timeline) -> None:
        """
        Analyze a timeline to identify all source files and their usage.
        Updates the source_usage dictionary.

        Args:
            timeline: OTIO Timeline object to analyze
        """
        logger.info(f"Analyzing timeline: {timeline.name}")

        # Extract all clips from the timeline
        clips = get_timeline_clips(timeline)

        for clip in clips:
            source_info = get_clip_source_info(clip)

            # Skip clips without source file information
            if not source_info['source_file']:
                logger.warning(f"Clip '{clip.name}' has no source file reference - skipping")
                continue

            # Record this usage of the source file
            self.source_usage[source_info['source_file']].append({
                'name': source_info['name'],
                'source_start': source_info['source_start'],
                'source_end': source_info['source_end'],
                'timeline_start': source_info['timeline_start'],
                'timeline_end': source_info['timeline_end'],
                'timeline_name': timeline.name  # Track which timeline this usage is from
            })

        logger.info(f"Found {len(clips)} clips in timeline '{timeline.name}'")
        logger.info(f"Now tracking {len(self.source_usage)} unique source files across all timelines")

    def get_unique_sources(self) -> List[str]:
        """
        Get a list of all unique source files used across all analyzed timelines.

        Returns:
            List of source file paths
        """
        return list(self.source_usage.keys())

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
        if source_file:
            return self.source_usage.get(source_file, [])
        return dict(self.source_usage)

    def get_consolidated_ranges(self, source_file: str,
                                start_handles: int = 0,
                                end_handles: int = None) -> List[Dict[str, Any]]:
        """
        Get consolidated time ranges for a source file, merging overlapping segments.

        Args:
            source_file: Path to the source file
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of dictionaries with consolidated source ranges
        """
        # Get all segments for this source
        segments = self.source_usage.get(source_file, [])
        if not segments:
            logger.warning(f"No usage found for source: {source_file}")
            return []

        # If end_handles is not specified, use the same value as start_handles
        if end_handles is None:
            end_handles = start_handles

        # Convert handles to the appropriate time units
        # We'll assume the first segment's time base is representative
        if segments:
            first_segment = segments[0]
            if (first_segment['source_start'] and
                    hasattr(first_segment['source_start'], 'rate')):
                frame_rate = first_segment['source_start'].rate
            else:
                # Default to 24fps if we can't determine the rate
                frame_rate = 24

            # Convert handles to time units
            start_handle_time = otio.opentime.RationalTime(start_handles, frame_rate)
            end_handle_time = otio.opentime.RationalTime(end_handles, frame_rate)
        else:
            # Zero handles as default with 24fps
            start_handle_time = otio.opentime.RationalTime(0, 24)
            end_handle_time = otio.opentime.RationalTime(0, 24)

        # Sort segments by start time
        sorted_segments = sorted(segments,
                                 key=lambda x: x['source_start'].value if x['source_start'] else float('inf'))

        # Merge overlapping segments
        consolidated = []
        if sorted_segments:
            # Start with the first segment
            current_range = {
                'name': f"{os.path.basename(source_file)}_consolidated_1",
                'source_file': source_file,
                'source_start': sorted_segments[0]['source_start'] - start_handle_time,
                'source_end': sorted_segments[0]['source_end'] + end_handle_time,
                'original_segments': [sorted_segments[0]]
            }

            # Ensure source_start is not negative
            if current_range['source_start'].value < 0:
                current_range['source_start'] = otio.opentime.RationalTime(0, current_range['source_start'].rate)

            # Process remaining segments
            for segment in sorted_segments[1:]:
                segment_start = segment['source_start'] - start_handle_time
                segment_end = segment['source_end'] + end_handle_time

                # Ensure segment_start is not negative
                if segment_start.value < 0:
                    segment_start = otio.opentime.RationalTime(0, segment_start.rate)

                # If this segment overlaps with the current range, extend it
                if segment_start <= current_range['source_end']:
                    if segment_end > current_range['source_end']:
                        current_range['source_end'] = segment_end
                    current_range['original_segments'].append(segment)
                else:
                    # No overlap, start a new range
                    consolidated.append(current_range)
                    current_range = {
                        'name': f"{os.path.basename(source_file)}_consolidated_{len(consolidated) + 1}",
                        'source_file': source_file,
                        'source_start': segment_start,
                        'source_end': segment_end,
                        'original_segments': [segment]
                    }

            # Add the last range
            consolidated.append(current_range)

        logger.info(f"Consolidated {len(segments)} segments into {len(consolidated)} ranges for {source_file}")
        return consolidated

    def get_all_consolidated_ranges(self, start_handles: int = 0,
                                    end_handles: int = None) -> List[Dict[str, Any]]:
        """
        Get consolidated time ranges for all source files.

        Args:
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of dictionaries with consolidated source ranges for all sources
        """
        all_consolidated = []

        for source_file in self.source_usage:
            consolidated = self.get_consolidated_ranges(source_file, start_handles, end_handles)
            all_consolidated.extend(consolidated)

        return all_consolidated

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
        # Get all segments for this source
        segments = self.source_usage.get(source_file, [])
        if not segments:
            logger.warning(f"No usage found for source: {source_file}")
            return []

        # Sort segments by start time
        sorted_segments = sorted(segments,
                                 key=lambda x: x['source_start'].value if x['source_start'] else float('inf'))

        # Find gaps between segments
        gaps = []
        for i in range(len(sorted_segments) - 1):
            current_end = sorted_segments[i]['source_end']
            next_start = sorted_segments[i + 1]['source_start']

            # If there's a gap between these segments
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

        for source_file in self.source_usage:
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
                if duration.rate != total_gap_duration.rate:
                    duration = duration.rescaled_to(total_gap_duration.rate)

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
                          start_handles: int = 0, end_handles: int = None) -> List[Dict[str, Any]]:
        """
        Create optimized segments for a source file by splitting at significant gaps.

        Args:
            source_file: Path to the source file
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of dictionaries with optimized source ranges
        """
        # If end_handles is not specified, use the same value as start_handles
        if end_handles is None:
            end_handles = start_handles

        # Get all segments for this source
        segments = self.source_usage.get(source_file, [])
        if not segments:
            logger.warning(f"No usage found for source: {source_file}")
            return []

        # Find gaps that are large enough to split at
        gaps = self.find_gaps(source_file, min_gap_duration)

        # If no significant gaps, merge all segments into one range
        if not gaps:
            # Sort segments by start time
            sorted_segments = sorted(segments,
                                     key=lambda x: x['source_start'].value if x['source_start'] else float('inf'))

            # Convert handles to the appropriate time units
            if sorted_segments:
                first_segment = sorted_segments[0]
                if (first_segment['source_start'] and
                        hasattr(first_segment['source_start'], 'rate')):
                    frame_rate = first_segment['source_start'].rate
                else:
                    # Default to 24fps if we can't determine the rate
                    frame_rate = 24

                # Convert handles to time units
                start_handle_time = otio.opentime.RationalTime(start_handles, frame_rate)
                end_handle_time = otio.opentime.RationalTime(end_handles, frame_rate)
            else:
                # Zero handles as default with 24fps
                start_handle_time = otio.opentime.RationalTime(0, 24)
                end_handle_time = otio.opentime.RationalTime(0, 24)

            # Create a single range covering all segments
            consolidated = [{
                'name': f"{source_file.split('/')[-1].split('\\')[-1]}_consolidated",
                'source_file': source_file,
                'source_start': sorted_segments[0]['source_start'] - start_handle_time,
                'source_end': sorted_segments[-1]['source_end'] + end_handle_time,
                'original_segments': sorted_segments.copy()
            }]

            # Ensure source_start is not negative
            if consolidated[0]['source_start'].value < 0:
                consolidated[0]['source_start'] = otio.opentime.RationalTime(0, consolidated[0]['source_start'].rate)

            return consolidated

        # Sort both segments and gaps by start time
        sorted_segments = sorted(segments,
                                 key=lambda x: x['source_start'].value if x['source_start'] else float('inf'))
        sorted_gaps = sorted(gaps,
                             key=lambda x: x['gap_start'].value if x['gap_start'] else float('inf'))

        # Convert handles to the appropriate time units
        if sorted_segments:
            first_segment = sorted_segments[0]
            if (first_segment['source_start'] and
                    hasattr(first_segment['source_start'], 'rate')):
                frame_rate = first_segment['source_start'].rate
            else:
                # Default to 24fps if we can't determine the rate
                frame_rate = 24

            # Convert handles to time units
            start_handle_time = otio.opentime.RationalTime(start_handles, frame_rate)
            end_handle_time = otio.opentime.RationalTime(end_handles, frame_rate)
        else:
            # Zero handles as default with 24fps
            start_handle_time = otio.opentime.RationalTime(0, 24)
            end_handle_time = otio.opentime.RationalTime(0, 24)

        # Group segments separated by significant gaps
        optimized_ranges = []
        current_group = []

        for i, segment in enumerate(sorted_segments):
            current_group.append(segment)

            # If this is the last segment or the next segment is after a significant gap
            is_last_segment = (i == len(sorted_segments) - 1)
            is_before_gap = False

            if not is_last_segment:
                next_segment = sorted_segments[i + 1]
                segment_end = segment['source_end']
                next_start = next_segment['source_start']

                # Check if this segment and the next are separated by a gap
                for gap in sorted_gaps:
                    if (gap['gap_start'] == segment_end and
                            gap['gap_end'] == next_start):
                        is_before_gap = True
                        break

            # If we've reached a boundary, create a consolidated range
            if is_last_segment or is_before_gap:
                if current_group:
                    range_start = current_group[0]['source_start'] - start_handle_time
                    range_end = current_group[-1]['source_end'] + end_handle_time

                    # Ensure range_start is not negative
                    if range_start.value < 0:
                        range_start = otio.opentime.RationalTime(0, range_start.rate)

                    optimized_range = {
                        'name': f"{os.path.basename(source_file)}_opt_{len(optimized_ranges) + 1}",
                        'source_file': source_file,
                        'source_start': range_start,
                        'source_end': range_end,
                        'original_segments': current_group.copy()
                    }
                    optimized_ranges.append(optimized_range)
                    current_group = []

        logger.info(f"Created {len(optimized_ranges)} optimized ranges for {source_file} "
                    f"based on {len(gaps)} significant gaps")
        return optimized_ranges

    def optimize_all_segments(self, min_gap_duration: float,
                              start_handles: int = 0, end_handles: int = None) -> List[Dict[str, Any]]:
        """
        Create optimized segments for all source files.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            List of dictionaries with optimized source ranges for all sources
        """
        all_optimized = []

        for source_file in self.source_usage:
            optimized = self.optimize_segments(source_file, min_gap_duration, start_handles, end_handles)
            all_optimized.extend(optimized)

        return all_optimized

    def get_timeline_statistics(self) -> Dict[str, Any]:
        """
        Generate statistics about the timeline(s) and source usage.

        Returns:
            Dictionary with various statistics
        """
        total_clips = 0
        unique_sources = len(self.source_usage)
        timeline_names = []

        # Calculate total duration of all used segments and gaps
        total_used_duration = otio.opentime.RationalTime(0, 24)

        # Process each timeline to collect clips and durations
        for timeline in self.timelines:
            timeline_names.append(timeline.name)

            # Count clips in this timeline
            clips = get_timeline_clips(timeline)
            total_clips += len(clips)

            # Get timeline duration if available
            if timeline.duration():
                timeline_duration = timeline.duration()
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
                             start_handles: int = 0, end_handles: int = None) -> Dict[str, Any]:
        """
        Create a comprehensive transfer plan based on all analyzed timelines.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            Dictionary with transfer plan information
        """
        # Get optimized segments
        optimized_segments = self.optimize_all_segments(min_gap_duration, start_handles, end_handles)

        # Generate statistics
        stats = self.get_timeline_statistics()

        # Calculate potential savings
        original_duration = otio.opentime.RationalTime(0, 24)
        optimized_duration = otio.opentime.RationalTime(0, 24)

        for source_file, segments in self.source_usage.items():
            # Find source file duration (assume it extends from first to last used frame)
            if segments:
                sorted_segments = sorted(segments,
                                         key=lambda x: x['source_start'].value if x['source_start'] else float('inf'))
                first_segment = sorted_segments[0]
                last_segment = sorted_segments[-1]

                # Roughly estimate original duration as time from start of first to end of last
                source_duration = last_segment['source_end'] - first_segment['source_start']
                original_duration += source_duration

        # Calculate optimized duration
        for segment in optimized_segments:
            segment_duration = segment['source_end'] - segment['source_start']
            optimized_duration += segment_duration

        # Create the transfer plan
        transfer_plan = {
            'timeline_count': len(self.timelines),
            'unique_sources': len(self.source_usage),
            'optimized_segments': optimized_segments,
            'segment_count': len(optimized_segments),
            'original_duration': original_duration,
            'optimized_duration': optimized_duration,
            'start_handles': start_handles,
            'end_handles': end_handles if end_handles is not None else start_handles,
            'min_gap_duration': min_gap_duration,
            'statistics': stats
        }

        # Calculate savings percentage if original duration > 0
        if original_duration.value > 0:
            savings_percentage = (1 - (optimized_duration.value / original_duration.value)) * 100
            transfer_plan['savings_percentage'] = savings_percentage

        logger.info(f"Created transfer plan for {len(self.timelines)} timelines with "
                    f"{len(optimized_segments)} optimized segments.")

        return transfer_plan
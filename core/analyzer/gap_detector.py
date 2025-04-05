"""
Gap Detector Module

This module identifies unused regions ("gaps") in source files based on
the portions used in an editing timeline. It helps to optimize media transfers
by identifying parts of source files that can be skipped.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any

import opentimelineio as otio

# Configure logging
logger = logging.getLogger(__name__)


class GapDetector:
    """
    Detects and manages gaps (unused regions) in source media files.
    """

    def __init__(self, source_usage: Dict[str, List[Dict[str, Any]]]):
        """
        Initialize the gap detector with source usage information.

        Args:
            source_usage: Dictionary mapping source files to their usage ranges
                         (as provided by TimelineAnalyzer.get_source_usage())
        """
        self.source_usage = source_usage

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
                          handles: int = 0) -> List[Dict[str, Any]]:
        """
        Create optimized segments for a source file by splitting at significant gaps.

        Args:
            source_file: Path to the source file
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            handles: Number of frames to add before and after each range as "handles"

        Returns:
            List of dictionaries with optimized source ranges
        """
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
            if handles > 0 and sorted_segments:
                first_segment = sorted_segments[0]
                if (first_segment['source_start'] and
                        hasattr(first_segment['source_start'], 'rate')):
                    handle_time = otio.opentime.RationalTime(handles,
                                                             first_segment['source_start'].rate)
                else:
                    # Default to 24fps if we can't determine the rate
                    handle_time = otio.opentime.RationalTime(handles, 24)
            else:
                # Zero handles as default
                handle_time = otio.opentime.RationalTime(0, 24)

            # Create a single range covering all segments
            consolidated = [{
                'name': f"{source_file.split('/')[-1].split('\\')[-1]}_consolidated",
                'source_file': source_file,
                'source_start': sorted_segments[0]['source_start'] - handle_time,
                'source_end': sorted_segments[-1]['source_end'] + handle_time,
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
        if handles > 0 and sorted_segments:
            first_segment = sorted_segments[0]
            if (first_segment['source_start'] and
                    hasattr(first_segment['source_start'], 'rate')):
                handle_time = otio.opentime.RationalTime(handles,
                                                         first_segment['source_start'].rate)
            else:
                # Default to 24fps if we can't determine the rate
                handle_time = otio.opentime.RationalTime(handles, 24)
        else:
            # Zero handles as default
            handle_time = otio.opentime.RationalTime(0, 24)

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
                    range_start = current_group[0]['source_start'] - handle_time
                    range_end = current_group[-1]['source_end'] + handle_time

                    # Ensure range_start is not negative
                    if range_start.value < 0:
                        range_start = otio.opentime.RationalTime(0, range_start.rate)

                    optimized_range = {
                        'name': f"{source_file.split('/')[-1].split('\\')[-1]}_opt_{len(optimized_ranges) + 1}",
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
                              handles: int = 0) -> List[Dict[str, Any]]:
        """
        Create optimized segments for all source files.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            handles: Number of frames to add before and after each range as "handles"

        Returns:
            List of dictionaries with optimized source ranges for all sources
        """
        all_optimized = []

        for source_file in self.source_usage:
            optimized = self.optimize_segments(source_file, min_gap_duration, handles)
            all_optimized.extend(optimized)

        return all_optimized
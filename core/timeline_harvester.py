"""
TimelineHarvester Module

This module provides the main facade for the TimelineHarvester application.
It encapsulates the complexity of reading timeline files, analyzing them,
creating optimized transfer plans, and exporting results.
"""

import logging
import os
from typing import Dict, List, Optional, Any

import opentimelineio as otio

from core.analyzer import TimelineAnalyzer
from core.models import Timeline, TransferPlan, TransferSegment

# Configure logging
logger = logging.getLogger(__name__)


class TimelineHarvester:
    """
    Main facade for the TimelineHarvester application.

    This class provides a simple interface for the main features of the application:
    - Reading timeline files (EDL, AAF, XML)
    - Analyzing timelines to identify source media usage
    - Creating optimized transfer plans
    - Exporting results to various formats
    """

    def __init__(self):
        """Initialize a new TimelineHarvester instance."""
        self.analyzer = TimelineAnalyzer()
        self.transfer_plan = None

    def add_timeline(self, file_path: str, fps: Optional[float] = None) -> Timeline:
        """
        Add a timeline file to the analysis.

        Args:
            file_path: Path to the timeline file (EDL, AAF, XML)
            fps: Frames per second to use if not specified in the file

        Returns:
            Timeline object created from the file
        """
        logger.info(f"Adding timeline from file: {file_path}")

        if not os.path.exists(file_path):
            logger.error(f"Timeline file not found: {file_path}")
            raise FileNotFoundError(f"Timeline file not found: {file_path}")

        # Add timeline to analyzer
        timeline = self.analyzer.add_timeline(file_path, fps)
        logger.info(f"Added timeline: {timeline.name} with {len(timeline.clips)} clips")

        return timeline

    def add_multiple_timelines(self, file_paths: List[str], fps: Optional[float] = None) -> List[Timeline]:
        """
        Add multiple timeline files to the analysis.

        Args:
            file_paths: List of paths to timeline files
            fps: Frames per second to use if not specified in the files

        Returns:
            List of Timeline objects created from the files
        """
        logger.info(f"Adding {len(file_paths)} timeline files")
        return [self.add_timeline(path, fps) for path in file_paths]

    def get_source_usage(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get detailed information about source file usage across all timelines.

        Returns:
            Dictionary mapping source files to their usage details
        """
        logger.info("Retrieving source usage information")
        return self.analyzer.get_source_usage()

    def find_gaps(self, min_gap_duration: Optional[float] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find gaps (unused regions) in source files across all timelines.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            Dictionary mapping source files to lists of gaps
        """
        logger.info(f"Finding gaps with min duration: {min_gap_duration or 'None'}")
        return self.analyzer.find_all_gaps(min_gap_duration)

    def calculate_gap_savings(self, min_gap_duration: Optional[float] = None) -> Dict[str, Any]:
        """
        Calculate potential savings from skipping gaps in source files.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.

        Returns:
            Dictionary with statistics about potential savings
        """
        logger.info(f"Calculating gap savings with min duration: {min_gap_duration or 'None'}")
        return self.analyzer.calculate_gap_savings(min_gap_duration)

    def create_transfer_plan(self,
                             min_gap_duration: float = 0.0,
                             start_handles: int = 0,
                             end_handles: Optional[int] = None) -> TransferPlan:
        """
        Create a transfer plan based on all analyzed timelines.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant
            start_handles: Number of frames to add before each range as "handles"
            end_handles: Number of frames to add after each range as "handles"
                        If None, will use the same value as start_handles

        Returns:
            TransferPlan object with optimized segments
        """
        logger.info(f"Creating transfer plan with min_gap_duration={min_gap_duration}, "
                    f"handles={start_handles}/{end_handles or start_handles}")

        self.transfer_plan = self.analyzer.create_transfer_plan(
            min_gap_duration=min_gap_duration,
            start_handles=start_handles,
            end_handles=end_handles
        )

        # Log some information about the created plan
        stats = self.transfer_plan.statistics
        logger.info(f"Created transfer plan with {stats.get('segment_count', 0)} segments "
                    f"for {stats.get('unique_sources', 0)} unique sources")

        return self.transfer_plan

    def export_transfer_plan(self, output_path: str, format_name: Optional[str] = None) -> str:
        """
        Export the current transfer plan as a consolidated timeline file.

        Args:
            output_path: Path where the output file should be written
            format_name: Format to use for the output file (e.g., 'edl', 'xml')
                        If None, format will be detected from the file extension

        Returns:
            Path to the written file

        Raises:
            ValueError: If no transfer plan has been created yet
        """
        if not self.transfer_plan:
            logger.error("No transfer plan has been created yet")
            raise ValueError("No transfer plan has been created yet. Call create_transfer_plan() first.")

        logger.info(f"Exporting transfer plan to: {output_path}")

        # Get the consolidated timeline from the transfer plan
        consolidated_timeline = self.transfer_plan.get_consolidated_timeline()

        # Write the timeline to the output file
        write_timeline(consolidated_timeline, output_path, format_name)

        logger.info(f"Transfer plan exported to: {output_path}")
        return output_path

    def export_segment(self, segment: TransferSegment, output_path: str,
                       format_name: Optional[str] = None) -> str:
        """
        Export a single transfer segment as a timeline file.

        Args:
            segment: TransferSegment to export
            output_path: Path where the output file should be written
            format_name: Format to use for the output file

        Returns:
            Path to the written file
        """
        logger.info(f"Exporting segment '{segment.name}' to: {output_path}")

        # Create a timeline with just this segment
        timeline = otio.schema.Timeline(name=segment.name)
        video_track = otio.schema.Track(name="Video", kind="Video")
        timeline.tracks.append(video_track)
        video_track.append(segment.get_otio_clip())

        # Write the timeline to the output file
        write_timeline(timeline, output_path, format_name)

        logger.info(f"Segment exported to: {output_path}")
        return output_path

    def export_segments_batch(self, output_dir: str,
                              format_name: Optional[str] = None,
                              filename_pattern: str = "{segment_name}.{ext}") -> List[str]:
        """
        Export all segments in the current transfer plan as individual files.

        Args:
            output_dir: Directory where the output files should be written
            format_name: Format to use for the output files
            filename_pattern: Pattern for generating filenames

        Returns:
            List of paths to the written files

        Raises:
            ValueError: If no transfer plan has been created yet
        """
        if not self.transfer_plan:
            logger.error("No transfer plan has been created yet")
            raise ValueError("No transfer plan has been created yet. Call create_transfer_plan() first.")

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Determine default extension based on format
        ext = format_name or "edl"

        # Export each segment
        exported_files = []
        for segment in self.transfer_plan.segments:
            # Generate filename
            filename = filename_pattern.format(
                segment_name=segment.name,
                source_name=os.path.basename(segment.source_file),
                ext=ext
            )
            output_path = os.path.join(output_dir, filename)

            # Export segment
            self.export_segment(segment, output_path, format_name)
            exported_files.append(output_path)

        logger.info(f"Exported {len(exported_files)} segments to {output_dir}")
        return exported_files

    def export_report(self, output_path: str) -> str:
        """
        Export a detailed report about the transfer plan.

        Args:
            output_path: Path where the report should be written

        Returns:
            Path to the written report

        Raises:
            ValueError: If no transfer plan has been created yet
        """
        if not self.transfer_plan:
            logger.error("No transfer plan has been created yet")
            raise ValueError("No transfer plan has been created yet. Call create_transfer_plan() first.")

        logger.info(f"Exporting transfer plan report to: {output_path}")

        # Calculate statistics and savings
        stats = self.transfer_plan.statistics
        savings = self.transfer_plan.estimate_savings()

        # Write the report
        with open(output_path, 'w') as f:
            f.write("# TimelineHarvester Transfer Plan Report\n\n")

            # Plan overview
            f.write("## Plan Overview\n")
            f.write(f"- Plan Name: {self.transfer_plan.name}\n")
            f.write(f"- Timelines: {stats.get('timeline_count', 0)}\n")
            f.write(f"- Unique Sources: {stats.get('unique_sources', 0)}\n")
            f.write(f"- Total Segments: {stats.get('segment_count', 0)}\n")
            f.write(f"- Min Gap Duration: {self.transfer_plan.min_gap_duration} seconds\n")
            f.write(f"- Handles: {self.transfer_plan.start_handles}/{self.transfer_plan.end_handles} frames\n\n")

            # Savings
            f.write("## Estimated Savings\n")
            if 'savings_percentage' in savings:
                f.write(f"- Savings: {savings['savings_percentage']:.2f}%\n")
            if 'original_duration' in savings and 'optimized_duration' in savings:
                orig_sec = savings['original_duration'].value / savings['original_duration'].rate
                opt_sec = savings['optimized_duration'].value / savings['optimized_duration'].rate
                f.write(f"- Original Duration: {orig_sec:.2f} seconds\n")
                f.write(f"- Optimized Duration: {opt_sec:.2f} seconds\n")
                f.write(f"- Reduction: {orig_sec - opt_sec:.2f} seconds\n\n")

            # Segments
            f.write("## Segments\n")
            for i, segment in enumerate(self.transfer_plan.segments):
                duration_sec = segment.duration.value / segment.duration.rate
                f.write(f"### Segment {i + 1}: {segment.name}\n")
                f.write(f"- Source: {segment.source_file}\n")
                f.write(f"- Duration: {duration_sec:.2f} seconds\n")
                f.write(f"- Clips: {len(segment.timeline_clips)}\n\n")

        logger.info(f"Transfer plan report exported to: {output_path}")
        return output_path

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about the analyzed timelines.

        Returns:
            Dictionary with various statistics
        """
        logger.info("Retrieving statistics")
        return self.analyzer.get_timeline_statistics()
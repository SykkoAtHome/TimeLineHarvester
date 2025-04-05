"""
TimelineHarvester Module

This module provides the main facade for the TimelineHarvester application.
It integrates the file management, timeline analysis, and optimized transfer
capabilities into a clean, unified interface.
"""

import os
import logging
from typing import Dict, List, Optional, Union, Any

import opentimelineio as otio

from .models import Timeline, TransferPlan, TransferSegment
from .analyzer import TimelineAnalyzer
from .file_manager import FileManager

# Configure logging
logger = logging.getLogger(__name__)


class TimelineHarvester:
    """
    Main facade for the TimelineHarvester application.

    This class provides a simplified interface to the core functionality:
    - Loading and managing timeline files
    - Analyzing source media usage
    - Optimizing media transfers
    - Exporting results
    """

    def __init__(self):
        """Initialize a new TimelineHarvester instance."""
        self.analyzer = TimelineAnalyzer()
        self.current_plan = None

    def load_timeline(self, file_path: str, fps: Optional[float] = None) -> Timeline:
        """
        Load a timeline file for analysis.

        Args:
            file_path: Path to a timeline file (EDL, AAF, XML)
            fps: Optional frames per second to use if not specified in the file

        Returns:
            The loaded Timeline object
        """
        logger.info(f"Loading timeline from: {file_path}")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Timeline file not found: {file_path}")

        # Add the timeline to our analyzer
        timeline = self.analyzer.add_timeline(file_path, fps)
        logger.info(f"Loaded timeline '{timeline.name}' with {len(timeline.clips)} clips")

        return timeline

    def load_multiple_timelines(self, file_paths: List[str], fps: Optional[float] = None) -> List[Timeline]:
        """
        Load multiple timeline files for analysis.

        Args:
            file_paths: List of paths to timeline files
            fps: Optional frames per second to use if not specified in the files

        Returns:
            List of loaded Timeline objects
        """
        logger.info(f"Loading {len(file_paths)} timeline files")
        return [self.load_timeline(path, fps) for path in file_paths]

    def get_source_files(self) -> List[str]:
        """
        Get a list of all unique source files used in the loaded timelines.

        Returns:
            List of source file paths
        """
        return self.analyzer.get_unique_sources()

    def get_source_usage(self, source_file: Optional[str] = None) -> Dict:
        """
        Get detailed usage information for source files.

        Args:
            source_file: Optional specific source file to get info for.
                         If None, returns info for all sources.

        Returns:
            Dictionary with source file usage details
        """
        return self.analyzer.get_source_usage(source_file)

    def find_gaps(self, min_gap_duration: Optional[float] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find gaps (unused regions) in source files.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.
                             If None, all gaps are reported.

        Returns:
            Dictionary mapping source files to lists of gap information
        """
        logger.info(f"Finding gaps with min duration: {min_gap_duration}")
        return self.analyzer.find_all_gaps(min_gap_duration)

    def calculate_potential_savings(self, min_gap_duration: Optional[float] = None) -> Dict[str, Any]:
        """
        Calculate potential savings from skipping unused regions in source files.

        Args:
            min_gap_duration: Minimum duration (in seconds) to consider a gap significant.

        Returns:
            Dictionary with statistics about potential savings
        """
        logger.info(f"Calculating potential savings with min gap duration: {min_gap_duration}")
        return self.analyzer.calculate_gap_savings(min_gap_duration)

    def create_transfer_plan(self,
                             min_gap_duration: float = 0.0,
                             start_handles: int = 0,
                             end_handles: Optional[int] = None,
                             name: Optional[str] = None) -> TransferPlan:
        """
        Create an optimized transfer plan.

        Args:
            min_gap_duration: Minimum duration (in seconds) to split at
            start_handles: Number of frames to add before each segment
            end_handles: Number of frames to add after each segment
            name: Optional name for the transfer plan

        Returns:
            The created TransferPlan object
        """
        logger.info(f"Creating transfer plan with min_gap_duration={min_gap_duration}, "
                    f"handles={start_handles}/{end_handles or start_handles}")

        # Create the transfer plan
        self.current_plan = self.analyzer.create_transfer_plan(
            min_gap_duration=min_gap_duration,
            start_handles=start_handles,
            end_handles=end_handles
        )

        # Set custom name if provided
        if name:
            self.current_plan.name = name

        # Log information about the plan
        stats = self.current_plan.statistics
        logger.info(f"Created transfer plan '{self.current_plan.name}' with "
                    f"{stats.get('segment_count', 0)} segments for "
                    f"{stats.get('unique_sources', 0)} source files")

        return self.current_plan

    def export_transfer_plan(self, output_path: str, format_name: Optional[str] = None) -> str:
        """
        Export the current transfer plan as a timeline file.

        Args:
            output_path: Path where to write the output file
            format_name: Format to use (e.g., 'edl', 'xml')

        Returns:
            Path to the exported file

        Raises:
            ValueError: If no transfer plan has been created
        """
        if not self.current_plan:
            raise ValueError("No transfer plan has been created. Call create_transfer_plan() first.")

        logger.info(f"Exporting transfer plan to: {output_path}")
        return FileManager.write_transfer_plan(self.current_plan, output_path, format_name)

    def export_segments(self, output_dir: str,
                        format_name: Optional[str] = None,
                        filename_pattern: str = "{name}.{ext}") -> List[str]:
        """
        Export each segment in the current transfer plan as a separate file.

        Args:
            output_dir: Directory where to write the output files
            format_name: Format to use for the output files
            filename_pattern: Pattern for generating filenames

        Returns:
            List of paths to the exported files

        Raises:
            ValueError: If no transfer plan has been created
        """
        if not self.current_plan:
            raise ValueError("No transfer plan has been created. Call create_transfer_plan() first.")

        logger.info(f"Exporting segments to directory: {output_dir}")
        return FileManager.write_segments_batch(
            self.current_plan.segments,
            output_dir,
            format_name,
            filename_pattern
        )

    def generate_report(self, output_path: str) -> str:
        """
        Generate a detailed report about the current transfer plan.

        Args:
            output_path: Path where to write the report

        Returns:
            Path to the generated report

        Raises:
            ValueError: If no transfer plan has been created
        """
        if not self.current_plan:
            raise ValueError("No transfer plan has been created. Call create_transfer_plan() first.")

        logger.info(f"Generating report to: {output_path}")

        # Get statistics and savings information
        stats = self.current_plan.statistics
        savings = self.current_plan.estimate_savings()

        # Create the report
        with open(output_path, 'w') as f:
            f.write(f"# TimelineHarvester Transfer Plan: {self.current_plan.name}\n\n")

            f.write("## Overview\n")
            f.write(f"- Timelines analyzed: {stats.get('timeline_count', 0)}\n")
            f.write(f"- Unique source files: {stats.get('unique_sources', 0)}\n")
            f.write(f"- Total segments: {stats.get('segment_count', 0)}\n")
            f.write(f"- Minimum gap duration: {self.current_plan.min_gap_duration} seconds\n")
            f.write(f"- Handles: {self.current_plan.start_handles}/{self.current_plan.end_handles} frames\n\n")

            f.write("## Estimated Savings\n")
            if 'savings_percentage' in savings:
                f.write(f"- Overall savings: {savings['savings_percentage']:.2f}%\n")
            if 'original_duration' in savings and 'optimized_duration' in savings:
                orig_sec = savings['original_duration'].value / savings['original_duration'].rate
                opt_sec = savings['optimized_duration'].value / savings['optimized_duration'].rate
                f.write(f"- Original duration: {orig_sec:.2f} seconds\n")
                f.write(f"- Optimized duration: {opt_sec:.2f} seconds\n")
                f.write(f"- Total reduction: {orig_sec - opt_sec:.2f} seconds\n\n")

            f.write("## Segments Details\n")
            for i, segment in enumerate(self.current_plan.segments):
                duration_sec = segment.duration.value / segment.duration.rate
                f.write(f"### {i + 1}. {segment.name}\n")
                f.write(f"- Source file: {segment.source_file}\n")
                f.write(f"- Duration: {duration_sec:.2f} seconds\n")
                f.write(f"- Number of clips covered: {len(segment.timeline_clips)}\n\n")

        logger.info(f"Report generated at: {output_path}")
        return output_path

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about the analyzed timelines.

        Returns:
            Dictionary with various statistics
        """
        return self.analyzer.get_timeline_statistics()
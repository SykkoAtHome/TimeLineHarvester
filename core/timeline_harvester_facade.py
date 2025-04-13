#!/usr/bin/env python3
# core/timeline_harvester_facade.py
"""
Facade class providing a simplified interface to the TimelineHarvester core logic.
Coordinates work between ProjectManager and various processing services.
"""

import logging
import os
from typing import List, Dict, Optional, Callable, Any

from opentimelineio import opentime

# Import utilities
from utils import handle_utils
# Import models for type hints
from .models import EditFileMetadata, EditShot, OutputProfile
# Import services
from .processing.calculation_service import CalculationService
from .processing.export_service import ExportService
from .processing.source_processor import SourceProcessor
from .processing.transcode_service import TranscodeService
# Import project manager
from .project_manager import ProjectManager

logger = logging.getLogger(__name__)


def format_time_for_display(value: Optional[opentime.RationalTime], rate: Optional[float], display_mode: str) -> str:
    """Formats RationalTime to Timecode or Frames string for display."""
    if not isinstance(value, opentime.RationalTime):
        return "N/A"

    current_rate = rate
    if current_rate is None or current_rate <= 0:
        inferred_rate = getattr(value, 'rate', None)
        if inferred_rate and inferred_rate > 0:
            current_rate = inferred_rate
        else:
            return f"{value.value} (Rate?)"

    current_rate = float(current_rate)
    try:
        if display_mode == "Timecode":
            return opentime.to_timecode(value, current_rate)
        elif display_mode == "Frames":
            frames = round(value.rescaled_to(current_rate).value) if value.rate != current_rate else round(value.value)
            return str(int(frames))
        else:
            return str(value)
    except Exception as e:
        logger.warning(f"Error formatting time {value} rate {current_rate}: {e}")
        return f"Err ({value.value})"


class TimelineHarvesterFacade:
    """
    Main entry point for interacting with TimelineHarvester core logic.
    Delegates tasks to specialized managers and services.
    """

    def __init__(self):
        self.project_manager = ProjectManager()
        # Services will be instantiated lazily when needed
        self._source_processor = None
        self._calculation_service = None
        self._export_service = None
        self._transcode_service = None
        logger.info("TimelineHarvesterFacade initialized")

    # --- Service Getters (Lazy Initialization) ---

    def _get_source_processor(self) -> SourceProcessor:
        """Gets or creates the SourceProcessor instance."""
        self._source_processor = SourceProcessor(self.project_manager.get_state())
        return self._source_processor

    def _get_calculation_service(self) -> CalculationService:
        """Gets or creates the CalculationService instance."""
        self._calculation_service = CalculationService(self.project_manager.get_state())
        return self._calculation_service

    def _get_export_service(self) -> ExportService:
        """Gets or creates the ExportService instance."""
        self._export_service = ExportService(self.project_manager.get_state())
        return self._export_service

    def _get_transcode_service(self) -> TranscodeService:
        """Gets or creates the TranscodeService instance."""
        self._transcode_service = TranscodeService(self.project_manager.get_state())
        return self._transcode_service

    # --- Project State Access & Management ---

    def get_project_state_snapshot(self) -> Any:
        """Provides access to the current state object (read-only recommended)."""
        return self.project_manager.get_state()

    def is_project_dirty(self) -> bool:
        """Checks if the project has unsaved changes."""
        return self.project_manager.get_state().is_dirty

    def mark_project_dirty(self, dirty: bool = True):
        """Manually marks the project as dirty or clean."""
        self.project_manager.mark_dirty(dirty)

    def get_current_project_path(self) -> Optional[str]:
        """Returns the path of the currently loaded project file."""
        return self.project_manager.current_project_path

    def new_project(self):
        """Creates a new, empty project."""
        logger.info("Creating new project")
        self.project_manager.new_project()
        self.mark_project_dirty(False)

    def load_project(self, file_path: str) -> bool:
        """Loads a project from a file."""
        logger.info(f"Loading project from '{file_path}'")
        return self.project_manager.load_project(file_path)

    def save_project(self, file_path: Optional[str] = None) -> bool:
        """Saves the current project."""
        logger.info(f"Saving project to '{file_path or 'current path'}'")
        return self.project_manager.save_project(file_path)

    # --- Configuration Methods ---

    def add_edit_file_path(self, file_path: str) -> bool:
        """Adds an edit file path to the project state."""
        state = self.project_manager.get_state()
        abs_path = os.path.abspath(file_path)

        if not os.path.exists(abs_path):
            logger.error(f"Edit file not found: {abs_path}")
            return False

        # Avoid duplicates
        if any(ef.path == abs_path for ef in state.edit_files):
            logger.warning(f"Edit file already in list: {abs_path}")
            return True

        # Add and mark dirty
        state.edit_files.append(EditFileMetadata(path=abs_path))
        logger.info(f"Added edit file path: {abs_path}")
        self.mark_project_dirty()
        return True

    def set_edit_file_paths(self, paths: List[str]):
        """Sets the list of edit files, replacing existing ones."""
        state = self.project_manager.get_state()
        new_files = []

        for p in paths:
            abs_path = os.path.abspath(p)
            if os.path.exists(abs_path):
                new_files.append(EditFileMetadata(path=abs_path))
            else:
                logger.warning(f"Ignoring non-existent edit file path: {p}")

        # Check if changed before marking dirty
        if [f.path for f in state.edit_files] != [f.path for f in new_files]:
            state.edit_files = new_files
            logger.info(f"Set edit files list ({len(new_files)} files)")
            self.mark_project_dirty()

    def set_source_search_paths(self, paths: List[str]):
        """Sets the original source search paths in the project settings."""
        state = self.project_manager.get_state()
        valid_paths = sorted([os.path.abspath(p) for p in paths if os.path.isdir(p)])

        if state.settings.source_search_paths != valid_paths:
            state.settings.source_search_paths = valid_paths
            logger.info(f"Set source search paths: {valid_paths}")
            self.mark_project_dirty()
            # Invalidate finder instance so it gets recreated with new paths
            self._source_processor = None

    def set_graded_source_search_paths(self, paths: List[str]):
        """Sets the graded source search paths."""
        state = self.project_manager.get_state()
        valid_paths = sorted([os.path.abspath(p) for p in paths if os.path.isdir(p)])

        if state.settings.graded_source_search_paths != valid_paths:
            state.settings.graded_source_search_paths = valid_paths
            logger.info(f"Set graded source search paths: {valid_paths}")
            self.mark_project_dirty()

    def set_source_lookup_strategy(self, strategy: str):
        """Sets the source lookup strategy."""
        state = self.project_manager.get_state()

        if state.settings.source_lookup_strategy != strategy:
            state.settings.source_lookup_strategy = strategy
            logger.info(f"Set source lookup strategy: {strategy}")
            self.mark_project_dirty()
            self._source_processor = None  # Strategy change requires re-init of finder

    def set_output_profiles(self, profiles_config: List[Dict]):
        """Sets the output profiles for transcoding."""
        state = self.project_manager.get_state()
        new_profiles = []
        valid_names = set()

        for config in profiles_config:
            try:
                name = config.get('name', '').strip()
                if name and config.get('extension') and name not in valid_names:
                    new_profiles.append(OutputProfile(**config))
                    valid_names.add(name)
            except Exception as e:
                logger.warning(f"Skipping invalid profile: {config}, {e}")

        # Check if profiles actually changed
        if [p.__dict__ for p in state.settings.output_profiles] != [p.__dict__ for p in new_profiles]:
            state.settings.output_profiles = new_profiles
            logger.info(f"Set output profiles ({len(new_profiles)} profiles)")
            self.mark_project_dirty()

    def set_color_prep_handles(self, start: int, end: Optional[int] = None):
        """Sets color prep handles."""
        state = self.project_manager.get_state()
        norm_start, norm_end = handle_utils.normalize_handles(start, end)

        if state.settings.color_prep_start_handles != norm_start or \
                state.settings.color_prep_end_handles != norm_end:
            state.settings.color_prep_start_handles = norm_start
            state.settings.color_prep_end_handles = norm_end
            logger.info(f"Set color handles: Start={norm_start}, End={norm_end}")
            self.mark_project_dirty()

    def set_color_prep_separator(self, separator: int):
        """Sets color prep separator frames."""
        state = self.project_manager.get_state()
        try:
            norm_sep = max(0, int(separator))
        except:
            norm_sep = 0

        if state.settings.color_prep_separator != norm_sep:
            state.settings.color_prep_separator = norm_sep
            logger.info(f"Set color separator: {norm_sep} frames")
            self.mark_project_dirty()

    def set_split_gap_threshold(self, threshold_frames: int):
        """Sets the split gap threshold for color prep."""
        state = self.project_manager.get_state()
        try:
            norm_thr = int(threshold_frames)
            norm_thr = -1 if norm_thr < -1 else norm_thr
        except:
            norm_thr = -1

        if state.settings.split_gap_threshold_frames != norm_thr:
            state.settings.split_gap_threshold_frames = norm_thr
            logger.info(f"Set split gap threshold: {norm_thr} frames")
            self.mark_project_dirty()

    def set_online_output_directory(self, directory: Optional[str]):
        """Sets the output directory for online transcoding."""
        state = self.project_manager.get_state()
        valid_dir = os.path.abspath(directory) if directory and os.path.isdir(directory) else None

        if state.settings.online_output_directory != valid_dir:
            state.settings.online_output_directory = valid_dir
            logger.info(f"Set online output directory: {valid_dir}")
            self.mark_project_dirty()

    # --- Workflow Execution Methods ---

    def run_source_analysis(self) -> bool:
        """
        Executes the full source analysis workflow: parse -> find -> correct AAF.
        Updates the project state.
        Returns True on success, False on failure.
        """
        logger.info("Running source analysis")
        try:
            processor = self._get_source_processor()
            # Parsing clears previous results internally
            parse_success = processor.parse_edit_files()
            if not parse_success:
                return False

            # Finding sources and correcting AAF
            processor.find_and_correct_sources()
            self.mark_project_dirty()
            return True
        except Exception as e:
            logger.error(f"Source analysis failed: {e}", exc_info=True)
            return False

    def run_calculation(self, stage: str) -> bool:
        """
        Runs the transfer batch calculation for the specified stage.
        Updates the project state.
        Returns True on success, False on failure.
        """
        logger.info(f"Running calculation for stage '{stage}'")
        try:
            calculator = self._get_calculation_service()
            success = calculator.calculate_transfer_batch(stage)
            if success:
                self.mark_project_dirty()
            return success
        except Exception as e:
            logger.error(f"Calculation for stage '{stage}' failed: {e}", exc_info=True)
            return False

    def run_export(self, stage: str, output_path: str) -> bool:
        """
        Runs the export process for the specified stage.
        Returns True on success, False on failure.
        """
        logger.info(f"Running export for stage '{stage}' to '{output_path}'")
        try:
            exporter = self._get_export_service()
            return exporter.export_batch(stage, output_path)
        except ValueError as ve:
            logger.error(f"Export validation failed: {ve}")
            return False
        except Exception as e:
            logger.error(f"Export for stage '{stage}' failed: {e}", exc_info=True)
            return False

    def run_online_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """
        Runs the online transcoding process. Updates project state (segment status).
        Raises exceptions on failure (to be caught by WorkerThread/caller).
        """
        logger.info("Running online transcoding")
        transcoder = self._get_transcode_service()
        transcoder.run_transcoding(progress_callback)
        self.mark_project_dirty()

    # --- Data Retrieval Methods ---

    def get_edit_files_summary(self) -> List[Dict]:
        """Gets summary of loaded edit files."""
        state = self.project_manager.get_state()
        return [{"filename": meta.filename, "path": meta.path, "format": meta.format_type or "N/A"}
                for meta in state.edit_files]

    def get_edit_shots_summary(self) -> List[Dict]:
        """
        Gets detailed summary of edit shots, providing RAW time objects and rates
        for the GUI to format and sort.
        """
        state = self.project_manager.get_state()
        summary = []

        # Determine sequence rate once
        sequence_rate: Optional[float] = None
        if state.edit_shots:
            for shot in state.edit_shots:
                if shot.timeline_range and shot.timeline_range.duration.rate > 0:
                    sequence_rate = float(shot.timeline_range.duration.rate)
                    break
            if sequence_rate is None:
                for shot in state.edit_shots:
                    if shot.edit_media_range and shot.edit_media_range.duration.rate > 0:
                        sequence_rate = float(shot.edit_media_range.duration.rate)
                        break
        if sequence_rate is None:
            sequence_rate = 25.0

        logger.debug(f"Using sequence rate {sequence_rate} for Edit Shots Summary")

        for idx, shot in enumerate(state.edit_shots):
            source_info = shot.found_original_source
            original_path = source_info.path if source_info else "N/A"
            edit_media_id = shot.edit_media_path or "N/A"

            # Get Raw Time Objects and Rates
            source_start_rt = source_info.start_timecode if source_info else None
            source_duration_rt = source_info.duration if source_info else None
            source_rate = float(source_info.frame_rate) if source_info and source_info.frame_rate else None

            source_point_in_rt = shot.edit_media_range.start_time if shot.edit_media_range else None
            source_point_duration_rt = shot.edit_media_range.duration if shot.edit_media_range else None
            source_point_rate = float(
                source_point_duration_rt.rate) if source_point_duration_rt and source_point_duration_rt.rate > 0 else None

            edit_in_rt = shot.timeline_range.start_time if shot.timeline_range else None
            edit_duration_rt = shot.timeline_range.duration if shot.timeline_range else None
            current_sequence_rate = sequence_rate

            # Calculate exclusive end times (raw)
            source_out_rt_excl = None
            if source_start_rt and source_duration_rt:
                try:
                    source_out_rt_excl = source_start_rt + source_duration_rt
                except:
                    pass

            source_point_out_rt_excl = None
            if source_point_in_rt and source_point_duration_rt:
                try:
                    source_point_out_rt_excl = source_point_in_rt + source_point_duration_rt
                except:
                    pass

            edit_out_rt_excl = None
            if edit_in_rt and edit_duration_rt:
                try:
                    rescaled_dur = edit_duration_rt.rescaled_to(edit_in_rt.rate)
                    edit_out_rt_excl = edit_in_rt + rescaled_dur
                except:
                    pass

            # Build Summary Item with RAW data
            summary_item = {
                "index": idx + 1,
                "clip_name": shot.clip_name or os.path.basename(edit_media_id) or "N/A",
                "edit_media_id": edit_media_id,
                "source_path": original_path,
                "status": shot.lookup_status,

                # Raw Original Source Data
                "source_in_rt": source_start_rt,
                "source_out_rt_excl": source_out_rt_excl,
                "source_duration_rt": source_duration_rt,
                "source_rate": source_rate,

                # Raw Source Point Data (Absolute)
                "source_point_in_rt": source_point_in_rt,
                "source_point_out_rt_excl": source_point_out_rt_excl,
                "source_point_duration_rt": source_point_duration_rt,
                "source_point_rate": source_point_rate,

                # Raw Edit Position Data (Absolute)
                "edit_in_rt": edit_in_rt,
                "edit_out_rt_excl": edit_out_rt_excl,
                "edit_duration_rt": edit_duration_rt,
                "sequence_rate": current_sequence_rate
            }
            summary.append(summary_item)

        return summary

    def get_transfer_segments_summary(self, stage='color') -> List[Dict]:
        """Gets summary of calculated transfer segments for a stage."""
        state = self.project_manager.get_state()
        batch = state.color_transfer_batch if stage == 'color' else state.online_transfer_batch
        if not batch:
            return []

        summary = []
        for i, seg in enumerate(batch.segments):
            tc_string = "N/A"
            duration_sec = 0.0
            rate = seg.original_source.frame_rate if seg.original_source else None

            if seg.transfer_source_range and rate and rate > 0:
                try:
                    duration_sec = seg.transfer_source_range.duration.rescaled_to(rate).to_seconds()
                except:
                    duration_sec = seg.transfer_source_range.duration.to_seconds()
                try:
                    tc_string = opentime.to_timecode(seg.transfer_source_range.start_time.rescaled_to(rate), rate=rate)
                except:
                    tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s (Rate Error)"
            elif seg.transfer_source_range:
                duration_sec = seg.transfer_source_range.duration.to_seconds() if seg.transfer_source_range.duration.rate > 0 else 0.0
                tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s"

            source_basename = os.path.basename(seg.original_source.path) if seg.original_source else "N/A"
            summary.append({
                "index": i + 1,
                "source_basename": source_basename,
                "source_path": seg.original_source.path if seg.original_source else "N/A",
                "range_start_tc": tc_string,
                "duration_sec": duration_sec,
                "status": seg.status,
                "error": seg.error_message or ""
            })

        return summary

    def get_unresolved_shots_summary(self) -> List[Dict]:
        """Gets summary of shots not found or with errors."""
        state = self.project_manager.get_state()
        unresolved_shots_list = []
        seen_identifiers_ids = set()

        def add_unique_shot(shot: EditShot):
            shot_id = id(shot)
            if shot_id not in seen_identifiers_ids:
                seen_identifiers_ids.add(shot_id)
                unresolved_shots_list.append(shot)

        # Gather from batches first
        for batch in [state.color_transfer_batch, state.online_transfer_batch]:
            if batch and batch.unresolved_shots:
                [add_unique_shot(shot) for shot in batch.unresolved_shots if isinstance(shot, EditShot)]

        # Gather from main list
        for shot in state.edit_shots:
            if shot.lookup_status != 'found':
                add_unique_shot(shot)

        summary = []
        try:
            sorted_unresolved = sorted(unresolved_shots_list,
                                       key=lambda s: (s.edit_media_path or "", s.clip_name or ""))
        except:
            sorted_unresolved = unresolved_shots_list

        for shot in sorted_unresolved:
            range_str = "N/A"
            if shot.edit_media_range and isinstance(shot.edit_media_range.start_time, opentime.RationalTime) and \
                    isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                try:
                    rate = float(shot.edit_media_range.duration.rate)
                    if rate <= 0:
                        rate = float(shot.edit_media_range.start_time.rate)
                    if rate > 0:
                        start_time = shot.edit_media_range.start_time
                        duration = shot.edit_media_range.duration
                        end_time_incl = start_time + opentime.RationalTime(duration.value - 1,
                                                                           duration.rate) if duration.value > 0 else start_time
                        start_tc = opentime.to_timecode(start_time, rate)
                        end_tc = opentime.to_timecode(end_time_incl, rate)
                        duration_frames = int(round(duration.rescaled_to(rate).value))
                        range_str = f"{start_tc} - {end_tc} ({duration_frames} frames)"
                    else:
                        range_str = f"Invalid Rate ({rate})"
                except Exception as e:
                    range_str = f"Error formatting range: {e}"

            lookup_error_msg = shot.edit_metadata.get("lookup_error", "") or shot.edit_metadata.get(
                "_aaf_correction_error", "")
            status_display = f"{shot.lookup_status.upper()}" + (f" ({lookup_error_msg})" if lookup_error_msg else "")

            summary.append({
                "name": shot.clip_name or os.path.basename(shot.edit_media_path or "") or "N/A",
                "proxy_path": shot.edit_media_path or "N/A",
                "status": status_display,
                "edit_range": range_str
            })

        return summary

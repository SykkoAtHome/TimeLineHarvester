# core/timeline_harvester_facade.py
"""
Facade class providing a simplified interface to the TimelineHarvester core logic.
Coordinates work between ProjectManager and various processing services.
"""

import logging
import os
from typing import List, Dict, Optional, Callable, Any

from opentimelineio import opentime  # For time formatting helpers

# Import utilities if needed directly by the facade (e.g., for handle normalization display)
from utils import handle_utils  # Assuming these exist in utils package
# Import Models for type hints and potentially direct access (though discouraged)
from .models import EditFileMetadata, EditShot, OutputProfile
from .processing.calculation_service import CalculationService
from .processing.export_service import ExportService
from .processing.source_processor import SourceProcessor
from .processing.transcode_service import TranscodeService
# Import Manager and Services
from .project_manager import ProjectManager

logger = logging.getLogger(__name__)


# --- Time Formatting Helper (Could be moved to utils/display_utils.py) ---
# Copied from gui/results_display.py for facade use, consider centralizing
def format_time_for_display(value: Optional[opentime.RationalTime], rate: Optional[float], display_mode: str) -> str:
    """Formats RationalTime to Timecode or Frames string for display."""
    if not isinstance(value, opentime.RationalTime): return "N/A"
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
        logger.warning(f"Error formatting time {value} rate {current_rate}: {e}"); return f"Err ({value.value})"


# --- Facade Class ---
class TimelineHarvesterFacade:
    """
    Main entry point for interacting with TimelineHarvester core logic.
    Delegates tasks to specialized managers and services.
    """

    # Optional: If using Qt for signals between core and GUI
    # from PyQt5.QtCore import QObject, pyqtSignal
    # class TimelineHarvesterFacade(QObject):
    #    projectDirtyStateChanged = pyqtSignal(bool) # Example signal

    def __init__(self):
        self.project_manager = ProjectManager()
        # Services can be instantiated lazily when needed or kept None
        self._source_processor: Optional[SourceProcessor] = None
        self._calculation_service: Optional[CalculationService] = None
        self._export_service: Optional[ExportService] = None
        self._transcode_service: Optional[TranscodeService] = None
        logger.info("TimelineHarvesterFacade initialized.")

    # --- Internal Service Getters (Lazy Initialization) ---
    def _get_source_processor(self) -> SourceProcessor:
        # Creates instance only when first needed, ensures it uses current state
        # Note: This means SourceFinder might be re-initialized if settings change
        # between calls, which is generally desired.
        # if self._source_processor is None or self._source_processor.state is not self.project_manager.get_state():
        # Always create with current state to be safe? Or update state if instance exists?
        # Let's recreate for simplicity now.
        self._source_processor = SourceProcessor(self.project_manager.get_state())
        return self._source_processor

    def _get_calculation_service(self) -> CalculationService:
        # if self._calculation_service is None: # Basic lazy init
        self._calculation_service = CalculationService(self.project_manager.get_state())
        return self._calculation_service

    def _get_export_service(self) -> ExportService:
        # if self._export_service is None:
        self._export_service = ExportService(self.project_manager.get_state())
        return self._export_service

    def _get_transcode_service(self) -> TranscodeService:
        # if self._transcode_service is None:
        self._transcode_service = TranscodeService(self.project_manager.get_state())
        return self._transcode_service

    # --- Project State Access & Management ---
    # Methods GUI will call to interact with the project

    def get_project_state_snapshot(self) -> Any:
        """Provides access to the *current* state object (read-only recommended)."""
        # Be cautious returning the raw state object if GUI might modify it directly.
        # Consider returning a copy or specific data views if needed.
        return self.project_manager.get_state()

    def is_project_dirty(self) -> bool:
        """Checks if the project has unsaved changes."""
        return self.project_manager.get_state().is_dirty

    def mark_project_dirty(self, dirty: bool = True):
        """Manually marks the project as dirty or clean."""
        self.project_manager.mark_dirty(dirty)
        # Emit signal if using Qt signals
        # if hasattr(self, 'projectDirtyStateChanged'):
        #     self.projectDirtyStateChanged.emit(dirty)

    def get_current_project_path(self) -> Optional[str]:
        """Returns the path of the currently loaded project file."""
        return self.project_manager.current_project_path

    def new_project(self):
        """Creates a new, empty project."""
        logger.info("Facade: new_project requested.")
        self.project_manager.new_project()
        self.mark_project_dirty(False)  # New project isn't dirty initially

    def load_project(self, file_path: str) -> bool:
        """Loads a project from a file."""
        logger.info(f"Facade: load_project requested from '{file_path}'.")
        success = self.project_manager.load_project(file_path)
        # State is marked clean inside load_project on success
        return success

    def save_project(self, file_path: Optional[str] = None) -> bool:
        """Saves the current project."""
        logger.info(f"Facade: save_project requested (Path: {file_path or 'current'}).")
        # Pass path explicitly if provided, otherwise manager uses current path
        success = self.project_manager.save_project(file_path)
        # State is marked clean inside save_project on success
        return success

    # --- Configuration Methods ---
    # These methods modify the settings within the ProjectState

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
        logger.info(f"Added edit file path to state: {abs_path}")
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
                logger.warning(f"Ignoring non-existent edit file path during set: {p}")
        # Check if changed before marking dirty
        if [f.path for f in state.edit_files] != [f.path for f in new_files]:
            state.edit_files = new_files
            logger.info(f"Set edit files list in state ({len(new_files)} files).")
            self.mark_project_dirty()

    def set_source_search_paths(self, paths: List[str]):
        """Sets the original source search paths in the project settings."""
        state = self.project_manager.get_state()
        valid_paths = sorted([os.path.abspath(p) for p in paths if os.path.isdir(p)])
        if state.settings.source_search_paths != valid_paths:
            state.settings.source_search_paths = valid_paths
            logger.info(f"Set source search paths in state: {valid_paths}")
            self.mark_project_dirty()
            # Invalidate finder instance so it gets recreated with new paths
            self._source_processor = None  # Or add an update_settings method

    def set_graded_source_search_paths(self, paths: List[str]):
        """Sets the graded source search paths."""
        state = self.project_manager.get_state()
        valid_paths = sorted([os.path.abspath(p) for p in paths if os.path.isdir(p)])
        if state.settings.graded_source_search_paths != valid_paths:
            state.settings.graded_source_search_paths = valid_paths
            logger.info(f"Set graded source search paths in state: {valid_paths}")
            self.mark_project_dirty()

    def set_source_lookup_strategy(self, strategy: str):
        """Sets the source lookup strategy."""
        state = self.project_manager.get_state()
        # Add validation if needed
        if state.settings.source_lookup_strategy != strategy:
            state.settings.source_lookup_strategy = strategy
            logger.info(f"Set source lookup strategy in state: {strategy}")
            self.mark_project_dirty()
            self._source_processor = None  # Strategy change requires re-init of finder

    def set_output_profiles(self, profiles_config: List[Dict]):
        """Sets the output profiles for transcoding."""
        state = self.project_manager.get_state()
        # Reuse validation logic from old set_output_profiles or move it here/to ProjectSettings
        new_profiles = []
        valid_names = set()
        # (Add validation logic as in old TimelineHarvester.set_output_profiles here)
        for config in profiles_config:
            try:
                name = config.get('name', '').strip()
                # ... rest of validation ...
                if name and config.get('extension') and name not in valid_names:
                    new_profiles.append(OutputProfile(**config))  # Assuming keys match model
                    valid_names.add(name)
            except Exception as e:
                logger.warning(f"Skipping invalid profile: {config}, {e}")

        # Check if profiles actually changed
        if [p.__dict__ for p in state.settings.output_profiles] != [p.__dict__ for p in new_profiles]:
            state.settings.output_profiles = new_profiles
            logger.info(f"Set output profiles in state ({len(new_profiles)} profiles).")
            self.mark_project_dirty()

    def set_color_prep_handles(self, start: int, end: Optional[int] = None):
        """Sets color prep handles."""
        state = self.project_manager.get_state()
        norm_start, norm_end = handle_utils.normalize_handles(start, end)
        if state.settings.color_prep_start_handles != norm_start or \
                state.settings.color_prep_end_handles != norm_end:
            state.settings.color_prep_start_handles = norm_start
            state.settings.color_prep_end_handles = norm_end
            logger.info(f"Set color handles in state: Start={norm_start}, End={norm_end}")
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
            logger.info(f"Set color separator in state: {norm_sep} frames")
            self.mark_project_dirty()

    def set_split_gap_threshold(self, threshold_frames: int):
        """Sets the split gap threshold for color prep."""
        state = self.project_manager.get_state()
        try:
            norm_thr = int(threshold_frames); norm_thr = -1 if norm_thr < -1 else norm_thr
        except:
            norm_thr = -1
        if state.settings.split_gap_threshold_frames != norm_thr:
            state.settings.split_gap_threshold_frames = norm_thr
            logger.info(f"Set split gap threshold in state: {norm_thr} frames")
            self.mark_project_dirty()

    def set_online_output_directory(self, directory: Optional[str]):
        """Sets the output directory for online transcoding."""
        state = self.project_manager.get_state()
        valid_dir = os.path.abspath(directory) if directory and os.path.isdir(directory) else None
        if state.settings.online_output_directory != valid_dir:
            state.settings.online_output_directory = valid_dir
            logger.info(f"Set online output directory in state: {valid_dir}")
            self.mark_project_dirty()

    # --- Workflow Execution Methods ---
    # These methods trigger the actual processing steps

    def run_source_analysis(self) -> bool:
        """
        Executes the full source analysis workflow: parse -> find -> correct AAF.
        Updates the project state.
        Returns True on success, False on failure.
        """
        logger.info("Facade: run_source_analysis requested.")
        try:
            processor = self._get_source_processor()
            # Parsing clears previous results internally now
            parse_success = processor.parse_edit_files()
            if not parse_success:
                # Error already logged by processor
                return False
            # Finding sources and correcting AAF
            processor.find_and_correct_sources()
            self.mark_project_dirty()  # Mark dirty after successful analysis/correction
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
        logger.info(f"Facade: run_calculation requested for stage '{stage}'.")
        try:
            calculator = self._get_calculation_service()
            success = calculator.calculate_transfer_batch(stage)
            if success:
                self.mark_project_dirty()  # Calculation modifies state
            return success
        except Exception as e:
            logger.error(f"Calculation for stage '{stage}' failed: {e}", exc_info=True)
            # Update state with error batch? CalculationService might do this already.
            return False

    def run_export(self, stage: str, output_path: str) -> bool:
        """
        Runs the export process for the specified stage.
        Returns True on success, False on failure.
        """
        logger.info(f"Facade: run_export requested for stage '{stage}' to '{output_path}'.")
        try:
            exporter = self._get_export_service()
            return exporter.export_batch(stage, output_path)
        except ValueError as ve:  # Catch specific errors from ExportService pre-checks
            logger.error(f"Export validation failed: {ve}")
            return False
        except Exception as e:
            logger.error(f"Export for stage '{stage}' failed: {e}", exc_info=True)
            return False

    def run_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """
        Runs the online transcoding process. Updates project state (segment status).
        Raises exceptions on failure (to be caught by WorkerThread/caller).
        """
        logger.info("Facade: run_transcoding requested.")
        # Exceptions will be caught by the caller (e.g., WorkerThread)
        transcoder = self._get_transcode_service()
        transcoder.run_transcoding(progress_callback)
        # Mark dirty because segment statuses might have changed
        self.mark_project_dirty()

    # --- Data Retrieval Methods for GUI ---
    # These methods query the current ProjectState and format data for display

    def get_edit_files_summary(self) -> List[Dict]:
        """Gets summary of loaded edit files."""
        state = self.project_manager.get_state()
        return [{"filename": meta.filename, "path": meta.path, "format": meta.format_type or "N/A"}
                for meta in state.edit_files]

    def get_edit_shots_summary(self, time_format: str = "Timecode") -> List[Dict]:
        """Gets detailed summary of edit shots, formatted for display."""
        state = self.project_manager.get_state()
        summary = []
        # Determine sequence rate (copied logic, maybe centralize rate finding?)
        sequence_rate: Optional[float] = None
        if state.edit_shots:
            for shot in state.edit_shots:
                if shot.timeline_range and shot.timeline_range.duration.rate > 0: sequence_rate = float(
                    shot.timeline_range.duration.rate); break
            if sequence_rate is None:
                for shot in state.edit_shots:
                    if shot.edit_media_range and shot.edit_media_range.duration.rate > 0: sequence_rate = float(
                        shot.edit_media_range.duration.rate); break
        if sequence_rate is None: sequence_rate = 25.0

        for idx, shot in enumerate(state.edit_shots):
            source_info = shot.found_original_source
            original_path = source_info.path if source_info else "N/A"
            edit_media_id = shot.edit_media_path or "N/A"
            source_rate = float(source_info.frame_rate) if source_info and source_info.frame_rate else None
            source_point_rate = float(
                shot.edit_media_range.duration.rate) if shot.edit_media_range and shot.edit_media_range.duration.rate > 0 else None
            current_sequence_rate = sequence_rate  # Use consistent rate for edit times

            # Calculate inclusive end times for display
            source_out_rt_incl = None
            if source_info and source_info.start_timecode and source_info.duration and source_info.duration.value > 0:
                try:
                    source_out_rt_incl = source_info.start_timecode + opentime.RationalTime(
                        source_info.duration.value - 1, source_info.duration.rate)
                except:
                    pass
            source_point_out_rt_incl = None
            if shot.edit_media_range and shot.edit_media_range.duration.value > 0:
                try:
                    source_point_out_rt_incl = shot.edit_media_range.start_time + opentime.RationalTime(
                        shot.edit_media_range.duration.value - 1, shot.edit_media_range.duration.rate)
                except:
                    pass
            edit_out_rt_incl = None
            if shot.timeline_range and shot.timeline_range.duration.value > 0:
                try:
                    edit_out_rt_incl = shot.timeline_range.start_time + opentime.RationalTime(
                        shot.timeline_range.duration.value - 1, shot.timeline_range.duration.rate)
                except:
                    pass

            summary_item = {
                "index": idx + 1,
                "clip_name": shot.clip_name or os.path.basename(edit_media_id) or "N/A",
                "edit_media_id": edit_media_id,
                "source_path": original_path,
                "status": shot.lookup_status,
                # Formatted times
                "source_in_str": format_time_for_display(source_info.start_timecode if source_info else None,
                                                         source_rate, time_format),
                "source_out_str": format_time_for_display(source_out_rt_incl, source_rate, time_format),
                "source_dur_str": format_time_for_display(source_info.duration if source_info else None, source_rate,
                                                          time_format),
                "source_point_in_str": format_time_for_display(
                    shot.edit_media_range.start_time if shot.edit_media_range else None, source_point_rate,
                    time_format),
                "source_point_out_str": format_time_for_display(source_point_out_rt_incl, source_point_rate,
                                                                time_format),
                "source_point_dur_str": format_time_for_display(
                    shot.edit_media_range.duration if shot.edit_media_range else None, source_point_rate, time_format),
                "edit_in_str": format_time_for_display(shot.timeline_range.start_time if shot.timeline_range else None,
                                                       current_sequence_rate, time_format),
                "edit_out_str": format_time_for_display(edit_out_rt_incl, current_sequence_rate, time_format),
                "edit_dur_str": format_time_for_display(shot.timeline_range.duration if shot.timeline_range else None,
                                                        current_sequence_rate, time_format),
                # Raw values for sorting or other logic if needed by GUI? Maybe not necessary.
                # "source_in_rt": shot.found_original_source.start_timecode if shot.found_original_source else None,
                # ... etc
            }
            summary.append(summary_item)
        return summary

    def get_transfer_segments_summary(self, stage='color') -> List[Dict]:
        """Gets summary of calculated transfer segments for a stage."""
        state = self.project_manager.get_state()
        batch = state.color_transfer_batch if stage == 'color' else state.online_transfer_batch
        if not batch: return []
        summary = []
        for i, seg in enumerate(batch.segments):
            tc_string = "N/A";
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
            summary.append({"index": i + 1, "source_basename": source_basename,
                            "source_path": seg.original_source.path if seg.original_source else "N/A",
                            "range_start_tc": tc_string, "duration_sec": duration_sec, "status": seg.status,
                            "error": seg.error_message or "", })
        return summary

    def get_unresolved_shots_summary(self) -> List[Dict]:
        """Gets summary of shots not found or with errors."""
        state = self.project_manager.get_state()
        unresolved_shots_list: List[EditShot] = []
        seen_identifiers_ids: set[int] = set()

        def add_unique_shot(shot: EditShot):
            shot_id = id(shot)
            if shot_id not in seen_identifiers_ids: seen_identifiers_ids.add(shot_id); unresolved_shots_list.append(
                shot)

        # Gather from batches first
        for batch in [state.color_transfer_batch, state.online_transfer_batch]:
            if batch and batch.unresolved_shots: [add_unique_shot(shot) for shot in batch.unresolved_shots if
                                                  isinstance(shot, EditShot)]
        # Gather from main list
        for shot in state.edit_shots:
            if shot.lookup_status != 'found': add_unique_shot(shot)

        summary = []
        try:
            sorted_unresolved = sorted(unresolved_shots_list,
                                       key=lambda s: (s.edit_media_path or "", s.clip_name or ""))
        except:
            sorted_unresolved = unresolved_shots_list

        for shot in sorted_unresolved:
            range_str = "N/A"  # Format the source point range (absolute)
            if shot.edit_media_range and isinstance(shot.edit_media_range.start_time,
                                                    opentime.RationalTime) and isinstance(
                    shot.edit_media_range.duration, opentime.RationalTime):
                try:
                    rate = float(shot.edit_media_range.duration.rate)
                    if rate <= 0: rate = float(shot.edit_media_range.start_time.rate)
                    if rate > 0:
                        start_time = shot.edit_media_range.start_time;
                        duration = shot.edit_media_range.duration
                        end_time_incl = start_time + opentime.RationalTime(duration.value - 1,
                                                                           duration.rate) if duration.value > 0 else start_time
                        start_tc = opentime.to_timecode(start_time, rate);
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
            summary.append({"name": shot.clip_name or os.path.basename(shot.edit_media_path or "") or "N/A",
                            "proxy_path": shot.edit_media_path or "N/A", "status": status_display,
                            "edit_range": range_str, })
        return summary

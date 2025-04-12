# core/timeline_harvester.py
"""
Main facade class for TimelineHarvester logic.

Coordinates parsing edit files, finding original source media,
calculating transfer segments for different stages (Color, Online),
managing project state save/load, and triggering export/transcode operations.
"""

import logging
import os
import json  # For project save/load
from typing import List, Dict, Optional, Any, Tuple, Callable, Union, Set  # Added Set, Tuple
import opentimelineio as otio
from opentimelineio import opentime  # Explicit import

# Import necessary components from the core package
from . import parser as edit_parser
from .source_finder import SourceFinder
from . import calculator as transfer_calculator
from . import ffmpeg as ffmpeg_runner_module
from .models import EditFileMetadata, OriginalSourceFile, EditShot, OutputProfile, TransferSegment, TransferBatch
# Import utils for time conversion helpers during save/load and handles
from utils import time_utils, handle_utils  # Import handle_utils for setting defaults

logger = logging.getLogger(__name__)


# --- Serialization Helpers (No changes needed here) ---
def time_to_json(otio_time: Optional[Union[otio.opentime.RationalTime, otio.opentime.TimeRange]]) -> Optional[
    Union[List, Dict]]:
    """Serializes OTIO RationalTime or TimeRange to a JSON-compatible format."""
    if isinstance(otio_time, opentime.RationalTime):
        return [otio_time.value, otio_time.rate]
    elif isinstance(otio_time, opentime.TimeRange):
        return {
            "start_time": [otio_time.start_time.value, otio_time.start_time.rate],
            "duration": [otio_time.duration.value, otio_time.duration.rate]}
    return None


def time_from_json(json_data: Optional[Union[List, Dict]]) -> Optional[
    Union[otio.opentime.RationalTime, otio.opentime.TimeRange]]:
    """Deserializes JSON data back into OTIO RationalTime or TimeRange."""
    if isinstance(json_data, list) and len(json_data) == 2:
        try:
            return opentime.RationalTime(value=json_data[0], rate=json_data[1])
        except:
            return None  # Handle errors gracefully
    elif isinstance(json_data, dict) and "start_time" in json_data and "duration" in json_data:
        try:
            start_time = time_from_json(json_data["start_time"])
            duration = time_from_json(json_data["duration"])
            if isinstance(start_time, opentime.RationalTime) and isinstance(duration, opentime.RationalTime):
                return opentime.TimeRange(start_time=start_time, duration=duration)
        except:
            return None  # Handle errors gracefully
    return None


# --- Main Harvester Class ---
class TimelineHarvester:
    """
    Coordinates the different steps of the timeline harvesting process.
    Manages project state including configuration, parsed data, and results.
    """

    def __init__(self):
        # --- State ---
        self.edit_files: List[EditFileMetadata] = []
        self.edit_shots: List[EditShot] = []
        self.original_sources_cache: Dict[str, OriginalSourceFile] = {}
        self.color_transfer_batch: Optional[TransferBatch] = None
        self.online_transfer_batch: Optional[TransferBatch] = None
        # --- Configuration ---
        self.project_name: Optional[str] = None
        self.output_profiles: List[OutputProfile] = []
        self.source_search_paths: List[str] = []
        self.graded_source_search_paths: List[str] = []
        self.source_lookup_strategy: str = "basic_name_match"
        self.color_prep_start_handles: int = 24  # Default start handles for color
        self.color_prep_end_handles: int = 24  # Default end handles for color
        self.color_prep_separator: int = 0  # Default separator for color export
        self.split_gap_threshold_frames: int = -1  # <<< NEW: Default -1 (disabled)
        self.online_prep_handles: int = 12  # Default handles for online
        self.online_target_resolution: Optional[str] = None
        self.online_analyze_transforms: bool = False
        self.online_output_directory: Optional[str] = None
        # --- Internal Instances ---
        self._source_finder_instance: Optional[SourceFinder] = None
        self._graded_finder_instance: Optional[SourceFinder] = None
        self._ffmpeg_runner_instance: Optional[ffmpeg_runner_module.FFmpegRunner] = None
        logger.info("TimelineHarvester core engine initialized.")

    def clear_state(self):
        """Resets the internal state, preparing for a new project or load."""
        self.edit_files = []
        self.edit_shots = []
        self.original_sources_cache = {}
        self.color_transfer_batch = None
        self.online_transfer_batch = None
        self.project_name = None
        # Reset configuration to defaults
        self.output_profiles = []
        self.source_search_paths = []
        self.graded_source_search_paths = []
        self.source_lookup_strategy = "basic_name_match"
        self.color_prep_start_handles = 24
        self.color_prep_end_handles = 24
        self.color_prep_separator = 0
        self.split_gap_threshold_frames = -1  # <<< NEW: Reset to default
        self.online_prep_handles = 12
        self.online_target_resolution = None
        self.online_analyze_transforms = False
        self.online_output_directory = None
        # Reset internal instances
        self._source_finder_instance = None
        self._graded_finder_instance = None
        self._ffmpeg_runner_instance = None  # Reset runner instance as well
        logger.info("TimelineHarvester state cleared.")

    # --- File Handling ---
    def add_edit_file_path(self, file_path: str) -> bool:
        """Adds an edit file path for later processing."""
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            logger.error(f"Edit file not found: {abs_path}")
            return False
        if any(ef.path == abs_path for ef in self.edit_files):
            logger.warning(f"Edit file already in list: {abs_path}")
            return True  # Already present
        meta = EditFileMetadata(path=abs_path)
        self.edit_files.append(meta)
        logger.info(f"Added edit file path to process: {abs_path}")
        return True

    # --- Processing Steps ---
    def parse_added_edit_files(self) -> bool:
        """Parses all edit files in the list. Populates self.edit_shots."""
        self.edit_shots = []  # Clear previous results
        successful_parses = 0
        total_shots_parsed = 0
        if not self.edit_files: logger.warning("No edit files added to parse."); return False

        logger.info(f"Starting parsing for {len(self.edit_files)} edit file(s)...")
        all_parsed_shots = []  # Collect shots from all files
        for meta in self.edit_files:
            try:
                shots = edit_parser.read_and_parse_edit_file(meta.path)
                _, ext = os.path.splitext(meta.filename)
                meta.format_type = ext.lower().lstrip('.') or "unknown"
                all_parsed_shots.extend(shots)  # Add to temporary list
                total_shots_parsed += len(shots)
                successful_parses += 1
            except otio.exceptions.OTIOError as otio_err:
                logger.error(f"Failed to parse edit file '{meta.filename}' using OTIO: {otio_err}")
                meta.format_type = "parse_error (OTIO)"
            except FileNotFoundError as fnf_err:
                logger.error(f"Edit file '{meta.filename}' not found during parsing: {fnf_err}")
                meta.format_type = "file_not_found"
            except Exception as e:
                logger.error(f"Unexpected error parsing edit file '{meta.filename}': {e}",
                             exc_info=False)  # Log less verbosely by default
                meta.format_type = "parse_error (Other)"

        # Remove duplicates based on identifier and range after parsing all files
        unique_shots_map = {}
        for shot in all_parsed_shots:
            if not shot.edit_media_path or not shot.edit_media_range: continue  # Skip invalid shots
            try:
                # Use the same identifier logic as get_unresolved_shots_summary
                tr = shot.edit_media_range
                identifier_tuple = (shot.edit_media_path, float(tr.start_time.value), float(tr.start_time.rate),
                                    float(tr.duration.value), float(tr.duration.rate))
                if identifier_tuple not in unique_shots_map:
                    unique_shots_map[identifier_tuple] = shot
            except Exception as ident_err:
                logger.warning(
                    f"Could not create identifier for shot during duplicate check: {ident_err}. Shot: {shot.clip_name}")

        self.edit_shots = list(unique_shots_map.values())
        duplicates_removed = len(all_parsed_shots) - len(self.edit_shots)
        if duplicates_removed > 0:
            logger.info(f"Removed {duplicates_removed} duplicate EditShots after parsing all files.")

        logger.info(
            f"Parsing complete. Parsed {successful_parses}/{len(self.edit_files)} files. Found {len(self.edit_shots)} unique EditShots.")
        return len(self.edit_files) > 0

    def _get_source_finder(self) -> Optional[SourceFinder]:
        """Initializes or returns the SourceFinder for ORIGINAL sources."""
        # Check if config changed or instance is None
        if not self._source_finder_instance or \
                set(self._source_finder_instance.search_paths) != set(self.source_search_paths) or \
                self._source_finder_instance.strategy != self.source_lookup_strategy:
            if not self.source_search_paths:
                logger.error("Cannot create SourceFinder: No original source search paths set.")
                self._source_finder_instance = None  # Ensure it's None
                return None
            logger.debug("Initializing/Re-initializing SourceFinder for original sources...")
            self._source_finder_instance = SourceFinder(
                self.source_search_paths, self.source_lookup_strategy
            )
            # Always link the main cache, allowing finder to reuse verified sources
            self._source_finder_instance.verified_cache = self.original_sources_cache
            logger.info(
                f"SourceFinder ready. Strategy: '{self.source_lookup_strategy}', Paths: {len(self.source_search_paths)}")
        return self._source_finder_instance

    # TODO: Implement _get_graded_finder() using self.graded_source_search_paths

    def find_original_sources(self) -> Tuple[int, int, int]:
        """Finds and verifies original source files for parsed EditShots."""
        if not self.edit_shots: logger.warning("No edit shots for source lookup."); return 0, 0, 0

        finder = self._get_source_finder()
        if not finder:
            error_count = 0
            for shot in self.edit_shots:
                if shot.lookup_status == "pending": shot.lookup_status = "error"; error_count += 1
            logger.error(f"Source lookup skipped for {error_count} shots: SourceFinder unavailable.")
            return 0, 0, error_count

        found_count, not_found_count, error_count = 0, 0, 0
        # Reset status only for pending shots before lookup
        shots_to_check = []
        for s in self.edit_shots:
            if s.lookup_status != 'found':  # Re-check not_found and error states too if paths changed
                s.lookup_status = 'pending'
                s.found_original_source = None  # Clear previous potentially invalid link
                shots_to_check.append(s)
            # Keep 'found' status if already found, unless we implement forced re-check

        logger.info(f"Starting original source lookup for {len(shots_to_check)} pending/failed EditShots...")

        for shot in shots_to_check:
            try:
                original_file = finder.find_source(shot)  # find_source checks its internal cache first
                if original_file:
                    shot.found_original_source = original_file
                    shot.lookup_status = "found"
                    found_count += 1
                    # Update shared cache (finder updates its internal cache on success)
                    # Ensure the main cache always has the latest verified info
                    self.original_sources_cache[original_file.path] = original_file
                else:
                    shot.lookup_status = "not_found"
                    not_found_count += 1
            except Exception as e:
                logger.error(f"Error during source lookup for shot '{shot.clip_name}': {e}", exc_info=True)
                shot.lookup_status = "error"
                error_count += 1

        total_processed = found_count + not_found_count + error_count
        # Recalculate final counts based on the entire list after processing
        final_found = sum(1 for s in self.edit_shots if s.lookup_status == 'found')
        final_not_found = sum(1 for s in self.edit_shots if s.lookup_status == 'not_found')
        final_error = sum(1 for s in self.edit_shots if s.lookup_status == 'error')
        logger.info(f"Original source lookup finished. Processed: {total_processed} shots. "
                    f"Final Status -> Found: {final_found}, Not Found: {final_not_found}, Errors: {final_error}")
        # Return counts based on what was processed in *this run*
        return found_count, not_found_count, error_count

    # --- Configuration Methods ---
    def set_source_search_paths(self, paths: List[str]):
        """Sets the directories to search for original source files."""
        valid_paths = sorted([os.path.abspath(p) for p in paths if os.path.isdir(p)])
        if len(valid_paths) != len(paths): logger.warning("Some source paths invalid/ignored.")
        if valid_paths != sorted(self.source_search_paths):  # Check if actually changed
            self.source_search_paths = valid_paths
            self._source_finder_instance = None  # Reset finder to use new paths on next call
            logger.info(f"Set original source search paths (count: {len(self.source_search_paths)})")

    def set_graded_source_search_paths(self, paths: List[str]):
        """Sets the directories to search for graded source files."""
        valid_paths = sorted([os.path.abspath(p) for p in paths if os.path.isdir(p)])
        if len(valid_paths) != len(paths): logger.warning("Some graded paths invalid/ignored.")
        if valid_paths != sorted(self.graded_source_search_paths):
            self.graded_source_search_paths = valid_paths
            self._graded_finder_instance = None  # Reset graded finder
            logger.info(f"Set graded source search paths (count: {len(self.graded_source_search_paths)})")

    def set_source_lookup_strategy(self, strategy: str):
        """Sets the strategy for matching edit media to original/graded sources."""
        if strategy != self.source_lookup_strategy:
            # TODO: Validate strategy against known list?
            self.source_lookup_strategy = strategy
            self._source_finder_instance = None  # Reset finders
            self._graded_finder_instance = None
            logger.info(f"Set source lookup strategy: {self.source_lookup_strategy}")

    def set_output_profiles(self, profiles_config: List[Dict]):
        """Sets the target output profiles for transcoding (primarily Online)."""
        # Basic validation and creation of OutputProfile objects
        new_profiles = []
        valid_names = set()
        for config in profiles_config:
            try:
                name = config.get('name')
                ext = config.get('extension')
                opts = config.get('ffmpeg_options', [])
                if name and ext and name not in valid_names:
                    if not isinstance(opts, list): raise TypeError("ffmpeg_options must be a list")
                    new_profiles.append(OutputProfile(name=str(name), extension=str(ext), ffmpeg_options=opts))
                    valid_names.add(name)
                else:
                    logger.warning(f"Skipping invalid or duplicate profile config: {config}")
            except Exception as e:
                logger.warning(f"Skipping invalid profile config {config}: {e}")

        # Simple check if lists differ (doesn't check content deeply but often sufficient)
        if len(new_profiles) != len(self.output_profiles) or \
                [p.name for p in new_profiles] != [p.name for p in self.output_profiles]:
            self.output_profiles = new_profiles
            logger.info(f"Set {len(self.output_profiles)} output profiles.")

    def set_color_prep_handles(self, start_handles: int, end_handles: int):
        norm_start, norm_end = handle_utils.normalize_handles(start_handles, end_handles)
        changed = False
        if norm_start != self.color_prep_start_handles: self.color_prep_start_handles = norm_start; changed = True
        if norm_end != self.color_prep_end_handles: self.color_prep_end_handles = norm_end; changed = True
        if changed: logger.info(
            f"Set color handles: Start={self.color_prep_start_handles}, End={self.color_prep_end_handles}")

    def set_color_prep_separator(self, separator: int):
        norm_sep = max(0, int(separator))
        if norm_sep != self.color_prep_separator: self.color_prep_separator = norm_sep; logger.info(
            f"Set color separator: {self.color_prep_separator}f")

    def set_split_gap_threshold(self, threshold_frames: int):
        """Sets the threshold for splitting segments based on gap length."""
        norm_threshold = int(threshold_frames)
        if norm_threshold < -1: norm_threshold = -1
        if norm_threshold != self.split_gap_threshold_frames:
            self.split_gap_threshold_frames = norm_threshold
            status = "disabled" if norm_threshold < 0 else f"{norm_threshold} frames"
            logger.info(f"Set Split Gap Threshold: {status}")

    # TODO: Add setters for online prep settings

    # --- Calculation and Transcoding ---
    def calculate_transfer(self, stage: str):
        """Calculates the TransferBatch for a specific stage ('color' or 'online')."""
        logger.info(f"Calculating transfer batch for stage: '{stage}'...")
        if stage == 'color':
            self.color_transfer_batch = None
        elif stage == 'online':
            self.online_transfer_batch = None
        else:
            logger.error(f"Unknown stage '{stage}'.");
            return

        if stage == 'color':
            # Calculator uses symmetric handles based on handle_frames arg
            handles_to_use = self.color_prep_start_handles
            shots_to_process = [s for s in self.edit_shots if s.lookup_status == 'found']
            split_threshold = self.split_gap_threshold_frames  # Use stored value
            profiles_for_stage = []
            output_dir_for_stage = None
            batch_name = f"{self.project_name or 'Project'}_ColorPrep"
        elif stage == 'online':
            handles_to_use = self.online_prep_handles
            # TODO: Define graded source finding and use those shots
            shots_to_process = [s for s in self.edit_shots if s.lookup_status == 'found']  # Placeholder
            split_threshold = -1  # TODO: Add online specific threshold later?
            profiles_for_stage = self.output_profiles
            output_dir_for_stage = self.online_output_directory
            batch_name = f"{self.project_name or 'Project'}_OnlinePrep"
            if not output_dir_for_stage: logger.error("Online output directory not set."); return
            if not profiles_for_stage: logger.error("Online output profiles not set."); return
        else:
            return  # Should not happen

        if not shots_to_process:
            logger.warning(f"[{stage}] No valid shots found to calculate segments.")
            batch = TransferBatch(handle_frames=handles_to_use, output_directory=output_dir_for_stage,
                                  batch_name=batch_name)
            batch.unresolved_shots = [s for s in self.edit_shots if s.lookup_status != 'found']
        else:
            try:
                # Call the calculator logic with the threshold
                batch = transfer_calculator.calculate_transfer_batch(
                    edit_shots=shots_to_process,
                    handle_frames=handles_to_use,
                    split_gap_threshold_frames=split_threshold  # Pass threshold
                )
                # Post-process batch
                batch.unresolved_shots.extend(
                    [s for s in self.edit_shots if s.lookup_status != 'found' and s not in batch.unresolved_shots])
                batch.source_edit_files = self.edit_files
                batch.batch_name = batch_name
                batch.output_directory = output_dir_for_stage
                batch.output_profiles_used = profiles_for_stage
                batch.handle_frames = handles_to_use

            except Exception as e:
                logger.error(f"Fatal error during transfer calculation for stage '{stage}': {e}", exc_info=True)
                batch = TransferBatch(handle_frames=handles_to_use, output_directory=output_dir_for_stage,
                                      batch_name=f"{batch_name}_Error")
                batch.calculation_errors.append(f"Fatal calculation error: {str(e)}")
                batch.unresolved_shots = self.edit_shots

        # Store the result
        if stage == 'color':
            self.color_transfer_batch = batch
        elif stage == 'online':
            self.online_transfer_batch = batch

        log_msg = f"{stage.capitalize()} batch calculation complete. " \
                  f"Segments: {len(batch.segments)}, " \
                  f"Unresolved: {len(batch.unresolved_shots)}, " \
                  f"Errors: {len(batch.calculation_errors)}"
        if batch.calculation_errors:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def _get_ffmpeg_runner(self) -> Optional[ffmpeg_runner_module.FFmpegRunner]:
        """Initializes or returns the FFmpegRunner instance."""
        if not self._ffmpeg_runner_instance:
            logger.debug("Initializing FFmpegRunner...")
            self._ffmpeg_runner_instance = ffmpeg_runner_module.FFmpegRunner()
            if not self._ffmpeg_runner_instance.ffmpeg_path:
                logger.critical("FFmpegRunner could not be initialized (ffmpeg executable not found).")
                self._ffmpeg_runner_instance = None
        return self._ffmpeg_runner_instance

    def run_online_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """Runs FFmpeg transcoding specifically for the calculated Online TransferBatch."""
        logger.info("Attempting to start ONLINE transcoding process...")
        batch_to_run = self.online_transfer_batch
        if not batch_to_run: raise ValueError("Online transfer batch not calculated.")
        if not batch_to_run.segments: raise ValueError("Online transfer batch contains no segments to transcode.")
        if not batch_to_run.output_profiles_used: raise ValueError("No output profiles configured for online batch.")
        if not batch_to_run.output_directory: raise ValueError("Online output directory not configured for batch.")

        # Make sure output directory exists
        try:
            os.makedirs(batch_to_run.output_directory, exist_ok=True)
        except OSError as e:
            raise OSError(f"Cannot create online output directory '{batch_to_run.output_directory}': {e}") from e

        runner = self._get_ffmpeg_runner()
        if not runner: raise RuntimeError("FFmpeg runner is not available (ffmpeg executable not found).")

        try:
            logger.info(f"Executing FFmpeg for ONLINE batch: {len(batch_to_run.segments)} segments.")
            runner.run_batch(batch_to_run, progress_callback)  # run_batch handles internal logic
            logger.info("Online transcoding process finished by runner.")
        except Exception as e:
            logger.error(f"Online transcoding run failed: {e}", exc_info=True)
            raise  # Re-raise the exception

    # --- Project Save/Load Methods ---
    def get_project_data_for_save(self) -> Dict:
        """Gathers current state into a dictionary suitable for JSON serialization."""
        logger.debug("Gathering project data for saving...")
        try:
            serialized_profiles = [p.__dict__ for p in self.output_profiles]
            config_data = {
                "source_lookup_strategy": self.source_lookup_strategy,
                "source_search_paths": self.source_search_paths,
                "graded_source_search_paths": self.graded_source_search_paths,
                "output_profiles": serialized_profiles,
                "color_prep_start_handles": self.color_prep_start_handles,
                "color_prep_end_handles": self.color_prep_end_handles,
                "color_prep_separator": self.color_prep_separator,
                "split_gap_threshold_frames": self.split_gap_threshold_frames,  # <<< NEW: Save threshold
                "online_prep_handles": self.online_prep_handles,
                "online_target_resolution": self.online_target_resolution,
                "online_analyze_transforms": self.online_analyze_transforms,
                "online_output_directory": self.online_output_directory,
            }
            serialized_edit_files = [{'path': f.path, 'format': f.format_type} for f in self.edit_files]
            serialized_edit_shots = []
            for shot in self.edit_shots:
                serialized_edit_shots.append({
                    "clip_name": shot.clip_name, "edit_media_path": shot.edit_media_path,
                    "edit_media_range": time_to_json(shot.edit_media_range),
                    "timeline_range": time_to_json(shot.timeline_range),
                    "edit_metadata": shot.edit_metadata,
                    "found_original_source_path": shot.found_original_source.path if shot.found_original_source else None,
                    "lookup_status": shot.lookup_status})
            serialized_source_cache = {}
            for path, source in self.original_sources_cache.items():
                serialized_source_cache[path] = {
                    "path": source.path, "duration": time_to_json(source.duration),
                    "frame_rate": source.frame_rate, "start_timecode": time_to_json(source.start_timecode),
                    "is_verified": source.is_verified, "metadata": source.metadata}

            # Helper to serialize a batch safely
            def serialize_batch(batch: Optional[TransferBatch], all_edit_shots: List[EditShot]) -> Optional[Dict]:
                if not batch: return None
                edit_shots_map = {shot: i for i, shot in enumerate(all_edit_shots)}  # Map shot object to index
                serialized_segments = []
                for seg in batch.segments:
                    covered_indices = [edit_shots_map.get(s_shot) for s_shot in seg.source_edit_shots if
                                       s_shot in edit_shots_map]
                    covered_indices = [idx for idx in covered_indices if
                                       idx is not None]  # Filter out None if shot not found in map
                    serialized_segments.append({
                        "original_source_path": seg.original_source.path if seg.original_source else None,
                        # Handle potential None source
                        "transfer_source_range": time_to_json(seg.transfer_source_range),
                        "output_targets": seg.output_targets, "status": seg.status,
                        "error_message": seg.error_message,
                        "source_edit_shots_indices": covered_indices})
                unresolved_indices = [edit_shots_map.get(s_shot) for s_shot in batch.unresolved_shots if
                                      s_shot in edit_shots_map]
                unresolved_indices = [idx for idx in unresolved_indices if idx is not None]
                return {"batch_name": batch.batch_name, "handle_frames": batch.handle_frames,
                        "output_directory": batch.output_directory, "segments": serialized_segments,
                        "unresolved_shots_indices": unresolved_indices,
                        "calculation_errors": batch.calculation_errors,
                        "output_profiles_names": [p.name for p in batch.output_profiles_used],
                        "source_edit_files_paths": [f.path for f in batch.source_edit_files]}

            project_data = {
                "app_version": "1.1.0",  # TODO: Get from actual version info
                "project_name": self.project_name, "config": config_data,
                "edit_files": serialized_edit_files,
                "analysis_results": {"edit_shots": serialized_edit_shots,
                                     "original_sources_cache": serialized_source_cache, },
                "color_prep_results": {"transfer_batch": serialize_batch(self.color_transfer_batch, self.edit_shots), },
                "online_prep_results": {
                    "transfer_batch": serialize_batch(self.online_transfer_batch, self.edit_shots), }}
            return project_data
        except Exception as e:
            logger.error(f"Error gathering project data for save: {e}", exc_info=True)
            raise

    def save_project(self, file_path: str) -> bool:
        """Saves the current project state to a JSON file."""
        logger.info(f"Saving project state to: {file_path}")
        try:
            project_data = self.get_project_data_for_save()
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Project saved successfully to {file_path}")
            return True
        except TypeError as e:
            logger.error(f"Serialization error saving project: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Failed to save project: {e}", exc_info=True)
            return False

    def load_project(self, file_path: str) -> bool:
        """Loads project state from a JSON file."""
        logger.info(f"Loading project state from: {file_path}")
        if not os.path.exists(file_path): logger.error(f"Project file not found: {file_path}"); return False
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            self.clear_state()

            # --- Restore Config ---
            self.project_name = project_data.get("project_name")
            saved_app_version = project_data.get("app_version", "Unknown")
            logger.info(f"Loading project '{self.project_name}', saved with app version {saved_app_version}.")
            # TODO: Add version compatibility check

            config = project_data.get("config", {})
            self.set_source_lookup_strategy(config.get("source_lookup_strategy", "basic_name_match"))
            self.set_source_search_paths(config.get("source_search_paths", []))
            self.set_graded_source_search_paths(config.get("graded_source_search_paths", []))
            self.set_output_profiles(config.get("output_profiles", []))  # Use setter for validation
            color_start_h = config.get("color_prep_start_handles", 24)
            color_end_h = config.get("color_prep_end_handles", color_start_h)
            self.set_color_prep_handles(color_start_h, color_end_h)
            self.set_color_prep_separator(config.get("color_prep_separator", 0))
            self.set_split_gap_threshold(config.get("split_gap_threshold_frames", -1))  # <<< NEW: Load threshold
            # TODO: Use setters for online config when implemented
            self.online_prep_handles = config.get("online_prep_handles", 12)
            self.online_target_resolution = config.get("online_target_resolution")
            self.online_analyze_transforms = config.get("online_analyze_transforms", False)
            self.online_output_directory = config.get("online_output_directory")

            # --- Restore Edit Files ---
            self.edit_files = [EditFileMetadata(path=f_data['path'], format_type=f_data.get('format'))
                               for f_data in project_data.get("edit_files", []) if
                               isinstance(f_data, dict) and 'path' in f_data]

            # --- Restore Cache ---
            analysis_results = project_data.get("analysis_results", {})
            sources_cache_data = analysis_results.get("original_sources_cache", {})
            self.original_sources_cache = {}
            for path, source_data in sources_cache_data.items():
                if isinstance(source_data, dict):
                    loaded_rate = source_data.get("frame_rate")
                    loaded_duration = time_from_json(source_data.get("duration"))
                    if loaded_rate and loaded_duration:  # Basic validation
                        try:
                            self.original_sources_cache[path] = OriginalSourceFile(
                                path=source_data.get("path", path), duration=loaded_duration, frame_rate=loaded_rate,
                                start_timecode=time_from_json(source_data.get("start_timecode")),  # Handles None ok
                                is_verified=source_data.get("is_verified", False),
                                metadata=source_data.get("metadata", {}))
                        except Exception as cache_err:
                            logger.warning(f"Skipping invalid source cache entry for {path}: {cache_err}")
                    else:
                        logger.warning(f"Skipping invalid source cache entry (missing rate/duration) for {path}")

            # --- Restore Edit Shots and link to cache ---
            edit_shots_data = analysis_results.get("edit_shots", [])
            self.edit_shots = []
            temp_edit_shots_map = {}  # index -> shot for batch linking
            for i, shot_data in enumerate(edit_shots_data):
                if isinstance(shot_data, dict):
                    try:
                        edit_range = time_from_json(shot_data.get("edit_media_range"))
                        if not isinstance(edit_range, opentime.TimeRange):
                            logger.warning(
                                f"Skipping edit shot due to invalid edit_media_range data: {shot_data.get('clip_name')}")
                            continue

                        original_source_path = shot_data.get("found_original_source_path")
                        found_original = self.original_sources_cache.get(
                            original_source_path) if original_source_path else None

                        shot = EditShot(
                            clip_name=shot_data.get("clip_name"),
                            edit_media_path=shot_data.get("edit_media_path", ""),
                            edit_media_range=edit_range,
                            timeline_range=time_from_json(shot_data.get("timeline_range")),  # Handles None ok
                            edit_metadata=shot_data.get("edit_metadata", {}),
                            found_original_source=found_original,
                            lookup_status=shot_data.get("lookup_status", "pending"))
                        self.edit_shots.append(shot)
                        temp_edit_shots_map[i] = shot
                    except Exception as shot_err:
                        logger.warning(f"Error loading edit shot data at index {i}: {shot_err}. Data: {shot_data}")

            # --- Helper to Deserialize Transfer Batch ---
            def deserialize_batch(batch_data: Optional[Dict], stage: str, all_edit_shots: List[EditShot]) -> Optional[
                TransferBatch]:
                if not batch_data or not isinstance(batch_data, dict): return None
                logger.debug(f"Deserializing transfer batch for stage: {stage}")
                try:
                    handles = batch_data.get("handle_frames",
                                             self.color_prep_start_handles if stage == 'color' else self.online_prep_handles)
                    output_dir = batch_data.get("output_directory",
                                                self.online_output_directory if stage == 'online' else None)
                    profile_names_used = batch_data.get("output_profiles_names", [])
                    profiles_used = [p for p in self.output_profiles if p.name in profile_names_used]

                    batch = TransferBatch(
                        batch_name=batch_data.get("batch_name", f"Loaded_Batch_{stage}"),
                        handle_frames=handles, output_directory=output_dir,
                        calculation_errors=batch_data.get("calculation_errors", []),
                        output_profiles_used=profiles_used,
                        source_edit_files=self.edit_files  # Assume current edit files apply
                    )
                    serialized_segments = batch_data.get("segments", [])
                    unresolved_indices = set(batch_data.get("unresolved_shots_indices", []))

                    # Map index back to shot object using temp_edit_shots_map
                    shots_by_index = {i: shot for i, shot in enumerate(all_edit_shots)}

                    for i, seg_data in enumerate(serialized_segments):
                        if isinstance(seg_data, dict):
                            original_source = self.original_sources_cache.get(seg_data.get("original_source_path"))
                            transfer_range = time_from_json(seg_data.get("transfer_source_range"))
                            if not original_source or not isinstance(transfer_range, opentime.TimeRange):
                                logger.warning(f"Skipping invalid segment data during load: {seg_data}")
                                continue

                            covered_shots = [shots_by_index.get(idx) for idx in
                                             seg_data.get("source_edit_shots_indices", []) if idx in shots_by_index]
                            covered_shots = [s for s in covered_shots if
                                             s is not None]  # Filter out potential None values

                            batch.segments.append(TransferSegment(
                                original_source=original_source, transfer_source_range=transfer_range,
                                output_targets=seg_data.get("output_targets", {}),
                                status=seg_data.get("status", "calculated"),
                                error_message=seg_data.get("error_message"), source_edit_shots=covered_shots))

                    batch.unresolved_shots = [shots_by_index.get(idx) for idx in unresolved_indices if
                                              idx in shots_by_index]
                    batch.unresolved_shots = [s for s in batch.unresolved_shots if s is not None]  # Filter None

                    return batch
                except Exception as batch_err:
                    logger.error(f"Error deserializing {stage} batch: {batch_err}", exc_info=True)
                    return None

            # --- Deserialize Batches ---
            self.color_transfer_batch = deserialize_batch(
                project_data.get("color_prep_results", {}).get("transfer_batch"), 'color', self.edit_shots)
            self.online_transfer_batch = deserialize_batch(
                project_data.get("online_prep_results", {}).get("transfer_batch"), 'online', self.edit_shots)

            logger.info(f"Project '{self.project_name}' loaded successfully.")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Failed parsing project JSON '{file_path}': {e}");
            return False
        except KeyError as e:
            logger.error(f"Missing key loading project '{file_path}': {e}");
            return False
        except Exception as e:
            logger.error(f"Failed loading project '{file_path}': {e}", exc_info=True);
            return False

    # --- Data Retrieval Methods for GUI ---
    def get_edit_files_summary(self) -> List[Dict]:
        """Provides summary of loaded edit files."""
        return [{"filename": meta.filename, "path": meta.path, "format": meta.format_type or "N/A"}
                for meta in self.edit_files]

    def get_edit_shots_summary(self) -> List[Dict]:
        """Provides summary for display, formatting edit_range as IN - OUT (X frames)."""
        summary = []
        for shot in self.edit_shots:
            original_path = shot.found_original_source.path if shot.found_original_source else "N/A"
            range_str = "N/A"
            if shot.edit_media_range and \
                    isinstance(shot.edit_media_range.start_time, opentime.RationalTime) and \
                    isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                try:
                    rate = shot.edit_media_range.duration.rate
                    if rate <= 0: rate = shot.edit_media_range.start_time.rate
                    if rate > 0:
                        start_time = shot.edit_media_range.start_time
                        duration = shot.edit_media_range.duration
                        end_time_incl = shot.edit_media_range.end_time_inclusive()
                        start_tc = opentime.to_timecode(start_time, rate)
                        end_tc = opentime.to_timecode(end_time_incl, rate)
                        duration_frames = int(round(duration.value))
                        range_str = f"{start_tc} - {end_tc} ({duration_frames} frames)"
                    else:
                        range_str = f"Invalid Rate ({rate})"
                except Exception as e:
                    logger.debug(f"Could not format range {shot.edit_media_range} for shot '{shot.clip_name}': {e}")
                    range_str = str(shot.edit_media_range)  # Fallback

            edit_path_basename = os.path.basename(shot.edit_media_path or "") or "N/A"
            summary.append({
                "name": shot.clip_name or edit_path_basename,
                "proxy_path": shot.edit_media_path or "N/A",  # Shows the identifier
                "original_path": original_path,
                "status": shot.lookup_status,
                "edit_range": range_str,
            })
        return summary

    def get_transfer_segments_summary(self, stage='color') -> List[Dict]:
        """Provides summary for segments of a specific stage's batch."""
        batch = self.color_transfer_batch if stage == 'color' else self.online_transfer_batch
        if not batch: return []
        summary = []
        for i, seg in enumerate(batch.segments):
            tc_string = "N/A"
            duration_sec = 0.0
            rate = seg.original_source.frame_rate if seg.original_source else None
            if seg.transfer_source_range and rate and rate > 0:
                duration_sec = seg.transfer_source_range.duration.to_seconds()
                try:
                    tc_string = opentime.to_timecode(seg.transfer_source_range.start_time, rate=rate)
                except:
                    tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s"
            elif seg.transfer_source_range:  # Handle case where rate is missing/invalid
                duration_sec = seg.transfer_source_range.duration.to_seconds() if seg.transfer_source_range.duration.rate > 0 else 0.0
                tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s"

            source_basename = os.path.basename(seg.original_source.path) if seg.original_source else "N/A"
            source_path = seg.original_source.path if seg.original_source else "N/A"
            summary.append({
                "index": i + 1, "source_basename": source_basename,
                "source_path": source_path, "range_start_tc": tc_string,
                "duration_sec": duration_sec, "status": seg.status,
                "error": seg.error_message or "", })
        return summary

    def get_unresolved_shots_summary(self) -> List[Dict]:
        """
        Provides a summary of shots that were not found or encountered errors,
        formatting edit_range as IN - OUT (X frames).
        """
        unresolved_shots_list: List[EditShot] = []
        seen_identifiers: Set[Tuple[str, float, float, float, float]] = set()

        def add_unique_shot(shot: EditShot):
            if not shot.edit_media_path or not isinstance(shot.edit_media_range, opentime.TimeRange) or \
                    not isinstance(shot.edit_media_range.start_time, opentime.RationalTime) or \
                    not isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                # logger.warning(f"Skipping shot with missing/invalid path/range in add_unique_shot: {shot.clip_name}")
                return  # Silently skip invalid ones here
            try:
                tr = shot.edit_media_range
                identifier = (shot.edit_media_path, float(tr.start_time.value), float(tr.start_time.rate),
                              float(tr.duration.value), float(tr.duration.rate))
            except Exception as e:
                logger.error(f"Failed to create identifier for shot {shot.clip_name or shot.edit_media_path}: {e}",
                             exc_info=True)
                return
            if identifier not in seen_identifiers:
                seen_identifiers.add(identifier)
                unresolved_shots_list.append(shot)

        # Gather shots
        processed_batches = []
        if self.color_transfer_batch and self.color_transfer_batch.unresolved_shots:
            processed_batches.append(self.color_transfer_batch.unresolved_shots)
        if self.online_transfer_batch and self.online_transfer_batch.unresolved_shots:
            processed_batches.append(self.online_transfer_batch.unresolved_shots)
        for batch_unresolved in processed_batches:
            for shot in batch_unresolved:
                if isinstance(shot, EditShot): add_unique_shot(shot)
        for shot in self.edit_shots:
            if shot.lookup_status != 'found': add_unique_shot(shot)

        # Create Summary
        summary = []
        try:  # Sorting
            sorted_unresolved = sorted(unresolved_shots_list, key=lambda s: s.edit_media_path or "")
        except Exception as sort_err:
            logger.warning(f"Could not sort unresolved shots: {sort_err}")
            sorted_unresolved = unresolved_shots_list

        for shot in sorted_unresolved:
            # Format Edit Range
            range_str = "N/A"
            if shot.edit_media_range and \
                    isinstance(shot.edit_media_range.start_time, opentime.RationalTime) and \
                    isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                try:
                    rate = shot.edit_media_range.duration.rate
                    if rate <= 0: rate = shot.edit_media_range.start_time.rate
                    if rate > 0:
                        start_time = shot.edit_media_range.start_time
                        duration = shot.edit_media_range.duration
                        end_time_incl = shot.edit_media_range.end_time_inclusive()
                        start_tc = opentime.to_timecode(start_time, rate)
                        end_tc = opentime.to_timecode(end_time_incl, rate)
                        duration_frames = int(round(duration.value))
                        range_str = f"{start_tc} - {end_tc} ({duration_frames} frames)"
                    else:
                        range_str = f"Invalid Rate ({rate})"
                except Exception as e:
                    logger.debug(
                        f"Could not format range {shot.edit_media_range} for unresolved shot '{shot.clip_name}': {e}")
                    range_str = str(shot.edit_media_range)

            edit_path_basename = os.path.basename(shot.edit_media_path or "") or "N/A"
            summary.append({
                "name": shot.clip_name or edit_path_basename,
                "proxy_path": shot.edit_media_path or "N/A",
                "status": shot.lookup_status,
                "edit_range": range_str,
            })
        return summary

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
from typing import List, Dict, Optional, Any, Tuple, Callable, Union, Set
import opentimelineio as otio
from opentimelineio import opentime  # Explicit import

# Import necessary components from the core package
from . import parser as edit_parser
from .source_finder import SourceFinder
from . import calculator as transfer_calculator
from . import ffmpeg as ffmpeg_runner_module
from .models import EditFileMetadata, OriginalSourceFile, EditShot, OutputProfile, TransferSegment, TransferBatch
# Import utils for time conversion helpers during save/load
from utils import time_utils, handle_utils  # Import handle_utils for setting defaults

logger = logging.getLogger(__name__)


# --- Serialization Helpers ---
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
        self.online_prep_handles = 12
        self.online_target_resolution = None
        self.online_analyze_transforms = False
        self.online_output_directory = None
        # Reset internal instances
        self._source_finder_instance = None
        self._graded_finder_instance = None
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
        for meta in self.edit_files:
            try:
                # Use parser, which now returns only shots
                shots = edit_parser.read_and_parse_edit_file(meta.path)
                # Guess format type from extension for metadata
                _, ext = os.path.splitext(meta.filename)
                meta.format_type = ext.lower().lstrip('.') or "unknown"  # Store extension
                self.edit_shots.extend(shots)
                total_shots_parsed += len(shots)
                successful_parses += 1
            except otio.exceptions.OTIOError as otio_err:
                logger.error(f"Failed to parse edit file '{meta.filename}' using OTIO: {otio_err}")
                meta.format_type = "parse_error (OTIO)"
            except FileNotFoundError as fnf_err:
                logger.error(f"Edit file '{meta.filename}' not found during parsing: {fnf_err}")
                meta.format_type = "file_not_found"
            except Exception as e:
                logger.error(f"Unexpected error parsing edit file '{meta.filename}': {e}", exc_info=False)
                meta.format_type = "parse_error (Other)"

        logger.info(
            f"Parsing complete. Parsed {successful_parses}/{len(self.edit_files)} files. Found {total_shots_parsed} EditShots.")
        # Return True if process ran, even if some files failed
        return len(self.edit_files) > 0

    def _get_source_finder(self) -> Optional[SourceFinder]:
        """Initializes or returns the SourceFinder for ORIGINAL sources."""
        if not self._source_finder_instance:
            if not self.source_search_paths:
                logger.error("Cannot create SourceFinder: No original source search paths set.")
                return None
            logger.debug("Initializing SourceFinder for original sources...")
            self._source_finder_instance = SourceFinder(
                self.source_search_paths, self.source_lookup_strategy
            )
            self._source_finder_instance.verified_cache = self.original_sources_cache
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
        shots_to_check = [s for s in self.edit_shots if s.lookup_status == "pending"]
        logger.info(f"Starting original source lookup for {len(shots_to_check)} pending EditShots...")

        for shot in shots_to_check:
            try:
                original_file = finder.find_source(shot)
                if original_file:
                    shot.found_original_source = original_file
                    shot.lookup_status = "found"
                    found_count += 1
                    # Update shared cache (finder updates its internal cache on success)
                    self.original_sources_cache[original_file.path] = original_file
                else:
                    shot.lookup_status = "not_found"
                    not_found_count += 1
            except Exception as e:
                logger.error(f"Error during source lookup for shot '{shot.clip_name}': {e}", exc_info=True)
                shot.lookup_status = "error"
                error_count += 1

        total_processed = found_count + not_found_count + error_count
        logger.info(
            f"Original source lookup finished. Processed: {total_processed}. Found: {found_count}, Not Found: {not_found_count}, Errors: {error_count}")
        return found_count, not_found_count, error_count

    # --- Configuration Methods ---
    def set_source_search_paths(self, paths: List[str]):
        """Sets the directories to search for original source files."""
        valid_paths = [os.path.abspath(p) for p in paths if os.path.isdir(p)]
        if len(valid_paths) != len(paths): logger.warning("Some source paths invalid/ignored.")
        if set(valid_paths) != set(self.source_search_paths):  # Check if actually changed
            self.source_search_paths = valid_paths
            self._source_finder_instance = None  # Reset finder
            logger.info(f"Set original source search paths (count: {len(self.source_search_paths)})")

    def set_graded_source_search_paths(self, paths: List[str]):
        """Sets the directories to search for graded source files."""
        valid_paths = [os.path.abspath(p) for p in paths if os.path.isdir(p)]
        if len(valid_paths) != len(paths): logger.warning("Some graded paths invalid/ignored.")
        if set(valid_paths) != set(self.graded_source_search_paths):
            self.graded_source_search_paths = valid_paths
            self._graded_finder_instance = None  # Reset graded finder
            logger.info(f"Set graded source search paths (count: {len(self.graded_source_search_paths)})")

    def set_source_lookup_strategy(self, strategy: str):
        """Sets the strategy for matching edit media to original/graded sources."""
        if strategy != self.source_lookup_strategy:
            # TODO: Validate strategy?
            self.source_lookup_strategy = strategy
            self._source_finder_instance = None  # Reset finders
            self._graded_finder_instance = None
            logger.info(f"Set source lookup strategy: {self.source_lookup_strategy}")

    def set_output_profiles(self, profiles_config: List[Dict]):
        """Sets the target output profiles for transcoding (primarily Online)."""
        new_profiles = []
        # Basic validation
        for config in profiles_config:
            try:
                if 'name' in config and 'extension' in config:
                    config['ffmpeg_options'] = config.get('ffmpeg_options', [])  # Ensure list exists
                    if not isinstance(config['ffmpeg_options'], list): raise TypeError("ffmpeg_options must be list")
                    new_profiles.append(OutputProfile(**config))
                else:
                    logger.warning(f"Skipping invalid profile config: {config}")
            except Exception as e:
                logger.warning(f"Skipping invalid profile config {config}: {e}")
        # Check if profiles actually changed? Needs deeper comparison. Assume changed for now.
        self.output_profiles = new_profiles
        logger.info(f"Set {len(self.output_profiles)} output profiles.")

    def set_color_prep_handles(self, start_handles: int, end_handles: int):
        """Sets the handles specifically for the Color Prep stage."""
        norm_start, norm_end = handle_utils.normalize_handles(start_handles, end_handles)
        changed = False
        if norm_start != self.color_prep_start_handles:
            self.color_prep_start_handles = norm_start
            changed = True
        if norm_end != self.color_prep_end_handles:
            self.color_prep_end_handles = norm_end
            changed = True
        if changed: logger.info(
            f"Set color prep handles: Start={self.color_prep_start_handles}, End={self.color_prep_end_handles}")

    def set_color_prep_separator(self, separator: int):
        """Sets the separator gap for Color Prep export."""
        norm_sep = max(0, int(separator))
        if norm_sep != self.color_prep_separator:
            self.color_prep_separator = norm_sep
            logger.info(f"Set color prep separator: {self.color_prep_separator} frames")

    # TODO: Add setters for online prep settings (handles, output dir etc.)

    # --- Calculation and Transcoding ---
    def calculate_transfer(self, stage: str):  # Removed handle/dir args, use internal state
        """Calculates the TransferBatch for a specific stage ('color' or 'online')."""
        logger.info(f"Calculating transfer batch for stage: '{stage}'...")
        # Clear previous batch for this stage
        if stage == 'color':
            self.color_transfer_batch = None
        elif stage == 'online':
            self.online_transfer_batch = None
        else:
            logger.error(f"Unknown stage '{stage}'.");
            return

        # Get settings and inputs based on stage
        if stage == 'color':
            handles_to_use = self.color_prep_start_handles  # Calculator currently uses symmetric based on start
            shots_to_process = [s for s in self.edit_shots if s.lookup_status == 'found']
            profiles_for_stage = []
            output_dir_for_stage = None
            batch_name = f"{self.project_name or 'Project'}_ColorPrep"
        elif stage == 'online':
            handles_to_use = self.online_prep_handles  # Use online handles value
            # TODO: Get shots based on *graded* source analysis result
            shots_to_process = [s for s in self.edit_shots if s.lookup_status == 'found']  # Placeholder
            profiles_for_stage = self.output_profiles
            output_dir_for_stage = self.online_output_directory
            batch_name = f"{self.project_name or 'Project'}_OnlinePrep"
            if not output_dir_for_stage: logger.error("Online output directory not set."); return
            if not profiles_for_stage: logger.error("Online output profiles not set."); return
        else:
            return  # Already handled

        if not shots_to_process:
            logger.warning(f"[{stage}] No valid shots found to calculate segments.")
            batch = TransferBatch(handle_frames=handles_to_use, output_directory=output_dir_for_stage,
                                  batch_name=batch_name)
            batch.unresolved_shots = [s for s in self.edit_shots if s.lookup_status != 'found']
        else:
            try:
                # Call the calculator logic
                batch = transfer_calculator.calculate_transfer_batch(
                    edit_shots=shots_to_process,
                    handle_frames=handles_to_use,  # Pass the correct handles for the stage
                    # Calculator currently ignores profiles/output dir args
                )
                # Post-process the calculated batch
                batch.unresolved_shots.extend(
                    [s for s in self.edit_shots if s.lookup_status != 'found' and s not in batch.unresolved_shots])
                batch.source_edit_files = self.edit_files
                batch.batch_name = batch_name
                # Add stage-specific info needed by runner/exporter
                batch.output_directory = output_dir_for_stage  # Set directory on batch object
                batch.output_profiles_used = profiles_for_stage  # Set profiles on batch object
                batch.handle_frames = handles_to_use  # Store handles used for this batch

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
                self._ffmpeg_runner_instance = None  # Ensure it's None if failed
        return self._ffmpeg_runner_instance

    def run_online_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """Runs FFmpeg transcoding specifically for the calculated Online TransferBatch."""
        logger.info("Attempting to start ONLINE transcoding process...")
        batch_to_run = self.online_transfer_batch
        if not batch_to_run: raise ValueError("Online transfer batch not calculated.")
        if not batch_to_run.segments: raise ValueError("Online transfer batch contains no segments.")
        if not batch_to_run.output_profiles_used: raise ValueError("No output profiles configured for online batch.")
        if not batch_to_run.output_directory: raise ValueError("Online output directory not configured for batch.")

        runner = self._get_ffmpeg_runner()
        if not runner: raise RuntimeError("FFmpeg runner is not available.")

        try:
            logger.info(f"Executing FFmpeg for ONLINE batch: {len(batch_to_run.segments)} segments.")
            # Pass the specific batch to the runner
            runner.run_batch(batch_to_run, progress_callback)
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
            def serialize_batch(batch: Optional[TransferBatch]) -> Optional[Dict]:
                if not batch: return None
                edit_shots_list = self.edit_shots  # Use current list for index lookup
                serialized_segments = []
                for seg in batch.segments:
                    covered_indices = []
                    for s_shot in seg.source_edit_shots:
                        try:
                            covered_indices.append(edit_shots_list.index(s_shot))
                        except ValueError:
                            pass  # Ignore shots not found in main list
                    serialized_segments.append({
                        "original_source_path": seg.original_source.path,
                        "transfer_source_range": time_to_json(seg.transfer_source_range),
                        "output_targets": seg.output_targets, "status": seg.status,
                        "error_message": seg.error_message,
                        "source_edit_shots_indices": covered_indices})
                unresolved_indices = []
                for s_shot in batch.unresolved_shots:
                    try:
                        unresolved_indices.append(edit_shots_list.index(s_shot))
                    except ValueError:
                        pass
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
                "color_prep_results": {"transfer_batch": serialize_batch(self.color_transfer_batch), },
                "online_prep_results": {"transfer_batch": serialize_batch(self.online_transfer_batch), }}
            return project_data
        except Exception as e:
            logger.error(f"Error gathering project data for save: {e}", exc_info=True)
            raise  # Re-raise to be caught by save_project

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
            self.clear_state()  # Start fresh

            # --- Restore State ---
            self.project_name = project_data.get("project_name")
            saved_app_version = project_data.get("app_version", "Unknown")
            logger.info(f"Loading project '{self.project_name}', saved with app version {saved_app_version}.")
            # TODO: Add version compatibility check

            config = project_data.get("config", {})
            self.source_lookup_strategy = config.get("source_lookup_strategy", "basic_name_match")
            self.source_search_paths = config.get("source_search_paths", [])
            self.graded_source_search_paths = config.get("graded_source_search_paths", [])
            profiles_data = config.get("output_profiles", [])
            self.output_profiles = [OutputProfile(**p_data) for p_data in profiles_data if isinstance(p_data, dict)]
            self.color_prep_start_handles = config.get("color_prep_start_handles", 24)
            self.color_prep_end_handles = config.get("color_prep_end_handles", self.color_prep_start_handles)
            self.color_prep_separator = config.get("color_prep_separator", 0)
            self.online_prep_handles = config.get("online_prep_handles", 12)
            self.online_target_resolution = config.get("online_target_resolution")
            self.online_analyze_transforms = config.get("online_analyze_transforms", False)
            self.online_output_directory = config.get("online_output_directory")

            self.edit_files = [EditFileMetadata(path=f_data['path'], format_type=f_data.get('format'))
                               for f_data in project_data.get("edit_files", []) if
                               isinstance(f_data, dict) and 'path' in f_data]

            # Restore Cache
            analysis_results = project_data.get("analysis_results", {})
            sources_cache_data = analysis_results.get("original_sources_cache", {})
            self.original_sources_cache = {}
            for path, source_data in sources_cache_data.items():
                if isinstance(source_data, dict):
                    # Basic validation of loaded data
                    loaded_rate = source_data.get("frame_rate")
                    loaded_duration = time_from_json(source_data.get("duration"))
                    if loaded_rate and loaded_duration:
                        self.original_sources_cache[path] = OriginalSourceFile(
                            path=source_data.get("path", path), duration=loaded_duration, frame_rate=loaded_rate,
                            start_timecode=time_from_json(source_data.get("start_timecode")),
                            is_verified=source_data.get("is_verified", False), metadata=source_data.get("metadata", {}))
                    else:
                        logger.warning(f"Skipping invalid source cache entry for {path}")

            # Restore Edit Shots and link to cache
            edit_shots_data = analysis_results.get("edit_shots", [])
            self.edit_shots = []
            temp_edit_shots_map = {}  # index -> shot for batch linking
            for i, shot_data in enumerate(edit_shots_data):
                if isinstance(shot_data, dict):
                    original_source_path = shot_data.get("found_original_source_path")
                    found_original = self.original_sources_cache.get(
                        original_source_path) if original_source_path else None
                    edit_range = time_from_json(shot_data.get("edit_media_range"))
                    timeline_range = time_from_json(shot_data.get("timeline_range"))
                    if not isinstance(edit_range, opentime.TimeRange): logger.warning(
                        f"Skipping edit shot due to invalid range data: {shot_data}"); continue

                    shot = EditShot(
                        clip_name=shot_data.get("clip_name"), edit_media_path=shot_data.get("edit_media_path", ""),
                        edit_media_range=edit_range, timeline_range=timeline_range,
                        edit_metadata=shot_data.get("edit_metadata", {}),
                        found_original_source=found_original, lookup_status=shot_data.get("lookup_status", "pending"))
                    self.edit_shots.append(shot)
                    temp_edit_shots_map[i] = shot

            # Helper to Deserialize Transfer Batch
            def deserialize_batch(batch_data: Optional[Dict], stage: str) -> Optional[TransferBatch]:
                if not batch_data or not isinstance(batch_data, dict): return None
                logger.debug(f"Deserializing transfer batch for stage: {stage}")
                handles = batch_data.get("handle_frames",
                                         self.color_prep_start_handles if stage == 'color' else self.online_prep_handles)
                output_dir = batch_data.get("output_directory",
                                            self.online_output_directory if stage == 'online' else None)
                # Find profiles used by name
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

                for i, seg_data in enumerate(serialized_segments):
                    if isinstance(seg_data, dict):
                        original_source = self.original_sources_cache.get(seg_data.get("original_source_path"))
                        transfer_range = time_from_json(seg_data.get("transfer_source_range"))
                        if not original_source or not isinstance(transfer_range, opentime.TimeRange): logger.warning(
                            ...); continue

                        covered_shots = [temp_edit_shots_map.get(idx) for idx in
                                         seg_data.get("source_edit_shots_indices", []) if idx in temp_edit_shots_map]

                        batch.segments.append(TransferSegment(
                            original_source=original_source, transfer_source_range=transfer_range,
                            output_targets=seg_data.get("output_targets", {}),
                            status=seg_data.get("status", "calculated"),
                            error_message=seg_data.get("error_message"), source_edit_shots=covered_shots))
                batch.unresolved_shots = [temp_edit_shots_map.get(idx) for idx in unresolved_indices if
                                          idx in temp_edit_shots_map]
                return batch

            # Deserialize Batches
            self.color_transfer_batch = deserialize_batch(
                project_data.get("color_prep_results", {}).get("transfer_batch"), 'color')
            self.online_transfer_batch = deserialize_batch(
                project_data.get("online_prep_results", {}).get("transfer_batch"), 'online')

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

    # --- Configuration Methods ---
    # (set_source_search_paths, set_graded_source_search_paths, set_source_lookup_strategy,
    #  set_output_profiles, set_color_prep_handles, set_color_prep_separator,
    #  set_online_prep_handles, set_online_output_directory etc. need to be defined here)
    def set_color_prep_handles(self, start_handles: int, end_handles: int):
        # ... (implementation as before) ...
        norm_start, norm_end = handle_utils.normalize_handles(start_handles, end_handles)
        changed = False
        if norm_start != self.color_prep_start_handles: self.color_prep_start_handles = norm_start; changed = True
        if norm_end != self.color_prep_end_handles: self.color_prep_end_handles = norm_end; changed = True
        if changed: logger.info(
            f"Set color handles: Start={self.color_prep_start_handles}, End={self.color_prep_end_handles}")

    def set_color_prep_separator(self, separator: int):
        # ... (implementation as before) ...
        norm_sep = max(0, int(separator))
        if norm_sep != self.color_prep_separator: self.color_prep_separator = norm_sep; logger.info(
            f"Set color separator: {self.color_prep_separator}f")

    # ... Add other setters as needed ...

    # --- Data Retrieval Methods for GUI ---
    # (get_edit_files_summary, get_edit_shots_summary, get_transfer_segments_summary, get_unresolved_shots_summary)
    # Ensure get_transfer_segments_summary uses the 'stage' parameter correctly
    def get_edit_files_summary(self) -> List[Dict]:
        return [{"filename": meta.filename, "path": meta.path, "format": meta.format_type or "N/A"}
                for meta in self.edit_files]

    def get_edit_shots_summary(self) -> List[Dict]:
        """Provides summary for display, formatting edit_range as IN - OUT (X frames)."""
        summary = []
        for shot in self.edit_shots:
            original_path = shot.found_original_source.path if shot.found_original_source else "N/A"

            # --- Format Edit Range as IN - OUT (frames) ---
            range_str = "N/A"
            if shot.edit_media_range and \
                    isinstance(shot.edit_media_range.start_time, opentime.RationalTime) and \
                    isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                try:
                    # Determine the rate from the range itself
                    rate = shot.edit_media_range.duration.rate
                    if rate <= 0:
                        rate = shot.edit_media_range.start_time.rate

                    if rate > 0:
                        # Get components
                        start_time = shot.edit_media_range.start_time
                        duration = shot.edit_media_range.duration
                        # Calculate inclusive end time (start + duration - 1 frame)
                        # Note: end_time_inclusive() handles the frame math correctly
                        end_time_incl = shot.edit_media_range.end_time_inclusive()

                        # Convert times to timecode strings
                        start_tc = opentime.to_timecode(start_time, rate)
                        end_tc = opentime.to_timecode(end_time_incl, rate)

                        # Get duration in frames (integer value)
                        # duration.value already represents frames at the given rate
                        duration_frames = int(round(duration.value))  # Round just in case value isn't integer

                        # Create the desired string format
                        range_str = f"{start_tc} - {end_tc} ({duration_frames} frames)"
                    else:
                        logger.warning(
                            f"Cannot format edit_range for clip '{shot.clip_name}' due to invalid rate: {rate}")
                        # Fallback for invalid rate
                        range_str = f"Start: {shot.edit_media_range.start_time.value}, Dur: {shot.edit_media_range.duration.value} (Rate: {rate})"

                except Exception as e:
                    logger.warning(
                        f"Could not format edit_media_range {shot.edit_media_range} to IN-OUT format for clip '{shot.clip_name}': {e}")
                    range_str = str(shot.edit_media_range)  # Fallback to default

            # --- End Formatting ---

            edit_path_basename = os.path.basename(shot.edit_media_path or "") or "N/A"
            summary.append({
                "name": shot.clip_name or edit_path_basename,
                "proxy_path": shot.edit_media_path or "N/A",
                "original_path": original_path,
                "status": shot.lookup_status,
                "edit_range": range_str,  # Use the formatted string
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
            rate = seg.original_source.frame_rate  # Get rate from segment's source
            if seg.transfer_source_range and rate:
                duration_sec = seg.transfer_source_range.duration.to_seconds()
                try:
                    tc_string = seg.transfer_source_range.start_time.to_timecode(rate=rate)
                except:
                    tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s"
            summary.append({
                "index": i + 1, "source_basename": os.path.basename(seg.original_source.path),
                "source_path": seg.original_source.path, "range_start_tc": tc_string,
                "duration_sec": duration_sec, "status": seg.status,
                "error": seg.error_message or "", })
        return summary

    def get_unresolved_shots_summary(self) -> List[Dict]:
        """
        Provides a summary of shots that were not found or encountered errors,
        formatting edit_range as IN - OUT (X frames).
        """
        # --- Gathering unresolved shots logic (using identifiers) remains the same ---
        unresolved_shots_list: List[EditShot] = []
        seen_identifiers: Set[Tuple[str, float, float, float, float]] = set()

        def add_unique_shot(shot: EditShot):
            if not shot.edit_media_path or not isinstance(shot.edit_media_range, opentime.TimeRange) or \
                    not isinstance(shot.edit_media_range.start_time, opentime.RationalTime) or \
                    not isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                logger.warning(f"Skipping shot with missing/invalid path/range in add_unique_shot: {shot.clip_name}")
                return
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

        # Gather shots from batches
        processed_batches = []
        if self.color_transfer_batch and self.color_transfer_batch.unresolved_shots:
            processed_batches.append(self.color_transfer_batch.unresolved_shots)
        if self.online_transfer_batch and self.online_transfer_batch.unresolved_shots:
            processed_batches.append(self.online_transfer_batch.unresolved_shots)
        for batch_unresolved in processed_batches:
            for shot in batch_unresolved:
                if isinstance(shot, EditShot):
                    add_unique_shot(shot)
                else:
                    logger.warning(f"Invalid item in batch unresolved_shots: {type(shot)}")
        # Gather shots from main list
        for shot in self.edit_shots:
            if shot.lookup_status != 'found': add_unique_shot(shot)
        # --- End Gathering ---

        # --- Create Summary with Formatted Range ---
        summary = []
        try:
            sorted_unresolved = sorted(unresolved_shots_list, key=lambda s: s.edit_media_path or "")
        except Exception as sort_err:
            logger.warning(f"Could not sort unresolved shots, using original order. Error: {sort_err}")
            sorted_unresolved = unresolved_shots_list

        for shot in sorted_unresolved:
            # --- Format Edit Range as IN - OUT (frames) ---
            range_str = "N/A"
            # Check if range and its components are valid before formatting
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
                        logger.warning(
                            f"Cannot format edit_range for unresolved clip '{shot.clip_name}' due to invalid rate: {rate}")
                        range_str = f"Start: {shot.edit_media_range.start_time.value}, Dur: {shot.edit_media_range.duration.value} (Rate: {rate})"
                except Exception as e:
                    logger.warning(
                        f"Could not format edit_media_range {shot.edit_media_range} to IN-OUT format for unresolved clip '{shot.clip_name}': {e}")
                    range_str = str(shot.edit_media_range)  # Fallback
            # --- End Formatting ---

            edit_path_basename = os.path.basename(shot.edit_media_path or "") or "N/A"
            summary.append({
                "name": shot.clip_name or edit_path_basename,
                "proxy_path": shot.edit_media_path or "N/A",
                "status": shot.lookup_status,
                "edit_range": range_str,  # Use the formatted string
            })
        return summary

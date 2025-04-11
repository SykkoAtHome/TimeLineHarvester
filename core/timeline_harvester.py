# core/timeline_harvester.py
"""
Main facade class for TimelineHarvester logic.

Coordinates parsing edit files, finding original source media,
calculating transfer segments for different stages (Color, Online),
managing project state save/load, and triggering export/transcode operations.
"""

import json  # For project save/load
import logging
import os
from typing import List, Dict, Optional, Tuple, Callable, Union

import opentimelineio as otio

# Import utils - needed for time conversion helpers during save/load
from utils import handle_utils
from . import calculator as transfer_calculator
from . import ffmpeg as ffmpeg_runner_module
# Import necessary components from the core package
from . import parser as edit_parser
from .models import EditFileMetadata, OriginalSourceFile, EditShot, OutputProfile, TransferSegment, TransferBatch
from .source_finder import SourceFinder

logger = logging.getLogger(__name__)


# --- Serialization Helpers (Move to a dedicated serialization module later?) ---

def time_to_json(otio_time: Optional[Union[otio.opentime.RationalTime, otio.opentime.TimeRange]]) -> Optional[
    Union[List, Dict]]:
    """Serializes OTIO RationalTime or TimeRange to a JSON-compatible format."""
    if isinstance(otio_time, otio.opentime.RationalTime):
        # Store as [value, rate] list
        return [otio_time.value, otio_time.rate]
    elif isinstance(otio_time, otio.opentime.TimeRange):
        # Store as dict with start_time and duration lists
        return {
            "start_time": [otio_time.start_time.value, otio_time.start_time.rate],
            "duration": [otio_time.duration.value, otio_time.duration.rate]
        }
    return None


def time_from_json(json_data: Optional[Union[List, Dict]]) -> Optional[
    Union[otio.opentime.RationalTime, otio.opentime.TimeRange]]:
    """Deserializes JSON data back into OTIO RationalTime or TimeRange."""
    if isinstance(json_data, list) and len(json_data) == 2:
        try:
            return otio.opentime.RationalTime(value=json_data[0], rate=json_data[1])
        except Exception as e:
            logger.error(f"Error deserializing RationalTime from {json_data}: {e}")
            return None
    elif isinstance(json_data, dict) and "start_time" in json_data and "duration" in json_data:
        try:
            start_time = time_from_json(json_data["start_time"])
            duration = time_from_json(json_data["duration"])
            if isinstance(start_time, otio.opentime.RationalTime) and isinstance(duration, otio.opentime.RationalTime):
                return otio.opentime.TimeRange(start_time=start_time, duration=duration)
            else:
                logger.error(f"Error deserializing TimeRange: Invalid start or duration in {json_data}")
                return None
        except Exception as e:
            logger.error(f"Error deserializing TimeRange from {json_data}: {e}")
            return None
    elif json_data is not None:
        logger.warning(f"Unrecognized JSON data format for time deserialization: {json_data}")
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
        self.original_sources_cache: Dict[str, OriginalSourceFile] = {}  # Key: abs path
        # Store transfer batches separately for each stage
        self.color_transfer_batch: Optional[TransferBatch] = None
        self.online_transfer_batch: Optional[TransferBatch] = None

        # --- Configuration ---
        self.project_name: Optional[str] = None
        self.output_profiles: List[OutputProfile] = []  # Primarily used for Online stage
        self.source_search_paths: List[str] = []  # For Originals
        self.graded_source_search_paths: List[str] = []  # For Graded (Online stage input)
        self.source_lookup_strategy: str = "basic_name_match"
        # Stage-specific settings
        self.color_prep_handles: int = 24
        self.online_prep_handles: int = 12
        self.online_target_resolution: Optional[str] = None  # e.g., "3840x2160"
        self.online_analyze_transforms: bool = False
        self.online_output_directory: Optional[str] = None  # Base output for online transcodes

        # --- Internal Instances (lazy loaded) ---
        self._source_finder_instance: Optional[SourceFinder] = None
        self._graded_finder_instance: Optional[SourceFinder] = None  # Separate finder instance for graded?
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
        self.output_profiles = []  # Clear profiles
        self.source_search_paths = []
        self.graded_source_search_paths = []
        self.source_lookup_strategy = "basic_name_match"
        self.color_prep_handles = 24
        self.online_prep_handles = 12
        self.online_target_resolution = None
        self.online_analyze_transforms = False
        self.online_output_directory = None
        # Reset internal instances
        self._source_finder_instance = None
        self._graded_finder_instance = None
        # Don't reset ffmpeg runner, as finding the exe can be kept
        # self._ffmpeg_runner_instance = None
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
            return True
        meta = EditFileMetadata(path=abs_path)  # Filename set in post_init
        self.edit_files.append(meta)
        logger.info(f"Added edit file path to process: {abs_path}")
        # Mark project as potentially dirty? Depends if adding files counts as change.
        return True

    # --- Processing Steps ---
    def parse_added_edit_files(self) -> bool:
        """Parses all edit files in the list. Populates self.edit_shots."""
        self.edit_shots = []
        successful_parses = 0
        total_shots_parsed = 0
        if not self.edit_files: logger.warning("No edit files added to parse."); return False

        logger.info(f"Starting parsing for {len(self.edit_files)} edit file(s)...")
        for meta in self.edit_files:
            try:
                # Call the updated parser function (now returns only shots)
                shots = edit_parser.read_and_parse_edit_file(meta.path)
                # We don't get adapter name back directly anymore,
                # could try to guess based on extension for metadata?
                _, ext = os.path.splitext(meta.filename)
                meta.format_type = ext.lower() or "unknown"  # Store extension as format type
                self.edit_shots.extend(shots)
                total_shots_parsed += len(shots)
                successful_parses += 1
                logger.debug(f"Parsed {len(shots)} shots from '{meta.filename}'.")
            except otio.exceptions.OTIOError as otio_err:  # Catch specific OTIO errors
                logger.error(f"Failed to parse edit file '{meta.filename}' using OTIO: {otio_err}")
                meta.format_type = "parse_error (OTIO)"
            except FileNotFoundError as fnf_err:  # Catch file not found
                logger.error(f"Edit file '{meta.filename}' not found during parsing: {fnf_err}")
                meta.format_type = "file_not_found"
            except Exception as e:  # Catch other unexpected errors
                logger.error(f"Unexpected error parsing edit file '{meta.filename}': {e}", exc_info=False)
                meta.format_type = "parse_error (Other)"

        logger.info(
            f"Parsing complete. Successfully parsed {successful_parses}/{len(self.edit_files)} files. Total EditShots found: {total_shots_parsed}.")
        # Return True if at least one file was processed, even if some failed
        return len(self.edit_files) > 0  # Indicate process ran

    def _get_source_finder(self) -> Optional[SourceFinder]:
        """Initializes or returns the SourceFinder for ORIGINAL sources."""
        # Use specific paths for original sources
        if not self._source_finder_instance:
            if not self.source_search_paths:
                logger.error("Cannot create SourceFinder: No original source search paths are set.")
                return None
            self._source_finder_instance = SourceFinder(
                self.source_search_paths,  # Use original paths
                self.source_lookup_strategy
            )
            # Share the cache between finders if desired, or keep separate? Shared seems better.
            self._source_finder_instance.verified_cache = self.original_sources_cache
        return self._source_finder_instance

    # TODO: Implement _get_graded_finder() similar to above but using self.graded_source_search_paths

    def find_original_sources(self) -> Tuple[int, int, int]:
        """Finds and verifies original source files for parsed EditShots."""
        if not self.edit_shots: logger.warning("No edit shots available for source lookup."); return 0, 0, 0

        finder = self._get_source_finder()  # Get finder configured for original sources
        if not finder:
            # Mark all pending shots as error
            error_count = 0
            for shot in self.edit_shots:
                if shot.lookup_status == "pending": shot.lookup_status = "error"; error_count += 1
            logger.error(f"Source lookup skipped for {error_count} shots due to missing SourceFinder/paths.")
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
                    # Update cache if finder added a new entry (finder handles verification check)
                    if original_file.path not in self.original_sources_cache:
                        self.original_sources_cache[original_file.path] = original_file
                else:
                    shot.lookup_status = "not_found"
                    not_found_count += 1
            except Exception as e:
                logger.error(f"Error during source lookup for shot '{shot.clip_name}': {e}", exc_info=True)
                shot.lookup_status = "error"
                error_count += 1

        # Update main cache reference just in case finder updated it internally
        self.original_sources_cache = finder.verified_cache
        total_processed = found_count + not_found_count + error_count
        logger.info(
            f"Original source lookup finished. Processed: {total_processed}. Found: {found_count}, Not Found: {not_found_count}, Errors: {error_count}")
        return found_count, not_found_count, error_count

    # TODO: Add find_graded_sources() method similar to above

    def calculate_transfer(self, handle_frames: int, output_dir: Optional[str], stage: str):
        """Calculates the TransferBatch for a specific stage (color or online)."""
        logger.info(f"Calculating transfer batch for stage: '{stage}'...")
        self.color_transfer_batch = None if stage == 'color' else self.color_transfer_batch
        self.online_transfer_batch = None if stage == 'online' else self.online_transfer_batch

        # Determine which shots and config to use based on stage
        if stage == 'color':
            shots_to_process = [s for s in self.edit_shots if s.lookup_status == 'found' and s.found_original_source]
            current_handles = self.color_prep_handles  # Use handles specific to this stage
            profiles_for_stage = []  # No transcoding profiles needed for color EDL/XML
            output_dir_for_stage = None  # No output dir needed for calculation
        elif stage == 'online':
            # TODO: Needs logic to find graded sources first
            # For now, assume we process shots that had an original found
            shots_to_process = [s for s in self.edit_shots if
                                s.lookup_status == 'found' and s.found_original_source]  # Placeholder
            current_handles = self.online_prep_handles
            profiles_for_stage = self.output_profiles  # Use profiles configured for online
            output_dir_for_stage = self.online_output_directory  # Use configured online output dir
            if not output_dir_for_stage:
                logger.error("Online output directory not set. Cannot calculate online batch.")
                # Create empty batch with error?
                batch = TransferBatch(handle_frames=current_handles, batch_name=f"Batch_{stage}_Error")
                batch.calculation_errors.append("Online output directory not configured.")
                self.online_transfer_batch = batch
                return
        else:
            logger.error(f"Unknown stage '{stage}' specified for calculate_transfer.")
            return

        if not shots_to_process:
            logger.warning(f"[{stage}] No shots available for transfer calculation.")
            batch = TransferBatch(handle_frames=current_handles, output_directory=output_dir_for_stage,
                                  batch_name=f"Batch_{stage}")
            # Populate unresolved shots based on the *full* edit_shots list
            batch.unresolved_shots = [s for s in self.edit_shots if s.lookup_status != 'found']
        else:
            try:
                # Call the calculator logic
                batch = transfer_calculator.calculate_transfer_batch(
                    edit_shots=shots_to_process,
                    handle_frames=current_handles,
                    output_profiles=profiles_for_stage,
                    output_directory=output_dir_for_stage  # Will be None for color stage
                )
                # Post-process the batch
                batch.unresolved_shots.extend(
                    [s for s in self.edit_shots if s.lookup_status != 'found' and s not in batch.unresolved_shots])
                batch.source_edit_files = self.edit_files
                batch.output_profiles_used = profiles_for_stage
                batch.batch_name = f"Batch_{stage}"  # Add name/type marker

            except Exception as e:
                logger.error(f"Fatal error during transfer calculation for stage '{stage}': {e}", exc_info=True)
                batch = TransferBatch(handle_frames=current_handles, output_directory=output_dir_for_stage,
                                      batch_name=f"Batch_{stage}_Error")
                batch.calculation_errors.append(f"Fatal calculation error: {str(e)}")
                batch.unresolved_shots = self.edit_shots  # Mark all as unresolved

        # Store the result in the correct attribute
        if stage == 'color':
            self.color_transfer_batch = batch
            logger.info(
                f"Color prep batch calculated. Segments: {len(batch.segments)}, Unresolved: {len(batch.unresolved_shots)}, Errors: {len(batch.calculation_errors)}")
        elif stage == 'online':
            self.online_transfer_batch = batch
            logger.info(
                f"Online prep batch calculated. Segments: {len(batch.segments)}, Unresolved: {len(batch.unresolved_shots)}, Errors: {len(batch.calculation_errors)}")

    def _get_ffmpeg_runner(self) -> Optional[ffmpeg_runner_module.FFmpegRunner]:
        """Initializes or returns the FFmpegRunner instance."""
        if not self._ffmpeg_runner_instance:
            self._ffmpeg_runner_instance = ffmpeg_runner_module.FFmpegRunner()
            if not self._ffmpeg_runner_instance.ffmpeg_path:
                logger.critical("FFmpegRunner could not be initialized (ffmpeg executable not found).")
                self._ffmpeg_runner_instance = None  # Ensure it's None if failed
                return None
        return self._ffmpeg_runner_instance

    def run_online_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """Runs FFmpeg transcoding specifically for the calculated Online TransferBatch."""
        logger.info("Attempting to start ONLINE transcoding process...")
        batch_to_run = self.online_transfer_batch  # Use the specific online batch
        if not batch_to_run:
            msg = "Online transfer batch has not been calculated. Cannot transcode."
            logger.error(msg)
            raise ValueError(msg)
        if not batch_to_run.segments:
            msg = "Online transfer batch contains no segments to transcode."
            logger.warning(msg)
            # Nothing to do, consider it successful? Or raise? Raise for clarity.
            raise ValueError(msg)
        if not batch_to_run.output_profiles_used:
            msg = "No output profiles were associated with the online batch. Cannot transcode."
            logger.error(msg)
            raise ValueError(msg)

        runner = self._get_ffmpeg_runner()
        if not runner:
            # Error logged by _get_ffmpeg_runner
            raise RuntimeError("FFmpeg runner is not available.")

        try:
            logger.info(f"Executing FFmpeg for ONLINE batch: {len(batch_to_run.segments)} segments.")
            # Pass the specific batch to the runner
            runner.run_batch(batch_to_run, progress_callback)
            logger.info("Online transcoding process finished by runner.")
        except Exception as e:
            logger.error(f"Online transcoding run failed: {e}", exc_info=True)
            raise  # Re-raise the exception for the calling thread (GUI) to handle

    # --- Project Save/Load Methods ---
    def get_project_data_for_save(self) -> Dict:
        """Gathers current state into a dictionary suitable for JSON serialization."""
        # ... (Implementation using time_to_json and serialize_batch as before) ...
        logger.debug("Gathering project data for saving...")
        serialized_profiles = [p.__dict__ for p in self.output_profiles]
        config_data = {
            "source_lookup_strategy": self.source_lookup_strategy,
            "source_search_paths": self.source_search_paths,
            "graded_source_search_paths": self.graded_source_search_paths,
            "output_profiles": serialized_profiles,
            "color_prep_handles": self.color_prep_handles,
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

        def serialize_batch(batch: Optional[TransferBatch]) -> Optional[Dict]:
            if not batch: return None
            # Need self.edit_shots available in this scope or pass it in
            edit_shots_list = self.edit_shots
            serialized_segments = []
            for seg in batch.segments:
                # Find indices safely
                covered_indices = []
                for s_shot in seg.source_edit_shots:
                    try:
                        covered_indices.append(edit_shots_list.index(s_shot))
                    except ValueError:
                        logger.warning(f"Covered shot not found in main edit_shots list during save.")

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
                    logger.warning(f"Unresolved shot not found in main edit_shots list during save.")

            return {"batch_name": batch.batch_name, "handle_frames": batch.handle_frames,
                    "output_directory": batch.output_directory, "segments": serialized_segments,
                    "unresolved_shots_indices": unresolved_indices,
                    "calculation_errors": batch.calculation_errors,
                    # Save paths instead of full objects for context
                    "output_profiles_names": [p.name for p in batch.output_profiles_used],
                    "source_edit_files_paths": [f.path for f in batch.source_edit_files]}

        project_data = {
            "app_version": "1.1.0",  # Update as needed
            "project_name": self.project_name, "config": config_data,
            "edit_files": serialized_edit_files,
            "analysis_results": {"edit_shots": serialized_edit_shots,
                                 "original_sources_cache": serialized_source_cache, },
            "color_prep_results": {"transfer_batch": serialize_batch(self.color_transfer_batch), },
            "online_prep_results": {"transfer_batch": serialize_batch(self.online_transfer_batch), }}
        return project_data

    def save_project(self, file_path: str) -> bool:
        """Saves the current project state to a JSON file."""
        # ... (Implementation as before, using get_project_data_for_save and json.dump) ...
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
        # ... (Implementation using json.load and time_from_json as before) ...
        # ... (Needs careful reconstruction of objects and references) ...
        logger.info(f"Loading project state from: {file_path}")
        if not os.path.exists(file_path): logger.error(f"Project file not found: {file_path}"); return False
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            self.clear_state()  # Start fresh

            # Restore basic info & config
            self.project_name = project_data.get("project_name")
            saved_app_version = project_data.get("app_version", "Unknown")
            logger.info(f"Loading project '{self.project_name}', saved with app version {saved_app_version}.")
            config = project_data.get("config", {})
            self.source_lookup_strategy = config.get("source_lookup_strategy", "basic_name_match")
            self.source_search_paths = config.get("source_search_paths", [])
            self.graded_source_search_paths = config.get("graded_source_search_paths", [])
            profiles_data = config.get("output_profiles", [])
            self.output_profiles = [OutputProfile(**p_data) for p_data in profiles_data if isinstance(p_data, dict)]
            self.color_prep_handles = config.get("color_prep_handles", 24)
            self.online_prep_handles = config.get("online_prep_handles", 12)
            self.online_target_resolution = config.get("online_target_resolution")
            self.online_analyze_transforms = config.get("online_analyze_transforms", False)
            self.online_output_directory = config.get("online_output_directory")

            # Restore edit files
            edit_files_data = project_data.get("edit_files", [])
            self.edit_files = [EditFileMetadata(path=f_data['path'], format_type=f_data.get('format'))
                               for f_data in edit_files_data if isinstance(f_data, dict) and 'path' in f_data]

            # Restore Original Sources Cache
            analysis_results = project_data.get("analysis_results", {})
            sources_cache_data = analysis_results.get("original_sources_cache", {})
            self.original_sources_cache = {}  # Clear existing cache first
            for path, source_data in sources_cache_data.items():
                if isinstance(source_data, dict):
                    self.original_sources_cache[path] = OriginalSourceFile(
                        path=source_data.get("path", path), duration=time_from_json(source_data.get("duration")),
                        frame_rate=source_data.get("frame_rate"),
                        start_timecode=time_from_json(source_data.get("start_timecode")),
                        is_verified=source_data.get("is_verified", False), metadata=source_data.get("metadata", {}))

            # Restore Edit Shots and link to cache
            edit_shots_data = analysis_results.get("edit_shots", [])
            self.edit_shots = []  # Clear existing shots
            temp_edit_shots_map = {}  # Store by index during load if needed by batch deserialization
            for i, shot_data in enumerate(edit_shots_data):
                if isinstance(shot_data, dict):
                    original_source_path = shot_data.get("found_original_source_path")
                    found_original = self.original_sources_cache.get(
                        original_source_path) if original_source_path else None
                    edit_range = time_from_json(shot_data.get("edit_media_range"))
                    timeline_range = time_from_json(shot_data.get("timeline_range"))
                    if not isinstance(edit_range, otio.opentime.TimeRange): continue  # Skip invalid

                    shot = EditShot(
                        clip_name=shot_data.get("clip_name"), edit_media_path=shot_data.get("edit_media_path", ""),
                        edit_media_range=edit_range, timeline_range=timeline_range,
                        edit_metadata=shot_data.get("edit_metadata", {}),
                        found_original_source=found_original, lookup_status=shot_data.get("lookup_status", "pending"))
                    self.edit_shots.append(shot)
                    temp_edit_shots_map[i] = shot  # Store with original index

            # --- Helper to Deserialize Transfer Batch ---
            def deserialize_batch(batch_data: Optional[Dict], stage: str) -> Optional[TransferBatch]:
                if not batch_data or not isinstance(batch_data, dict): return None
                logger.debug(f"Deserializing transfer batch for stage: {stage}")
                # Use handles specific to the stage being loaded
                handles = self.color_prep_handles if stage == 'color' else self.online_prep_handles
                # Use output dir specific to the stage
                output_dir = self.online_output_directory if stage == 'online' else None

                batch = TransferBatch(
                    batch_name=batch_data.get("batch_name", f"Loaded_Batch_{stage}"),
                    handle_frames=batch_data.get("handle_frames", handles),  # Use loaded or stage default
                    output_directory=batch_data.get("output_directory", output_dir),  # Use loaded or stage default
                    calculation_errors=batch_data.get("calculation_errors", []),
                    # Restore references based on loaded data
                    output_profiles_used=self.output_profiles,  # Assume profiles match for now
                    source_edit_files=self.edit_files  # Assume edit files match
                )
                serialized_segments = batch_data.get("segments", [])
                unresolved_indices = set(batch_data.get("unresolved_shots_indices", []))

                for i, seg_data in enumerate(serialized_segments):
                    if isinstance(seg_data, dict):
                        original_source = self.original_sources_cache.get(seg_data.get("original_source_path"))
                        transfer_range = time_from_json(seg_data.get("transfer_source_range"))
                        if not original_source or not isinstance(transfer_range,
                                                                 otio.opentime.TimeRange): continue  # Skip invalid

                        covered_shots = []
                        indices = seg_data.get("source_edit_shots_indices", [])
                        for idx in indices:
                            # Use the temp map created during EditShot deserialization
                            if idx in temp_edit_shots_map: covered_shots.append(temp_edit_shots_map[idx])

                        batch.segments.append(TransferSegment(
                            original_source=original_source, transfer_source_range=transfer_range,
                            output_targets=seg_data.get("output_targets", {}),
                            status=seg_data.get("status", "calculated"),
                            error_message=seg_data.get("error_message"), source_edit_shots=covered_shots))
                # Reconstruct unresolved shots list using the temp map
                for idx in unresolved_indices:
                    if idx in temp_edit_shots_map: batch.unresolved_shots.append(temp_edit_shots_map[idx])
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
    # (set_source_search_paths, set_source_lookup_strategy, set_output_profiles as before)
    def set_source_search_paths(self, paths: List[str]):
        valid_paths = [os.path.abspath(p) for p in paths if os.path.isdir(p)]
        if len(valid_paths) != len(paths): logger.warning("Some source paths invalid/ignored.")
        if valid_paths != self.source_search_paths:  # Check if changed
            self.source_search_paths = valid_paths
            self._source_finder_instance = None  # Reset finder instance
            logger.info(f"Set original source search paths: {self.source_search_paths}")
            # Mark project dirty? Yes, config change.
            # self.mark_project_dirty() # Need reference back to main window or signal

    def set_graded_source_search_paths(self, paths: List[str]):  # New method
        valid_paths = [os.path.abspath(p) for p in paths if os.path.isdir(p)]
        if len(valid_paths) != len(paths): logger.warning("Some graded paths invalid/ignored.")
        if valid_paths != self.graded_source_search_paths:
            self.graded_source_search_paths = valid_paths
            self._graded_finder_instance = None  # Reset graded finder
            logger.info(f"Set graded source search paths: {self.graded_source_search_paths}")
            # self.mark_project_dirty()

    def set_source_lookup_strategy(self, strategy: str):
        if strategy != self.source_lookup_strategy:
            self.source_lookup_strategy = strategy
            self._source_finder_instance = None  # Reset finder
            self._graded_finder_instance = None
            logger.info(f"Set source lookup strategy: {self.source_lookup_strategy}")
            # self.mark_project_dirty()

    def set_output_profiles(self, profiles_config: List[Dict]):
        # ... (Implementation as before) ...
        new_profiles = []
        for config in profiles_config:
            try:
                if 'name' in config and 'extension' in config:
                    config['ffmpeg_options'] = config.get('ffmpeg_options', [])
                    if not isinstance(config['ffmpeg_options'], list): raise TypeError("ffmpeg_options must be list")
                    new_profiles.append(OutputProfile(**config))
                else:
                    logger.warning(f"Skipping invalid profile config: {config}")
            except TypeError as e:
                logger.warning(f"Skipping invalid profile config {config}: {e}")
        # Check if profiles actually changed before marking dirty?
        # Simple approach: Assume change if called.
        self.output_profiles = new_profiles
        logger.info(f"Set {len(self.output_profiles)} output profiles.")
        # self.mark_project_dirty()

    def set_color_prep_handles(self, handles: int):
        norm_h, _ = handle_utils.normalize_handles(handles, None)
        if norm_h != self.color_prep_handles:
            self.color_prep_handles = norm_h
            logger.info(f"Set color prep handles: {self.color_prep_handles}")
            # self.mark_project_dirty()

    def set_online_prep_handles(self, handles: int):
        norm_h, _ = handle_utils.normalize_handles(handles, None)
        if norm_h != self.online_prep_handles:
            self.online_prep_handles = norm_h
            logger.info(f"Set online prep handles: {self.online_prep_handles}")
            # self.mark_project_dirty()

    def set_online_output_directory(self, dir_path: Optional[str]):
        abs_path = os.path.abspath(dir_path) if dir_path else None
        if abs_path and not os.path.isdir(abs_path):
            logger.warning(f"Online output directory path is not a valid directory: {abs_path}")
            abs_path = None  # Treat invalid path as None

        if abs_path != self.online_output_directory:
            self.online_output_directory = abs_path
            logger.info(f"Set online output directory: {self.online_output_directory}")
            # self.mark_project_dirty()

    # --- Data Retrieval Methods for GUI ---
    # (get_edit_files_summary, get_transfer_segments_summary, get_unresolved_shots_summary)
    # Need update to handle stage parameter or return data based on current state
    def get_edit_files_summary(self) -> List[Dict]:
        return [{"filename": meta.filename, "path": meta.path, "format": meta.format_type or "N/A"}
                for meta in self.edit_files]

    def get_edit_shots_summary(self) -> List[Dict]:
        # Returns summary for ALL shots, status indicates progress
        # ... (Implementation as before) ...
        summary = []
        for shot in self.edit_shots:
            original_path = shot.found_original_source.path if shot.found_original_source else "N/A"
            summary.append({
                "name": shot.clip_name or os.path.basename(shot.edit_media_path),
                "proxy_path": shot.edit_media_path,
                "original_path": original_path,
                "status": shot.lookup_status,
                "edit_range": str(shot.edit_media_range) if shot.edit_media_range else "N/A", })
        return summary

    def get_transfer_segments_summary(self, stage='color') -> List[Dict]:
        """Provides summary for segments of a specific stage's batch."""
        batch = self.color_transfer_batch if stage == 'color' else self.online_transfer_batch
        if not batch: return []
        summary = []
        for i, seg in enumerate(batch.segments):
            tc_string = "N/A"
            duration_sec = 0.0
            if seg.transfer_source_range:
                duration_sec = seg.transfer_source_range.duration.to_seconds()
                # Use rate from the *original source* associated with the segment
                rate = seg.original_source.frame_rate
                if rate:
                    try:
                        tc_string = seg.transfer_source_range.start_time.to_timecode(rate=rate)
                    except:
                        tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s"
            summary.append({
                "index": i + 1,
                "source_basename": os.path.basename(seg.original_source.path),
                "source_path": seg.original_source.path,
                "range_start_tc": tc_string,
                "duration_sec": duration_sec,
                "status": seg.status,  # Transcode status (pending, running, completed, failed)
                "error": seg.error_message or "", })
        return summary

    def get_unresolved_shots_summary(self) -> List[Dict]:
        """Provides summary of shots not found or with errors."""
        # Combine unresolved from calculation batches if they exist, otherwise use main list
        unresolved_in_batches = set()
        if self.color_transfer_batch: unresolved_in_batches.update(self.color_transfer_batch.unresolved_shots)
        if self.online_transfer_batch: unresolved_in_batches.update(self.online_transfer_batch.unresolved_shots)

        # If batches exist, use their combined list, otherwise filter main list
        source_list = list(unresolved_in_batches) if (
                self.color_transfer_batch or self.online_transfer_batch) else self.edit_shots

        summary = []
        for shot in source_list:
            if shot.lookup_status != 'found':  # Filter based on status
                summary.append({
                    "name": shot.clip_name or os.path.basename(shot.edit_media_path),
                    "proxy_path": shot.edit_media_path,
                    "status": shot.lookup_status,
                    "edit_range": str(shot.edit_media_range) if shot.edit_media_range else "N/A", })
        return summary

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
from . import parser as edit_parser  # Upewnij się, że importujesz parser
from .source_finder import SourceFinder
from . import calculator as transfer_calculator
from . import ffmpeg as ffmpeg_runner_module
from .models import EditFileMetadata, OriginalSourceFile, EditShot, OutputProfile, TransferSegment, TransferBatch
# Import utils for time conversion helpers during save/load and handles
from utils import time_utils, handle_utils  # Import handle_utils for setting defaults

logger = logging.getLogger(__name__)


# --- Serialization Helpers (bez zmian) ---
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
        except Exception as e:
            logger.warning(f"Error converting list to RationalTime: {e}, data: {json_data}")
            return None  # Handle errors gracefully
    elif isinstance(json_data, dict) and "start_time" in json_data and "duration" in json_data:
        try:
            start_time = time_from_json(json_data["start_time"])
            duration = time_from_json(json_data["duration"])
            if isinstance(start_time, opentime.RationalTime) and isinstance(duration, opentime.RationalTime):
                return opentime.TimeRange(start_time=start_time, duration=duration)
            else:
                logger.warning(
                    f"Invalid start/duration types for TimeRange from JSON: start={type(start_time)}, dur={type(duration)}, data={json_data}")
                return None
        except Exception as e:
            logger.warning(f"Error converting dict to TimeRange: {e}, data: {json_data}")
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
        self.split_gap_threshold_frames: int = -1  # Default -1 (disabled)
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
        self.split_gap_threshold_frames = -1  # Reset to default
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
        if not self.edit_files:
            logger.warning("No edit files added to parse.")
            return False

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
                meta.format_type = f"parse_error ({type(e).__name__})"

        # Remove duplicates based on identifier and range after parsing all files
        unique_shots_map = {}
        for shot in all_parsed_shots:
            if not shot.edit_media_path or not isinstance(shot.edit_media_range, opentime.TimeRange):
                logger.warning(f"Skipping invalid shot during duplicate check: {shot.clip_name}")
                continue  # Skip invalid shots
            try:
                # Create a unique tuple identifier for the shot usage
                tr = shot.edit_media_range
                # Use float representations for ranges to avoid RationalTime hash issues
                identifier_tuple = (
                    shot.edit_media_path,
                    float(tr.start_time.value), float(tr.start_time.rate),
                    float(tr.duration.value), float(tr.duration.rate)
                )
                if identifier_tuple not in unique_shots_map:
                    unique_shots_map[identifier_tuple] = shot
            except Exception as ident_err:
                logger.warning(
                    f"Could not create identifier tuple for shot during duplicate check: {ident_err}. Shot: {shot.clip_name}")

        self.edit_shots = list(unique_shots_map.values())
        duplicates_removed = len(all_parsed_shots) - len(self.edit_shots)
        if duplicates_removed > 0:
            logger.info(f"Removed {duplicates_removed} duplicate EditShots after parsing all files.")

        logger.info(
            f"Parsing complete. Parsed {successful_parses}/{len(self.edit_files)} files. Found {len(self.edit_shots)} unique EditShots.")
        return successful_parses > 0  # Return True if at least one file was parsed

    def _get_source_finder(self) -> Optional[SourceFinder]:
        """Initializes or returns the SourceFinder for ORIGINAL sources."""
        # Check if config changed or instance is None
        current_paths_set = set(os.path.abspath(p) for p in self.source_search_paths)
        finder_paths_set = set(self._source_finder_instance.search_paths) if self._source_finder_instance else set()

        if not self._source_finder_instance or \
                finder_paths_set != current_paths_set or \
                self._source_finder_instance.strategy != self.source_lookup_strategy:

            if not self.source_search_paths:
                logger.error("Cannot create SourceFinder: No original source search paths set.")
                self._source_finder_instance = None  # Ensure it's None
                return None
            logger.info("Initializing/Re-initializing SourceFinder for original sources...")
            try:
                self._source_finder_instance = SourceFinder(
                    self.source_search_paths, self.source_lookup_strategy
                )
                # Always link the main cache, allowing finder to reuse verified sources
                self._source_finder_instance.verified_cache = self.original_sources_cache
                logger.info(
                    f"SourceFinder ready. Strategy: '{self.source_lookup_strategy}', Paths: {len(self.source_search_paths)}")
            except Exception as finder_init_err:
                logger.critical(f"Failed to initialize SourceFinder: {finder_init_err}", exc_info=True)
                self._source_finder_instance = None
                return None
        return self._source_finder_instance

    # TODO: Implement _get_graded_finder() using self.graded_source_search_paths

    def find_original_sources(self) -> Tuple[int, int, int]:
        """
        Finds and verifies original source files for parsed EditShots,
        then corrects AAF source points if necessary.
        """
        if not self.edit_shots:
            logger.warning("No edit shots available for source lookup.")
            return 0, 0, 0

        finder = self._get_source_finder()
        if not finder:
            # Mark pending shots as error if finder is unavailable
            error_count = 0
            for shot in self.edit_shots:
                if shot.lookup_status == "pending":
                    shot.lookup_status = "error"
                    shot.edit_metadata["lookup_error"] = "SourceFinder unavailable (ffprobe? paths?)"
                    error_count += 1
            if error_count > 0:
                logger.error(f"Source lookup skipped for {error_count} pending shots: SourceFinder unavailable.")
            # Return 0 found, 0 not_found, and count of shots marked as error
            return 0, 0, error_count

        found_count, not_found_count, error_count = 0, 0, 0
        # Determine which shots need checking (pending or previously failed)
        shots_to_check = []
        for s in self.edit_shots:
            # Re-check if not 'found'
            if s.lookup_status != 'found':
                s.lookup_status = 'pending'  # Reset status for re-checking
                s.found_original_source = None  # Clear previous potentially invalid link
                s.edit_metadata.pop("lookup_error", None)  # Clear previous error message
                shots_to_check.append(s)
            # Keep 'found' status for shots already successfully processed

        logger.info(f"Starting original source lookup for {len(shots_to_check)} pending/failed EditShots...")

        # --- Perform Lookup ---
        for shot in shots_to_check:
            try:
                original_file = finder.find_source(shot)  # find_source checks cache first
                if original_file:
                    shot.found_original_source = original_file
                    shot.lookup_status = "found"
                    found_count += 1
                    # Update the main harvester cache
                    self.original_sources_cache[original_file.path] = original_file
                    logger.debug(f"  Found source for '{shot.clip_name or shot.edit_media_path}': {original_file.path}")
                else:
                    shot.lookup_status = "not_found"
                    shot.edit_metadata["lookup_error"] = "No matching original source found in search paths."
                    not_found_count += 1
                    logger.debug(f"  Source not found for '{shot.clip_name or shot.edit_media_path}'.")
            except Exception as e:
                logger.error(f"Error during source lookup for shot '{shot.clip_name or shot.edit_media_path}': {e}",
                             exc_info=True)
                shot.lookup_status = "error"
                shot.edit_metadata["lookup_error"] = f"Exception during lookup: {e}"
                error_count += 1

        # --- *** NOW CORRECT AAF SOURCE POINTS *** ---
        # Call the correction function *after* lookup is complete
        # It will operate on the entire self.edit_shots list
        logger.info("Running AAF source point correction after source lookup...")
        try:
            corrected_aaf_count = edit_parser.correct_aaf_source_points(self.edit_shots)
            logger.info(f"AAF source point correction process completed. Corrected: {corrected_aaf_count} shots.")
            # If correction happened, the project state *might* have changed significantly
            # if corrected_aaf_count > 0: self.mark_project_dirty() # Optional: Mark dirty if correction occurs
        except Exception as corr_err:
            logger.error(f"Error occurred during AAF source point correction phase: {corr_err}", exc_info=True)
            # This shouldn't halt the process, but indicates a problem in the correction logic

        # --- Final Logging ---
        # Recalculate final counts based on the entire list state *after* lookup and correction attempt
        final_found = sum(1 for s in self.edit_shots if s.lookup_status == 'found')
        final_not_found = sum(1 for s in self.edit_shots if s.lookup_status == 'not_found')
        final_error = sum(1 for s in self.edit_shots if s.lookup_status == 'error')
        final_pending = sum(
            1 for s in self.edit_shots if s.lookup_status == 'pending')  # Should be 0 if all were checked

        logger.info(f"Original source lookup finished. "
                    f"Processed: {len(shots_to_check)} shots this run. "
                    f"Final Status -> Found: {final_found}, Not Found: {final_not_found}, "
                    f"Error: {final_error}, Pending: {final_pending}")

        # Return counts based on what was processed in *this run's lookup phase*
        # Note: These counts don't directly reflect the AAF correction step.
        return found_count, not_found_count, error_count

    # --- Configuration Methods (bez zmian) ---
    def set_source_search_paths(self, paths: List[str]):
        """Sets the directories to search for original source files."""
        valid_paths = []
        invalid_count = 0
        for p in paths:
            abs_p = os.path.abspath(p)
            if os.path.isdir(abs_p):
                if abs_p not in valid_paths:  # Avoid duplicates
                    valid_paths.append(abs_p)
            else:
                invalid_count += 1
                logger.warning(f"Ignoring invalid source search path (not a directory or doesn't exist): {p}")

        # Sort for consistent comparison
        valid_paths.sort()
        current_paths_sorted = sorted(self.source_search_paths)

        if invalid_count > 0:
            logger.warning(f"{invalid_count} invalid source paths ignored.")

        if valid_paths != current_paths_sorted:  # Check if actually changed
            self.source_search_paths = valid_paths
            self._source_finder_instance = None  # Reset finder to use new paths on next call
            logger.info(f"Set {len(self.source_search_paths)} valid original source search paths.")
            # Consider marking project dirty? Probably yes.
            # self.mark_project_dirty()

    def set_graded_source_search_paths(self, paths: List[str]):
        """Sets the directories to search for graded source files."""
        # Similar validation as above
        valid_paths = []
        invalid_count = 0
        for p in paths:
            abs_p = os.path.abspath(p)
            if os.path.isdir(abs_p):
                if abs_p not in valid_paths:
                    valid_paths.append(abs_p)
            else:
                invalid_count += 1
                logger.warning(f"Ignoring invalid graded source search path: {p}")

        valid_paths.sort()
        current_paths_sorted = sorted(self.graded_source_search_paths)

        if invalid_count > 0:
            logger.warning(f"{invalid_count} invalid graded paths ignored.")

        if valid_paths != current_paths_sorted:
            self.graded_source_search_paths = valid_paths
            self._graded_finder_instance = None  # Reset graded finder
            logger.info(f"Set {len(self.graded_source_search_paths)} valid graded source search paths.")
            # self.mark_project_dirty()

    def set_source_lookup_strategy(self, strategy: str):
        """Sets the strategy for matching edit media to original/graded sources."""
        # TODO: Validate strategy against a list of known/supported strategies
        known_strategies = ["basic_name_match"]
        if strategy not in known_strategies:
            logger.error(
                f"Attempted to set unknown source lookup strategy: '{strategy}'. Using default 'basic_name_match'.")
            strategy = "basic_name_match"

        if strategy != self.source_lookup_strategy:
            self.source_lookup_strategy = strategy
            self._source_finder_instance = None  # Reset finders as strategy changed
            self._graded_finder_instance = None
            logger.info(f"Set source lookup strategy: {self.source_lookup_strategy}")
            # self.mark_project_dirty()

    def set_output_profiles(self, profiles_config: List[Dict]):
        """Sets the target output profiles for transcoding (primarily Online)."""
        new_profiles = []
        valid_names = set()
        for config in profiles_config:
            try:
                name = config.get('name')
                ext = config.get('extension')
                opts = config.get('ffmpeg_options', [])
                if not name or not isinstance(name, str) or not name.strip():
                    logger.warning(f"Skipping profile config due to missing/empty name: {config}")
                    continue
                name = name.strip()
                if not ext or not isinstance(ext, str) or not ext.strip():
                    logger.warning(f"Skipping profile config '{name}' due to missing/empty extension.")
                    continue
                ext = ext.strip().lstrip('.')  # Clean extension

                if not isinstance(opts, list):
                    logger.warning(
                        f"Skipping profile config '{name}' due to invalid ffmpeg_options (not a list): {opts}")
                    continue
                # Validate options are strings?
                valid_opts = [str(opt) for opt in opts]

                if name in valid_names:
                    logger.warning(f"Skipping duplicate profile name '{name}'.")
                    continue

                new_profiles.append(OutputProfile(name=name, extension=ext, ffmpeg_options=valid_opts))
                valid_names.add(name)

            except Exception as e:
                logger.warning(f"Skipping invalid profile config {config}: {e}")

        # Simple check if lists differ (doesn't check content deeply but often sufficient)
        # More robust check could compare dict representations
        current_profile_reprs = sorted([p.__dict__ for p in self.output_profiles], key=lambda x: x['name'])
        new_profile_reprs = sorted([p.__dict__ for p in new_profiles], key=lambda x: x['name'])

        if new_profile_reprs != current_profile_reprs:
            self.output_profiles = new_profiles
            logger.info(f"Set {len(self.output_profiles)} valid output profiles.")
            # self.mark_project_dirty()

    def set_color_prep_handles(self, start_handles: int, end_handles: Optional[int] = None):
        """Sets normalized color prep handles."""
        # Allow end_handles=None to mean symmetric
        norm_start, norm_end = handle_utils.normalize_handles(start_handles, end_handles)
        changed = False
        if norm_start != self.color_prep_start_handles:
            self.color_prep_start_handles = norm_start
            changed = True
        if norm_end != self.color_prep_end_handles:
            self.color_prep_end_handles = norm_end
            changed = True
        if changed:
            logger.info(
                f"Set color handles: Start={self.color_prep_start_handles}f, End={self.color_prep_end_handles}f")
            # self.mark_project_dirty()

    def set_color_prep_separator(self, separator: int):
        """Sets normalized color prep separator frames."""
        try:
            norm_sep = max(0, int(separator))
            if norm_sep != self.color_prep_separator:
                self.color_prep_separator = norm_sep
                logger.info(f"Set color separator gap: {self.color_prep_separator} frames")
                # self.mark_project_dirty()
        except (ValueError, TypeError):
            logger.warning(
                f"Invalid value for color separator '{separator}', keeping current value {self.color_prep_separator}.")

    def set_split_gap_threshold(self, threshold_frames: int):
        """Sets the threshold for splitting segments based on gap length."""
        try:
            # Allow -1 for disabled, otherwise non-negative
            norm_threshold = int(threshold_frames)
            if norm_threshold < -1:
                norm_threshold = -1  # Clamp lower bound to -1
        except (ValueError, TypeError):
            logger.warning(f"Invalid value for split gap threshold '{threshold_frames}', disabling splitting (-1).")
            norm_threshold = -1

        if norm_threshold != self.split_gap_threshold_frames:
            self.split_gap_threshold_frames = norm_threshold
            status = "disabled" if norm_threshold < 0 else f"{norm_threshold} frames"
            logger.info(f"Set Split Gap Threshold: {status}")
            # self.mark_project_dirty()

    # TODO: Add setters for online prep settings

    # --- Calculation and Transcoding (bez zmian) ---
    def calculate_transfer(self, stage: str):
        """Calculates the TransferBatch for a specific stage ('color' or 'online')."""
        logger.info(f"Calculating transfer batch for stage: '{stage}'...")
        if stage == 'color':
            self.color_transfer_batch = None  # Clear previous results
        elif stage == 'online':
            self.online_transfer_batch = None  # Clear previous results
        else:
            logger.error(f"Unknown stage '{stage}'. Valid stages are 'color' or 'online'.")
            return

        # Determine settings based on stage
        if stage == 'color':
            # Calculator uses symmetric handles based on handle_frames arg
            # Use the larger of start/end handles if they differ? Or just start? Let's use start.
            handles_to_use = self.color_prep_start_handles
            shots_to_process = [s for s in self.edit_shots if s.lookup_status == 'found']
            split_threshold = self.split_gap_threshold_frames  # Use stored value
            profiles_for_stage = []  # Not needed for color prep calculation itself
            output_dir_for_stage = None
            batch_name = f"{self.project_name or 'Project'}_ColorPrep"
        elif stage == 'online':
            handles_to_use = self.online_prep_handles
            # TODO: Define graded source finding logic here. For now, use originals.
            shots_to_process = [s for s in self.edit_shots if s.lookup_status == 'found']  # Placeholder
            split_threshold = -1  # No splitting for online prep by default
            profiles_for_stage = self.output_profiles
            output_dir_for_stage = self.online_output_directory
            batch_name = f"{self.project_name or 'Project'}_OnlinePrep"
            if not output_dir_for_stage:
                logger.error("Cannot calculate for Online: Output directory not set.")
                # Create an empty batch to store errors?
                batch = TransferBatch(handle_frames=handles_to_use, batch_name=f"{batch_name}_Error")
                batch.calculation_errors.append("Online output directory not set.")
                self.online_transfer_batch = batch
                return
            if not profiles_for_stage:
                logger.error("Cannot calculate for Online: Output profiles not set.")
                batch = TransferBatch(handle_frames=handles_to_use, batch_name=f"{batch_name}_Error")
                batch.calculation_errors.append("Online output profiles not set.")
                self.online_transfer_batch = batch
                return
        else:
            return  # Should not happen due to initial check

        if not shots_to_process:
            logger.warning(f"[{stage}] No valid shots found (lookup_status='found') to calculate segments.")
            # Create an empty batch with appropriate settings
            batch = TransferBatch(
                handle_frames=handles_to_use,
                output_directory=output_dir_for_stage,
                batch_name=batch_name,
                output_profiles_used=profiles_for_stage
            )
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
                batch.handle_frames = handles_to_use  # Store handles used for this batch

            except Exception as e:
                logger.error(f"Fatal error during transfer calculation for stage '{stage}': {e}", exc_info=True)
                batch = TransferBatch(
                    handle_frames=handles_to_use,
                    output_directory=output_dir_for_stage,
                    batch_name=f"{batch_name}_Error",
                    output_profiles_used=profiles_for_stage
                )
                batch.calculation_errors.append(f"Fatal calculation error: {str(e)}")
                batch.unresolved_shots = self.edit_shots  # Mark all as unresolved

        # Store the result
        if stage == 'color':
            self.color_transfer_batch = batch
        elif stage == 'online':
            self.online_transfer_batch = batch

        log_msg = f"{stage.capitalize()} batch calculation complete. " \
                  f"Segments: {len(batch.segments)}, " \
                  f"Unresolved Shots: {len(batch.unresolved_shots)}, " \
                  f"Calculation Errors: {len(batch.calculation_errors)}"
        if batch.calculation_errors:
            logger.warning(log_msg)
            for err in batch.calculation_errors: logger.warning(f"  - {err}")
        else:
            logger.info(log_msg)

    def _get_ffmpeg_runner(self) -> Optional[ffmpeg_runner_module.FFmpegRunner]:
        """Initializes or returns the FFmpegRunner instance."""
        if not self._ffmpeg_runner_instance:
            logger.debug("Initializing FFmpegRunner...")
            try:
                self._ffmpeg_runner_instance = ffmpeg_runner_module.FFmpegRunner()
                if not self._ffmpeg_runner_instance.ffmpeg_path:
                    logger.critical("FFmpegRunner could not be initialized (ffmpeg executable not found).")
                    self._ffmpeg_runner_instance = None
            except Exception as ffmpeg_init_err:
                logger.critical(f"Failed to initialize FFmpegRunner: {ffmpeg_init_err}", exc_info=True)
                self._ffmpeg_runner_instance = None

        return self._ffmpeg_runner_instance

    def run_online_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """Runs FFmpeg transcoding specifically for the calculated Online TransferBatch."""
        logger.info("Attempting to start ONLINE transcoding process...")
        batch_to_run = self.online_transfer_batch
        if not batch_to_run:
            raise ValueError("Online transfer batch not calculated. Run 'Calculate for Online' first.")
        if not batch_to_run.segments:
            # Check if calculation errors exist
            if batch_to_run.calculation_errors:
                raise ValueError(f"Online calculation failed: {'; '.join(batch_to_run.calculation_errors)}")
            else:
                raise ValueError("Online transfer batch contains no segments to transcode (perhaps no sources found?).")
        if not batch_to_run.output_profiles_used:
            raise ValueError("No output profiles configured for the online batch.")
        if not batch_to_run.output_directory:
            raise ValueError("Online output directory not configured for the batch.")

        # Make sure output directory exists
        try:
            os.makedirs(batch_to_run.output_directory, exist_ok=True)
            logger.info(f"Ensured online output directory exists: {batch_to_run.output_directory}")
        except OSError as e:
            raise OSError(f"Cannot create online output directory '{batch_to_run.output_directory}': {e}") from e

        runner = self._get_ffmpeg_runner()
        if not runner:
            raise RuntimeError("FFmpeg runner is not available (ffmpeg executable not found).")

        # --- Assign output targets BEFORE running ---
        logger.info("Assigning output target paths for online batch...")
        assign_errors = []
        total_tasks = 0
        for segment in batch_to_run.segments:
            segment.output_targets = {}  # Clear previous targets
            original_basename = os.path.splitext(os.path.basename(segment.original_source.path))[0]
            segment_index = batch_to_run.segments.index(segment)  # Get index for unique naming

            for profile in batch_to_run.output_profiles_used:
                try:
                    # Construct filename: <OriginalName>_<ProfileName>_<SegmentIndex>.<ProfileExt>
                    # Ensure index is zero-padded for sorting if many segments from same source exist
                    output_filename = f"{original_basename}_{profile.name}_{segment_index:04d}.{profile.extension}"
                    output_path = os.path.join(batch_to_run.output_directory, output_filename)
                    segment.output_targets[profile.name] = output_path
                    total_tasks += 1
                except Exception as name_err:
                    msg = f"Error creating output name for segment {segment_index}, profile '{profile.name}': {name_err}"
                    logger.error(msg)
                    assign_errors.append(msg)
                    segment.status = "failed"  # Mark segment as failed if naming fails
                    segment.error_message = msg
                    break  # Stop processing profiles for this segment

        if assign_errors:
            raise ValueError(f"Failed to assign output filenames: {'; '.join(assign_errors)}")
        if total_tasks == 0:
            raise ValueError("No transcode tasks generated (check segment/profile configuration).")
        # --- End Assign Output Targets ---

        try:
            logger.info(
                f"Executing FFmpeg for ONLINE batch: {len(batch_to_run.segments)} segments, {total_tasks} total tasks.")
            # Reset status before run? run_batch should handle it.
            runner.run_batch(batch_to_run, progress_callback)  # run_batch handles internal logic
            logger.info("Online transcoding process finished by runner.")
        except Exception as e:
            logger.error(f"Online transcoding run failed: {e}", exc_info=True)
            raise  # Re-raise the exception

    # --- Project Save/Load Methods (bez zmian) ---
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
                "split_gap_threshold_frames": self.split_gap_threshold_frames,  # Save threshold
                "online_prep_handles": self.online_prep_handles,
                "online_target_resolution": self.online_target_resolution,
                "online_analyze_transforms": self.online_analyze_transforms,
                "online_output_directory": self.online_output_directory,
            }
            serialized_edit_files = [{'path': f.path, 'format': f.format_type} for f in self.edit_files]
            serialized_edit_shots = []
            for shot in self.edit_shots:
                # Ensure metadata doesn't contain problematic flags after successful correction
                clean_metadata = shot.edit_metadata.copy()
                clean_metadata.pop('_needs_aaf_offset_correction', None)
                clean_metadata.pop('_aaf_correction_error', None)

                serialized_edit_shots.append({
                    "clip_name": shot.clip_name, "edit_media_path": shot.edit_media_path,
                    "edit_media_range": time_to_json(shot.edit_media_range),  # Save corrected range
                    "timeline_range": time_to_json(shot.timeline_range),
                    "edit_metadata": clean_metadata,  # Save cleaned metadata
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
                # Create a temporary mapping from object ID to index for stability
                edit_shots_id_map = {id(shot): i for i, shot in enumerate(all_edit_shots)}

                serialized_segments = []
                for seg in batch.segments:
                    # Find indices using object IDs
                    covered_indices = [edit_shots_id_map.get(id(s_shot)) for s_shot in seg.source_edit_shots if
                                       id(s_shot) in edit_shots_id_map]
                    covered_indices = [idx for idx in covered_indices if
                                       idx is not None]  # Filter out None if shot not found in map

                    serialized_segments.append({
                        "original_source_path": seg.original_source.path if seg.original_source else None,
                        # Handle potential None source
                        "transfer_source_range": time_to_json(seg.transfer_source_range),
                        "output_targets": seg.output_targets,  # Save assigned targets if they exist
                        "status": seg.status,
                        "error_message": seg.error_message,
                        "source_edit_shots_indices": covered_indices})

                unresolved_indices = [edit_shots_id_map.get(id(s_shot)) for s_shot in batch.unresolved_shots if
                                      id(s_shot) in edit_shots_id_map]
                unresolved_indices = [idx for idx in unresolved_indices if idx is not None]

                return {
                    "batch_name": batch.batch_name,
                    "handle_frames": batch.handle_frames,
                    "output_directory": batch.output_directory,
                    "segments": serialized_segments,
                    "unresolved_shots_indices": unresolved_indices,
                    "calculation_errors": batch.calculation_errors,
                    "output_profiles_names": [p.name for p in batch.output_profiles_used],  # Store profile names
                    "source_edit_files_paths": [f.path for f in batch.source_edit_files]  # Store paths
                }

            project_data = {
                "app_version": "1.1.1",  # Increment version due to AAF fix
                "project_name": self.project_name,
                "config": config_data,
                "edit_files": serialized_edit_files,
                "analysis_results": {
                    "edit_shots": serialized_edit_shots,
                    "original_sources_cache": serialized_source_cache,
                },
                "color_prep_results": {
                    "transfer_batch": serialize_batch(self.color_transfer_batch, self.edit_shots),
                },
                "online_prep_results": {
                    "transfer_batch": serialize_batch(self.online_transfer_batch, self.edit_shots),
                }
            }
            return project_data
        except Exception as e:
            logger.error(f"Error gathering project data for save: {e}", exc_info=True)
            raise

    def save_project(self, file_path: str) -> bool:
        """Saves the current project state to a JSON file."""
        logger.info(f"Saving project state to: {file_path}")
        try:
            project_data = self.get_project_data_for_save()
            # Ensure directory exists
            output_dir = os.path.dirname(file_path)
            if output_dir:  # Create dir only if path includes one
                os.makedirs(output_dir, exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Project saved successfully to {file_path}")
            return True
        except TypeError as e:
            logger.error(f"Serialization error saving project: {e}", exc_info=True)
            # Provide more detail if possible
            if "Object of type RationalTime is not JSON serializable" in str(e) or \
                    "Object of type TimeRange is not JSON serializable" in str(e):
                logger.error("Ensure all OTIO time objects are converted using time_to_json.")
            return False
        except Exception as e:
            logger.error(f"Failed to save project: {e}", exc_info=True)
            return False

    def load_project(self, file_path: str) -> bool:
        """Loads project state from a JSON file."""
        logger.info(f"Loading project state from: {file_path}")
        if not os.path.exists(file_path):
            logger.error(f"Project file not found: {file_path}")
            return False
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)

            # Clear existing state before loading
            self.clear_state()

            # --- Restore Config ---
            self.project_name = project_data.get("project_name")
            saved_app_version = project_data.get("app_version", "Unknown")
            logger.info(f"Loading project '{self.project_name}', saved with app version {saved_app_version}.")
            # TODO: Add version compatibility check if needed

            config = project_data.get("config", {})
            self.set_source_lookup_strategy(config.get("source_lookup_strategy", "basic_name_match"))
            self.set_source_search_paths(config.get("source_search_paths", []))
            self.set_graded_source_search_paths(config.get("graded_source_search_paths", []))
            self.set_output_profiles(config.get("output_profiles", []))  # Use setter for validation
            color_start_h = config.get("color_prep_start_handles", 24)
            # Handle legacy save where end handles might not exist or be tied to symmetric flag
            color_end_h = config.get("color_prep_end_handles", color_start_h)  # Default to start if missing
            self.set_color_prep_handles(color_start_h, color_end_h)
            self.set_color_prep_separator(config.get("color_prep_separator", 0))
            self.set_split_gap_threshold(config.get("split_gap_threshold_frames", -1))  # Load threshold
            # TODO: Use setters for online config when implemented
            self.online_prep_handles = config.get("online_prep_handles", 12)
            self.online_target_resolution = config.get("online_target_resolution")
            self.online_analyze_transforms = config.get("online_analyze_transforms", False)
            self.online_output_directory = config.get("online_output_directory")

            # --- Restore Edit Files ---
            self.edit_files = []
            for f_data in project_data.get("edit_files", []):
                if isinstance(f_data, dict) and 'path' in f_data:
                    # Check if file still exists? Optional, maybe warn user later.
                    self.edit_files.append(EditFileMetadata(path=f_data['path'], format_type=f_data.get('format')))
                else:
                    logger.warning(f"Skipping invalid edit file data during load: {f_data}")

            # --- Restore Cache ---
            analysis_results = project_data.get("analysis_results", {})
            sources_cache_data = analysis_results.get("original_sources_cache", {})
            self.original_sources_cache = {}
            for path, source_data in sources_cache_data.items():
                if isinstance(source_data, dict):
                    loaded_rate = source_data.get("frame_rate")
                    loaded_duration = time_from_json(source_data.get("duration"))
                    if loaded_rate and isinstance(loaded_duration, opentime.RationalTime):  # Basic validation
                        try:
                            # Ensure start_timecode handles None correctly via time_from_json
                            start_tc = time_from_json(source_data.get("start_timecode"))
                            self.original_sources_cache[path] = OriginalSourceFile(
                                path=source_data.get("path", path),
                                duration=loaded_duration,
                                frame_rate=float(loaded_rate),
                                start_timecode=start_tc,  # time_from_json returns None if input is None/invalid
                                is_verified=source_data.get("is_verified", False),
                                metadata=source_data.get("metadata", {}))
                        except Exception as cache_err:
                            logger.warning(f"Skipping invalid source cache entry for {path}: {cache_err}")
                    else:
                        logger.warning(f"Skipping invalid source cache entry (missing rate/duration) for {path}")

            # --- Restore Edit Shots and link to cache ---
            edit_shots_data = analysis_results.get("edit_shots", [])
            self.edit_shots = []
            # Create a mapping from index (in saved list) to the new shot object
            # This is crucial for linking batches correctly.
            loaded_shots_by_index = {}
            for i, shot_data in enumerate(edit_shots_data):
                if isinstance(shot_data, dict):
                    try:
                        edit_range = time_from_json(shot_data.get("edit_media_range"))
                        if not isinstance(edit_range, opentime.TimeRange):
                            logger.warning(
                                f"Skipping edit shot due to invalid edit_media_range data: {shot_data.get('clip_name')}")
                            continue

                        timeline_range = time_from_json(shot_data.get("timeline_range"))  # Handles None ok

                        original_source_path = shot_data.get("found_original_source_path")
                        found_original = self.original_sources_cache.get(
                            original_source_path) if original_source_path else None

                        # Recreate the EditShot object
                        shot = EditShot(
                            clip_name=shot_data.get("clip_name"),
                            edit_media_path=shot_data.get("edit_media_path", ""),
                            edit_media_range=edit_range,  # Load corrected range
                            timeline_range=timeline_range,
                            edit_metadata=shot_data.get("edit_metadata", {}),  # Load cleaned metadata
                            found_original_source=found_original,
                            lookup_status=shot_data.get("lookup_status", "pending"))

                        # Check if the source link is still valid
                        if original_source_path and not found_original:
                            logger.warning(
                                f"Original source '{original_source_path}' for loaded shot '{shot.clip_name}' not found in restored cache. Resetting status.")
                            shot.lookup_status = 'pending'  # Reset status if link broken

                        self.edit_shots.append(shot)
                        loaded_shots_by_index[i] = shot  # Store mapping by saved index

                    except Exception as shot_err:
                        logger.warning(f"Error loading edit shot data at index {i}: {shot_err}. Data: {shot_data}")

            # --- Helper to Deserialize Transfer Batch ---
            def deserialize_batch(batch_data: Optional[Dict], stage: str, loaded_shots_map: Dict[int, EditShot]) -> \
            Optional[TransferBatch]:
                if not batch_data or not isinstance(batch_data, dict): return None
                logger.debug(f"Deserializing transfer batch for stage: {stage}")
                try:
                    # Determine default handles based on stage if not in save file
                    default_handles = self.color_prep_start_handles if stage == 'color' else self.online_prep_handles
                    handles = batch_data.get("handle_frames", default_handles)

                    default_output_dir = self.online_output_directory if stage == 'online' else None
                    output_dir = batch_data.get("output_directory", default_output_dir)

                    profile_names_used = batch_data.get("output_profiles_names", [])
                    # Find profile objects from the currently loaded self.output_profiles
                    profiles_used = [p for p in self.output_profiles if p.name in profile_names_used]
                    if len(profiles_used) != len(profile_names_used):
                        logger.warning(
                            f"Could not find all saved output profiles ({profile_names_used}) in current config for {stage} batch.")

                    # Find source edit file objects from the currently loaded self.edit_files
                    source_file_paths = batch_data.get("source_edit_files_paths", [])
                    source_files = [f for f in self.edit_files if f.path in source_file_paths]

                    batch = TransferBatch(
                        batch_name=batch_data.get("batch_name", f"Loaded_Batch_{stage}"),
                        handle_frames=handles,
                        output_directory=output_dir,
                        calculation_errors=batch_data.get("calculation_errors", []),
                        output_profiles_used=profiles_used,  # Use restored profile objects
                        source_edit_files=source_files  # Use restored file objects
                    )

                    serialized_segments = batch_data.get("segments", [])
                    unresolved_indices = set(batch_data.get("unresolved_shots_indices", []))

                    # --- Link Segments and Unresolved Shots ---
                    for i, seg_data in enumerate(serialized_segments):
                        if isinstance(seg_data, dict):
                            original_source = self.original_sources_cache.get(seg_data.get("original_source_path"))
                            transfer_range = time_from_json(seg_data.get("transfer_source_range"))

                            if not original_source or not isinstance(transfer_range, opentime.TimeRange):
                                logger.warning(
                                    f"Skipping invalid segment data during load (missing source/range): {seg_data}")
                                batch.calculation_errors.append(
                                    f"Segment {i} load error: Missing source or invalid range.")
                                continue

                            # Map saved indices back to EditShot objects
                            covered_shots = [loaded_shots_map.get(idx) for idx in
                                             seg_data.get("source_edit_shots_indices", [])]
                            covered_shots = [s for s in covered_shots if
                                             s is not None]  # Filter out None values if index was bad

                            # Check if source link is still valid
                            if not original_source:
                                logger.warning(
                                    f"Original source '{seg_data.get('original_source_path')}' for loaded segment {i} not found in cache.")
                                # How to handle? Skip segment? Add error?
                                batch.calculation_errors.append(f"Segment {i} load error: Original source link broken.")
                                continue  # Skip adding this segment

                            batch.segments.append(TransferSegment(
                                original_source=original_source,
                                transfer_source_range=transfer_range,
                                output_targets=seg_data.get("output_targets", {}),  # Load saved targets
                                status=seg_data.get("status", "calculated"),  # Default to calculated if missing
                                error_message=seg_data.get("error_message"),
                                source_edit_shots=covered_shots))

                    # Link unresolved shots using the map
                    batch.unresolved_shots = [loaded_shots_map.get(idx) for idx in unresolved_indices]
                    batch.unresolved_shots = [s for s in batch.unresolved_shots if s is not None]  # Filter None

                    return batch
                except Exception as batch_err:
                    logger.error(f"Error deserializing {stage} batch: {batch_err}", exc_info=True)
                    return None  # Return None on error

            # --- Deserialize Batches using the index->object map ---
            self.color_transfer_batch = deserialize_batch(
                project_data.get("color_prep_results", {}).get("transfer_batch"), 'color', loaded_shots_by_index)
            self.online_transfer_batch = deserialize_batch(
                project_data.get("online_prep_results", {}).get("transfer_batch"), 'online', loaded_shots_by_index)

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

    # --- Data Retrieval Methods for GUI (bez zmian) ---
    def get_edit_files_summary(self) -> List[Dict]:
        """Provides summary of loaded edit files."""
        return [{"filename": meta.filename, "path": meta.path, "format": meta.format_type or "N/A"}
                for meta in self.edit_files]

    def get_edit_shots_summary(self) -> List[Dict]:
        """
        Provides detailed summary data for each EditShot for GUI display.
        Includes corrected time values after AAF processing.
        """
        summary = []
        # Determine overall sequence rate (best effort)
        sequence_rate: Optional[float] = None
        if self.edit_shots:  # Check if shots exist
            # Try finding rate from first shot with timeline_range
            for shot in self.edit_shots:
                if shot.timeline_range and shot.timeline_range.duration.rate > 0:
                    sequence_rate = float(shot.timeline_range.duration.rate)
                    break
            # Fallback: try finding rate from first shot with edit_media_range
            if sequence_rate is None:
                for shot in self.edit_shots:
                    if shot.edit_media_range and shot.edit_media_range.duration.rate > 0:
                        sequence_rate = float(shot.edit_media_range.duration.rate)
                        break
        # Final fallback
        if sequence_rate is None: sequence_rate = 25.0
        logger.debug(f"Using sequence rate {sequence_rate} for Edit Shots Summary.")

        for idx, shot in enumerate(self.edit_shots):
            source_info = shot.found_original_source
            original_path = source_info.path if source_info else "N/A"
            edit_media_id = shot.edit_media_path or "N/A"

            # --- Original Source File Times ---
            source_start_rt = source_info.start_timecode if source_info else None
            source_duration_rt = source_info.duration if source_info else None
            source_rate = float(source_info.frame_rate) if source_info and source_info.frame_rate else None
            source_end_rt_excl = None
            if source_start_rt and source_duration_rt:
                try:
                    source_end_rt_excl = source_start_rt + source_duration_rt
                except:
                    pass

            # --- Source Point Times (from EditShot.edit_media_range - NOW ABSOLUTE) ---
            source_point_in_rt = shot.edit_media_range.start_time if shot.edit_media_range else None
            source_point_duration_rt = shot.edit_media_range.duration if shot.edit_media_range else None
            source_point_rate = float(
                source_point_duration_rt.rate) if source_point_duration_rt and source_point_duration_rt.rate > 0 else None
            source_point_out_rt_excl = None
            if source_point_in_rt and source_point_duration_rt:
                try:
                    source_point_out_rt_excl = source_point_in_rt + source_point_duration_rt
                except:
                    pass

            # --- Edit Position Times (from EditShot.timeline_range - ABSOLUTE) ---
            edit_in_rt = shot.timeline_range.start_time if shot.timeline_range else None
            edit_duration_rt = shot.timeline_range.duration if shot.timeline_range else None
            edit_out_rt_excl = None
            # Use the determined sequence rate for consistency in this column
            current_sequence_rate = sequence_rate
            if edit_in_rt and edit_duration_rt:
                try:
                    # Rescale duration to start time rate for calculation safety
                    rescaled_dur = edit_duration_rt.rescaled_to(edit_in_rt.rate)
                    edit_out_rt_excl = edit_in_rt + rescaled_dur
                except:
                    pass  # Ignore errors

            # --- Prepare Summary Item ---
            summary_item = {
                "index": idx + 1,
                "clip_name": shot.clip_name or os.path.basename(edit_media_id) or "N/A",
                "edit_media_id": edit_media_id,
                "source_path": original_path,
                "status": shot.lookup_status,
                # Original Source
                "source_in_rt": source_start_rt,
                "source_out_rt_excl": source_end_rt_excl,
                "source_duration_rt": source_duration_rt,
                "source_rate": source_rate,
                # Source Point (from Edit - ABSOLUTE)
                "source_point_in_rt": source_point_in_rt,
                "source_point_out_rt_excl": source_point_out_rt_excl,
                "source_point_duration_rt": source_point_duration_rt,
                "source_point_rate": source_point_rate,
                # Edit Position (Absolute on Timeline)
                "edit_in_rt": edit_in_rt,
                "edit_out_rt_excl": edit_out_rt_excl,
                "edit_duration_rt": edit_duration_rt,
                "sequence_rate": current_sequence_rate  # Pass the rate to use for formatting this shot's edit times
            }
            summary.append(summary_item)
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
                try:
                    # Convert duration to seconds using the source rate
                    duration_sec = seg.transfer_source_range.duration.rescaled_to(rate).to_seconds()
                except Exception:
                    duration_sec = seg.transfer_source_range.duration.to_seconds()  # Fallback

                try:
                    # Format start timecode using the source rate
                    tc_string = opentime.to_timecode(seg.transfer_source_range.start_time.rescaled_to(rate), rate=rate)
                except Exception:
                    tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s (Rate Error)"  # Fallback if TC fails

            elif seg.transfer_source_range:  # Handle case where rate is missing/invalid
                duration_sec = seg.transfer_source_range.duration.to_seconds() if seg.transfer_source_range.duration.rate > 0 else 0.0
                tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s"

            source_basename = os.path.basename(seg.original_source.path) if seg.original_source else "N/A"
            source_path = seg.original_source.path if seg.original_source else "N/A"

            # Get transcode status from output_targets if stage is 'online'
            transcode_status = seg.status  # Default status (calculated, pending, running, failed, completed)
            error_msg = seg.error_message or ""
            if stage == 'online' and transcode_status == 'completed':
                # Optionally check individual target files? For now, 'completed' means runner finished successfully.
                pass
            elif stage == 'online' and transcode_status == 'failed':
                # Error message should already be set by the runner
                pass

            summary.append({
                "index": i + 1,
                "source_basename": source_basename,
                "source_path": source_path,
                "range_start_tc": tc_string,
                "duration_sec": duration_sec,
                "status": transcode_status,  # Use the segment's overall status
                "error": error_msg,
            })
        return summary

    def get_unresolved_shots_summary(self) -> List[Dict]:
        """
        Provides a summary of shots not found or with errors,
        formatting the (corrected) edit_range as IN - OUT (frames).
        """
        unresolved_shots_list: List[EditShot] = []
        # Use object ID for robust uniqueness check
        seen_identifiers_ids: Set[int] = set()

        def add_unique_shot(shot: EditShot):
            shot_id = id(shot)
            if shot_id not in seen_identifiers_ids:
                seen_identifiers_ids.add(shot_id)
                unresolved_shots_list.append(shot)

        # Gather unresolved shots from batches and main list
        for batch in [self.color_transfer_batch, self.online_transfer_batch]:
            if batch and batch.unresolved_shots:
                for shot in batch.unresolved_shots:
                    if isinstance(shot, EditShot): add_unique_shot(shot)

        # Also check the main list for any shots not in 'found' status
        for shot in self.edit_shots:
            if shot.lookup_status != 'found':
                add_unique_shot(shot)

        # Create Summary
        summary = []
        try:  # Sort list by identifier path, then clip name
            sorted_unresolved = sorted(unresolved_shots_list,
                                       key=lambda s: (s.edit_media_path or "", s.clip_name or ""))
        except Exception as sort_err:
            logger.warning(f"Could not sort unresolved shots: {sort_err}")
            sorted_unresolved = unresolved_shots_list  # Use unsorted list on error

        for shot in sorted_unresolved:
            # Format Edit Range (Source Point - now absolute) as IN - OUT (frames)
            range_str = "N/A"
            if shot.edit_media_range and \
                    isinstance(shot.edit_media_range.start_time, opentime.RationalTime) and \
                    isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                try:
                    rate = float(shot.edit_media_range.duration.rate)
                    if rate <= 0:  # Try start time rate if duration rate invalid
                        rate = float(shot.edit_media_range.start_time.rate)

                    if rate > 0:
                        start_time = shot.edit_media_range.start_time
                        duration = shot.edit_media_range.duration
                        # Calculate end time inclusive for display
                        end_time_incl = start_time + opentime.RationalTime(duration.value - 1,
                                                                           duration.rate) if duration.value > 0 else start_time

                        start_tc = opentime.to_timecode(start_time, rate)
                        end_tc = opentime.to_timecode(end_time_incl, rate)
                        # Calculate duration in frames at the determined rate
                        duration_frames = int(round(duration.rescaled_to(rate).value))
                        range_str = f"{start_tc} - {end_tc} ({duration_frames} frames)"
                    else:
                        range_str = f"Invalid Rate ({rate})"
                except Exception as e:
                    range_str = f"Error formatting range: {e}"  # Fallback

            edit_path_basename = os.path.basename(shot.edit_media_path or "") or "N/A"
            lookup_error_msg = shot.edit_metadata.get("lookup_error", "")
            status_display = f"{shot.lookup_status.upper()}"
            if lookup_error_msg: status_display += f" ({lookup_error_msg})"

            summary.append({
                "name": shot.clip_name or edit_path_basename,
                "proxy_path": shot.edit_media_path or "N/A",  # This holds the identifier
                "status": status_display,  # Include error message if present
                "edit_range": range_str,  # Use the formatted string
            })
        return summary

    # --- Helper to ensure UI is refreshed after corrections ---
    # This might be called by the MainWindow after the worker finishes analysis
    def _refresh_results_display(self):
        """Refreshes all result tabs based on current harvester data."""
        logger.info("Refreshing results display panels...")
        # Assuming the main window manages calling this
        # Get fresh summaries which now include corrected data
        analysis_summary = self.get_edit_shots_summary()
        color_plan_summary = self.get_transfer_segments_summary(stage='color')
        online_plan_summary = self.get_transfer_segments_summary(stage='online')
        unresolved_summary = self.get_unresolved_shots_summary()

        # Update the relevant UI elements (assuming these methods exist in the GUI classes)
        if hasattr(self, 'color_prep_tab') and self.color_prep_tab:
            self.color_prep_tab.results_widget.display_analysis_summary(analysis_summary)
            self.color_prep_tab.results_widget.display_plan_summary(color_plan_summary)
            self.color_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
        if hasattr(self, 'online_prep_tab') and self.online_prep_tab:
            # self.online_prep_tab.results_widget.display_analysis_summary(analysis_summary) # If needed
            # self.online_prep_tab.results_widget.display_plan_summary(online_plan_summary)
            # self.online_prep_tab.results_widget.display_unresolved_summary(unresolved_summary)
            pass  # Update online results when implemented

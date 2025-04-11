# core/timeline_harvester.py
"""
Main facade class for TimelineHarvester logic.

Coordinates parsing edit files, finding original source media,
calculating transfer segments, and managing the overall process.
"""

import logging
import os
from typing import List, Dict, Optional, Any, Tuple, Callable  # Added Callable

# Import necessary components from the core package
from . import parser as edit_parser
from .source_finder import SourceFinder
from . import calculator as transfer_calculator
from . import ffmpeg as ffmpeg_runner_module
from .models import EditFileMetadata, EditShot, OriginalSourceFile, TransferBatch, OutputProfile

logger = logging.getLogger(__name__)


class TimelineHarvester:
    """
    Coordinates the different steps of the timeline harvesting process.
    """

    def __init__(self):
        # --- State ---
        self.edit_files: List[EditFileMetadata] = []
        self.edit_shots: List[EditShot] = []
        self.original_sources_cache: Dict[str, OriginalSourceFile] = {}
        self.transfer_batch: Optional[TransferBatch] = None

        # --- Configuration (to be set via UI or other means) ---
        self.output_profiles: List[OutputProfile] = []
        self.source_search_paths: List[str] = []
        self.source_lookup_strategy: str = "basic_name_match"

        self._source_finder_instance: Optional[SourceFinder] = None
        self._ffmpeg_runner_instance: Optional[ffmpeg_runner_module.FFmpegRunner] = None  # Cache runner instance

        logger.info("TimelineHarvester core engine initialized.")

    def clear_state(self):
        """Resets the internal state for a new analysis job."""
        self.edit_files = []
        self.edit_shots = []
        self.original_sources_cache = {}
        self.transfer_batch = None
        self._source_finder_instance = None
        # Keep ffmpeg runner instance? Maybe, as finding exe is done once.
        # self._ffmpeg_runner_instance = None
        logger.info("TimelineHarvester state cleared.")

    def add_edit_file_path(self, file_path: str) -> bool:
        """Adds an edit file path to the list for later processing."""
        # ... (implementation as before) ...
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            logger.error(f"Edit file not found: {abs_path}")
            return False
        if any(ef.path == abs_path for ef in self.edit_files):
            logger.warning(f"Edit file already in list: {abs_path}")
            return True
        meta = EditFileMetadata(path=abs_path)
        self.edit_files.append(meta)
        logger.info(f"Added edit file path to process: {abs_path}")
        return True

    def parse_added_edit_files(self) -> bool:
        """Parses all edit files previously added."""
        # ... (implementation as before) ...
        self.edit_shots = []
        successful_parses = 0
        total_shots_parsed = 0
        if not self.edit_files:
            logger.warning("No edit files added to parse.")
            return False
        logger.info(f"Starting parsing for {len(self.edit_files)} edit file(s)...")
        for meta in self.edit_files:
            try:
                shots, adapter_name = edit_parser.read_and_parse_edit_file(meta.path)
                meta.format_type = adapter_name or "otio_unknown"
                self.edit_shots.extend(shots)
                total_shots_parsed += len(shots)
                successful_parses += 1
                logger.debug(f"Parsed {len(shots)} shots from '{meta.filename}' using adapter '{meta.format_type}'.")
            except Exception as e:
                logger.error(f"Failed to parse edit file '{meta.filename}': {e}", exc_info=False)
                meta.format_type = "parse_error"
        logger.info(
            f"Parsing complete. Successfully parsed {successful_parses}/{len(self.edit_files)} files. Total EditShots found: {total_shots_parsed}.")
        return successful_parses > 0

    def _get_source_finder(self) -> Optional[SourceFinder]:
        """Initializes or returns the SourceFinder instance."""
        # ... (implementation as before) ...
        if not self._source_finder_instance:
            if not self.source_search_paths:
                logger.error("Cannot create SourceFinder: No source search paths are set.")
                return None
            self._source_finder_instance = SourceFinder(
                self.source_search_paths,
                self.source_lookup_strategy
            )
            self._source_finder_instance.verified_cache = self.original_sources_cache
        return self._source_finder_instance

    def find_original_sources(self) -> Tuple[int, int, int]:
        """Attempts to find and verify original source files for all parsed EditShots."""
        # ... (implementation as before, calls finder.find_source) ...
        if not self.edit_shots:
            logger.warning("No edit shots available to perform source lookup.")
            return 0, 0, 0
        finder = self._get_source_finder()
        if not finder:
            error_count = 0
            for shot in self.edit_shots:
                if shot.lookup_status == "pending":
                    shot.lookup_status = "error"
                    error_count += 1
            logger.error(f"Source lookup skipped for {error_count} shots due to missing SourceFinder.")
            return 0, 0, error_count

        found_count = 0
        not_found_count = 0
        error_count = 0
        shots_to_check = [s for s in self.edit_shots if s.lookup_status == "pending"]
        logger.info(f"Starting source lookup for {len(shots_to_check)} pending EditShots...")
        for i, shot in enumerate(shots_to_check):
            logger.debug(
                f"Looking up source {i + 1}/{len(shots_to_check)} for: '{shot.clip_name}' (Edit media: {shot.edit_media_path})")
            try:
                original_file = finder.find_source(shot)
                if original_file:
                    shot.found_original_source = original_file
                    shot.lookup_status = "found"
                    found_count += 1
                else:
                    shot.lookup_status = "not_found"
                    not_found_count += 1
            except Exception as e:
                logger.error(f"Error during source lookup for shot '{shot.clip_name}': {e}", exc_info=True)
                shot.lookup_status = "error"
                error_count += 1
        self.original_sources_cache = finder.verified_cache  # Update main cache
        total_processed = found_count + not_found_count + error_count
        logger.info(
            f"Source lookup finished. Processed: {total_processed}. Found: {found_count}, Not Found: {not_found_count}, Errors: {error_count}")
        return found_count, not_found_count, error_count

    # --- Configuration Methods ---
    def set_source_search_paths(self, paths: List[str]):
        """Sets the directories where original source files should be searched."""
        # ... (implementation as before) ...
        valid_paths = [os.path.abspath(p) for p in paths if os.path.isdir(p)]
        if len(valid_paths) != len(paths):
            logger.warning("Some provided source search paths were invalid or not directories and were ignored.")
        self.source_search_paths = valid_paths
        self._source_finder_instance = None
        logger.info(f"Set source search paths: {self.source_search_paths}")

    def set_source_lookup_strategy(self, strategy: str):
        """Sets the strategy for matching edit media to original sources."""
        # ... (implementation as before) ...
        self.source_lookup_strategy = strategy
        self._source_finder_instance = None
        logger.info(f"Set source lookup strategy: {self.source_lookup_strategy}")

    def set_output_profiles(self, profiles_config: List[Dict]):
        """Sets the target output profiles for transcoding."""
        # ... (implementation as before) ...
        self.output_profiles = []
        for config in profiles_config:
            try:
                if 'name' in config and 'extension' in config:
                    config['ffmpeg_options'] = config.get('ffmpeg_options', [])
                    if not isinstance(config['ffmpeg_options'], list):
                        raise TypeError("ffmpeg_options must be a list")
                    self.output_profiles.append(OutputProfile(**config))
                else:
                    logger.warning(f"Skipping invalid profile config (missing name or extension): {config}")
            except TypeError as e:
                logger.warning(f"Skipping invalid profile config {config}: {e}")
        logger.info(f"Set {len(self.output_profiles)} output profiles.")

    # --- Calculation and Transcoding ---

    def calculate_transfer(self, handle_frames: int, output_dir: str):
        """
        Calculates the TransferBatch using the calculator module.
        Uses previously parsed shots and found original sources.
        Stores the result in `self.transfer_batch`.
        """
        self.transfer_batch = None  # Clear previous batch calculation
        logger.info(f"Starting transfer calculation. Handles: {handle_frames}, Output Dir: {output_dir}")

        shots_to_process = [s for s in self.edit_shots if s.lookup_status == "found"]
        if not shots_to_process:
            logger.warning("No shots with found original sources available for transfer calculation.")
            self.transfer_batch = TransferBatch(handle_frames=handle_frames,
                                                output_directory=output_dir)  # Create empty batch
            self.transfer_batch.unresolved_shots = [s for s in self.edit_shots if s.lookup_status != 'found']
            return  # Nothing to calculate

        if not self.output_profiles:
            logger.error("Cannot calculate transfer: No output profiles have been set.")
            self.transfer_batch = TransferBatch(handle_frames=handle_frames, output_directory=output_dir)
            self.transfer_batch.calculation_errors.append("No output profiles set.")
            self.transfer_batch.unresolved_shots = self.edit_shots  # All are unresolved in this case
            return

        try:
            # Call the function from the calculator module
            self.transfer_batch = transfer_calculator.calculate_transfer_batch(
                edit_shots=shots_to_process,
                handle_frames=handle_frames,
                output_profiles=self.output_profiles,  # Pass configured profiles
                output_directory=output_dir
            )
            # Add remaining unresolved shots and context
            self.transfer_batch.unresolved_shots.extend([s for s in self.edit_shots if s.lookup_status != 'found'])
            self.transfer_batch.source_edit_files = self.edit_files
            # output_profiles_used is set inside calculate_transfer_batch in this example

            logger.info(
                f"Transfer batch calculation complete. Segments: {len(self.transfer_batch.segments)}, Unresolved: {len(self.transfer_batch.unresolved_shots)}, Calc Errors: {len(self.transfer_batch.calculation_errors)}")

        except Exception as e:
            logger.error(f"Fatal error during transfer calculation: {e}", exc_info=True)
            # Create an empty batch indicating the failure
            self.transfer_batch = TransferBatch(handle_frames=handle_frames, output_directory=output_dir)
            self.transfer_batch.calculation_errors.append(f"Fatal calculation error: {str(e)}")
            self.transfer_batch.unresolved_shots = self.edit_shots  # Mark all as unresolved

    def _get_ffmpeg_runner(self) -> Optional[ffmpeg_runner_module.FFmpegRunner]:
        """Initializes or returns the FFmpegRunner instance."""
        if not self._ffmpeg_runner_instance:
            self._ffmpeg_runner_instance = ffmpeg_runner_module.FFmpegRunner()
            # Check if runner initialization failed (e.g., ffmpeg not found)
            if not self._ffmpeg_runner_instance.ffmpeg_path:
                logger.critical("FFmpegRunner could not be initialized (ffmpeg not found).")
                return None
        return self._ffmpeg_runner_instance

    def run_transcoding(self, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """
        Runs FFmpeg transcoding for the calculated TransferBatch using the ffmpeg module.

        Args:
            progress_callback: Optional function like func(completed, total, message).
        """
        logger.info("Attempting to start transcoding process...")
        if not self.transfer_batch:
            msg = "No transfer batch has been calculated. Cannot start transcoding."
            logger.error(msg)
            raise ValueError(msg)
        if not self.transfer_batch.segments:
            # Check if there are segments, even if batch exists
            msg = "Transfer batch contains no segments to transcode."
            logger.warning(msg)
            # Consider this a "success" in the sense that there's nothing to do
            # Or raise an error? Let's raise for clarity.
            raise ValueError(msg)

        runner = self._get_ffmpeg_runner()
        if not runner:
            msg = "FFmpeg runner could not be initialized. Cannot transcode."
            logger.critical(msg)
            raise RuntimeError(msg)  # Raise critical error

        try:
            logger.info(f"Executing FFmpeg batch: {len(self.transfer_batch.segments)} segments.")
            # Pass the entire batch object to the runner
            runner.run_batch(self.transfer_batch, progress_callback)
            logger.info("Transcoding process finished by runner.")
            # Note: Segment statuses within self.transfer_batch are updated by run_batch
        except Exception as e:
            logger.error(f"Transcoding run failed: {e}", exc_info=True)
            # Propagate the error for the GUI thread to handle
            raise  # Re-raise the exception

    # --- Data Retrieval Methods for GUI ---
    # (Implementations as before, providing simplified dicts/lists)
    def get_edit_files_summary(self) -> List[Dict]:
        """Returns summary info about loaded edit files."""
        # ... (implementation as before) ...
        return [
            {"filename": meta.filename, "path": meta.path, "format": meta.format_type or "N/A"}
            for meta in self.edit_files
        ]

    def get_edit_shots_summary(self) -> List[Dict]:
        """Provides a summary of EditShots status."""
        # ... (implementation as before) ...
        summary = []
        for shot in self.edit_shots:
            original_path = "N/A"
            if shot.found_original_source:
                original_path = shot.found_original_source.path
            summary.append({
                "name": shot.clip_name or os.path.basename(shot.edit_media_path),
                "proxy_path": shot.edit_media_path,
                "original_path": original_path,
                "status": shot.lookup_status,
                "edit_range": str(shot.edit_media_range) if shot.edit_media_range else "N/A",
            })
        return summary

    def get_transfer_segments_summary(self) -> List[Dict]:
        """Provides a summary of calculated TransferSegments."""
        # ... (implementation as before, using self.transfer_batch) ...
        if not self.transfer_batch: return []
        summary = []
        for i, seg in enumerate(self.transfer_batch.segments):
            tc_string = "N/A"
            duration_sec = 0.0
            if seg.transfer_source_range:
                duration_sec = seg.transfer_source_range.duration.to_seconds()
                if seg.original_source.frame_rate:
                    try:
                        tc_string = seg.transfer_source_range.start_time.to_timecode(
                            rate=seg.original_source.frame_rate)
                    except:
                        tc_string = f"{seg.transfer_source_range.start_time.to_seconds():.3f}s"  # Fallback
            summary.append({
                "index": i + 1,
                "source_basename": os.path.basename(seg.original_source.path),
                "source_path": seg.original_source.path,
                "range_start_tc": tc_string,
                "duration_sec": duration_sec,
                "status": seg.status,
                "error": seg.error_message or "",
            })
        return summary

    def get_unresolved_shots_summary(self) -> List[Dict]:
        """Provides a summary of shots that couldn't be resolved or had errors."""
        # ... (implementation as before, using self.transfer_batch if available) ...
        unresolved = []
        if self.transfer_batch:
            unresolved = self.transfer_batch.unresolved_shots
        elif self.edit_shots:  # Fallback if batch not calculated yet
            unresolved = [s for s in self.edit_shots if s.lookup_status != 'found']

        summary = []
        for shot in unresolved:
            summary.append({
                "name": shot.clip_name or os.path.basename(shot.edit_media_path),
                "proxy_path": shot.edit_media_path,
                "status": shot.lookup_status,
                "edit_range": str(shot.edit_media_range) if shot.edit_media_range else "N/A",
            })
        return summary

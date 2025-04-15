# core/processing/source_processor.py
"""
Coordinates the source processing steps: parsing edit files, finding original sources,
and correcting AAF source points based on found originals.
Operates on and updates the ProjectState.
"""

import logging
import os
from typing import Tuple, List, Dict, Optional


from ..project_state import ProjectState
from ..source_finder import SourceFinder
from .. import parser as edit_parser
from ..models import EditShot
from opentimelineio import opentime

logger = logging.getLogger(__name__)


class SourceProcessor:
    """Handles parsing, source finding, and AAF correction."""

    def __init__(self, state: ProjectState):
        """
        Initializes the processor with the project state.

        Args:
            state: The ProjectState object to operate on.
        """
        if not isinstance(state, ProjectState):
            raise TypeError("SourceProcessor requires a valid ProjectState instance.")
        self.state = state
        # Note: SourceFinder initialization could be delayed until find_and_correct_sources
        # if search paths might change between parsing and finding.
        # For simplicity now, we assume settings are stable when processor is created.
        self._source_finder: Optional[SourceFinder] = None
        logger.debug("SourceProcessor initialized.")

    def _get_finder_instance(self) -> Optional[SourceFinder]:
        """Gets or creates the SourceFinder instance based on current state settings."""
        # Check if finder needs to be created or updated
        current_paths = self.state.settings.source_search_paths
        current_strategy = self.state.settings.source_lookup_strategy

        if not self._source_finder or \
                set(self._source_finder.search_paths) != set(current_paths) or \
                self._source_finder.strategy != current_strategy:

            if not current_paths:
                logger.error("Cannot create SourceFinder: No original source search paths set in project settings.")
                self._source_finder = None
                return None

            logger.info(f"Initializing SourceFinder (Paths: {len(current_paths)}, Strategy: '{current_strategy}')")
            try:
                self._source_finder = SourceFinder(current_paths, current_strategy)
                # Link the finder's cache to the project state's cache
                self._source_finder.verified_cache = self.state.original_sources_cache
                logger.info("SourceFinder instance ready.")
            except Exception as finder_err:
                logger.critical(f"Failed to initialize SourceFinder: {finder_err}", exc_info=True)
                self._source_finder = None
                return None

        return self._source_finder

    def parse_edit_files(self) -> bool:
        """
        Parses edit files defined in the project state.
        Updates state.edit_shots and state.edit_files[...].format_type.
        Clears previous analysis results (edit_shots, cache, batches).

        Returns:
            True if at least one file was parsed successfully, False otherwise.
        """
        # --- Clear previous analysis results before parsing ---
        # This prevents mixing old shots with new ones if parsing is re-run
        self.state.clear_analysis_results()
        logger.info("Cleared previous analysis results before parsing.")
        # Note: We keep edit_files list itself, just clear the parsed shots etc.

        if not self.state.edit_files:
            logger.warning("No edit files in project state to parse.")
            return False

        logger.info(f"Starting parsing for {len(self.state.edit_files)} edit file(s)...")
        all_parsed_shots: List[EditShot] = []
        successful_parses = 0

        for meta in self.state.edit_files:
            logger.info(f"Parsing: {meta.filename}")
            try:
                # Use the parser module function
                shots = edit_parser.read_and_parse_edit_file(meta.path)
                _, ext = os.path.splitext(meta.filename)
                meta.format_type = ext.lower().lstrip('.') or "unknown"  # Update format type in state
                all_parsed_shots.extend(shots)
                successful_parses += 1
                logger.info(f"Successfully parsed '{meta.filename}', found {len(shots)} shots.")
            except Exception as e:
                logger.error(f"Failed to parse edit file '{meta.filename}': {e}", exc_info=True)
                meta.format_type = f"parse_error ({type(e).__name__})"  # Update format type

        # --- Deduplicate shots ---
        unique_shots_map: Dict[tuple, EditShot] = {}
        duplicates_found = 0
        for shot in all_parsed_shots:
            # Ensure required fields exist for creating the identifier tuple
            if not shot.edit_media_path or not isinstance(shot.edit_media_range, opentime.TimeRange) or \
                    not isinstance(shot.edit_media_range.start_time, opentime.RationalTime) or \
                    not isinstance(shot.edit_media_range.duration, opentime.RationalTime):
                logger.warning(f"Skipping shot during deduplication due to missing data: {shot.clip_name}")
                continue
            try:
                tr = shot.edit_media_range
                identifier_tuple = (
                    shot.edit_media_path,
                    float(tr.start_time.value), float(tr.start_time.rate),
                    float(tr.duration.value), float(tr.duration.rate)
                )
                if identifier_tuple not in unique_shots_map:
                    unique_shots_map[identifier_tuple] = shot
                else:
                    duplicates_found += 1
            except Exception as ident_err:
                logger.warning(f"Could not create identifier tuple for shot: {ident_err}. Shot: {shot.clip_name}")

        # Update the project state with the unique shots
        self.state.edit_shots = list(unique_shots_map.values())

        if duplicates_found > 0:
            logger.info(f"Removed {duplicates_found} duplicate EditShots after parsing.")

        logger.info(
            f"Parsing phase complete. Parsed {successful_parses}/{len(self.state.edit_files)} files. Stored {len(self.state.edit_shots)} unique EditShots in state.")
        return successful_parses > 0

    def find_and_correct_sources(self) -> Tuple[int, int, int]:
        """
        Finds original sources for EditShots in the state, updates their status,
        and then runs the AAF correction process.

        Returns:
            Tuple[int, int, int]: Counts of (found, not_found, error) during the source finding phase.
                                  Note: AAF correction happens after this return value is determined.
        """
        if not self.state.edit_shots:
            logger.warning("No edit shots available in state for source lookup.")
            return 0, 0, 0

        finder = self._get_finder_instance()
        if not finder:
            # Mark all pending shots as error if finder is unavailable
            error_count = 0
            for shot in self.state.edit_shots:
                if shot.lookup_status == "pending":
                    shot.lookup_status = "error"
                    shot.edit_metadata["lookup_error"] = "SourceFinder unavailable (ffprobe/paths missing?)"
                    error_count += 1
            if error_count > 0:
                logger.error(f"Source lookup skipped for {error_count} pending shots: SourceFinder unavailable.")
            return 0, 0, error_count

        # --- Perform Source Lookup ---
        found_count = 0
        not_found_count = 0
        error_count = 0
        # Determine which shots need checking (reset status if not 'found')
        shots_to_check: List[EditShot] = []
        for shot in self.state.edit_shots:
            if shot.lookup_status != 'found':
                shot.lookup_status = 'pending'  # Reset
                shot.found_original_source = None
                shot.edit_metadata.pop("lookup_error", None)
                # Also clear AAF correction error flags if retrying
                shot.edit_metadata.pop("_aaf_correction_error", None)
                shots_to_check.append(shot)

        logger.info(f"Starting original source lookup for {len(shots_to_check)} shots...")
        for shot in shots_to_check:
            try:
                original_file = finder.find_source(shot)  # Uses cache internally
                if original_file:
                    shot.found_original_source = original_file
                    shot.lookup_status = "found"
                    found_count += 1
                    # The cache is linked, so self.state.original_sources_cache is updated automatically
                else:
                    shot.lookup_status = "not_found"
                    shot.edit_metadata["lookup_error"] = "No matching original source found in search paths."
                    not_found_count += 1
            except Exception as e:
                logger.error(f"Error looking up source for '{shot.clip_name or shot.edit_media_path}': {e}",
                             exc_info=True)
                shot.lookup_status = "error"
                shot.edit_metadata["lookup_error"] = f"Exception during lookup: {str(e)}"
                error_count += 1

        # --- Run AAF Correction ---
        logger.info("Running AAF source point correction process...")
        try:
            # Pass the list of shots from the current state
            corrected_aaf_count = edit_parser.correct_aaf_source_points(self.state.edit_shots)
            logger.info(f"AAF correction finished. Corrected {corrected_aaf_count} shots.")
        except Exception as corr_err:
            # Log the error, but don't halt the overall process
            logger.error(f"An error occurred during the AAF correction phase: {corr_err}", exc_info=True)

        # --- Final Logging ---
        # Log the final status counts after both lookup and correction attempt
        final_found = sum(1 for s in self.state.edit_shots if s.lookup_status == 'found')
        final_not_found = sum(1 for s in self.state.edit_shots if s.lookup_status == 'not_found')
        final_error = sum(1 for s in self.state.edit_shots if s.lookup_status == 'error')
        final_pending = sum(1 for s in self.state.edit_shots if s.lookup_status == 'pending')  # Should be 0

        logger.info(f"Source processing finished. "
                    f"Lookup attempted for {len(shots_to_check)} shots. "
                    f"Final Status -> Found: {final_found}, Not Found: {final_not_found}, "
                    f"Error: {final_error}, Pending: {final_pending}")

        # Return the counts from the *lookup* phase
        return found_count, not_found_count, error_count

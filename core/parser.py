# core/parser.py
"""
Parses edit files, extracting identifier, source point range (edit_media_range),
timeline position range (timeline_range), tape name, and metadata. Includes
post-processing step to correct relative AAF source points after original source
timecode is known. Handles identifier extraction more robustly, especially for AAF files.
"""

import logging
import os
from typing import List, Optional, Union, Dict, Any

import opentimelineio as otio
from opentimelineio import opentime
from opentimelineio import schema

# Importuj model EditShot z poprawną ścieżką względną
from .models import EditShot, MediaType

logger = logging.getLogger(__name__)


def get_rate(
        otio_obj: Union[schema.Clip, schema.Timeline, schema.Track, schema.ExternalReference, schema.MissingReference],
        default_rate: float = 25.0) -> float:
    """Safely attempts to get a valid frame rate from various OTIO objects."""
    rate = default_rate
    try:
        # Try common rate attributes first
        if hasattr(otio_obj, 'rate'):
            obj_rate = getattr(otio_obj, 'rate')
            # Handle RationalTime rate attribute (e.g., in some schema versions)
            if isinstance(obj_rate, opentime.RationalTime) and obj_rate.rate > 0:
                return float(obj_rate.rate)
            # Handle direct float/int rate attribute
            elif isinstance(obj_rate, (float, int)) and obj_rate > 0:
                return float(obj_rate)

        # Check common time range attributes for rate info
        for range_attr in ['source_range', 'available_range', 'duration', 'global_start_time']:
            if hasattr(otio_obj, range_attr):
                time_obj = getattr(otio_obj, range_attr)
                obj_rate_val = None
                if isinstance(time_obj, opentime.TimeRange):
                    # Prefer duration rate, fallback to start_time rate
                    if time_obj.duration and isinstance(time_obj.duration,
                                                        opentime.RationalTime) and time_obj.duration.rate > 0:
                        obj_rate_val = time_obj.duration.rate
                    elif time_obj.start_time and isinstance(time_obj.start_time,
                                                            opentime.RationalTime) and time_obj.start_time.rate > 0:
                        obj_rate_val = time_obj.start_time.rate
                elif isinstance(time_obj, opentime.RationalTime) and time_obj.rate > 0:
                    # Handle direct RationalTime attributes like global_start_time
                    obj_rate_val = time_obj.rate

                # If a valid rate was found in this attribute, return it
                if obj_rate_val:
                    return float(obj_rate_val)

    except Exception as e:
        # Log unexpected errors during rate detection, but don't crash
        logger.debug(f"Could not reliably determine rate for {type(otio_obj)}: {e}")

    # Final check and fallback to default rate
    final_rate = rate if isinstance(rate, (float, int)) and rate > 0 else default_rate
    logger.debug(f"Using rate {final_rate:.3f} for {type(otio_obj)}")
    return final_rate


def read_and_parse_edit_file(file_path: str) -> List[EditShot]:
    """Reads an edit file, extracting essential EditShot data, including tape name."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Edit file not found: {file_path}")

    logger.info(f"Attempting to read edit file: {file_path}")
    timeline: Optional[schema.Timeline] = None
    is_aaf = file_path.lower().endswith('.aaf')  # Check if it's AAF early

    try:
        # Read the file using OTIO
        result = otio.adapters.read_from_file(file_path)

        # Find the main timeline object
        if isinstance(result, schema.Timeline):
            timeline = result
        elif isinstance(result, schema.SerializableCollection):
            logger.warning(
                f"OTIO returned a Collection for '{os.path.basename(file_path)}'. Searching for main timeline.")
            # Find the first timeline in the collection
            timeline = next(result.find_children(kind=schema.Timeline), None)

        if not timeline:
            raise otio.exceptions.OTIOError("No valid timeline found in file.")

        logger.info(f"Successfully read OTIO timeline: '{timeline.name}'")

        # Determine sequence rate and start time
        sequence_rate = get_rate(timeline, default_rate=25.0)
        sequence_start_time = timeline.global_start_time

        if not sequence_start_time or not isinstance(sequence_start_time,
                                                     opentime.RationalTime) or sequence_start_time.rate <= 0:
            logger.warning(f"Could not determine valid sequence start time, assuming 0@{sequence_rate:.3f}fps start.")
            sequence_start_time = opentime.RationalTime(0, sequence_rate)
        elif sequence_start_time.rate != sequence_rate:
            logger.warning(
                f"Sequence start time rate ({sequence_start_time.rate}) differs from sequence rate ({sequence_rate}). Rescaling start time.")
            try:
                sequence_start_time = sequence_start_time.rescaled_to(sequence_rate)
            except Exception as e:
                logger.error(f"Failed to rescale sequence start time: {e}. Using 0 start.", exc_info=True)
                sequence_start_time = opentime.RationalTime(0, sequence_rate)

        # Log sequence info
        start_tc_str = "N/A"
        try:
            start_tc_str = opentime.to_timecode(sequence_start_time, sequence_rate)
        except Exception:
            pass  # Ignore formatting errors
        logger.info(
            f"Sequence Rate: {sequence_rate:.3f} fps, Sequence Start Time: {sequence_start_time} ({start_tc_str})")

    except Exception as e:
        logger.error(f"Error reading/parsing edit file '{file_path}': {e}", exc_info=True)
        raise  # Re-raise the exception after logging

    # --- Process Clips ---
    edit_shots: List[EditShot] = []
    clip_counter = 0
    skipped_counter = 0
    item_counter = 0

    try:
        for clip in timeline.find_clips():
            item_counter += 1
            # Ensure it's a standard Clip object
            if not isinstance(clip, schema.Clip):
                logger.debug(f"Skipping item #{item_counter}: Not an OTIO Clip object.")
                continue

            media_ref = clip.media_reference
            if not media_ref:
                logger.warning(f"Skipping clip #{item_counter} ('{clip.name or 'N/A'}'): No media reference found.")
                skipped_counter += 1
                continue

            # Validate source range (used portion of the media)
            source_point_range_otio = clip.source_range
            if not source_point_range_otio or \
                    not isinstance(source_point_range_otio.start_time, opentime.RationalTime) or \
                    not isinstance(source_point_range_otio.duration, opentime.RationalTime) or \
                    source_point_range_otio.duration.value <= 0 or \
                    source_point_range_otio.duration.rate <= 0:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name or 'N/A'}'): Invalid source_range: {source_point_range_otio}")
                skipped_counter += 1
                continue
            final_source_point_range = source_point_range_otio  # Keep the range as read

            # Calculate edit position (timeline range)
            edit_position_range: Optional[otio.opentime.TimeRange] = None
            try:
                # Get the clip's range relative to its parent (usually the track)
                relative_range = timeline.range_of_child(clip)
                if relative_range and \
                        isinstance(relative_range.start_time, opentime.RationalTime) and \
                        isinstance(relative_range.duration, opentime.RationalTime) and \
                        relative_range.duration.value > 0 and \
                        relative_range.start_time.rate > 0 and \
                        relative_range.duration.rate > 0:

                    # Rescale relative start and duration to sequence rate for calculations
                    edit_start_relative = relative_range.start_time.rescaled_to(sequence_rate)
                    edit_duration = relative_range.duration.rescaled_to(sequence_rate)

                    # Calculate absolute start time on the sequence
                    absolute_start_time = sequence_start_time + edit_start_relative
                    edit_position_range = opentime.TimeRange(start_time=absolute_start_time, duration=edit_duration)
                else:
                    logger.debug(f"Invalid relative range for clip '{clip.name}': {relative_range}")

            except Exception as range_err:
                logger.error(f"Error calculating edit position range for '{clip.name}': {range_err}", exc_info=False)

            # --- Determine Identifier (for finding the source file) ---
            identifier: Optional[str] = None
            clip_name_str = clip.name.strip() if clip.name else None

            # Priority 1: Look for common keys in metadata
            if media_ref.metadata:
                possible_id_keys = ["Source File", "Source Name", "file", "filename", "source_clip", "Offline File"]
                for key in possible_id_keys:
                    found_key = next((k for k in media_ref.metadata if k.lower() == key.lower()), None)
                    if found_key:
                        meta_val = str(media_ref.metadata[found_key]).strip()
                        if meta_val:
                            # Take basename if it looks like a path
                            id_candidate = os.path.basename(
                                meta_val) if '/' in meta_val or '\\' in meta_val else meta_val
                            identifier = id_candidate
                            logger.debug(f"Identifier found in metadata ('{found_key}'): {identifier}")
                            break  # Stop searching after finding one

            # Priority 2: For AAF, check specific AAF metadata fields if no identifier yet
            if not identifier and is_aaf and media_ref.metadata:
                aaf_meta = media_ref.metadata.get('AAF', {})
                aaf_name = aaf_meta.get('Name')  # Often contains the clip name
                if aaf_name and isinstance(aaf_name, str) and aaf_name.strip():
                    identifier = aaf_name.strip()
                    logger.debug(f"Identifier found in AAF metadata ('Name'): {identifier}")

            # Priority 3: Use clip name if it looks like a filename (has extension)
            if not identifier and clip_name_str and '.' in clip_name_str and not clip_name_str.startswith('.'):
                identifier = clip_name_str
                logger.debug(f"Identifier derived from clip name: {identifier}")

            # Priority 4: Use target URL from ExternalReference
            if not identifier and isinstance(media_ref, schema.ExternalReference) and media_ref.target_url:
                try:
                    # Attempt to convert URL back to a file path
                    url_path = otio.url_utils.url_to_filepath(media_ref.target_url)
                    basename = os.path.basename(url_path).strip()
                    if basename:
                        identifier = basename
                        logger.debug(f"Identifier derived from target_url: {identifier}")
                except Exception as url_err:
                    logger.debug(f"Could not parse target URL {media_ref.target_url} for identifier: {url_err}")

            # Priority 5: Use media reference name as last resort
            if not identifier and media_ref.name:
                ref_name = media_ref.name.strip()
                if ref_name:
                    identifier = ref_name
                    logger.debug(f"Identifier derived from media_ref.name: {identifier}")

            # If no identifier found after all attempts, skip the clip
            if not identifier:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip_name_str or '(No Clip Name)'}'): No usable identifier found for source lookup.")
                skipped_counter += 1
                continue

            # --- Determine Tape Name (Reel/Tape) ---
            resolved_tape_name: Optional[str] = None
            # Priority 1: Look for common tape/reel keys in metadata
            if media_ref and media_ref.metadata:
                possible_tape_keys = ["Tape Name", "Reel Name", "TapeID", "Reel", "reel", "reel id", "Tape"]
                for key in possible_tape_keys:
                    found_key = next((k for k in media_ref.metadata if k.lower() == key.lower()), None)
                    if found_key:
                        meta_val = str(media_ref.metadata[found_key]).strip()
                        if meta_val:
                            resolved_tape_name = meta_val
                            logger.debug(f"Tape name found in metadata ('{found_key}'): {resolved_tape_name}")
                            break  # Found one

            # Priority 2: Fallback to the identifier if no specific tape name found
            if not resolved_tape_name:
                resolved_tape_name = identifier  # Use the determined identifier as tape name fallback
                logger.debug(f"No specific tape name found, using identifier as fallback: {resolved_tape_name}")

            # --- Copy Metadata ---
            edit_metadata: Dict[str, Any] = {}
            if media_ref and media_ref.metadata:
                try:
                    # Copy metadata safely, converting complex types to string
                    for k, v in media_ref.metadata.items():
                        if isinstance(v, (str, int, float, bool, type(None))):
                            edit_metadata[k] = v
                        elif isinstance(v, (list, tuple)):
                            # Try to copy list items safely
                            try:
                                edit_metadata[k] = [
                                    item if isinstance(item, (str, int, float, bool, type(None))) else str(item)
                                    for item in v]
                            except Exception:
                                edit_metadata[k] = str(v)  # Fallback to string representation
                        else:
                            edit_metadata[k] = str(v)  # Convert other types to string
                except Exception as meta_copy_err:
                    logger.warning(f"Error copying metadata for '{clip.name}': {meta_copy_err}")
                    # Store error indicator in metadata itself
                    edit_metadata['_metadata_error'] = str(meta_copy_err)

            # Add flag for AAF correction if needed
            if is_aaf:
                edit_metadata['_needs_aaf_offset_correction'] = True

            # --- Create EditShot Object ---
            shot = EditShot(
                clip_name=clip.name if clip.name else None,
                edit_media_path=identifier,
                edit_media_range=final_source_point_range,
                timeline_range=edit_position_range,
                tape_name=resolved_tape_name,  # Assign the resolved tape name
                edit_metadata=edit_metadata,  # Assign the copied metadata
                lookup_status="pending"  # Initial status
            )
            edit_shots.append(shot)
            clip_counter += 1

    except Exception as e:
        # Catch errors during clip processing loop
        msg = f"Error processing clips in '{os.path.basename(file_path)}': {e}"
        logger.error(msg, exc_info=True)
        # Re-raise as a generic exception to signal failure
        raise Exception(msg) from e

    # Log summary after processing all clips
    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Created {clip_counter} valid EditShots (skipped {skipped_counter}).")
    return edit_shots


def correct_aaf_source_points(edit_shots: List[EditShot]) -> int:
    """
    Post-processes source point ranges for shots parsed from AAF files.
    Uses the start_timecode from the verified OriginalSourceFile.

    Works with all media types including sequences.
    """
    corrected_count = 0
    logger.info("Attempting to correct AAF source point offsets...")

    for shot in edit_shots:
        # Check if correction is needed (flag set by parser) and source was found
        if shot.edit_metadata.get('_needs_aaf_offset_correction', False):
            logger.debug(f"Checking shot '{shot.clip_name or shot.edit_media_path}' for AAF correction.")

            if shot.lookup_status != 'found' or not shot.found_original_source:
                logger.warning(
                    f"Cannot correct AAF: Original source not found or not verified for shot '{shot.clip_name or shot.edit_media_path}'.")
                continue  # Skip correction if source isn't ready

            source_info = shot.found_original_source
            source_in = source_info.start_timecode  # Get start TC from verified source
            source_rate = source_info.frame_rate  # Get rate from verified source

            # For image sequences, handle potentially different rates
            if source_info.media_type == MediaType.IMAGE_SEQUENCE:
                # For sequences, we need to ensure we have valid timing information
                if not source_rate or source_rate <= 0:
                    logger.warning(f"Image sequence '{shot.clip_name}' has invalid frame rate. Using default 25 fps.")
                    source_rate = 25.0  # Default for sequences with no rate information

                # Ensure we have a valid start timecode for the sequence
                if not source_in or not isinstance(source_in, opentime.RationalTime):
                    logger.debug(f"Setting default start timecode for image sequence '{shot.clip_name}'")
                    source_in = opentime.RationalTime(0, source_rate)

            # Validate required data from verified source
            if not isinstance(source_in, opentime.RationalTime):
                logger.error(
                    f"Cannot correct AAF: Invalid or missing start_timecode ({source_in}) in verified OriginalSourceFile for '{shot.clip_name or shot.edit_media_path}'.")
                continue
            if not source_rate or source_rate <= 0:
                logger.error(
                    f"Cannot correct AAF: Invalid frame_rate ({source_rate}) in verified OriginalSourceFile for '{shot.clip_name or shot.edit_media_path}'.")
                continue

            # Get the offset range read from the AAF
            offset_range = shot.edit_media_range
            if not isinstance(offset_range, opentime.TimeRange) or \
                    not isinstance(offset_range.start_time, opentime.RationalTime) or \
                    not isinstance(offset_range.duration, opentime.RationalTime):
                logger.error(
                    f"Cannot correct AAF: Invalid edit_media_range (offset range) for '{shot.clip_name or shot.edit_media_path}': {offset_range}")
                continue

            offset_start = offset_range.start_time
            offset_duration = offset_range.duration

            try:
                # Ensure the offset times use the same rate as the verified source
                target_rate = source_rate
                if offset_start.rate != target_rate:
                    logger.debug(f"Rescaling AAF offset start {offset_start} to target rate {target_rate}")
                    offset_start = offset_start.rescaled_to(target_rate)

                if offset_duration.rate != target_rate:
                    logger.debug(f"Rescaling AAF offset duration {offset_duration} to target rate {target_rate}")
                    offset_duration = offset_duration.rescaled_to(target_rate)

                # Calculate the absolute start time by adding the offset to the source's start TC
                absolute_start = source_in + offset_start
                corrected_range = opentime.TimeRange(
                    start_time=absolute_start,
                    duration=offset_duration  # Duration remains the same
                )

                # Update the shot's edit_media_range with the corrected absolute range
                logger.debug(f"Corrected AAF range for '{shot.clip_name or shot.edit_media_path}': {corrected_range}")
                shot.edit_media_range = corrected_range
                shot.edit_metadata.pop('_needs_aaf_offset_correction', None)  # Remove flag
                corrected_count += 1

            except Exception as e:
                # Log error during calculation and mark the shot as error
                logger.error(
                    f"Error during AAF correction calculation for '{shot.clip_name or shot.edit_media_path}': {e}",
                    exc_info=True)
                shot.lookup_status = 'error'  # Mark as error due to correction failure
                shot.edit_metadata['_aaf_correction_error'] = str(e)

    # Log summary of corrections
    if corrected_count > 0:
        logger.info(f"Successfully corrected source point ranges for {corrected_count} AAF shots.")
    else:
        logger.info("No AAF shots required correction or data was missing for correction.")

    return corrected_count

# core/parser.py
"""
Parses edit files, extracting identifier, source point range (edit_media_range),
timeline position range (timeline_range), and metadata. Includes post-processing
step to correct relative AAF source points after original source timecode is known.
Handles identifier extraction more robustly, especially for AAF files.
"""
import logging
import os
from typing import List, Optional, Union

import opentimelineio as otio
from opentimelineio import opentime
from opentimelineio import schema

# Importuj model, aby używać EditShot
from .models import EditShot

logger = logging.getLogger(__name__)


# Helper function to get rate safely (bez zmian)
def get_rate(
        otio_obj: Union[schema.Clip, schema.Timeline, schema.Track, schema.ExternalReference, schema.MissingReference],
        default_rate: float = 25.0) -> float:
    """Safely attempts to get a valid frame rate from various OTIO objects."""
    rate = default_rate
    try:
        if hasattr(otio_obj, 'rate'):
            obj_rate = getattr(otio_obj, 'rate')
            if isinstance(obj_rate, opentime.RationalTime) and obj_rate.rate > 0:
                return float(obj_rate.rate)
            elif isinstance(obj_rate, (float, int)) and obj_rate > 0:
                return float(obj_rate)

        for range_attr in ['source_range', 'available_range', 'duration', 'global_start_time']:
            if hasattr(otio_obj, range_attr):
                time_obj = getattr(otio_obj, range_attr)
                obj_rate_val = None
                if isinstance(time_obj, opentime.TimeRange):
                    if time_obj.duration and isinstance(time_obj.duration,
                                                        opentime.RationalTime) and time_obj.duration.rate > 0:
                        obj_rate_val = time_obj.duration.rate
                    elif time_obj.start_time and isinstance(time_obj.start_time,
                                                            opentime.RationalTime) and time_obj.start_time.rate > 0:
                        obj_rate_val = time_obj.start_time.rate
                elif isinstance(time_obj, opentime.RationalTime) and time_obj.rate > 0:
                    obj_rate_val = time_obj.rate
                if obj_rate_val:
                    return float(obj_rate_val)
    except Exception as e:
        logger.debug(f"Could not determine rate for {type(otio_obj)}: {e}")
    final_rate = rate if isinstance(rate, (float, int)) and rate > 0 else default_rate
    logger.debug(f"Using rate {final_rate} for {type(otio_obj)}")
    return final_rate


def read_and_parse_edit_file(file_path: str) -> List[EditShot]:
    """
    Reads an edit file, extracting essential EditShot data.
    Marks AAF shots for later source point correction.
    Includes improved identifier extraction for AAF.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Edit file not found: {file_path}")

    logger.info(f"Attempting to read edit file: {file_path}")
    timeline: Optional[schema.Timeline] = None
    is_aaf = file_path.lower().endswith('.aaf')

    try:
        result = otio.adapters.read_from_file(file_path)
        if isinstance(result, schema.Timeline):
            timeline = result
        elif isinstance(result, schema.SerializableCollection):
            logger.warning(
                f"OTIO returned a Collection for '{os.path.basename(file_path)}'. Searching for main timeline.")
            timeline = next(result.find_children(kind=schema.Timeline), None)
        if not timeline:
            raise otio.exceptions.OTIOError("No valid timeline found in file.")

        logger.info(f"Successfully read OTIO timeline: '{timeline.name}'")

        sequence_rate = get_rate(timeline, default_rate=25.0)
        sequence_start_time = timeline.global_start_time
        if not sequence_start_time or not isinstance(sequence_start_time,
                                                     opentime.RationalTime) or sequence_start_time.rate <= 0:
            logger.warning(f"Assuming 0@{sequence_rate}fps start time for sequence.")
            sequence_start_time = opentime.RationalTime(0, sequence_rate)
        elif sequence_start_time.rate != sequence_rate:
            logger.warning(
                f"Rescaling timeline start time rate {sequence_start_time.rate} to sequence rate {sequence_rate}.")
            try:
                sequence_start_time = sequence_start_time.rescaled_to(sequence_rate)
            except Exception as e:
                logger.error(f"Failed rescale: {e}. Using 0 start."); sequence_start_time = opentime.RationalTime(0,
                                                                                                                  sequence_rate)
        start_tc_str = "N/A"
        try:
            start_tc_str = opentime.to_timecode(sequence_start_time, sequence_rate)
        except:
            pass
        logger.info(f"Sequence Rate: {sequence_rate}, Sequence Start Time: {sequence_start_time} ({start_tc_str})")

    except Exception as e:
        logger.error(f"Error reading/parsing edit file '{file_path}': {e}", exc_info=True)
        raise

    edit_shots: List[EditShot] = []
    clip_counter = 0
    skipped_counter = 0
    item_counter = 0

    try:
        for clip in timeline.find_clips():
            item_counter += 1
            if not isinstance(clip, schema.Clip):
                logger.debug(f"Skipping item #{item_counter}: Not an OTIO Clip.")
                continue

            media_ref = clip.media_reference
            if not media_ref:
                logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): No media reference.")
                skipped_counter += 1
                continue

            # --- 1. Source Point Range (edit_media_range) ---
            source_point_range_otio = clip.source_range
            if not source_point_range_otio or \
                    not isinstance(source_point_range_otio.start_time, opentime.RationalTime) or \
                    not isinstance(source_point_range_otio.duration, opentime.RationalTime) or \
                    source_point_range_otio.duration.value <= 0 or \
                    source_point_range_otio.duration.rate <= 0:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name}'): Invalid source_range: {source_point_range_otio}")
                skipped_counter += 1
                continue
            final_source_point_range = source_point_range_otio
            logger.debug(f"  Clip #{item_counter} ('{clip.name}'): Storing OTIO SrcRange = {final_source_point_range}")

            # --- 2. Edit Position Range (timeline_range) ---
            edit_position_range: Optional[otio.opentime.TimeRange] = None
            try:
                relative_range = timeline.range_of_child(clip)
                if relative_range and \
                        isinstance(relative_range.start_time, opentime.RationalTime) and \
                        isinstance(relative_range.duration, opentime.RationalTime) and \
                        relative_range.duration.value > 0 and \
                        relative_range.start_time.rate > 0 and \
                        relative_range.duration.rate > 0:
                    edit_start_relative = relative_range.start_time.rescaled_to(
                        sequence_rate) if relative_range.start_time.rate != sequence_rate else relative_range.start_time
                    edit_duration = relative_range.duration.rescaled_to(
                        sequence_rate) if relative_range.duration.rate != sequence_rate else relative_range.duration
                    absolute_start_time = sequence_start_time + edit_start_relative
                    edit_position_range = opentime.TimeRange(start_time=absolute_start_time, duration=edit_duration)
                    logger.debug(f"    Absolute Edit Range: {edit_position_range}")
                else:
                    logger.warning(f"  Invalid relative_range for clip #{item_counter} ('{clip.name}').")
            except Exception as range_err:
                logger.error(f"  Error calculating edit position range for '{clip.name}': {range_err}", exc_info=False)

            # --- 3. Get Identifier (Improved Logic) ---
            identifier = None
            clip_name_str = clip.name.strip() if clip.name else None
            logger.debug(f"    Identifier search for clip '{clip_name_str or '(No Clip Name)'}':")

            # A. Check standard metadata keys first
            if media_ref.metadata:
                possible_keys = ["Source File", "Source Name", "Tape Name", "Reel Name", "TapeID", "Reel", "reel",
                                 "source_clip", "reel id"]
                for key in possible_keys:
                    found_key = next((k for k in media_ref.metadata if k.lower() == key.lower()), None)
                    if found_key:
                        meta_val = str(media_ref.metadata[found_key]).strip()
                        if meta_val:
                            id_candidate = os.path.basename(
                                meta_val) if '/' in meta_val or '\\' in meta_val else meta_val
                            identifier = id_candidate
                            logger.debug(f"      Found ID via standard metadata key '{found_key}': '{identifier}'")
                            break  # Use first found standard key
            # *** B. Check AAF-specific metadata name ***
            if not identifier and is_aaf and media_ref.metadata:
                aaf_meta = media_ref.metadata.get('AAF', {})
                aaf_name = aaf_meta.get('Name')  # Get the AAF Mob Name
                if aaf_name and isinstance(aaf_name, str) and aaf_name.strip():
                    identifier = aaf_name.strip()
                    logger.debug(f"      Found ID via AAF metadata 'Name': '{identifier}'")

            # C. Fallback to clip name (if it looks like a filename)
            if not identifier and clip_name_str:
                if '.' in clip_name_str and not clip_name_str.startswith('.'):
                    identifier = clip_name_str
                    logger.debug(f"      Using clip name as ID (fallback): '{identifier}'")

            # D. Fallback to target URL basename
            if not identifier and isinstance(media_ref, schema.ExternalReference) and media_ref.target_url:
                try:
                    url_path = otio.url_utils.url_to_filepath(media_ref.target_url)
                    basename = os.path.basename(url_path).strip()
                    if basename:
                        identifier = basename
                        logger.debug(f"      Using target URL basename as ID (fallback): '{identifier}'")
                except Exception as url_err:
                    logger.debug(f"      Could not parse target URL {media_ref.target_url}: {url_err}")

            # E. Fallback to media reference name
            if not identifier and media_ref.name:
                ref_name = media_ref.name.strip()
                if ref_name:
                    identifier = ref_name
                    logger.debug(f"      Using media reference name as ID (last fallback): '{identifier}'")

            # F. Skip if still no identifier
            if not identifier:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip_name_str or '(No Clip Name)'}'): No usable identifier found after checking all sources.")
                skipped_counter += 1
                continue
            # --- End Identifier Logic ---

            # --- 4. Extract Metadata (Safely) ---
            edit_metadata = {}
            if media_ref.metadata:
                try:
                    for k, v in media_ref.metadata.items():
                        if isinstance(v, (str, int, float, bool, type(None))):
                            edit_metadata[k] = v
                        elif isinstance(v, (list, tuple)):
                            try:
                                edit_metadata[k] = [
                                    item if isinstance(item, (str, int, float, bool, type(None))) else str(item) for
                                    item in v]
                            except:
                                edit_metadata[k] = str(v)
                        else:
                            edit_metadata[k] = str(v)
                except Exception as meta_copy_err:
                    logger.warning(f"    Error copying metadata for '{clip.name}': {meta_copy_err}")
                    edit_metadata['_metadata_error'] = str(meta_copy_err)

            # Add AAF Correction Flag
            if is_aaf:
                edit_metadata['_needs_aaf_offset_correction'] = True
                logger.debug(f"    Marked clip for AAF offset correction.")

            # --- 5. Create EditShot ---
            shot = EditShot(
                clip_name=clip.name if clip.name else None,
                edit_media_path=identifier,
                edit_media_range=final_source_point_range,
                timeline_range=edit_position_range,
                edit_metadata=edit_metadata,
                lookup_status="pending"
            )
            edit_shots.append(shot)
            clip_counter += 1
            logger.debug(f"Parsed EditShot #{clip_counter}: Clip='{shot.clip_name or 'Unnamed'}', ID='{identifier}'")

    except Exception as e:
        msg = f"Error processing clips in '{os.path.basename(file_path)}': {e}"
        logger.error(msg, exc_info=True)
        raise Exception(msg) from e

    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Created {clip_counter} valid EditShots (skipped {skipped_counter}).")
    return edit_shots


# --- correct_aaf_source_points (bez zmian) ---
def correct_aaf_source_points(edit_shots: List[EditShot]) -> int:
    """
    Post-processes source point ranges for shots parsed from AAF files.
    Uses the absolute start timecode from the verified original source file
    to convert the relative offset stored during parsing into an absolute time.

    This function should be called *after* find_original_sources() has populated
    the `found_original_source.start_timecode` values.

    Args:
        edit_shots: List of EditShots (potentially mixed formats).

    Returns:
        Number of AAF shots successfully corrected.
    """
    corrected_count = 0
    logger.info("Attempting to correct AAF source point offsets...")

    for shot in edit_shots:
        if shot.edit_metadata.get('_needs_aaf_offset_correction', False):
            logger.debug(f"Checking shot '{shot.clip_name or shot.edit_media_path}' for AAF correction.")

            if shot.lookup_status != 'found' or not shot.found_original_source:
                logger.warning(f"  Cannot correct AAF: Original source not found for shot '{shot.clip_name}'.")
                continue

            source_in = shot.found_original_source.start_timecode
            if not isinstance(source_in, opentime.RationalTime):
                logger.error(
                    f"  Cannot correct AAF: Invalid or missing start_timecode ({source_in}) in verified OriginalSourceFile for '{shot.clip_name}'.")
                continue

            offset_range = shot.edit_media_range
            if not isinstance(offset_range, opentime.TimeRange) or \
                    not isinstance(offset_range.start_time, opentime.RationalTime) or \
                    not isinstance(offset_range.duration, opentime.RationalTime):
                logger.error(
                    f"  Cannot correct AAF: Invalid edit_media_range (offset range) for '{shot.clip_name}': {offset_range}")
                continue

            offset_start = offset_range.start_time
            offset_duration = offset_range.duration

            logger.debug(
                f"  Found AAF shot: '{shot.clip_name}'. Source IN: {source_in} (Rate: {source_in.rate}). Offset Start: {offset_start} (Rate: {offset_start.rate}).")

            try:
                if source_in.rate <= 0:
                    logger.error(f"  Cannot correct AAF: Source IN rate is invalid ({source_in.rate}).")
                    continue

                target_rate = source_in.rate
                if offset_start.rate != target_rate:
                    logger.debug(f"    Rescaling offset start rate {offset_start.rate} to source rate {target_rate}.")
                    offset_start = offset_start.rescaled_to(target_rate)

                if offset_duration.rate != target_rate:
                    logger.debug(
                        f"    Rescaling offset duration rate {offset_duration.rate} to source rate {target_rate}.")
                    offset_duration = offset_duration.rescaled_to(target_rate)

                absolute_start = source_in + offset_start
                logger.debug(f"    Calculated Absolute Start: {absolute_start}")

                corrected_range = opentime.TimeRange(
                    start_time=absolute_start,
                    duration=offset_duration
                )
                logger.info(
                    f"  Corrected AAF Src Pt Range for '{shot.clip_name or shot.edit_media_path}': {corrected_range}")

                shot.edit_media_range = corrected_range
                shot.edit_metadata.pop('_needs_aaf_offset_correction', None)
                logger.debug("    Removed AAF correction flag.")
                corrected_count += 1

            except Exception as e:
                logger.error(f"  Error during AAF correction calculation for '{shot.clip_name}': {e}", exc_info=True)
                shot.lookup_status = 'error'
                shot.edit_metadata['_aaf_correction_error'] = str(e)

    if corrected_count > 0:
        logger.info(f"Successfully corrected source point ranges for {corrected_count} AAF shots.")
    else:
        logger.info("No AAF shots required correction or data was missing.")

    return corrected_count

# core/parser.py
"""
Parses edit files, extracting identifier, source point range (edit_media_range),
timeline position range (timeline_range), and metadata. Aims to correctly
interpret ranges relative to file start vs sequence start.
"""
import logging
import os
from typing import List, Optional, Union

import opentimelineio
import opentimelineio as otio
from opentimelineio import opentime
from opentimelineio import schema  # Import schema to reference its classes

from .models import EditShot

logger = logging.getLogger(__name__)


# Helper function to get rate safely
def get_rate(
        otio_obj: Union[schema.Clip, schema.Timeline, schema.Track, schema.ExternalReference, schema.MissingReference],
        default_rate: float = 25.0) -> float:
    """Safely attempts to get a valid frame rate from various OTIO objects."""
    rate = default_rate
    try:
        # Check for rate attribute (might be float or RationalTime)
        if hasattr(otio_obj, 'rate'):
            obj_rate = getattr(otio_obj, 'rate')
            if isinstance(obj_rate, opentime.RationalTime) and obj_rate.rate > 0:
                return obj_rate.rate
            elif isinstance(obj_rate, (float, int)) and obj_rate > 0:
                return float(obj_rate)

        # Check common time range attributes
        for range_attr in ['source_range', 'available_range', 'duration', 'global_start_time']:
            if hasattr(otio_obj, range_attr):
                time_obj = getattr(otio_obj, range_attr)
                # Check for duration rate first in TimeRange
                if isinstance(time_obj, opentime.TimeRange) and time_obj.duration and time_obj.duration.rate > 0:
                    return time_obj.duration.rate
                # Then check start_time rate in TimeRange
                elif isinstance(time_obj, opentime.TimeRange) and time_obj.start_time and time_obj.start_time.rate > 0:
                    return time_obj.start_time.rate
                # Then check rate if it's a RationalTime directly
                elif isinstance(time_obj, opentime.RationalTime) and time_obj.rate > 0:
                    return time_obj.rate
        # Add more specific checks if needed for certain object types

    except Exception as e:
        logger.debug(f"Could not determine rate for {type(otio_obj)}, using default {default_rate}. Error: {e}")
    # Return rate only if valid, otherwise default
    rate_val = rate if isinstance(rate, (float, int)) and rate > 0 else default_rate
    logger.debug(f"Determined rate for {type(otio_obj)}: {rate_val}")
    return rate_val


def read_and_parse_edit_file(file_path: str) -> List[EditShot]:
    """
    Reads an edit file, extracting essential EditShot data.
    """
    # --- File Reading and Timeline Detection ---
    if not os.path.exists(file_path): raise FileNotFoundError(f"Edit file not found: {file_path}")
    logger.info(f"Attempting to read edit file: {file_path}")
    timeline: Optional[schema.Timeline] = None
    try:
        result = otio.adapters.read_from_file(file_path)
        if isinstance(result, schema.Timeline):
            timeline = result
        elif isinstance(result, schema.SerializableCollection):
            logger.warning(
                f"OTIO returned a Collection for '{os.path.basename(file_path)}'. Searching for main timeline.")
            timeline = next(result.find_children(kind=schema.Timeline), None)
        if not timeline: raise otio.exceptions.OTIOError("No valid timeline found in file.")
        logger.info(f"Successfully read OTIO timeline: '{timeline.name}'")
        # --- Get Sequence Rate and Start TC ---
        sequence_rate = get_rate(timeline, default_rate=25.0)
        # global_start_time SHOULD represent the actual starting timecode of the sequence
        sequence_start_time = timeline.global_start_time
        if not sequence_start_time or sequence_start_time.rate <= 0:
            logger.warning(f"Could not determine valid global_start_time from timeline. Assuming 0@{sequence_rate}fps.")
            sequence_start_time = opentime.RationalTime(0, sequence_rate)
        else:
            # Ensure sequence_start_time uses the determined sequence_rate if they differ
            if sequence_start_time.rate != sequence_rate:
                logger.warning(
                    f"Timeline global_start_time rate ({sequence_start_time.rate}) differs from determined sequence rate ({sequence_rate}). Rescaling global_start_time.")
                try:
                    sequence_start_time = sequence_start_time.rescaled_to(sequence_rate)
                except Exception as rescale_err:
                    logger.error(f"Failed to rescale global_start_time: {rescale_err}. Assuming 0 start time.")
                    sequence_start_time = opentime.RationalTime(0, sequence_rate)

        logger.info(
            f"Sequence Rate: {sequence_rate}, Sequence Start Time: {sequence_start_time} ({opentime.to_timecode(sequence_start_time, sequence_rate)})")

    except Exception as e:
        logger.error(f"Error reading/parsing edit file '{file_path}': {e}", exc_info=True)
        raise  # Re-raise original error type if possible

    # --- Parsing the OTIO timeline into EditShot objects ---
    edit_shots: List[EditShot] = []
    clip_counter = 0
    skipped_counter = 0
    item_counter = 0

    try:
        for clip in timeline.find_clips():
            item_counter += 1
            if not isinstance(clip, schema.Clip): continue
            media_ref = clip.media_reference
            if not media_ref: continue

            # --- Get Source Point Range (Essential) ---
            # This range is relative to the start of the media reference file
            source_point_range = clip.source_range
            if not source_point_range or \
                    not isinstance(source_point_range.start_time, opentime.RationalTime) or \
                    not isinstance(source_point_range.duration, opentime.RationalTime) or \
                    source_point_range.duration.value <= 0 or \
                    source_point_range.duration.rate <= 0:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name}'): Invalid/missing clip.source_range: {source_point_range}")
                skipped_counter += 1;
                continue
            source_point_rate = source_point_range.duration.rate
            logger.debug(
                f"  Clip #{item_counter} ('{clip.name}'): Source Point Range = {source_point_range} (Rate: {source_point_rate})")

            # --- Get Edit Position Range (Absolute on Timeline) ---
            # This range represents the clip's position on the sequence timeline
            edit_position_range: Optional[opentimelineio.opentime.TimeRange] = None
            try:
                # Get the range of the clip within the timeline's time space
                # This SHOULD return an absolute range including timeline.global_start_time
                parent_range = timeline.range_of_child(clip)
                logger.debug(f"  Raw parent_range from range_of_child(): {parent_range}")

                # Validate the received range
                if parent_range and \
                        isinstance(parent_range.start_time, opentime.RationalTime) and \
                        isinstance(parent_range.duration, opentime.RationalTime) and \
                        parent_range.duration.value > 0 and \
                        parent_range.start_time.rate > 0 and \
                        parent_range.duration.rate > 0:

                    # Ensure the range uses the main sequence rate
                    if parent_range.start_time.rate != sequence_rate:
                        logger.debug(
                            f"  Rescaling edit position range from {parent_range.start_time.rate} to {sequence_rate}")
                        rescaled_start = parent_range.start_time.rescaled_to(sequence_rate)
                        rescaled_duration = parent_range.duration.rescaled_to(sequence_rate)
                        edit_position_range = opentime.TimeRange(start_time=rescaled_start, duration=rescaled_duration)
                    else:
                        edit_position_range = parent_range  # Use directly if rates match
                else:
                    logger.warning(
                        f"  Invalid or zero duration parent_range obtained for clip #{item_counter} ('{clip.name}').")

            except Exception as range_err:
                logger.error(
                    f"  Error calculating edit position range for clip #{item_counter} ('{clip.name}'): {range_err}",
                    exc_info=False)
            logger.debug(
                f"  Clip #{item_counter} ('{clip.name}'): Final Edit Position Range = {edit_position_range} (Target Rate: {sequence_rate})")
            # --- End Edit Position Range ---

            # --- Get Identifier ---
            identifier = None;
            clip_name_str = clip.name.strip() if clip.name else None
            if media_ref.metadata:  # Try metadata
                for key in ["Source File", "Source Name"]:
                    found_key = next((k for k in media_ref.metadata if k.lower() == key.lower()), None)
                    if found_key: meta_val = str(
                        media_ref.metadata[found_key]).strip(); identifier = meta_val if meta_val else identifier; break
            if not identifier and clip_name_str: identifier = clip_name_str  # Try clip name
            if not identifier and isinstance(media_ref,
                                             schema.ExternalReference) and media_ref.target_url:  # Try URL basename
                try:
                    identifier = os.path.basename(
                        otio.url_utils.url_to_filepath(media_ref.target_url)).strip() or identifier
                except:
                    pass
            if not identifier and media_ref.name: identifier = media_ref.name.strip() or identifier  # Try ref name
            if not identifier: logger.warning(
                f"Skipping clip #{item_counter} ('{clip.name}'): No identifier found."); skipped_counter += 1; continue
            # --- End Identifier ---

            # --- Extract Metadata (Safely) ---
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
                    edit_metadata['_metadata_error'] = str(meta_copy_err)
            # --- End Metadata ---

            # --- Create EditShot ---
            shot = EditShot(
                clip_name=clip.name if clip.name else None,
                edit_media_path=identifier,  # Stores the identifier
                edit_media_range=source_point_range,  # Stores the Source Point Range (IN/OUT within source/proxy)
                timeline_range=edit_position_range,  # Stores the Edit Position Range (Absolute IN/OUT on sequence)
                edit_metadata=edit_metadata,
                lookup_status="pending"
            )
            edit_shots.append(shot)
            clip_counter += 1
            logger.debug(
                f"Parsed EditShot #{clip_counter}: Clip='{shot.clip_name or 'Unnamed'}', ID='{identifier}', SourcePointRange={source_point_range}, EditPosRange={edit_position_range}")

    except Exception as e:
        msg = f"Error processing clips in '{os.path.basename(file_path)}': {e}";
        logger.error(msg, exc_info=True);
        raise Exception(msg) from e

    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Created {clip_counter} valid EditShots (skipped {skipped_counter}).")
    return edit_shots

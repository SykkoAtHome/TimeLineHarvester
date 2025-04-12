"""
Parses edit files, extracting identifier, source point range (edit_media_range),
timeline position range (timeline_range), and metadata. Correctly handles
different file formats and their timing reference systems.
"""
import logging
import os
from typing import List, Optional, Union

import opentimelineio as otio
from opentimelineio import opentime
from opentimelineio import schema

from .models import EditShot

logger = logging.getLogger(__name__)


def get_rate(
        otio_obj: Union[schema.Clip, schema.Timeline, schema.Track, schema.ExternalReference, schema.MissingReference],
        default_rate: float = 25.0) -> float:
    """Safely attempts to get a valid frame rate from various OTIO objects."""
    rate = default_rate
    try:
        if hasattr(otio_obj, 'rate'):
            obj_rate = getattr(otio_obj, 'rate')
            if isinstance(obj_rate, opentime.RationalTime) and obj_rate.rate > 0:
                return obj_rate.rate
            elif isinstance(obj_rate, (float, int)) and obj_rate > 0:
                return float(obj_rate)

        for range_attr in ['source_range', 'available_range', 'duration', 'global_start_time']:
            if hasattr(otio_obj, range_attr):
                time_obj = getattr(otio_obj, range_attr)
                if isinstance(time_obj, opentime.TimeRange):
                    if time_obj.duration and time_obj.duration.rate > 0:
                        return time_obj.duration.rate
                    elif time_obj.start_time and time_obj.start_time.rate > 0:
                        return time_obj.start_time.rate
                elif isinstance(time_obj, opentime.RationalTime) and time_obj.rate > 0:
                    return time_obj.rate

    except Exception as e:
        logger.debug(f"Could not determine rate for {type(otio_obj)}: {e}")

    final_rate = rate if isinstance(rate, (float, int)) and rate > 0 else default_rate
    logger.debug(f"Using rate {final_rate} for {type(otio_obj)}")
    return final_rate


def read_and_parse_edit_file(file_path: str) -> List[EditShot]:
    """
    Reads an edit file, extracting essential EditShot data.
    Handles special timing for AAF files where source points are relative offsets.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Edit file not found: {file_path}")

    logger.info(f"Attempting to read edit file: {file_path}")
    timeline: Optional[schema.Timeline] = None

    # Detect if file is AAF to apply special processing
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

        # Get Sequence Rate and Start TC
        sequence_rate = get_rate(timeline, default_rate=25.0)
        sequence_start_time = timeline.global_start_time

        if not sequence_start_time or not isinstance(sequence_start_time,
                                                     opentime.RationalTime) or sequence_start_time.rate <= 0:
            logger.warning(f"Could not determine valid global_start_time from timeline. Assuming 0@{sequence_rate}fps.")
            sequence_start_time = opentime.RationalTime(0, sequence_rate)
        else:
            # Ensure sequence_start_time uses the determined sequence_rate
            if sequence_start_time.rate != sequence_rate:
                logger.warning(f"Timeline global_start_time rate mismatch. Rescaling.")
                try:
                    sequence_start_time = sequence_start_time.rescaled_to(sequence_rate)
                except Exception as rescale_err:
                    logger.error(f"Failed to rescale global_start_time: {rescale_err}. Assuming 0 start time.")
                    sequence_start_time = opentime.RationalTime(0, sequence_rate)

        # Format for logging
        start_tc_str = "N/A"
        try:
            start_tc_str = opentime.to_timecode(sequence_start_time, sequence_rate)
        except:
            pass

        logger.info(f"Sequence Rate: {sequence_rate}, Sequence Start Time: {sequence_start_time} ({start_tc_str})")

    except Exception as e:
        logger.error(f"Error reading/parsing edit file '{file_path}': {e}", exc_info=True)
        raise

    # Parsing the OTIO timeline into EditShot objects
    edit_shots: List[EditShot] = []
    clip_counter = 0
    skipped_counter = 0
    item_counter = 0

    try:
        for clip in timeline.find_clips():
            item_counter += 1
            if not isinstance(clip, schema.Clip):
                continue

            media_ref = clip.media_reference
            if not media_ref:
                continue

            # Get Source Point Range (Essential)
            source_point_range = clip.source_range

            if not source_point_range or \
                    not isinstance(source_point_range.start_time, opentime.RationalTime) or \
                    not isinstance(source_point_range.duration, opentime.RationalTime) or \
                    source_point_range.duration.value <= 0 or \
                    source_point_range.duration.rate <= 0:
                logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): Invalid source_range.")
                skipped_counter += 1
                continue

            # Store the rate associated with the source point range
            source_point_rate = source_point_range.duration.rate

            # Important: For AAF files, set a flag to indicate post-processing needed
            # source_point_range from AAF is an offset, not absolute position
            needs_aaf_offset_correction = is_aaf

            # Get Edit Position Range (Absolute on Timeline)
            edit_position_range: Optional[otio.opentime.TimeRange] = None
            try:
                relative_range = timeline.range_of_child(clip)

                if relative_range and \
                        isinstance(relative_range.start_time, opentime.RationalTime) and \
                        isinstance(relative_range.duration, opentime.RationalTime) and \
                        relative_range.duration.value > 0 and \
                        relative_range.start_time.rate > 0 and \
                        relative_range.duration.rate > 0:

                    # Rescale components to sequence rate if necessary
                    edit_start_relative = relative_range.start_time
                    edit_duration = relative_range.duration

                    if edit_start_relative.rate != sequence_rate:
                        edit_start_relative = edit_start_relative.rescaled_to(sequence_rate)
                    if edit_duration.rate != sequence_rate:
                        edit_duration = edit_duration.rescaled_to(sequence_rate)

                    # Calculate ABSOLUTE start time by adding sequence start time
                    absolute_start_time = sequence_start_time + edit_start_relative
                    edit_position_range = opentime.TimeRange(start_time=absolute_start_time, duration=edit_duration)

                else:
                    logger.warning(f"Invalid relative_range for clip #{item_counter} ('{clip.name}').")

            except Exception as range_err:
                logger.error(f"Error calculating edit position range: {range_err}", exc_info=False)

            # Get Identifier
            identifier = None
            clip_name_str = clip.name.strip() if clip.name else None

            if media_ref.metadata:  # Try metadata
                for key in ["Source File", "Source Name"]:
                    found_key = next((k for k in media_ref.metadata if k.lower() == key.lower()), None)
                    if found_key:
                        meta_val = str(media_ref.metadata[found_key]).strip()
                        identifier = meta_val if meta_val else identifier
                        break

            if not identifier and clip_name_str:
                identifier = clip_name_str  # Try clip name

            if not identifier and isinstance(media_ref, schema.ExternalReference) and media_ref.target_url:
                try:
                    identifier = os.path.basename(
                        otio.url_utils.url_to_filepath(media_ref.target_url)).strip() or identifier
                except:
                    pass

            if not identifier and media_ref.name:
                identifier = media_ref.name.strip() or identifier

            if not identifier:
                logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): No identifier found.")
                skipped_counter += 1
                continue

            # Extract Metadata (Safely)
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

            # Add AAF correction flag to metadata if needed
            if needs_aaf_offset_correction:
                edit_metadata['_needs_aaf_offset_correction'] = True

            # Create EditShot
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
            logger.debug(f"Parsed EditShot #{clip_counter}: Clip='{shot.clip_name or 'Unnamed'}', ID='{identifier}'")

    except Exception as e:
        msg = f"Error processing clips in '{os.path.basename(file_path)}': {e}"
        logger.error(msg, exc_info=True)
        raise Exception(msg) from e

    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Created {clip_counter} valid EditShots (skipped {skipped_counter}).")
    return edit_shots


def correct_aaf_source_points(edit_shots: List[EditShot]) -> int:
    """
    Post-processes AAF source point ranges using source timecode from original files.
    This function should be called after find_original_sources() has populated
    the start_timecode values from ffprobe.

    Args:
        edit_shots: List of EditShots that may need AAF offset correction

    Returns:
        Number of shots corrected
    """
    corrected_count = 0

    for shot in edit_shots:
        # Check if this shot needs AAF correction and has required data
        if shot.lookup_status == 'found' and \
                shot.found_original_source and \
                shot.found_original_source.start_timecode and \
                shot.edit_metadata.get('_needs_aaf_offset_correction', False):

            # Get source timecode from ffprobe (the true absolute Source IN)
            source_in = shot.found_original_source.start_timecode

            # Get the relative offset stored in edit_media_range.start_time
            offset = shot.edit_media_range.start_time

            # Ensure rates match for addition
            if offset.rate != source_in.rate:
                try:
                    offset = offset.rescaled_to(source_in.rate)
                except Exception as e:
                    logger.error(f"Failed to rescale AAF offset for '{shot.clip_name}': {e}")
                    continue

            try:
                # Calculate the absolute start time
                absolute_start = source_in + offset

                # Create corrected range with absolute start time
                corrected_range = opentime.TimeRange(
                    start_time=absolute_start,
                    duration=shot.edit_media_range.duration
                )

                # Update the shot's edit_media_range with corrected values
                shot.edit_media_range = corrected_range

                # Remove the correction flag
                shot.edit_metadata.pop('_needs_aaf_offset_correction', None)

                corrected_count += 1

                logger.debug(f"Corrected AAF source point range for '{shot.clip_name}': "
                             f"Source IN {source_in} + Offset {offset} = {absolute_start}")

            except Exception as e:
                logger.error(f"Error correcting AAF source point range for '{shot.clip_name}': {e}")

    if corrected_count > 0:
        logger.info(f"Corrected {corrected_count} AAF source point ranges using original timecodes")

    return corrected_count

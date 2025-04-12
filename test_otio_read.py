# core/parser.py
"""
Parses edit files (AAF, FCPXML, etc.) using OpenTimelineIO to extract EditShot objects.
Calculates absolute timeline positions and stores source ranges as provided by OTIO,
marking AAF shots for later correction. Includes diagnostics.
"""
import logging
import os
from typing import List, Optional, Union
import opentimelineio as otio
from opentimelineio import opentime
from opentimelineio import schema

from core.models import EditShot

logger = logging.getLogger(__name__)


# Helper function to get rate safely
def get_rate(
        otio_obj: Union[schema.Clip, schema.Timeline, schema.Track, schema.ExternalReference, schema.MissingReference],
        default_rate: float = 25.0) -> float:
    """Safely attempts to get a valid frame rate from various OTIO objects."""
    rate = default_rate
    try:
        if hasattr(otio_obj, 'rate'):
            obj_rate = getattr(otio_obj, 'rate')
            if isinstance(obj_rate, opentime.RationalTime) and obj_rate.rate > 0: return float(obj_rate.rate)
            if isinstance(obj_rate, (float, int)) and obj_rate > 0: return float(obj_rate)
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
                if obj_rate_val: return float(obj_rate_val)
    except Exception as e:
        logger.debug(f"Could not determine rate for {type(otio_obj)}: {e}")
    final_rate = rate if isinstance(rate, (float, int)) and rate > 0 else default_rate
    logger.debug(f"Using rate {final_rate} for {type(otio_obj)}")
    return final_rate


def read_and_parse_edit_file(file_path: str) -> List[EditShot]:
    """Reads an edit file, extracting EditShot data, including absolute timeline positions."""
    if not os.path.exists(file_path): raise FileNotFoundError(f"Edit file not found: {file_path}")
    logger.info(f"Attempting to read edit file: {file_path}")
    timeline: Optional[schema.Timeline] = None
    sequence_rate: float = 25.0
    sequence_start_time: opentime.RationalTime = opentime.RationalTime(0, sequence_rate)
    is_aaf = file_path.lower().endswith('.aaf')

    # --- Read File and Get Timeline Object ---
    try:
        result = otio.adapters.read_from_file(file_path)
        if isinstance(result, schema.Timeline):
            timeline = result
        elif isinstance(result, schema.SerializableCollection):
            logger.warning(f"OTIO Collection found in '{os.path.basename(file_path)}'. Using first timeline.")
            timeline = next(result.find_children(kind=schema.Timeline), None)
        if not timeline: raise otio.exceptions.OTIOError("No valid timeline found in file.")
        logger.info(f"Successfully read OTIO timeline: '{timeline.name}'")
        # Determine sequence rate and start time accurately
        sequence_rate = get_rate(timeline, default_rate=25.0)
        read_start_time = timeline.global_start_time
        if read_start_time and isinstance(read_start_time, opentime.RationalTime) and read_start_time.rate > 0:
            if read_start_time.rate != sequence_rate:
                logger.warning(f"Timeline global_start_time rate mismatch. Rescaling.")
                try:
                    sequence_start_time = read_start_time.rescaled_to(sequence_rate)
                except Exception:
                    sequence_start_time = opentime.RationalTime(0, sequence_rate)
            else:
                sequence_start_time = read_start_time
        else:
            sequence_start_time = opentime.RationalTime(0, sequence_rate); logger.warning(
                f"Using default start time: {sequence_start_time}")
        start_tc_str = "N/A";
        try:
            start_tc_str = opentime.to_timecode(sequence_start_time, sequence_rate);
        except:
            pass
        logger.info(f"Sequence Rate: {sequence_rate}, Sequence Start Time: {sequence_start_time} ({start_tc_str})")
    except Exception as e:
        logger.error(f"Error reading/parsing edit file '{file_path}': {e}", exc_info=True); raise

    # --- Parsing Clips ---
    edit_shots: List[EditShot] = [];
    clip_counter = 0;
    skipped_counter = 0;
    item_counter = 0
    try:
        for clip in timeline.find_clips():
            item_counter += 1
            if not isinstance(clip, schema.Clip): continue
            media_ref = clip.media_reference
            if not media_ref: continue

            # --- 1. Source Point Range (edit_media_range) ---
            # Get the range OTIO provides. For AAF, this might be relative.
            source_point_range_otio = clip.source_range
            if not source_point_range_otio or \
                    not isinstance(source_point_range_otio.start_time, opentime.RationalTime) or \
                    not isinstance(source_point_range_otio.duration, opentime.RationalTime) or \
                    source_point_range_otio.duration.value <= 0 or \
                    source_point_range_otio.duration.rate <= 0:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name}'): Invalid/missing clip.source_range from OTIO: {source_point_range_otio}")
                skipped_counter += 1;
                continue
            # We will store this potentially relative range for now. AAF correction happens later.
            final_source_point_range = source_point_range_otio
            logger.debug(
                f"  Clip #{item_counter} ('{clip.name}'): Storing OTIO Source Range = {final_source_point_range}")

            # --- 2. Edit Position Range (timeline_range) ---
            # Calculate the ABSOLUTE position on the timeline
            edit_position_range: Optional[otio.opentime.TimeRange] = None
            try:
                relative_range = timeline.range_of_child(clip)
                if relative_range and isinstance(relative_range.start_time, opentime.RationalTime) and \
                        isinstance(relative_range.duration, opentime.RationalTime) and \
                        relative_range.duration.value > 0 and relative_range.start_time.rate > 0 and relative_range.duration.rate > 0:
                    # Rescale components to sequence rate if needed
                    edit_start_relative = relative_range.start_time
                    edit_duration = relative_range.duration
                    if edit_start_relative.rate != sequence_rate: edit_start_relative = edit_start_relative.rescaled_to(
                        sequence_rate)
                    if edit_duration.rate != sequence_rate: edit_duration = edit_duration.rescaled_to(sequence_rate)
                    # *** FIX: Calculate ABSOLUTE start time by adding sequence start time ***
                    absolute_start_time = sequence_start_time + edit_start_relative
                    edit_position_range = opentime.TimeRange(start_time=absolute_start_time, duration=edit_duration)
            except Exception as e:
                logger.debug(f"  Error calculating edit position range: {e}")
            logger.debug(f"  Final Edit Position Range: {edit_position_range}")

            # --- 3. Get Identifier ---
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
                except Exception as e:
                    edit_metadata['_metadata_error'] = str(e)
            # *** Add AAF Correction Flag ***
            if is_aaf:
                edit_metadata['_needs_aaf_offset_correction'] = True
                logger.debug(f"    Marked clip #{item_counter} for AAF offset correction.")

            # --- 5. Create EditShot ---
            shot = EditShot(clip_name=clip.name if clip.name else None, edit_media_path=identifier,
                            edit_media_range=final_source_point_range,
                            # Store OTIO's range (potentially relative for AAF)
                            timeline_range=edit_position_range,  # Store absolute timeline range
                            edit_metadata=edit_metadata, lookup_status="pending")
            edit_shots.append(shot);
            clip_counter += 1
            logger.debug(
                f"Parsed EditShot #{clip_counter}: Clip='{shot.clip_name or 'Unnamed'}', ID='{identifier}', SrcPtRange={final_source_point_range}, EditPosRange={edit_position_range}")

    except Exception as e:
        msg = f"Error processing clips: {e}"; logger.error(msg, exc_info=True); raise Exception(msg) from e
    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Created {clip_counter} valid EditShots (skipped {skipped_counter}).")
    return edit_shots

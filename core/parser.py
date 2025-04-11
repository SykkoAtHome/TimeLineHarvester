# core/parser.py
"""
Parses various edit file formats (EDL, AAF, XML) using OpenTimelineIO
and converts the relevant timeline content into EditShot objects.
Relies on OTIO's internal adapter auto-detection.
"""

import logging
import os
from typing import List, Optional, Tuple  # Tuple no longer needed in return type
import opentimelineio as otio
# No BaseAdapter needed anymore
# from opentimelineio.adapters import Adapter as BaseAdapter

# Import our specific model
from .models import EditShot

logger = logging.getLogger(__name__)

# Return only the list of shots now
# core/parser.py

import logging
import os
from typing import List, Optional, Tuple  # Tuple no longer needed
import opentimelineio as otio
from opentimelineio import opentime  # Explicit import for time objects

# Import our specific model
from .models import EditShot

logger = logging.getLogger(__name__)


# Updated function signature - returns only List[EditShot]
def read_and_parse_edit_file(file_path: str) -> List[EditShot]:
    """
    Reads an edit file using OTIO (auto-detecting format) and parses
    its clips into EditShot objects.

    Args:
        file_path: The path to the edit file (EDL, AAF, XML, etc.).

    Returns:
        A list of EditShot objects found in the timeline.

    Raises:
        FileNotFoundError: If the file_path does not exist.
        otio.exceptions.OTIOError: If OTIO fails to read/parse the file, finds no adapter,
                                   or returns an unexpected object type.
        Exception: For other unexpected errors during processing.
    """
    if not os.path.exists(file_path):
        msg = f"Edit file not found at path: {file_path}"
        logger.error(msg)
        raise FileNotFoundError(msg)

    logger.info(f"Attempting to read edit file with OTIO auto-detection: {file_path}")
    timeline: Optional[otio.schema.Timeline] = None

    try:
        # Use read_from_file, relying on OTIO's internal detection
        result = otio.adapters.read_from_file(file_path)

        # Check the type returned by read_from_file
        if isinstance(result, otio.schema.Timeline):
            timeline = result
            logger.info(f"Successfully read OTIO timeline: '{timeline.name}'")
        elif isinstance(result, otio.schema.SerializableCollection):
            # Handle cases where OTIO returns a collection (common with AAF)
            logger.warning(
                f"OTIO returned a Collection for '{os.path.basename(file_path)}'. Searching for the main timeline.")
            # Find the first timeline within the collection
            timelines_in_collection = list(result.find_children(kind=otio.schema.Timeline, search_range=None))
            if timelines_in_collection:
                timeline = timelines_in_collection[0]
                logger.info(f"Using the first timeline found in the collection: '{timeline.name}'")
                if len(timelines_in_collection) > 1:
                    logger.warning(
                        f"Multiple timelines found in collection; only the first one ('{timeline.name}') will be processed.")
            else:
                # If no timeline is found within the collection
                msg = f"OTIO read '{os.path.basename(file_path)}' as a Collection, but no Timeline objects were found within it."
                logger.error(msg)
                raise otio.exceptions.OTIOError(msg)
        else:
            # Handle any other unexpected return types
            msg = f"OTIO read '{os.path.basename(file_path)}' but returned an unexpected type: {type(result)}. Expected Timeline or SerializableCollection."
            logger.error(msg)
            raise otio.exceptions.OTIOError(msg)

    except otio.exceptions.NoAdapterFoundError as e:
        # Catch specific error if OTIO couldn't find a suitable adapter
        msg = f"OTIO could not find an adapter for '{os.path.basename(file_path)}'. Is the required adapter (e.g., pyaaf2 for AAF) installed? Original error: {e}"
        logger.error(msg)
        raise otio.exceptions.OTIOError(msg) from e  # Re-raise as OTIOError
    except Exception as e:
        # Catch other potential OTIO or file reading errors
        if isinstance(e, otio.exceptions.OTIOError):
            msg = f"OTIO error reading file '{os.path.basename(file_path)}': {e}"
            logger.error(msg)
            raise  # Re-raise the specific OTIOError
        else:
            # Catch other unexpected errors during file reading/initial parsing
            msg = f"An unexpected error occurred while reading '{os.path.basename(file_path)}': {e}"
            logger.error(msg, exc_info=True)
            raise Exception(msg) from e  # Re-raise generic exception

    # --- Parsing the OTIO timeline into EditShot objects ---
    edit_shots: List[EditShot] = []
    clip_counter = 0  # Counts valid clips processed
    skipped_counter = 0  # Counts items skipped during iteration
    item_counter = 0  # Counts total items looked at by find_clips

    try:
        # Use find_clips() to iterate through all Clip objects recursively
        for clip in timeline.find_clips():
            item_counter += 1

            # Basic check (should be guaranteed by find_clips, but safe)
            if not isinstance(clip, otio.schema.Clip):
                logger.warning(f"Item #{item_counter} found by find_clips was not a Clip: {type(clip)}. Skipping.")
                skipped_counter += 1
                continue

            # Get media reference
            media_ref = clip.media_reference

            # --- Clip and Media Reference Validation ---
            if not media_ref:
                logger.debug(f"Skipping clip #{item_counter} ('{clip.name}'): No media reference.")
                skipped_counter += 1
                continue
            if not isinstance(media_ref, otio.schema.ExternalReference):
                ref_type = type(media_ref).__name__
                logger.debug(
                    f"Skipping clip #{item_counter} ('{clip.name}'): Non-external reference type ('{ref_type}').")
                skipped_counter += 1
                continue
            if not media_ref.target_url:
                logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): External reference missing target_url.")
                skipped_counter += 1
                continue

            # --- Source Range Validation ---
            source_range = clip.source_range
            if not source_range:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name}' at {media_ref.target_url}): Clip has no source_range defined.")
                skipped_counter += 1
                continue
            # Use opentime comparison for duration check
            zero_duration = opentime.RationalTime(0, source_range.duration.rate)
            if source_range.duration <= zero_duration:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name}' at {media_ref.target_url}): Clip has zero or negative duration ({source_range.duration}) in source_range.")
                skipped_counter += 1
                continue

            # --- Get Timeline Range (Optional, using transformed_range) ---
            timeline_range: Optional[otio.opentime.TimeRange] = None
            try:
                # Get range relative to the main timeline's time space and rate
                timeline_rate = timeline.global_start_time.rate if timeline.global_start_time else 24.0  # Use timeline rate
                timeline_range = clip.transformed_range(target_rate=timeline_rate)
                zero_timeline_duration = opentime.RationalTime(0, timeline_rate)
                if timeline_range.duration <= zero_timeline_duration:
                    logger.warning(
                        f"Clip #{item_counter} ('{clip.name}') has zero or negative duration ({timeline_range.duration}) on timeline. Range set to None.")
                    timeline_range = None
            except Exception as range_err:
                # Log the error but don't stop parsing other clips
                logger.warning(
                    f"Could not determine timeline range for clip #{item_counter} ('{clip.name}'): {range_err}. Setting range to None.")
                timeline_range = None  # Set to None if calculation fails

            # --- Extract Metadata ---
            # Create a new dict to avoid modifying OTIO object's metadata directly
            edit_metadata = dict(media_ref.metadata) if media_ref.metadata else {}

            # --- Create EditShot Object ---
            shot = EditShot(
                clip_name=clip.name if clip.name else None,  # Handle empty names
                edit_media_path=media_ref.target_url,
                edit_media_range=source_range,
                timeline_range=timeline_range,  # Can be None
                edit_metadata=edit_metadata,
                lookup_status="pending"  # Initial status
            )
            edit_shots.append(shot)
            clip_counter += 1  # Increment count of successfully processed clips
            logger.debug(f"Parsed EditShot #{clip_counter} from clip '{shot.clip_name or 'Unnamed'}'")

    except Exception as e:
        # Catch errors during the iteration/parsing phase
        msg = f"An error occurred while processing clips in '{os.path.basename(file_path)}': {e}"
        logger.error(msg, exc_info=True)
        # Re-raise the exception to signal failure to the caller
        raise Exception(msg) from e

    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Processed ~{item_counter} timeline items. Created {clip_counter} valid EditShots (skipped {skipped_counter} items).")

    # Return the list of successfully created EditShot objects
    return edit_shots

# core/parser.py
"""
Parses various edit file formats (EDL, AAF, XML) using OpenTimelineIO
and converts the relevant timeline content into EditShot objects.
Also determines the likely OTIO adapter name based on the file path.
"""

import logging
import os
from typing import List, Optional, Tuple
import opentimelineio as otio
# No need for BaseAdapter import with this approach

# Import our specific model
from .models import EditShot

logger = logging.getLogger(__name__)


def read_and_parse_edit_file(file_path: str) -> Tuple[List[EditShot], Optional[str]]:
    """
    Reads an edit file using OTIO, parses its clips into EditShot objects,
    and returns the shots along with the name of the OTIO adapter likely used.

    Args:
        file_path: The path to the edit file (EDL, AAF, XML, etc.).

    Returns:
        A tuple containing:
            - A list of EditShot objects found in the timeline.
            - The name of the OTIO adapter determined by `adapter_for_filepath`
              (e.g., 'cmx_3600_edl', 'aaf_adapter', 'fcpxml'), or None if unknown.

    Raises:
        FileNotFoundError: If the file_path does not exist.
        otio.exceptions.OTIOError: If OTIO fails to read or parse the file.
        Exception: For other unexpected errors during processing.
    """
    if not os.path.exists(file_path):
        msg = f"Edit file not found at path: {file_path}"
        logger.error(msg)
        raise FileNotFoundError(msg)

    logger.info(f"Attempting to parse edit file: {file_path}")
    adapter_name: Optional[str] = None
    timeline: Optional[otio.schema.Timeline] = None

    # --- Step 1: Determine the likely adapter ---
    try:
        # This function returns the adapter *instance* OTIO would use for this path
        guessed_adapter = otio.adapters.adapter_for_filepath(file_path)
        if guessed_adapter:
            adapter_name = guessed_adapter.name
            logger.info(f"Determined likely adapter for '{os.path.basename(file_path)}': '{adapter_name}'")
        else:
            logger.warning(
                f"Could not determine a specific adapter for '{os.path.basename(file_path)}'. OTIO will auto-detect.")
    except Exception as e:
        # This shouldn't normally fail unless OTIO has internal issues
        logger.warning(f"Error determining adapter for '{file_path}': {e}. Proceeding with auto-detection.")
        adapter_name = None  # Ensure it's None if determination failed

    # --- Step 2: Read the file using read_from_file ---
    try:
        # Use read_from_file for actual reading.
        # We could pass adapter_name=adapter_name here, but letting OTIO
        # auto-detect might be more robust if adapter_for_filepath guessed wrong.
        # For simplicity, we'll let it auto-detect fully.
        result = otio.adapters.read_from_file(file_path)

        # Ensure we got a Timeline object
        if isinstance(result, otio.schema.Timeline):
            timeline = result
            logger.info(f"Successfully read OTIO timeline object: '{timeline.name}'")
        # Handle cases where read_from_file might return a collection (e.g., some AAFs)
        elif isinstance(result, otio.schema.SerializableCollection):
            logger.warning(f"OTIO returned a Collection for '{file_path}'. Searching for the main timeline.")
            # Find the first timeline within the collection
            timelines_in_collection = list(result.find_children(kind=otio.schema.Timeline, search_range=None))
            if timelines_in_collection:
                timeline = timelines_in_collection[0]
                logger.info(f"Using the first timeline found in the collection: '{timeline.name}'")
                if len(timelines_in_collection) > 1:
                    logger.warning(
                        f"Multiple timelines found in collection; only the first one ('{timeline.name}') will be processed.")
            else:
                msg = f"OTIO read '{file_path}' as a Collection, but no Timeline objects were found within it."
                logger.error(msg)
                raise otio.exceptions.OTIOError(msg)
        else:
            # Handle any other unexpected return types
            msg = f"OTIO read '{file_path}' but returned an unexpected type: {type(result)}. Expected Timeline or SerializableCollection."
            logger.error(msg)
            raise otio.exceptions.OTIOError(msg)

    except Exception as e:
        # Catch OTIO reading errors or other file issues
        if isinstance(e, otio.exceptions.OTIOError):
            msg = f"OTIO failed to read file '{file_path}': {e}"
            logger.error(msg)
            raise otio.exceptions.OTIOError(msg) from e  # Re-raise specific error
        else:
            msg = f"An unexpected error occurred while reading '{file_path}': {e}"
            logger.error(msg, exc_info=True)
            raise Exception(msg) from e  # Re-raise generic error

    # --- Step 3: Parse the OTIO timeline into EditShot objects ---
    edit_shots: List[EditShot] = []
    clip_counter = 0
    skipped_counter = 0
    try:
        for clip in timeline.each_clip():
            clip_counter += 1
            media_ref = clip.media_reference
            # --- Clip and Media Reference Validation ---
            if not media_ref:
                logger.debug(f"Skipping clip #{clip_counter} ('{clip.name}'): No media reference.")
                skipped_counter += 1
                continue
            if not isinstance(media_ref, otio.schema.ExternalReference):
                ref_type = type(media_ref).__name__
                logger.debug(
                    f"Skipping clip #{clip_counter} ('{clip.name}'): Non-external reference type ('{ref_type}').")
                skipped_counter += 1
                continue
            if not media_ref.target_url:
                logger.warning(
                    f"Skipping clip #{clip_counter} ('{clip.name}'): External reference is missing target_url.")
                skipped_counter += 1
                continue
            # --- Source Range Validation ---
            source_range = clip.source_range
            if not source_range:
                logger.warning(
                    f"Skipping clip #{clip_counter} ('{clip.name}' at {media_ref.target_url}): Clip has no source_range defined.")
                skipped_counter += 1
                continue
            if source_range.duration.value <= 0:
                logger.warning(
                    f"Skipping clip #{clip_counter} ('{clip.name}' at {media_ref.target_url}): Clip has zero or negative duration ({source_range.duration}) in source_range.")
                skipped_counter += 1
                continue
            # --- Get Timeline Range (Optional) ---
            timeline_range: Optional[otio.opentime.TimeRange] = None
            try:
                timeline_range = clip.range_in_parent()
                if timeline_range.duration.value <= 0:
                    logger.warning(
                        f"Clip #{clip_counter} ('{clip.name}') has zero or negative duration ({timeline_range.duration}) on timeline. Range set to None.")
                    timeline_range = None
            except Exception as range_err:
                logger.warning(
                    f"Could not determine timeline range for clip #{clip_counter} ('{clip.name}'): {range_err}. Setting range to None.")
                timeline_range = None
            # --- Extract Metadata ---
            edit_metadata = dict(media_ref.metadata) if media_ref.metadata else {}
            # --- Create EditShot Object ---
            shot = EditShot(
                clip_name=clip.name if clip.name else None,
                edit_media_path=media_ref.target_url,
                edit_media_range=source_range,
                timeline_range=timeline_range,
                edit_metadata=edit_metadata,
                lookup_status="pending"
            )
            edit_shots.append(shot)
            logger.debug(f"Parsed EditShot #{len(edit_shots)} from clip '{shot.clip_name or 'Unnamed'}'")

    except Exception as e:
        # Catch errors during the clip iteration phase
        msg = f"An error occurred while iterating through clips in '{os.path.basename(file_path)}': {e}"
        logger.error(msg, exc_info=True)
        raise Exception(msg) from e

    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Found {len(edit_shots)} valid EditShots (skipped {skipped_counter} clips). Determined adapter: '{adapter_name or 'N/A'}'")

    # Return the list of parsed shots and the adapter name determined earlier
    return edit_shots, adapter_name

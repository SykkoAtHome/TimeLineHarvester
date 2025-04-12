# core/parser.py
"""
Parses various edit file formats (EDL, AAF, XML) using OpenTimelineIO
and converts the relevant timeline content into EditShot objects.
Focuses on extracting a usable identifier and source range.
"""

import logging
import os
from typing import List, Optional
import opentimelineio as otio
from opentimelineio import opentime

from .models import EditShot

logger = logging.getLogger(__name__)

def read_and_parse_edit_file(file_path: str) -> List[EditShot]:
    """
    Reads an edit file using OTIO, focusing on extracting essential EditShot data:
    identifier, source_range, and metadata.
    """
    # ... (File existence check and OTIO reading logic remain the same) ...
    if not os.path.exists(file_path):
        msg = f"Edit file not found at path: {file_path}"
        logger.error(msg)
        raise FileNotFoundError(msg)

    logger.info(f"Attempting to read edit file with OTIO auto-detection: {file_path}")
    timeline: Optional[otio.schema.Timeline] = None

    try:
        result = otio.adapters.read_from_file(file_path)
        if isinstance(result, otio.schema.Timeline):
            timeline = result
            logger.info(f"Successfully read OTIO timeline: '{timeline.name}'")
        elif isinstance(result, otio.schema.SerializableCollection):
            logger.warning(f"OTIO returned a Collection for '{os.path.basename(file_path)}'. Searching for the main timeline.")
            timelines_in_collection = list(result.find_children(kind=otio.schema.Timeline, search_range=None))
            if timelines_in_collection:
                timeline = timelines_in_collection[0]
                logger.info(f"Using the first timeline found in the collection: '{timeline.name}'")
                if len(timelines_in_collection) > 1:
                    logger.warning(f"Multiple timelines found; only the first ('{timeline.name}') will be processed.")
            else:
                msg = f"OTIO read '{os.path.basename(file_path)}' as a Collection, but no Timeline objects were found within it."
                logger.error(msg)
                raise otio.exceptions.OTIOError(msg)
        else:
            msg = f"OTIO read '{os.path.basename(file_path)}' but returned an unexpected type: {type(result)}. Expected Timeline or SerializableCollection."
            logger.error(msg)
            raise otio.exceptions.OTIOError(msg)

    except otio.exceptions.NoAdapterFoundError as e:
        msg = f"OTIO could not find an adapter for '{os.path.basename(file_path)}'. Is the required adapter (e.g., pyaaf2 for AAF) installed? Original error: {e}"
        logger.error(msg)
        raise otio.exceptions.OTIOError(msg) from e
    except Exception as e:
        if isinstance(e, otio.exceptions.OTIOError):
            msg = f"OTIO error reading file '{os.path.basename(file_path)}': {e}"
            logger.error(msg)
            raise
        else:
            msg = f"An unexpected error occurred while reading '{os.path.basename(file_path)}': {e}"
            logger.error(msg, exc_info=True)
            raise Exception(msg) from e

    # --- Parsing the OTIO timeline into EditShot objects ---
    edit_shots: List[EditShot] = []
    clip_counter = 0
    skipped_counter = 0
    item_counter = 0

    try:
        for clip in timeline.find_clips():
            item_counter += 1

            if not isinstance(clip, otio.schema.Clip):
                logger.warning(f"Item #{item_counter} found by find_clips was not a Clip: {type(clip)}. Skipping.")
                skipped_counter += 1
                continue

            media_ref = clip.media_reference
            if not media_ref:
                logger.debug(f"Skipping clip #{item_counter} ('{clip.name}'): No media reference.")
                skipped_counter += 1
                continue

            # We primarily care about the source_range and an identifier.
            # Let's try to get the source range first.
            source_range = clip.source_range
            if not source_range:
                logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): Clip has no source_range defined.")
                skipped_counter += 1
                continue
            # Validate TimeRange components
            if not isinstance(source_range.start_time, opentime.RationalTime) or \
               not isinstance(source_range.duration, opentime.RationalTime):
                 logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): Invalid components in source_range {source_range}.")
                 skipped_counter += 1
                 continue
            # Validate duration
            try:
                if source_range.duration.value <= 0 or source_range.duration.rate <= 0:
                     logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): Clip has zero/negative/invalid duration ({source_range.duration}) in source_range.")
                     skipped_counter += 1
                     continue
            except Exception as e: # Catch potential comparison errors or zero rate issues
                logger.error(f"Error checking duration for clip #{item_counter}: {e}. Skipping.", exc_info=False)
                skipped_counter += 1
                continue

            # Now, try to get the best possible identifier string for SourceFinder
            edit_media_identifier = None
            # 1. Try specific metadata keys (most reliable if present)
            possible_id_keys = ["Source File", "Source Name", "Tape Name", "Reel Name"]
            if media_ref.metadata:
                 for key in possible_id_keys:
                     found_meta_key = next((k for k in media_ref.metadata if k.lower() == key.lower()), None)
                     if found_meta_key:
                          meta_val = str(media_ref.metadata[found_meta_key]).strip()
                          if meta_val:
                              edit_media_identifier = meta_val
                              logger.debug(f"  Using metadata '{found_meta_key}': '{edit_media_identifier}' as identifier for clip #{item_counter} ('{clip.name}').")
                              break
            # 2. If no metadata, try target_url (might be just a filename)
            if not edit_media_identifier and isinstance(media_ref, otio.schema.ExternalReference) and media_ref.target_url:
                identifier_from_url = media_ref.target_url.strip()
                if identifier_from_url:
                    edit_media_identifier = identifier_from_url
                    logger.debug(f"  Using target_url: '{edit_media_identifier}' as identifier for clip #{item_counter} ('{clip.name}').")
            # 3. Fallback to media reference name
            if not edit_media_identifier and media_ref.name:
                identifier_from_name = media_ref.name.strip()
                if identifier_from_name:
                    edit_media_identifier = identifier_from_name
                    logger.debug(f"  Using media_ref name: '{edit_media_identifier}' as identifier for clip #{item_counter} ('{clip.name}').")
            # 4. Final fallback: clip name itself
            if not edit_media_identifier and clip.name:
                 identifier_from_clipname = clip.name.strip()
                 if identifier_from_clipname:
                      edit_media_identifier = identifier_from_clipname
                      logger.debug(f"  Using clip name: '{edit_media_identifier}' as identifier for clip #{item_counter}.")


            if not edit_media_identifier:
                 logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): Could not determine any usable identifier.")
                 skipped_counter += 1
                 continue

            # --- Extract Metadata (Safely) ---
            edit_metadata = {}
            if media_ref.metadata:
                 try:
                     for k, v in media_ref.metadata.items():
                         if isinstance(v, (str, int, float, bool, type(None))):
                             edit_metadata[k] = v
                         elif isinstance(v, (list, tuple)):
                              try:
                                  # Only copy list/tuple if items are basic types
                                  if all(isinstance(item, (str, int, float, bool, type(None))) for item in v):
                                       edit_metadata[k] = list(v) # Make a copy
                                  else:
                                       edit_metadata[k] = str(v)
                              except: edit_metadata[k] = str(v)
                         else: edit_metadata[k] = str(v)
                 except Exception as meta_copy_err:
                      logger.warning(f"  Could not fully process metadata for clip #{item_counter}: {meta_copy_err}")
                      edit_metadata['_metadata_error'] = str(meta_copy_err)

            # --- Timeline Range (Optional, Best Effort) ---
            # Keep the previous manual rescale logic, but don't skip the clip if it fails
            timeline_range: Optional[otio.opentime.TimeRange] = None
            try:
                parent_range = timeline.range_of_child(clip)
                if parent_range and isinstance(parent_range.start_time, opentime.RationalTime) and isinstance(parent_range.duration, opentime.RationalTime):
                     timeline_rate = 24.0
                     if timeline.global_start_time and timeline.global_start_time.rate > 0:
                         timeline_rate = timeline.global_start_time.rate
                     start_rate = parent_range.start_time.rate
                     duration_rate = parent_range.duration.rate
                     if start_rate > 0 and duration_rate > 0:
                         try:
                             rescaled_start = parent_range.start_time.rescaled_to(timeline_rate)
                             rescaled_duration = parent_range.duration.rescaled_to(timeline_rate)
                             temp_range = opentime.TimeRange(start_time=rescaled_start, duration=rescaled_duration)
                             zero_timeline_duration = opentime.RationalTime(0, timeline_rate)
                             if temp_range.duration > zero_timeline_duration:
                                 timeline_range = temp_range # Assign only if valid
                             else: logger.debug(f"  Timeline range duration zero/negative after rescale for clip #{item_counter}.")
                         except Exception as rescale_err: logger.debug(f"  Error rescaling timeline range components for clip #{item_counter}: {rescale_err}")
                     else: logger.debug(f"  Zero rate in parent range components for clip #{item_counter}.")
                else: logger.debug(f"  Could not get valid parent_range for clip #{item_counter}.")
            except Exception as range_err: logger.debug(f"  Error getting timeline range for clip #{item_counter}: {range_err}")


            # --- Create EditShot Object ---
            shot = EditShot(
                clip_name=clip.name if clip.name else None,
                edit_media_path=edit_media_identifier, # Use the best identifier found
                edit_media_range=source_range,         # Must be valid to reach here
                timeline_range=timeline_range,         # Optional
                edit_metadata=edit_metadata,           # Processed metadata
                lookup_status="pending"
            )
            edit_shots.append(shot)
            clip_counter += 1
            logger.debug(f"Parsed EditShot #{clip_counter}: Clip='{shot.clip_name or 'Unnamed'}', ID='{edit_media_identifier}', Range={source_range}")

    except Exception as e:
        msg = f"An error occurred while processing clips in '{os.path.basename(file_path)}': {e}"
        logger.error(msg, exc_info=True)
        raise Exception(msg) from e

    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Processed ~{item_counter} timeline items. Created {clip_counter} valid EditShots (skipped {skipped_counter} items).")

    return edit_shots
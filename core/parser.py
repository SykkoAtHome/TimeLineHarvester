# core/parser.py
"""
Parses edit files, extracting an identifier (like filename or tape name)
and source range for each clip, needed for source finding.
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
    Reads an edit file, extracting essential EditShot data:
    identifier (stored in edit_media_path), source_range, and metadata.
    """
    # --- File Reading and Timeline Detection ---
    if not os.path.exists(file_path): raise FileNotFoundError(f"Edit file not found: {file_path}")
    logger.info(f"Attempting to read edit file: {file_path}")
    timeline: Optional[otio.schema.Timeline] = None
    try:
        result = otio.adapters.read_from_file(file_path)
        # Simplified Timeline/Collection handling
        if isinstance(result, otio.schema.Timeline):
            timeline = result
        elif isinstance(result, otio.schema.SerializableCollection):
            logger.warning(
                f"OTIO returned a Collection for '{os.path.basename(file_path)}'. Searching for the main timeline.")
            timeline = next(result.find_children(kind=otio.schema.Timeline), None)  # Find first timeline or None
        if not timeline: raise otio.exceptions.OTIOError("No valid timeline found in file.")
        logger.info(f"Successfully read OTIO timeline: '{timeline.name}'")
    except Exception as e:  # Catch all read errors
        logger.error(f"Error reading/parsing edit file '{file_path}': {e}", exc_info=True)
        raise  # Re-raise after logging

    # --- Parsing the OTIO timeline into EditShot objects ---
    edit_shots: List[EditShot] = []
    clip_counter = 0
    skipped_counter = 0
    item_counter = 0

    try:
        for clip in timeline.find_clips():
            item_counter += 1

            if not isinstance(clip, otio.schema.Clip): continue  # Skip non-clips

            media_ref = clip.media_reference
            if not media_ref: continue  # Skip if no media ref

            # --- Get Source Range (Essential) ---
            source_range = clip.source_range
            if not source_range or not isinstance(source_range.start_time, opentime.RationalTime) or \
                    not isinstance(source_range.duration, opentime.RationalTime):
                logger.warning(f"Skipping clip #{item_counter} ('{clip.name}'): Invalid or missing source_range.")
                skipped_counter += 1
                continue
            try:  # Check duration validity
                if source_range.duration.value <= 0 or source_range.duration.rate <= 0:
                    logger.warning(
                        f"Skipping clip #{item_counter} ('{clip.name}'): Invalid source_range duration {source_range.duration}.")
                    skipped_counter += 1
                    continue
            except Exception:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name}'): Error checking source_range duration {source_range.duration}.")
                skipped_counter += 1
                continue
            # --- End Source Range ---

            # --- Get Identifier (for SourceFinder) ---
            identifier = None
            clip_name_str = clip.name.strip() if clip.name else None

            # 1. Try Metadata (Source File/Name)
            if media_ref.metadata:
                for key in ["Source File", "Source Name"]:
                    found_meta_key = next((k for k in media_ref.metadata if k.lower() == key.lower()), None)
                    if found_meta_key:
                        meta_val = str(media_ref.metadata[found_meta_key]).strip()
                        if meta_val:
                            identifier = meta_val
                            logger.debug(
                                f"  Using metadata '{found_meta_key}': '{identifier}' as identifier for clip #{item_counter}.")
                            break

            # 2. Try Clip Name
            if not identifier and clip_name_str:
                identifier = clip_name_str
                logger.debug(f"  Using clip name: '{identifier}' as identifier for clip #{item_counter}.")

            # 3. Try basename from target_url
            if not identifier and isinstance(media_ref, otio.schema.ExternalReference) and media_ref.target_url:
                try:
                    url_path = otio.url_utils.url_to_filepath(media_ref.target_url)
                    url_basename = os.path.basename(url_path).strip()
                    if url_basename:
                        identifier = url_basename
                        logger.debug(
                            f"  Using basename from target_url: '{identifier}' as identifier for clip #{item_counter}.")
                except Exception as url_err:
                    logger.warning(f"  Could not extract basename from target_url '{media_ref.target_url}': {url_err}")

            # 4. Try media_ref name
            if not identifier and media_ref.name:
                media_ref_name_str = media_ref.name.strip()
                if media_ref_name_str:
                    identifier = media_ref_name_str
                    logger.debug(f"  Using media_ref name: '{identifier}' as identifier for clip #{item_counter}.")

            # Final check
            if not identifier:
                logger.warning(
                    f"Skipping clip #{item_counter} ('{clip.name}'): Could not determine any usable identifier.")
                skipped_counter += 1
                continue
            # --- End Identifier ---

            # --- Extract Metadata (Safely) ---
            edit_metadata = {}
            if media_ref.metadata:
                try:  # Safe copy logic
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
                    logger.warning(f"  Could not fully process metadata for clip #{item_counter}: {meta_copy_err}")
                    edit_metadata['_metadata_error'] = str(meta_copy_err)
            # --- End Metadata ---

            # --- Timeline Range (Optional - Best Effort) ---
            timeline_range: Optional[otio.opentime.TimeRange] = None
            try:
                parent_range = timeline.range_of_child(clip)
                if parent_range and isinstance(parent_range.start_time, opentime.RationalTime) and isinstance(
                        parent_range.duration, opentime.RationalTime):
                    timeline_rate = 24.0  # Default rate
                    if timeline.global_start_time and timeline.global_start_time.rate > 0:
                        timeline_rate = timeline.global_start_time.rate
                    start_rate = parent_range.start_time.rate
                    duration_rate = parent_range.duration.rate
                    if start_rate > 0 and duration_rate > 0:
                        try:  # Manual rescale
                            rescaled_start = parent_range.start_time.rescaled_to(timeline_rate)
                            rescaled_duration = parent_range.duration.rescaled_to(timeline_rate)
                            temp_range = opentime.TimeRange(start_time=rescaled_start, duration=rescaled_duration)
                            if temp_range.duration.value > 0: timeline_range = temp_range
                        except Exception:
                            pass  # Ignore rescale errors silently
            except Exception:
                pass  # Ignore range_of_child errors silently
            # --- End Timeline Range ---

            # --- Create EditShot ---
            shot = EditShot(
                clip_name=clip.name if clip.name else None,
                edit_media_path=identifier,  # Store the identifier here
                edit_media_range=source_range,
                timeline_range=timeline_range,
                edit_metadata=edit_metadata,
                lookup_status="pending"
            )
            edit_shots.append(shot)
            clip_counter += 1
            logger.debug(
                f"Parsed EditShot #{clip_counter}: Clip='{shot.clip_name or 'Unnamed'}', ID='{identifier}', Range={source_range}")

    except Exception as e:
        msg = f"An error occurred while processing clips in '{os.path.basename(file_path)}': {e}"
        logger.error(msg, exc_info=True)
        raise Exception(msg) from e

    logger.info(
        f"Finished parsing '{os.path.basename(file_path)}'. Processed ~{item_counter} timeline items. Created {clip_counter} valid EditShots (skipped {skipped_counter} items).")
    return edit_shots

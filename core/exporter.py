# core/exporter.py
"""
Exports a calculated TransferBatch to standard edit list formats
like EDL or FCPXML, referencing the original source files with handles.
Primarily used for generating lists for color grading.
"""

import logging
import os
from collections import defaultdict  # Added for reel_counters
from typing import Optional, Dict, Any  # Added List

import opentimelineio as otio
from opentimelineio import opentime, schema

# Import necessary models
from .models import TransferBatch  # Use relative import within the package

logger = logging.getLogger(__name__)

# Mapping from common extensions to OTIO adapter names for WRITING
SUPPORTED_EXPORT_FORMATS: Dict[str, str] = {
    '.edl': 'cmx_3600_edl',
    '.xml': 'fcpxml',  # Default XML to FCPXML
    '.fcpxml': 'fcpxml',
}


def export_transfer_batch(
        transfer_batch: TransferBatch,
        output_path: str,
        timeline_name: Optional[str] = None,
        export_format_adapter_name: Optional[str] = None,
        adapter_options: Optional[Dict[str, Any]] = None,
        separator_frames: int = 0) -> bool:  # Added separator_frames argument
    """
    Exports the calculated segments from a TransferBatch to an EDL or FCPXML file.
    Optionally inserts black gaps (separators) between segments.

    Args:
        transfer_batch: The calculated TransferBatch object (e.g., color_transfer_batch).
                        Must contain valid segments.
        output_path: The full path for the output EDL or XML file.
        timeline_name: Optional name for the timeline in the exported file.
        export_format_adapter_name: Explicit OTIO adapter name (e.g., 'cmx_3600_edl', 'fcpxml').
                                   If None, detected from output_path extension.
        adapter_options: Optional dictionary of adapter-specific write options.
        separator_frames: Number of black frames (at timeline rate) to insert between segments.

    Returns:
        True if export was successful, False otherwise.
    """
    if not transfer_batch:
        logger.error("Cannot export: Transfer batch is None.")
        return False
    if not transfer_batch.segments:
        logger.warning("Transfer batch contains no segments to export. Skipping export.")
        # Consider returning True here if an empty batch is not an error state?
        # For now, return False as nothing was written.
        return False

    abs_output_path = os.path.abspath(output_path)

    # --- Determine Export Format Adapter ---
    adapter_name = export_format_adapter_name
    if not adapter_name:
        ext = os.path.splitext(abs_output_path)[1].lower()
        adapter_name = SUPPORTED_EXPORT_FORMATS.get(ext)
        if not adapter_name:
            logger.error(
                f"Cannot export: Unsupported file extension '{ext}'. Supported: {list(SUPPORTED_EXPORT_FORMATS.keys())}")
            return False

    # Check if the chosen adapter is available for writing
    available_adapters = otio.adapters.available_adapter_names()
    if adapter_name not in available_adapters:
        logger.error(
            f"Cannot export: OTIO adapter '{adapter_name}' is not available for writing in this environment. Available: {available_adapters}")
        return False
    elif adapter_name not in SUPPORTED_EXPORT_FORMATS.values():
        logger.warning(
            f"Exporting using potentially unsupported adapter '{adapter_name}'. Known supported: {list(SUPPORTED_EXPORT_FORMATS.values())}")

    # --- Create New OTIO Timeline ---
    export_timeline_name = timeline_name or transfer_batch.batch_name or f"{os.path.splitext(os.path.basename(abs_output_path))[0]}_Timeline"
    # Determine timeline rate reliably
    timeline_rate = 24.0  # Default
    for segment in transfer_batch.segments:
        if segment.original_source and segment.original_source.frame_rate:
            timeline_rate = segment.original_source.frame_rate;
            break
        elif segment.transfer_source_range:
            timeline_rate = segment.transfer_source_range.duration.rate;
            break
    logger.info(f"Creating export timeline '{export_timeline_name}' at {timeline_rate:.3f} fps.")

    export_timeline = otio.schema.Timeline(
        name=export_timeline_name,
        global_start_time=opentime.RationalTime(0, timeline_rate)
    )
    video_track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    export_timeline.tracks.append(video_track)

    # --- Create Separator Gap (if requested) ---
    separator_gap = None
    norm_sep_frames = max(0, int(separator_frames))  # Ensure non-negative integer
    if norm_sep_frames > 0:
        try:
            gap_duration = opentime.RationalTime(value=norm_sep_frames, rate=timeline_rate)
            separator_gap = schema.Gap(duration=gap_duration)  # Use schema.Gap
            logger.info(f"Will insert {norm_sep_frames}-frame gaps between segments.")
        except Exception as e:
            logger.error(
                f"Could not create separator gap object (duration: {norm_sep_frames} frames @ {timeline_rate}fps): {e}")
            # Proceed without gaps

    # --- Populate Timeline with Clips and Gaps ---
    added_clip_count = 0
    reel_counters: Dict[str, int] = defaultdict(int)

    for i, segment in enumerate(transfer_batch.segments):
        # --- Validate Segment ---
        if not (segment.original_source and segment.original_source.path and
                segment.transfer_source_range and segment.transfer_source_range.duration.value > 0):
            logger.warning(f"Skipping segment {i + 1} due to invalid source or range data.")
            continue

        original_source = segment.original_source
        transfer_range = segment.transfer_source_range

        # --- Add Separator Gap BEFORE the clip (except for the very first clip) ---
        if added_clip_count > 0 and separator_gap:  # Check if gap exists and not first clip
            try:
                # Add a *copy* of the gap to avoid issues if modifying gap instances
                video_track.append(separator_gap.deepcopy())
                logger.debug(f"Added {norm_sep_frames}f separator gap before segment {i + 1}.")
            except Exception as gap_err:
                logger.error(f"Failed to append separator gap before segment {i + 1}: {gap_err}")
                # Continue processing clips even if gap fails? Yes.

        # --- Create Media Reference ---
        try:
            abs_source_path = os.path.abspath(original_source.path)
            # Use filepath_to_url for cross-platform compatibility
            source_url = otio.url_utils.filepath_to_url(abs_source_path)
        except Exception as url_err:
            logger.error(
                f"Skipping segment {i + 1}: Could not create file URL for path '{original_source.path}': {url_err}.")
            continue

        media_ref = otio.schema.ExternalReference(target_url=source_url)
        if original_source.is_verified and original_source.duration and original_source.frame_rate:
            start_tc = original_source.start_timecode or opentime.RationalTime(0, original_source.frame_rate)
            media_ref.available_range = opentime.TimeRange(start_time=start_tc, duration=original_source.duration)

        # --- Determine Metadata (Reel, Clip Name) ---
        tape_name = os.path.splitext(os.path.basename(original_source.path))[0]
        clip_name_base = tape_name
        if segment.source_edit_shots:
            first_shot = segment.source_edit_shots[0]
            if first_shot.clip_name: clip_name_base = first_shot.clip_name
            if first_shot.edit_metadata:
                possible_keys = ["Tape Name", "Reel Name", "TapeID", "Reel", "reel", "source_clip",
                                 "reel id"]  # More keys
                for key in possible_keys:
                    # Case-insensitive check for key presence
                    found_key = next((k for k in first_shot.edit_metadata if k.lower() == key.lower()), None)
                    if found_key:
                        meta_tape_name = str(first_shot.edit_metadata[found_key]).strip()
                        if meta_tape_name: tape_name = meta_tape_name; break
        # Format tape name for EDL
        if adapter_name == 'cmx_3600_edl':
            tape_name = ''.join(c if c.isalnum() else '_' for c in tape_name.upper())[
                        :8]  # Keep only alphanum/_, uppercase, max 8

        media_ref.metadata[' Reel Name'] = tape_name
        media_ref.metadata['Tape Name'] = tape_name

        # --- Create OTIO Clip ---
        reel_counters[tape_name] += 1
        event_num = reel_counters[tape_name]
        clip_name_in_timeline = f"{tape_name}_{event_num:03d}"

        otio_clip = otio.schema.Clip(
            name=clip_name_in_timeline,
            media_reference=media_ref,
            source_range=transfer_range
        )
        otio_clip.metadata['Original Clip Name'] = clip_name_base
        otio_clip.metadata['Source File'] = os.path.basename(original_source.path)
        otio_clip.metadata['cmx_3600_edit_note'] = f"FROM CLIP {os.path.basename(original_source.path)}"

        # --- Add Clip to Track ---
        try:
            video_track.append(otio_clip)
            added_clip_count += 1
            logger.debug(
                f"Appended clip '{otio_clip.name}' to track. Source: {os.path.basename(original_source.path)}, Range: {transfer_range}")
        except Exception as append_err:
            logger.error(f"Failed to append clip '{otio_clip.name}' to track: {append_err}", exc_info=True)
            # Fail the entire export if a clip cannot be appended, as sequence would be wrong
            return False

    # --- Final Check and Write ---
    if added_clip_count == 0:
        logger.error("Export failed: No valid segments were successfully added to the export timeline.")
        return False

    logger.info(
        f"Writing {added_clip_count} clips (with gaps: {separator_gap is not None}) to '{abs_output_path}' using adapter '{adapter_name}'...")
    try:
        output_dir = os.path.dirname(abs_output_path)
        os.makedirs(output_dir, exist_ok=True)
        write_options = adapter_options or {}

        otio.adapters.write_to_file(
            export_timeline,
            abs_output_path,
            adapter_name=adapter_name,
            **write_options
        )
        logger.info(f"Successfully exported timeline to: {abs_output_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to write export file '{abs_output_path}': {e}", exc_info=True)
        return False

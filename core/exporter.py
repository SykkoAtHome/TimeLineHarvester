# core/exporter.py
import logging
import os
from collections import defaultdict
from typing import Optional, Dict, Any, List
import pathlib

import opentimelineio as otio
from opentimelineio import opentime, schema

# Import necessary models
from .models import TransferBatch, EditShot

logger = logging.getLogger(__name__)

# Mapping from common extensions to OTIO adapter names for WRITING
SUPPORTED_EXPORT_FORMATS: Dict[str, str] = {
    '.edl': 'cmx_3600',
    '.xml': 'fcp_xml',
    '.fcpxml': 'fcp_xml', # Map to fcp_xml, can be changed to fcpx_xml if needed and available
    '.aaf': 'AAF'
}


def export_transfer_batch(
        transfer_batch: TransferBatch,
        output_path: str,
        timeline_name: Optional[str] = None,
        export_format_adapter_name: Optional[str] = None,
        adapter_options: Optional[Dict[str, Any]] = None,
        separator_frames: int = 0) -> bool:
    """
    Exports the calculated segments from a TransferBatch to an EDL, XML or AAF file.
    Optionally inserts black gaps (separators) between segments.

    Args:
        transfer_batch: The calculated TransferBatch object.
        output_path: The full path for the output file.
        timeline_name: Optional name for the timeline in the exported file.
        export_format_adapter_name: Explicit OTIO adapter name. If None, detected from extension.
        adapter_options: Optional dictionary of adapter-specific write options.
        separator_frames: Number of black frames to insert between segments.

    Returns:
        True if export was successful, False otherwise.
    """
    if not transfer_batch:
        logger.error("Cannot export: Transfer batch is None.")
        return False
    if not transfer_batch.segments:
        logger.warning("Transfer batch contains no segments to export. Skipping export.")
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
    close_matches = [] # Initialize empty list for potential close matches

    if adapter_name not in available_adapters:
        # Check if a close match exists (e.g., fcpx_xml vs fcp_xml)
        close_matches = [a for a in available_adapters if adapter_name.replace('_', '') == a.replace('_', '')]
        if close_matches:
            original_adapter_name = adapter_name
            adapter_name = close_matches[0] # Use the first close match found
            logger.warning(f"Adapter '{original_adapter_name}' not found, but found close match '{adapter_name}'. Using it instead.")
        else:
            logger.error(
                f"Cannot export: OTIO adapter '{adapter_name}' is not available for writing in this environment. Available: {available_adapters}")
            return False

    # Warn if the final adapter (even if a close match) is not explicitly in our supported dict
    elif adapter_name not in SUPPORTED_EXPORT_FORMATS.values() and adapter_name not in close_matches:
        logger.warning(
            f"Exporting using potentially unsupported adapter '{adapter_name}'. Known supported: {list(SUPPORTED_EXPORT_FORMATS.values())}")

    # --- Create New OTIO Timeline ---
    # Prioritize the timeline name passed as an argument
    if timeline_name:
        export_timeline_name = timeline_name
    # Fallback to batch name or output filename if no name was passed
    elif transfer_batch.batch_name:
         export_timeline_name = transfer_batch.batch_name
    else:
        export_timeline_name = f"{os.path.splitext(os.path.basename(abs_output_path))[0]}_Timeline"

    # Determine timeline rate reliably
    timeline_rate = 25.0  # Default
    for segment in transfer_batch.segments:
        if segment.original_source and segment.original_source.frame_rate:
            timeline_rate = segment.original_source.frame_rate;
            break
        elif segment.transfer_source_range:
            timeline_rate = segment.transfer_source_range.duration.rate;
            break
    logger.info(f"Creating export timeline '{export_timeline_name}' at {timeline_rate:.3f} fps.")

    # Create the timeline object with the determined name
    export_timeline = otio.schema.Timeline(
        name=export_timeline_name,
        global_start_time=opentime.RationalTime(0, timeline_rate)
    )
    video_track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    export_timeline.tracks.append(video_track)

    # --- Create Separator Gap (if requested) ---
    separator_gap = None
    norm_sep_frames = max(0, int(separator_frames))
    if norm_sep_frames > 0:
        try:
            gap_duration = opentime.RationalTime(value=norm_sep_frames, rate=timeline_rate)
            separator_gap = schema.Gap(duration=gap_duration)
            logger.info(f"Will insert {norm_sep_frames}-frame gaps between segments.")
        except Exception as e:
            logger.error(f"Could not create separator gap object: {e}")

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

        # --- Add Separator Gap ---
        if added_clip_count > 0 and separator_gap:
            try:
                video_track.append(separator_gap.deepcopy())
                logger.debug(f"Added {norm_sep_frames}f separator gap before segment {i + 1}.")
            except Exception as gap_err:
                logger.error(f"Failed to append separator gap before segment {i + 1}: {gap_err}")

        # --- Create Media Reference URL ---
        try:
            abs_source_path = os.path.abspath(original_source.path)
            source_url = pathlib.Path(abs_source_path).as_uri()
        except Exception as url_err:
            logger.error(
                f"Skipping segment {i + 1}: Could not create file URL for path '{original_source.path}': {url_err}.")
            continue

        # --- Get Tape Name and Clip Name Base from EditShot (Prepared by Parser) ---
        base_tape_name: Optional[str] = None
        clip_name_base: str = os.path.splitext(os.path.basename(original_source.path))[0] # Fallback

        if segment.source_edit_shots:
            first_shot: EditShot = segment.source_edit_shots[0]
            if first_shot.clip_name:
                clip_name_base = first_shot.clip_name
            if first_shot.tape_name:
                base_tape_name = first_shot.tape_name
            else:
                logger.debug(f"Segment {i+1}: No tape_name found in EditShot, using source filename stem as fallback.")
                base_tape_name = os.path.splitext(os.path.basename(original_source.path))[0]
        else:
            logger.warning(f"Segment {i+1} has no linked source_edit_shots. Using source filename stem as tape name.")
            base_tape_name = os.path.splitext(os.path.basename(original_source.path))[0]

        # --- Format Tape Name based on target format (EDL vs Others) ---
        _tape_name_for_ref = base_tape_name
        _tape_name_for_meta = base_tape_name
        if adapter_name == 'cmx_3600':
            # Apply EDL formatting rules only for EDL metadata/naming
            _tape_name_for_meta = ''.join(c if c.isalnum() else '_' for c in base_tape_name.upper())[:8]

        # --- Create ExternalReference ---
        media_ref = otio.schema.ExternalReference(target_url=source_url)
        # Set the 'name' attribute after creation
        media_ref.name = _tape_name_for_ref

        # Set available_range if source is verified
        if original_source.is_verified and original_source.duration and original_source.frame_rate:
            start_tc = original_source.start_timecode or opentime.RationalTime(0, original_source.frame_rate)
            media_ref.available_range = opentime.TimeRange(start_time=start_tc, duration=original_source.duration)

        # Set standard metadata
        media_ref.metadata[' Reel Name'] = _tape_name_for_meta
        media_ref.metadata['Tape Name'] = _tape_name_for_meta

        # --- Create OTIO Clip ---
        reel_counters[_tape_name_for_meta] += 1
        event_num = reel_counters[_tape_name_for_meta]
        clip_name_in_timeline = f"{_tape_name_for_meta}_{event_num:03d}"

        otio_clip = otio.schema.Clip(
            name=clip_name_in_timeline,
            media_reference=media_ref,
            source_range=transfer_range
        )
        # Add other metadata
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
            return False # Fail entire export if one clip fails

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

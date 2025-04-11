# core/calculator.py
"""
Calculates the final TransferSegments based on verified EditShots
and OriginalSourceFiles. Handles applying handles, timebase conversions (simplified),
and segment aggregation.
"""

import logging
import os
from collections import defaultdict
from typing import List, Dict

import opentimelineio as otio

# Import utils for time and handle operations
from utils import handle_utils
# Import necessary models and utils
from .models import EditShot, OriginalSourceFile, OutputProfile, TransferSegment, TransferBatch

logger = logging.getLogger(__name__)


def calculate_transfer_batch(
        edit_shots: List[EditShot],
        handle_frames: int,
        output_profiles: List[OutputProfile],
        output_directory: str) -> TransferBatch:
    """
    Calculates the optimized TransferBatch from verified EditShots.

    Args:
        edit_shots: List of EditShots with found_original_source populated and verified.
        handle_frames: Number of handle frames to add (symmetrically).
        output_profiles: List of target output profiles.
        output_directory: Base directory for generated transfer files.

    Returns:
        A TransferBatch object containing the calculated TransferSegments.
    """
    # Initialize the batch object to store results and errors
    batch = TransferBatch(
        handle_frames=handle_frames,
        output_directory=output_directory,
        output_profiles_used=output_profiles  # Store profiles used
    )
    # Group shots by their verified original source file path
    shots_by_original_path: Dict[str, List[EditShot]] = defaultdict(list)
    for shot in edit_shots:
        # We assume only shots with verified sources are passed, but double-check
        if shot.found_original_source and shot.found_original_source.is_verified:
            shots_by_original_path[shot.found_original_source.path].append(shot)
        else:
            logger.warning(f"Shot '{shot.clip_name}' skipped during calculation: Missing verified original source.")
            batch.unresolved_shots.append(shot)  # Add to unresolved list in the batch

    if not shots_by_original_path:
        logger.warning("No shots with verified sources found to calculate transfer segments.")
        return batch  # Return the empty batch

    # --- Process each original source file ---
    for original_path, shots_for_source in shots_by_original_path.items():
        if not shots_for_source: continue  # Should not happen with defaultdict, but safety check

        original_source = shots_for_source[0].found_original_source  # Get the source object
        logger.info(
            f"Calculating segments for source: '{os.path.basename(original_path)}' ({len(shots_for_source)} shots)")

        # --- Step 1: Convert EditShot ranges to Original Source Timebase and Apply Handles ---
        # List to store tuples of (calculated_original_range_with_handles, original_edit_shot)
        ranges_in_original_timebase = []

        for shot in shots_for_source:
            try:
                # --- Timebase Conversion (Simplified) ---
                # Get rates
                edit_rate = shot.edit_media_range.start_time.rate
                original_rate = original_source.frame_rate
                if not original_rate:
                    raise ValueError("Original source frame rate is unknown.")

                # Convert edit range start and duration to original timebase
                # WARNING: This simple rescaling assumes linear mapping and ignores start TC offsets.
                # Real-world scenarios might need `otio.opentime.map_time` with start TCs.
                original_start = shot.edit_media_range.start_time.rescaled_to(original_rate)
                original_duration = shot.edit_media_range.duration.rescaled_to(original_rate)
                original_range = otio.opentime.TimeRange(original_start, original_duration)
                logger.debug(
                    f"  Shot '{shot.clip_name}': Edit range {shot.edit_media_range} -> Original range (rate {original_rate}) {original_range}")

                # --- Apply Handles ---
                # Use exclusive end time for applying handles correctly
                start_with_handles, end_exclusive_with_handles = handle_utils.apply_handles_to_range(
                    original_range.start_time,
                    original_range.end_time_exclusive(),
                    handle_frames,
                    handle_frames  # Symmetric handles
                )

                # --- Clamp Handles to Source Duration ---
                if original_source.duration:
                    zero_time = otio.opentime.RationalTime(0, original_rate)
                    # Use verified source duration as the limit (exclusive end)
                    max_time = original_source.duration  # Duration is already exclusive end relative to 0
                    clamped_start = max(zero_time, start_with_handles)
                    clamped_end_exclusive = min(max_time, end_exclusive_with_handles)

                    # Check if handles were clamped
                    if clamped_start != start_with_handles:
                        logger.warning(f"  Shot '{shot.clip_name}': Start handle clamped to source start.")
                    if clamped_end_exclusive != end_exclusive_with_handles:
                        logger.warning(f"  Shot '{shot.clip_name}': End handle clamped to source end.")

                    start_with_handles = clamped_start
                    end_exclusive_with_handles = clamped_end_exclusive
                else:
                    # This should ideally not happen if verification worked
                    logger.warning(
                        f"  Cannot clamp handles for shot '{shot.clip_name}': Original source duration unknown.")

                # --- Final Range Calculation ---
                final_duration = end_exclusive_with_handles - start_with_handles
                if final_duration.value <= 0:
                    logger.warning(
                        f"  Skipping shot '{shot.clip_name}': Resulting duration is zero or negative after handles/clamping ({final_duration}).")
                    batch.calculation_errors.append(f"Zero duration segment for {shot.clip_name} from {original_path}")
                    continue  # Skip this shot

                final_range = otio.opentime.TimeRange(start_with_handles, final_duration)
                ranges_in_original_timebase.append({'range': final_range, 'shot': shot})
                logger.debug(f"  Shot '{shot.clip_name}': Final range with handles: {final_range}")

            except Exception as e:
                msg = f"Error processing range for shot '{shot.clip_name}' (source: {original_path}): {e}"
                logger.error(msg, exc_info=True)
                batch.calculation_errors.append(msg)
                # Add shot to unresolved list if calculation failed
                if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)

        if not ranges_in_original_timebase:
            logger.warning(
                f"No valid ranges calculated for source '{original_path}' after applying handles/clamping. Skipping this source.")
            continue  # Move to the next source file

        # --- Step 2: Sort Ranges by Start Time ---
        # Sort based on the calculated start time in the original source timebase
        sorted_ranges = sorted(ranges_in_original_timebase, key=lambda x: x['range'].start_time.value)

        # --- Step 3: Aggregate Overlapping/Adjacent Segments ---
        if not sorted_ranges: continue  # Skip if list is empty

        merged_segments_data: List[Dict] = []  # Store temp data: {'range': TimeRange, 'shots': List[EditShot]}
        current_segment_data = None

        for item in sorted_ranges:
            current_range = item['range']
            current_shot = item['shot']

            if current_segment_data is None:
                # Start the first merged segment
                current_segment_data = {'range': current_range, 'shots': [current_shot]}
            else:
                # Check if the current range overlaps or is directly adjacent to the *merged* range
                # Use `end_time_exclusive()` for checks
                merged_end_exclusive = current_segment_data['range'].end_time_exclusive()
                current_start = current_range.start_time

                # Overlap or adjacency condition
                if current_start <= merged_end_exclusive:
                    # Merge: Extend the end time if the current range goes further
                    new_end_exclusive = max(merged_end_exclusive, current_range.end_time_exclusive())
                    current_segment_data['range'] = otio.opentime.TimeRange(
                        start_time=current_segment_data['range'].start_time,
                        duration=new_end_exclusive - current_segment_data['range'].start_time
                    )
                    # Add the shot to the list for this merged segment
                    current_segment_data['shots'].append(current_shot)
                    logger.debug(
                        f"  Merged shot '{current_shot.clip_name}' into existing segment. New range: {current_segment_data['range']}")
                else:
                    # Gap detected: Finalize the previous segment and start a new one
                    merged_segments_data.append(current_segment_data)
                    logger.debug(
                        f"  Finalized segment. Range: {current_segment_data['range']}, Shots: {[s.clip_name for s in current_segment_data['shots']]}")
                    # Start the new segment
                    current_segment_data = {'range': current_range, 'shots': [current_shot]}

        # Add the last processed segment
        if current_segment_data:
            merged_segments_data.append(current_segment_data)
            logger.debug(
                f"  Finalized last segment. Range: {current_segment_data['range']}, Shots: {[s.clip_name for s in current_segment_data['shots']]}")

        # --- Step 4: Create TransferSegment objects and Generate Output Paths ---
        for i, seg_data in enumerate(merged_segments_data):
            segment_index = i  # 0-based index for naming
            transfer_range = seg_data['range']
            covered_shots = seg_data['shots']

            # Generate output paths based on profiles
            try:
                output_targets = _generate_output_paths(
                    original_source,
                    transfer_range,
                    output_profiles,
                    output_directory,
                    segment_index  # Pass index for potential naming
                )
            except Exception as path_err:
                msg = f"Error generating output paths for segment {i + 1} of {original_path}: {path_err}"
                logger.error(msg)
                batch.calculation_errors.append(msg)
                # Cannot create segment without paths, add involved shots to unresolved
                for shot in covered_shots:
                    if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
                continue  # Skip creating this TransferSegment

            # Create the final TransferSegment object
            transfer_segment = TransferSegment(
                original_source=original_source,
                transfer_source_range=transfer_range,
                output_targets=output_targets,
                source_edit_shots=covered_shots,
                status="calculated"  # Mark as ready for transcoding
            )
            batch.segments.append(transfer_segment)

    logger.info(f"Calculation finished. Generated {len(batch.segments)} total TransferSegments.")
    if batch.calculation_errors:
        logger.warning(f"Calculation completed with {len(batch.calculation_errors)} errors.")
    if batch.unresolved_shots:
        logger.warning(f"{len(batch.unresolved_shots)} shots remain unresolved or had errors.")

    return batch


def _generate_output_paths(
        original_source: OriginalSourceFile,
        transfer_range: otio.opentime.TimeRange,
        output_profiles: List[OutputProfile],
        output_directory: str,
        segment_index: int) -> Dict[str, str]:
    """
    Generates output file paths for a segment and profiles.
    Creates necessary subdirectories.

    Args:
        original_source: The source file object.
        transfer_range: The calculated range (with handles) in original timebase.
        output_profiles: List of target profiles.
        output_directory: The base output directory.
        segment_index: The 0-based index of this segment for the source file.

    Returns:
        Dictionary mapping profile name to absolute output file path.

    Raises:
        OSError: If subdirectory creation fails.
    """
    output_targets = {}
    # Use original filename stem for output name
    base_filename, _ = os.path.splitext(os.path.basename(original_source.path))
    # Format start time (e.g., frame number) - ensure rate is valid
    start_frame = 0
    if transfer_range.start_time.rate > 0:
        try:
            start_frame = transfer_range.start_time.to_frames()
        except:  # Fallback if conversion fails
            start_frame = int(transfer_range.start_time.value)  # Use raw value as fallback

    segment_label = f"SEG{segment_index + 1:03d}_F{start_frame}"  # e.g., SEG001_F1234

    for profile in output_profiles:
        # Create a subdirectory for each profile within the main output dir
        profile_dir = os.path.join(output_directory, profile.name)
        try:
            os.makedirs(profile_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create output subdirectory '{profile_dir}': {e}")
            raise  # Re-raise error to stop calculation for this segment

        # Construct filename: SourceName_SEGxxx_Fyyyyy_ProfileName.ext
        filename = f"{base_filename}_{segment_label}_{profile.name}.{profile.extension}"
        output_path = os.path.abspath(os.path.join(profile_dir, filename))
        output_targets[profile.name] = output_path
        logger.debug(f"  Generated output target: {output_path}")

    return output_targets

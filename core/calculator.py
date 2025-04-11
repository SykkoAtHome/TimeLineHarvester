# core/calculator.py
"""
Calculates TransferSegments based on verified EditShots and OriginalSourceFiles.
Handles applying handles, timebase conversions (simplified frame mapping),
and segment aggregation for Color Prep stage (EDL/XML export).
"""

import logging
import os
from collections import defaultdict
from typing import List, Dict, Tuple  # Added Tuple

from opentimelineio import opentime  # Explicit import

# Import utils for time and handle operations
from utils import handle_utils
# Import necessary models
from .models import EditShot, TransferSegment, TransferBatch

logger = logging.getLogger(__name__)


def calculate_transfer_batch(
        edit_shots: List[EditShot],
        handle_frames: int,
) -> TransferBatch:
    """
    Calculates the optimized TransferBatch for Color Prep (EDL/XML export).

    Args:
        edit_shots: List of EditShots with verified original sources.
        handle_frames: Number of handle frames (symmetric).

    Returns:
        A TransferBatch object with calculated TransferSegments.
    """
    logger.info(f"Starting calculation for Color Prep Transfer Batch with {handle_frames} handles.")
    batch = TransferBatch(handle_frames=handle_frames, batch_name="ColorPrepBatch")
    shots_by_original_path: Dict[str, List[EditShot]] = defaultdict(list)
    valid_shots_for_calc = 0

    # --- Pre-filter and Group Shots ---
    for shot in edit_shots:
        if not (shot.lookup_status == 'found' and shot.found_original_source and
                shot.found_original_source.is_verified and
                shot.found_original_source.duration and shot.found_original_source.frame_rate and
                shot.edit_media_range and shot.edit_media_range.duration.value > 0):
            # Log reason for skipping if not already logged by finder
            if shot.lookup_status != 'found':
                logger.debug(f"Skipping '{shot.clip_name}': Status not 'found'.")
            elif not shot.found_original_source:
                logger.debug(f"Skipping '{shot.clip_name}': Missing linked original source.")
            elif not shot.found_original_source.is_verified:
                logger.debug(f"Skipping '{shot.clip_name}': Original source not verified.")
            elif not shot.found_original_source.duration:
                logger.debug(f"Skipping '{shot.clip_name}': Original source missing duration.")
            elif not shot.found_original_source.frame_rate:
                logger.debug(f"Skipping '{shot.clip_name}': Original source missing frame rate.")
            elif not shot.edit_media_range or shot.edit_media_range.duration.value <= 0:
                logger.debug(f"Skipping '{shot.clip_name}': Invalid edit range.")

            if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
            continue
        shots_by_original_path[shot.found_original_source.path].append(shot)
        valid_shots_for_calc += 1

    logger.info(
        f"Processing {valid_shots_for_calc} valid EditShots grouped by {len(shots_by_original_path)} original source files.")
    if not shots_by_original_path: return batch

    # --- Process Each Original Source ---
    for original_path, shots_for_source in shots_by_original_path.items():
        original_source = shots_for_source[0].found_original_source
        original_rate = original_source.frame_rate
        source_duration = original_source.duration
        source_start_tc = original_source.start_timecode or opentime.RationalTime(0, original_rate)

        logger.debug(
            f"Calculating for source: '{os.path.basename(original_path)}' (Rate: {original_rate}, Dur: {source_duration}, StartTC: {source_start_tc})")

        # --- Step 1: Calculate Handled Range in Original Timebase for each shot ---
        handled_ranges_to_merge: List[Tuple[opentime.TimeRange, EditShot]] = []
        for shot in shots_for_source:
            try:
                # --- Timebase/Timecode Conversion (Revised Simplified Logic) ---
                edit_start_time = shot.edit_media_range.start_time
                edit_duration = shot.edit_media_range.duration

                # Convert edit start time (relative to proxy start) to original's rate
                original_start_relative = edit_start_time.rescaled_to(original_rate)
                # Convert edit duration to original's rate
                original_duration = edit_duration.rescaled_to(original_rate)

                # Calculate absolute start time in original source
                # Assumes edit_start_time is offset from proxy's assumed 00:00:00:00 start
                # Adds this offset to the original's actual start timecode
                original_absolute_start_time = source_start_tc + original_start_relative

                # Define the range *without* handles in the original source's time context
                original_range_no_handles = opentime.TimeRange(
                    start_time=original_absolute_start_time,
                    duration=original_duration
                )
                logger.debug(f"  Shot '{shot.clip_name}': Edit range {shot.edit_media_range} "
                             f"-> Approx Original range (no handles) {original_range_no_handles}")

                # --- Apply Handles & Clamp ---
                start_h, end_h_exc = handle_utils.apply_handles_to_range(
                    original_range_no_handles.start_time,
                    original_range_no_handles.end_time_exclusive(),
                    handle_frames, handle_frames
                )

                # Clamp to [source_start_tc, source_start_tc + source_duration)
                clamped_start = max(source_start_tc, start_h)
                clamped_end_exc = min(source_start_tc + source_duration, end_h_exc)

                if clamped_start != start_h: logger.debug(f"  Shot '{shot.clip_name}': Start handle clamped.")
                if clamped_end_exc != end_h_exc: logger.debug(f"  Shot '{shot.clip_name}': End handle clamped.")

                final_duration = clamped_end_exc - clamped_start
                if final_duration.value <= 0:
                    msg = f"Zero/negative duration after handles/clamping for shot '{shot.clip_name}'"
                    logger.warning(f"  Skipping shot: {msg} ({final_duration}).")
                    batch.calculation_errors.append(msg + f" from {original_path}")
                    if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
                    continue

                final_range_with_handles = opentime.TimeRange(clamped_start, final_duration)
                handled_ranges_to_merge.append((final_range_with_handles, shot))
                logger.debug(f"  Shot '{shot.clip_name}': Calculated handled range: {final_range_with_handles}")

            except Exception as e:
                msg = f"Error processing range for shot '{shot.clip_name}': {e}"
                logger.error(msg, exc_info=True)
                batch.calculation_errors.append(msg + f" from {original_path}")
                if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)

        if not handled_ranges_to_merge:
            logger.warning(f"No valid handled ranges calculated for source '{original_path}'. Skipping source.")
            continue

        # --- Step 2: Sort Handled Ranges by Start Time ---
        sorted_handled_ranges = sorted(handled_ranges_to_merge, key=lambda x: x[0].start_time)

        # --- Step 3: Aggregate Overlapping/Adjacent Segments ---
        if not sorted_handled_ranges: continue

        aggregated_segments_data: List[Dict] = []  # Store {'range': TimeRange, 'shots': List[EditShot]}
        # Initialize with the first sorted range
        current_agg_range = sorted_handled_ranges[0][0]
        current_agg_shots = [sorted_handled_ranges[0][1]]  # Store the EditShot(s)

        for i in range(1, len(sorted_handled_ranges)):
            next_range_with_handles = sorted_handled_ranges[i][0]
            next_shot = sorted_handled_ranges[i][1]

            # Check overlap/adjacency: does the next range start at or before the current one ends?
            if next_range_with_handles.start_time <= current_agg_range.end_time_exclusive():
                # Merge: Extend the end time
                new_end_time = max(current_agg_range.end_time_exclusive(), next_range_with_handles.end_time_exclusive())
                current_agg_range = opentime.TimeRange(
                    start_time=current_agg_range.start_time,
                    duration=new_end_time - current_agg_range.start_time
                )
                current_agg_shots.append(next_shot)  # Add the shot that caused the merge
            else:
                # Gap: Finalize the previous segment
                aggregated_segments_data.append({'range': current_agg_range, 'shots': current_agg_shots})
                # Start a new segment
                current_agg_range = next_range_with_handles
                current_agg_shots = [next_shot]

        # Add the last aggregated segment
        if current_agg_range:
            aggregated_segments_data.append({'range': current_agg_range, 'shots': current_agg_shots})

        # --- Step 4: Create TransferSegment objects ---
        for i, seg_data in enumerate(aggregated_segments_data):
            final_transfer_range = seg_data['range']
            covered_shots = seg_data['shots']

            transfer_segment = TransferSegment(
                original_source=original_source,
                transfer_source_range=final_transfer_range,
                output_targets={},  # Not used for color prep export
                source_edit_shots=covered_shots,
                status="calculated"
            )
            batch.segments.append(transfer_segment)
            logger.debug(
                f"  Created TransferSegment #{i + 1}: Range={final_transfer_range}, Covered Shots={len(covered_shots)}")

    logger.info(f"Calculation finished. Generated {len(batch.segments)} total TransferSegments for Color Prep.")
    if batch.calculation_errors: logger.warning(f"Calculation completed with {len(batch.calculation_errors)} errors.")
    if batch.unresolved_shots: logger.warning(f"{len(batch.unresolved_shots)} shots remain unresolved or had errors.")

    return batch

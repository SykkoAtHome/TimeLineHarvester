# core/calculator.py
"""
Calculates TransferSegments based on verified EditShots and OriginalSourceFiles.
Handles applying handles, timebase conversions (simplified frame mapping),
segment aggregation, and splitting based on gap threshold for Color Prep.
"""

import logging
import os
from collections import defaultdict
from typing import List, Dict, Tuple, Optional  # Added Optional

from opentimelineio import opentime  # Explicit import

# Import utils for time and handle operations
from utils import handle_utils
# Import necessary models
from .models import EditShot, TransferSegment, TransferBatch

logger = logging.getLogger(__name__)


def calculate_transfer_batch(
        edit_shots: List[EditShot],
        handle_frames: int,
        split_gap_threshold_frames: int  # <<< NEW PARAMETER
) -> TransferBatch:
    """
    Calculates the optimized TransferBatch for Color Prep (EDL/XML export),
    optionally splitting segments if the gap exceeds a threshold.

    Args:
        edit_shots: List of EditShots with verified original sources.
        handle_frames: Number of handle frames (symmetric).
        split_gap_threshold_frames: Max allowed gap in frames between handled segments
                                     before splitting into a new TransferSegment.
                                     A value < 0 disables splitting.

    Returns:
        A TransferBatch object with calculated TransferSegments.
    """
    logger.info(
        f"Starting Transfer Batch calculation. Handles: {handle_frames}f, Split Gap Threshold: {split_gap_threshold_frames}f.")
    batch = TransferBatch(handle_frames=handle_frames, batch_name="ColorPrepBatch")  # Store handles in batch
    shots_by_original_path: Dict[str, List[EditShot]] = defaultdict(list)
    valid_shots_for_calc = 0

    # --- Pre-filter and Group Shots (No changes here) ---
    for shot in edit_shots:
        # ... (filtering logic remains the same) ...
        if not (shot.lookup_status == 'found' and shot.found_original_source and
                shot.found_original_source.is_verified and
                shot.found_original_source.duration and shot.found_original_source.frame_rate and
                shot.edit_media_range and shot.edit_media_range.duration.value > 0):
            # ... (logging skipped shots) ...
            if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
            continue
        shots_by_original_path[shot.found_original_source.path].append(shot)
        valid_shots_for_calc += 1

    logger.info(
        f"Processing {valid_shots_for_calc} valid EditShots grouped by {len(shots_by_original_path)} original source files.")
    if not shots_by_original_path: return batch

    # --- Process Each Original Source ---
    for original_path, shots_for_source in shots_by_original_path.items():
        if not shots_for_source: continue  # Should not happen with defaultdict, but safe check

        original_source = shots_for_source[0].found_original_source
        original_rate = original_source.frame_rate
        source_duration = original_source.duration
        source_start_tc = original_source.start_timecode or opentime.RationalTime(0, original_rate)

        # Validate essential source info needed for calculation
        if not original_rate or original_rate <= 0 or not source_duration or source_duration.value <= 0:
            msg = f"Skipping source '{os.path.basename(original_path)}' due to invalid rate ({original_rate}) or duration ({source_duration})."
            logger.error(msg)
            batch.calculation_errors.append(msg)
            # Add all shots from this source to unresolved
            for shot in shots_for_source:
                if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
                shot.lookup_status = "error"  # Mark as error since source is unusable
            continue  # Skip to next source

        logger.debug(
            f"Calculating for source: '{os.path.basename(original_path)}' (Rate: {original_rate}, Dur: {source_duration}, StartTC: {source_start_tc})")

        # --- Step 1: Calculate Handled Range in Original Timebase for each shot ---
        handled_ranges_to_merge: List[Tuple[opentime.TimeRange, EditShot]] = []
        for shot in shots_for_source:
            try:
                # ... (Timebase/Timecode Conversion - no changes here) ...
                edit_start_time = shot.edit_media_range.start_time
                edit_duration = shot.edit_media_range.duration
                original_start_relative = edit_start_time.rescaled_to(original_rate)
                original_duration = edit_duration.rescaled_to(original_rate)
                original_absolute_start_time = source_start_tc + original_start_relative
                original_range_no_handles = opentime.TimeRange(
                    start_time=original_absolute_start_time, duration=original_duration)
                # logger.debug(f"  Shot '{shot.clip_name}': Edit range {shot.edit_media_range} -> Approx Original (no handles) {original_range_no_handles}") # Optional detailed log

                # --- Apply Handles & Clamp (No changes here) ---
                # Using symmetric handles for now, based on handle_frames input
                start_h, end_h_exc = handle_utils.apply_handles_to_range(
                    original_range_no_handles.start_time,
                    original_range_no_handles.end_time_exclusive(),
                    handle_frames, handle_frames  # Apply symmetric handles
                )
                clamped_start = max(source_start_tc, start_h)
                clamped_end_exc = min(source_start_tc + source_duration, end_h_exc)

                # ... (Logging clamping, checking zero duration - no changes) ...
                final_duration = clamped_end_exc - clamped_start
                if final_duration.value <= 0:
                    msg = f"Zero/negative duration after handles/clamping for shot '{shot.clip_name}'"
                    logger.warning(
                        f"  Skipping shot: {msg} ({final_duration}). Original range: {original_range_no_handles}, Handled: {start_h}-{end_h_exc}")
                    batch.calculation_errors.append(msg + f" from {original_path}")
                    if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
                    continue

                final_range_with_handles = opentime.TimeRange(clamped_start, final_duration)
                handled_ranges_to_merge.append((final_range_with_handles, shot))
                logger.debug(f"  Shot '{shot.clip_name}': Calculated handled range: {final_range_with_handles}")

            except Exception as e:
                # ... (Error handling for individual shot processing - no changes) ...
                msg = f"Error processing range for shot '{shot.clip_name}': {e}"
                logger.error(msg, exc_info=True)
                batch.calculation_errors.append(msg + f" from {original_path}")
                if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)

        if not handled_ranges_to_merge:
            logger.warning(f"No valid handled ranges calculated for source '{original_path}'. Skipping aggregation.")
            continue

        # --- Step 2: Sort Handled Ranges by Start Time ---
        sorted_handled_ranges = sorted(handled_ranges_to_merge, key=lambda x: x[0].start_time)

        # --- Step 3: Aggregate Overlapping/Adjacent Segments (with Gap Splitting) ---
        aggregated_segments_data: List[Dict] = []
        if not sorted_handled_ranges: continue  # Should be redundant after check above

        # Initialize with the first sorted range
        current_agg_range = sorted_handled_ranges[0][0]
        current_agg_shots = [sorted_handled_ranges[0][1]]
        logger.debug(f"  Starting aggregation with range: {current_agg_range}")

        # Determine if splitting is enabled based on the threshold
        split_enabled = (split_gap_threshold_frames >= 0)
        max_gap_time: Optional[opentime.RationalTime] = None
        if split_enabled:
            try:
                # Use the rate determined for this source
                if original_rate > 0:
                    max_gap_time = opentime.RationalTime(split_gap_threshold_frames, original_rate)
                    logger.debug(f"  Splitting enabled. Max gap time: {max_gap_time}")
                else:  # Should have been caught earlier, but handle defensively
                    logger.error("  Cannot enable splitting: Invalid original source rate (<=0).")
                    split_enabled = False
            except Exception as e:
                logger.error(
                    f"  Error creating max_gap_time ({split_gap_threshold_frames}f @ {original_rate}fps): {e}. Disabling splitting.")
                split_enabled = False

        for i in range(1, len(sorted_handled_ranges)):
            next_range_with_handles, next_shot = sorted_handled_ranges[i]
            logger.debug(f"  Considering next range: {next_range_with_handles} (Shot: '{next_shot.clip_name}')")

            # Calculate the gap between the *end* of the current aggregated range
            # and the *start* of the next handled range.
            # Both ranges already include handles.
            gap_duration = next_range_with_handles.start_time - current_agg_range.end_time_exclusive()
            logger.debug(f"    Gap duration to next range: {gap_duration}")

            # Determine if we should merge based on the gap and the threshold
            should_merge = False
            if gap_duration.value <= 0:
                # Overlap or touching: Always merge
                should_merge = True
                logger.debug("    Ranges overlap or touch. Merging.")
            elif not split_enabled:
                # Splitting is disabled, and there's a positive gap: Don't merge
                should_merge = False
                logger.debug("    Positive gap exists and splitting is disabled. Not merging.")
            elif max_gap_time is not None and gap_duration <= max_gap_time:
                # Splitting is enabled, and the positive gap is within the threshold: Merge
                should_merge = True
                logger.debug(f"    Gap ({gap_duration}) is within threshold ({max_gap_time}). Merging.")
            else:
                # Splitting is enabled, and the positive gap exceeds the threshold: Don't merge
                should_merge = False
                logger.debug(f"    Gap ({gap_duration}) exceeds threshold ({max_gap_time}). Splitting segment.")

            # Perform action based on merge decision
            if should_merge:
                # Merge: Extend the end time of the current aggregated range
                new_end_time = max(current_agg_range.end_time_exclusive(), next_range_with_handles.end_time_exclusive())
                current_agg_range = opentime.TimeRange(
                    start_time=current_agg_range.start_time,
                    duration=new_end_time - current_agg_range.start_time
                )
                current_agg_shots.append(next_shot)  # Add the shot that caused the merge
                logger.debug(f"    Merged. New aggregated range: {current_agg_range}")
            else:
                # Don't Merge (Gap too large or splitting disabled with positive gap):
                # Finalize the previous segment
                logger.debug(f"  Finalizing segment: Range={current_agg_range}, Shots={len(current_agg_shots)}")
                aggregated_segments_data.append({'range': current_agg_range, 'shots': current_agg_shots})
                # Start a new segment with the next range
                current_agg_range = next_range_with_handles
                current_agg_shots = [next_shot]
                logger.debug(f"  Starting new segment: Range={current_agg_range}, Shots=1")

        # Add the last aggregated segment after the loop finishes
        if current_agg_range:
            logger.debug(f"  Finalizing last segment: Range={current_agg_range}, Shots={len(current_agg_shots)}")
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
                f"  Created TransferSegment #{i + 1}/{len(aggregated_segments_data)}: Range={final_transfer_range}, Covered Shots={len(covered_shots)}")

    logger.info(
        f"Calculation finished for batch '{batch.batch_name}'. Generated {len(batch.segments)} TransferSegments.")
    if batch.calculation_errors: logger.warning(f"Calculation completed with {len(batch.calculation_errors)} errors.")
    if batch.unresolved_shots: logger.warning(f"{len(batch.unresolved_shots)} shots remain unresolved or had errors.")

    return batch

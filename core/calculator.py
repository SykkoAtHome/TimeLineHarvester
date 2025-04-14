# core/calculator.py
"""
Calculates TransferSegments based on verified EditShots and OriginalSourceFiles.
Groups EditShots based on unhandled gaps, then applies handles to the aggregated groups.
Handles segment splitting based on the gap threshold *before* handles are applied.
"""

import logging
import os
from collections import defaultdict
from typing import List, Dict

from opentimelineio import opentime

# Import utils for time and handle operations
from utils import handle_utils
# Import necessary models
from .models import EditShot, TransferSegment, TransferBatch

logger = logging.getLogger(__name__)


def calculate_transfer_batch(
        edit_shots: List[EditShot],
        handle_frames: int,
        split_gap_threshold_frames: int
) -> TransferBatch:
    """
    Calculates the optimized TransferBatch for Color Prep (EDL/XML export).

    This version groups EditShots based on the gap between their original
    media ranges (before handles). If the unhandled gap exceeds the threshold,
    the shots are split into separate groups. Handles are then applied to the
    aggregated time range of each group.

    Args:
        edit_shots: List of EditShots with verified original sources.
        handle_frames: Number of handle frames (symmetric).
        split_gap_threshold_frames: Max allowed gap in frames between the original
                                     (unhandled) EditShot media ranges before splitting
                                     into a new group. A value < 0 disables splitting.

    Returns:
        A TransferBatch object with calculated TransferSegments.
    """
    logger.info(
        f"Starting Transfer Batch calculation. Handles: {handle_frames}f, "
        f"Split Gap Threshold (unhandled): {split_gap_threshold_frames}f."
    )
    batch = TransferBatch(handle_frames=handle_frames, batch_name="ColorPrepBatch")
    shots_by_original_path: Dict[str, List[EditShot]] = defaultdict(list)
    valid_shots_for_calc = 0

    # --- Pre-filter and Group Shots ---
    for shot in edit_shots:
        # Filter shots that have verified original sources and valid ranges
        if not (shot.lookup_status == 'found' and shot.found_original_source and
                shot.found_original_source.is_verified and
                shot.found_original_source.duration and shot.found_original_source.frame_rate and
                shot.edit_media_range and shot.edit_media_range.duration.value > 0):

            # Track unresolved shots
            if shot not in batch.unresolved_shots:
                batch.unresolved_shots.append(shot)
            continue

        shots_by_original_path[shot.found_original_source.path].append(shot)
        valid_shots_for_calc += 1

    logger.info(
        f"Processing {valid_shots_for_calc} valid EditShots grouped by "
        f"{len(shots_by_original_path)} original source files."
    )
    if not shots_by_original_path:
        return batch

    # --- Process Each Original Source ---
    for original_path, shots_for_source in shots_by_original_path.items():
        if not shots_for_source:
            continue

        original_source = shots_for_source[0].found_original_source
        original_rate = original_source.frame_rate
        source_duration = original_source.duration
        source_start_tc = original_source.start_timecode or opentime.RationalTime(0, original_rate)

        # Validate essential source info needed for calculation
        if not original_rate or original_rate <= 0 or not source_duration or source_duration.value <= 0:
            msg = (f"Skipping source '{os.path.basename(original_path)}' due to invalid rate "
                   f"({original_rate}) or duration ({source_duration}).")
            logger.error(msg)
            batch.calculation_errors.append(msg)
            for shot in shots_for_source:
                if shot not in batch.unresolved_shots:
                    batch.unresolved_shots.append(shot)
                shot.lookup_status = "error"
            continue

        # Calculate source boundaries for clamping (in frame space)
        source_start_frame = int(source_start_tc.value)
        source_end_frame = int(source_start_tc.value + source_duration.value)

        logger.info(
            f"Calculating for source: '{os.path.basename(original_path)}' (Rate: {original_rate}, "
            f"Dur: {source_duration}, StartTC: {source_start_tc}, "
            f"Frames: {source_start_frame}-{source_end_frame})"
        )

        # --- Step 1: Sort EditShots by Unhandled Start Time ---
        try:
            # Sort by the start time of the media range *as used in the edit*
            sorted_shots = sorted(
                shots_for_source,
                key=lambda s: s.edit_media_range.start_time.value if s.edit_media_range else float('inf')
            )
        except Exception as sort_err:
            msg = f"Error sorting EditShots for source '{os.path.basename(original_path)}': {sort_err}"
            logger.error(msg, exc_info=True)
            batch.calculation_errors.append(msg)
            for shot in shots_for_source:
                if shot not in batch.unresolved_shots:
                    batch.unresolved_shots.append(shot)
            continue

        # --- Step 2: Group Shots Based on Unhandled Gap Threshold ---
        list_of_shot_groups: List[List[EditShot]] = []
        if not sorted_shots:
            logger.warning(f"No valid shots to group for source '{os.path.basename(original_path)}'.")
            continue

        # Initialize with the first shot
        current_group: List[EditShot] = [sorted_shots[0]]
        logger.debug(f"  Starting new shot group with shot: '{sorted_shots[0].clip_name}'")

        # Determine if splitting is enabled based on the threshold
        split_enabled = (split_gap_threshold_frames >= 0)
        max_gap_frames = split_gap_threshold_frames if split_enabled else -1

        for i in range(1, len(sorted_shots)):
            last_shot_in_group = current_group[-1]
            next_shot = sorted_shots[i]

            # Calculate the gap between the *original* edit ranges (unhandled)
            gap_unhandled_frames = float('inf')  # Default to large gap if error occurs
            try:
                # Ensure times are comparable (same rate)
                last_range = last_shot_in_group.edit_media_range
                next_range = next_shot.edit_media_range

                if last_range.start_time.rate != original_rate:
                    last_range = opentime.TimeRange(
                        start_time=last_range.start_time.rescaled_to(original_rate),
                        duration=last_range.duration.rescaled_to(original_rate)
                    )
                if next_range.start_time.rate != original_rate:
                    next_range = opentime.TimeRange(
                        start_time=next_range.start_time.rescaled_to(original_rate),
                        duration=next_range.duration.rescaled_to(original_rate)
                    )

                last_end_frame_unhandled = int(last_range.end_time_exclusive().value)
                next_start_frame_unhandled = int(next_range.start_time.value)
                gap_unhandled_frames = next_start_frame_unhandled - last_end_frame_unhandled
                logger.debug(
                    f"  Comparing group ending with '{last_shot_in_group.clip_name}' to '{next_shot.clip_name}'"
                )
                logger.debug(f"    Gap between original edits (unhandled): {gap_unhandled_frames}f")

            except Exception as gap_calc_err:
                logger.error(f"    Error calculating unhandled gap: {gap_calc_err}")
                # Treat calculation error as a reason to split
                gap_unhandled_frames = float('inf')

            # Determine if we should merge based on the unhandled gap and threshold
            should_merge = False
            if gap_unhandled_frames <= 0:
                # Original edits overlap or touch: Always merge into the group
                should_merge = True
                logger.debug("    Original edits overlap or touch. Merging shot into group.")
            elif not split_enabled:
                # Splitting is disabled, and there's a positive gap: Always merge
                should_merge = True
                logger.debug("    Positive unhandled gap exists but splitting is disabled. Merging shot into group.")
            elif gap_unhandled_frames <= max_gap_frames:
                # Splitting is enabled, and the unhandled gap is within the threshold: Merge
                should_merge = True
                logger.debug(
                    f"    Unhandled gap ({gap_unhandled_frames}f) is within user threshold ({max_gap_frames}f). "
                    f"Merging shot into group."
                )
            else:
                # Splitting is enabled, and the unhandled gap exceeds the threshold: Don't merge
                should_merge = False
                logger.debug(
                    f"    Unhandled gap ({gap_unhandled_frames}f) exceeds user threshold ({max_gap_frames}f). "
                    f"Splitting."
                )

            # Perform action based on merge decision
            if should_merge:
                # Merge: Add the next shot to the current group
                current_group.append(next_shot)
                logger.debug(f"    Merged '{next_shot.clip_name}' into current group (size: {len(current_group)}).")
            else:
                # Don't Merge: Finalize the previous group and start a new one
                logger.debug(f"  Finalizing group with {len(current_group)} shot(s).")
                list_of_shot_groups.append(current_group)
                # Start a new group with the next shot
                current_group = [next_shot]
                logger.debug(f"  Starting new shot group with shot: '{next_shot.clip_name}'")

        # Add the last group after the loop finishes
        if current_group:
            logger.debug(f"  Finalizing last group with {len(current_group)} shot(s).")
            list_of_shot_groups.append(current_group)

        logger.info(f"Grouped shots into {len(list_of_shot_groups)} segment group(s) for this source.")

        # --- Step 3: Create TransferSegments from Shot Groups ---
        segment_counters = defaultdict(int)
        base_filename = os.path.splitext(os.path.basename(original_path))[0]

        for i, shot_group in enumerate(list_of_shot_groups):
            group_index = i + 1
            try:
                # 1. Find min/max of the ORIGINAL edit ranges within the group
                # Ensure all ranges use the original_rate for comparison
                group_ranges = [s.edit_media_range.rescaled_to(
                    original_rate) if s.edit_media_range.start_time.rate != original_rate else s.edit_media_range for s
                                in shot_group]

                min_start_rt = min(r.start_time for r in group_ranges)
                max_end_rt_excl = max(r.end_time_exclusive() for r in group_ranges)

                # Create the combined unhandled range
                unhandled_range = opentime.TimeRange(
                    start_time=min_start_rt,
                    duration=max_end_rt_excl - min_start_rt
                )
                logger.debug(f"  Group {group_index}: Combined unhandled range: {unhandled_range}")

                # 2. Apply handles to the combined unhandled range
                handled_start, handled_end_exclusive = handle_utils.apply_handles_to_range(
                    unhandled_range.start_time,
                    unhandled_range.end_time_exclusive(),
                    handle_frames,  # Use the globally passed handle_frames
                    handle_frames  # Assume symmetric for now
                )

                # 3. Clamp the handled range to the source file's boundaries
                final_start_frame = max(source_start_frame, int(handled_start.value))
                final_end_frame = min(source_end_frame, int(handled_end_exclusive.value))

                # Validate the final frame range
                if final_end_frame <= final_start_frame:
                    logger.warning(
                        f"  Group {group_index}: Invalid frame range after handles/clamping "
                        f"({final_start_frame}-{final_end_frame}). Skipping group."
                    )
                    # Add shots to unresolved? Or just log? Logged for now.
                    for shot in shot_group:
                        if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
                        shot.lookup_status = "error"  # Mark as error due to calculation issue
                    continue  # Skip creating segment for this group

                # Convert clamped frame range back to TimeRange
                final_transfer_range = opentime.TimeRange(
                    start_time=opentime.RationalTime(final_start_frame, original_rate),
                    duration=opentime.RationalTime(final_end_frame - final_start_frame, original_rate)
                )
                logger.debug(f"  Group {group_index}: Final handled & clamped range: {final_transfer_range}")

                # 4. Generate segment ID (add suffix if needed)
                segment_counters[base_filename] += 1

                # POPRAWKA - Lepsze wybieranie nazwy segmentu
                # Użyj clip_name jako podstawy, jeśli jest dostępny
                segment_id = base_filename
                if shot_group and len(shot_group) > 0:
                    representative_shot = shot_group[0]
                    if representative_shot.clip_name:
                        # Użyj nazwy pierwszego shota jako bazowej nazwy segmentu
                        segment_id = representative_shot.clip_name

                # Dodaj sufiks tylko jeśli jest więcej niż jeden segment dla tego źródła
                if len(list_of_shot_groups) > 1:
                    segment_id = f"{segment_id}_seg{segment_counters[base_filename]}"

                # 5. Create the TransferSegment
                transfer_segment = TransferSegment(
                    original_source=original_source,
                    transfer_source_range=final_transfer_range,
                    output_targets={},  # Populated later if needed (e.g., for transcoding)
                    source_edit_shots=shot_group,  # Link back to the shots in this group
                    status="calculated",
                    segment_id=segment_id  # Store the generated ID
                )

                # Add metadata to segment if needed (though segment_id field exists)
                # if not hasattr(transfer_segment, 'metadata'): transfer_segment.metadata = {}
                # transfer_segment.metadata['segment_id'] = segment_id

                batch.segments.append(transfer_segment)
                logger.debug(
                    f"  Created TransferSegment #{group_index}/{len(list_of_shot_groups)}: ID={segment_id}, "
                    f"Range={final_transfer_range}, Covered Shots={len(shot_group)}"
                )

            except Exception as group_proc_err:
                msg = f"Error processing shot group {group_index} for source '{base_filename}': {group_proc_err}"
                logger.error(msg, exc_info=True)
                batch.calculation_errors.append(msg)
                for shot in shot_group:  # Mark all shots in the failed group as unresolved/error
                    if shot not in batch.unresolved_shots: batch.unresolved_shots.append(shot)
                    shot.lookup_status = "error"  # Mark as error due to calculation issue

    # --- Final Logging ---
    logger.info(
        f"Calculation finished for batch '{batch.batch_name}'. Generated {len(batch.segments)} TransferSegments."
    )
    if batch.calculation_errors:
        logger.warning(f"Calculation completed with {len(batch.calculation_errors)} errors.")
    if batch.unresolved_shots:
        # Ensure unresolved list is unique
        unique_unresolved = []
        seen_ids = set()
        for shot in batch.unresolved_shots:
            if id(shot) not in seen_ids:
                unique_unresolved.append(shot)
                seen_ids.add(id(shot))
        batch.unresolved_shots = unique_unresolved
        logger.warning(f"{len(batch.unresolved_shots)} shots remain unresolved or had errors during calculation.")

    return batch

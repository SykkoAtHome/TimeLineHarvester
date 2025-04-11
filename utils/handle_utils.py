# utils/handle_utils.py
"""
Handle Utilities Module

Provides functions for normalizing handle values and applying them to time ranges.
"""

import logging
from typing import Optional, Tuple
import opentimelineio as otio

# Import from sibling module within the same package
from .time_utils import ensure_non_negative_time

logger = logging.getLogger(__name__)


def normalize_handles(start_handles: int, end_handles: Optional[int] = None) -> Tuple[int, int]:
    """
    Normalizes handle values, ensuring they are non-negative integers.
    If end_handles is None, it defaults to start_handles.

    Args:
        start_handles: Requested start handle frames.
        end_handles: Requested end handle frames (optional).

    Returns:
        Tuple of (normalized_start_handles, normalized_end_handles).
    """
    try:
        norm_start = max(0, int(start_handles))
    except (ValueError, TypeError):
        logger.warning(f"Invalid start_handles value '{start_handles}', defaulting to 0.")
        norm_start = 0

    if end_handles is None:
        norm_end = norm_start
    else:
        try:
            norm_end = max(0, int(end_handles))
        except (ValueError, TypeError):
            logger.warning(f"Invalid end_handles value '{end_handles}', defaulting to start handle value {norm_start}.")
            norm_end = norm_start

    return norm_start, norm_end


def _add_handle_frames_to_time(time_value: otio.opentime.RationalTime,
                               handle_frames: int,
                               is_start: bool = True) -> otio.opentime.RationalTime:
    """Internal helper to add/subtract handle frames, ensuring non-negative result for start."""
    if handle_frames == 0:
        return time_value
    if time_value.rate <= 0:
        logger.warning(f"Cannot apply handles to time with zero rate: {time_value}")
        return time_value  # Cannot modify if rate is invalid

    handle_time = otio.opentime.RationalTime(handle_frames, time_value.rate)

    if is_start:
        # Subtract handle for start time
        result = time_value - handle_time
        return ensure_non_negative_time(result)  # Clamp at zero
    else:
        # Add handle for end time
        return time_value + handle_time


def apply_handles_to_range(start_time: otio.opentime.RationalTime,
                           end_time_exclusive: otio.opentime.RationalTime,
                           start_handles: int,
                           end_handles: int) -> Tuple[otio.opentime.RationalTime, otio.opentime.RationalTime]:
    """
    Applies normalized handles to a time range defined by start and *exclusive* end time.

    Args:
        start_time: Start time of the original range.
        end_time_exclusive: Exclusive end time of the original range (start + duration).
        start_handles: Number of frames to add before the start time (non-negative).
        end_handles: Number of frames to add after the end time (non-negative).

    Returns:
        Tuple of (adjusted_start_time, adjusted_end_time_exclusive).
        The caller is responsible for clamping the result to the media's available range
        and ensuring the resulting duration is positive.

    Raises:
         ValueError: If start_time and end_time_exclusive have different rates.
    """
    if start_time.rate != end_time_exclusive.rate:
        # This should ideally not happen if ranges come from OTIO, but check defensively
        raise ValueError("Start time and end time exclusive must have the same rate to apply handles.")

    # Normalize handles first (ensure non-negative integers)
    norm_start_h, norm_end_h = normalize_handles(start_handles, end_handles)

    adjusted_start = _add_handle_frames_to_time(start_time, norm_start_h, is_start=True)
    # Apply end handles to the *exclusive* end time
    adjusted_end_exclusive = _add_handle_frames_to_time(end_time_exclusive, norm_end_h, is_start=False)

    # Note: adjusted_start could become >= adjusted_end_exclusive if handles are large
    # or the original duration was very small. The caller needs to validate the final range.
    return adjusted_start, adjusted_end_exclusive

"""
Handle Utilities Module

This module provides utility functions for working with handles (additional frames before
and after a clip) in the TimelineHarvester application.
"""

import logging
from typing import Optional, Tuple
import opentimelineio as otio

from .time_utils import add_handle_to_time

# Configure logging
logger = logging.getLogger(__name__)


def normalize_handles(start_handles: int, end_handles: Optional[int] = None) -> Tuple[int, int]:
    """
    Normalizes handle values, ensuring valid values for both start and end handles.

    Args:
        start_handles: Number of frames to add before each range as "handles"
        end_handles: Number of frames to add after each range as "handles".
                    If None, will use the same value as start_handles.

    Returns:
        Tuple of (start_handles, end_handles) with valid values
    """
    # Ensure start_handles is non-negative
    start_handles = max(0, start_handles)

    # If end_handles is not specified, use the same value as start_handles
    if end_handles is None:
        end_handles = start_handles
    else:
        # Ensure end_handles is non-negative
        end_handles = max(0, end_handles)

    return start_handles, end_handles


def apply_handles_to_range(start_time: otio.opentime.RationalTime,
                           end_time: otio.opentime.RationalTime,
                           start_handles: int,
                           end_handles: int) -> Tuple[otio.opentime.RationalTime, otio.opentime.RationalTime]:
    """
    Applies handles to a time range, adjusting the start and end times.

    Args:
        start_time: Start time of the range
        end_time: End time of the range
        start_handles: Number of frames to add before the range
        end_handles: Number of frames to add after the range

    Returns:
        Tuple of (adjusted_start_time, adjusted_end_time)
    """
    adjusted_start = add_handle_to_time(start_time, start_handles, is_start=True)
    adjusted_end = add_handle_to_time(end_time, end_handles, is_start=False)

    return adjusted_start, adjusted_end
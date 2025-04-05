"""
Time Utilities Module

This module provides common utility functions for time operations
used across the TimelineHarvester application.
"""

import logging
from typing import Optional, Union
import opentimelineio as otio

# Configure logging
logger = logging.getLogger(__name__)


def ensure_rational_time(time_value: Union[float, int, otio.opentime.RationalTime],
                         rate: float = 24.0) -> otio.opentime.RationalTime:
    """
    Ensures the provided time value is an otio.opentime.RationalTime.

    Args:
        time_value: A time value as float, int, or RationalTime
        rate: Frame rate to use if time_value is not already a RationalTime

    Returns:
        An otio.opentime.RationalTime object
    """
    if isinstance(time_value, otio.opentime.RationalTime):
        return time_value

    # Convert from numeric to RationalTime
    return otio.opentime.RationalTime(time_value * rate, rate)


def ensure_non_negative_time(time_value: otio.opentime.RationalTime) -> otio.opentime.RationalTime:
    """
    Ensures the provided time value is not negative.

    Args:
        time_value: A RationalTime object to check

    Returns:
        A RationalTime with value at least 0
    """
    if time_value.value < 0:
        logger.warning(f"Negative time value {time_value} detected, adjusting to 0")
        return otio.opentime.RationalTime(0, time_value.rate)
    return time_value


def add_handle_to_time(time_value: otio.opentime.RationalTime,
                       handle_frames: int,
                       is_start: bool = True) -> otio.opentime.RationalTime:
    """
    Adds a handle (in frames) to a time value.

    Args:
        time_value: The time value to modify
        handle_frames: Number of frames to add or subtract
        is_start: If True, handle will be subtracted (for start times),
                 if False, handle will be added (for end times)

    Returns:
        A new RationalTime with the handle applied
    """
    handle_time = otio.opentime.RationalTime(handle_frames, time_value.rate)

    if is_start:
        # For start times, we subtract the handle
        result = time_value - handle_time
        # Ensure result is not negative
        return ensure_non_negative_time(result)
    else:
        # For end times, we add the handle
        return time_value + handle_time


def rescale_time(time_value: otio.opentime.RationalTime,
                 target_rate: float) -> otio.opentime.RationalTime:
    """
    Rescales a time value to the target rate if needed.

    Args:
        time_value: The time value to rescale
        target_rate: The target frame rate

    Returns:
        A RationalTime rescaled to the target rate if needed
    """
    if time_value.rate != target_rate:
        return time_value.rescaled_to(target_rate)
    return time_value


def duration_to_seconds(duration: otio.opentime.RationalTime) -> float:
    """
    Converts a RationalTime duration to seconds.

    Args:
        duration: A RationalTime duration

    Returns:
        Duration in seconds as a float
    """
    return duration.value / duration.rate


def frames_to_rational_time(frames: int, rate: float = 24.0) -> otio.opentime.RationalTime:
    """
    Creates a RationalTime from a frame count.

    Args:
        frames: Number of frames
        rate: Frame rate

    Returns:
        A RationalTime representing the frames at the given rate
    """
    return otio.opentime.RationalTime(frames, rate)
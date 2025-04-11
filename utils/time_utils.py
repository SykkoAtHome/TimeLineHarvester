# utils/time_utils.py
"""
Time Utilities Module

Provides common utility functions for time operations using OpenTimelineIO time objects,
used across the TimelineHarvester application.
"""

import logging
from typing import Optional, Union
import opentimelineio as otio

logger = logging.getLogger(__name__)  # Use __name__ for module-specific logger


def ensure_rational_time(time_value: Union[float, int, otio.opentime.RationalTime],
                         rate: Optional[float] = None) -> otio.opentime.RationalTime:
    """
    Ensures the provided time value is an otio.opentime.RationalTime.
    If input is numeric, requires a valid rate. If input is RationalTime, rate is ignored.

    Args:
        time_value: A time value as float, int, or RationalTime.
        rate: Frame rate to use if time_value is numeric. Must be provided if time_value is numeric.

    Returns:
        An otio.opentime.RationalTime object.

    Raises:
        TypeError: If input type is unsupported.
        ValueError: If input is numeric but rate is missing or invalid.
    """
    if isinstance(time_value, otio.opentime.RationalTime):
        return time_value

    if isinstance(time_value, (float, int)):
        if rate is None or rate <= 0:
            raise ValueError("A positive frame rate must be provided when converting numeric time.")
        try:
            # Use max(0, ...) to prevent negative frame counts from numeric input
            frames = max(0, time_value) * rate
            # Use round() for potentially more accurate frame number from float seconds
            return otio.opentime.RationalTime(round(frames), rate)
        except Exception as e:
            logger.error(f"Error converting numeric time {time_value} at rate {rate} to RationalTime: {e}")
            raise ValueError(f"Invalid arguments for RationalTime conversion: time={time_value}, rate={rate}") from e
    raise TypeError(f"Unsupported type for time conversion: {type(time_value)}")


def ensure_non_negative_time(time_value: otio.opentime.RationalTime) -> otio.opentime.RationalTime:
    """Ensures the RationalTime value is not negative, returning time zero if it is."""
    if time_value.value < 0:
        # Return time zero with the original rate
        return otio.opentime.RationalTime(0, time_value.rate)
    return time_value


def rescale_time(time_value: otio.opentime.RationalTime,
                 target_rate: float) -> otio.opentime.RationalTime:
    """
    Rescales a RationalTime to the target rate if its rate differs.

    Args:
        time_value: The time value to rescale.
        target_rate: The target frame rate. Must be positive.

    Returns:
        A RationalTime rescaled to the target rate.

    Raises:
        ValueError: If target_rate is not positive.
    """
    if target_rate <= 0:
        raise ValueError("Target frame rate must be positive.")
    if time_value.rate != target_rate:
        try:
            return time_value.rescaled_to(target_rate)
        except ZeroDivisionError:  # Catch potential issue if original rate was 0?
            logger.error(f"Cannot rescale time {time_value} to rate {target_rate} due to zero rate.")
            # Return time zero at target rate as a fallback? Or raise? Raising is safer.
            raise ValueError(f"Cannot rescale time with rate {time_value.rate}") from None
    return time_value


def duration_to_seconds(duration: otio.opentime.RationalTime) -> float:
    """Converts a RationalTime duration to seconds."""
    if duration.rate == 0:
        logger.warning("Cannot calculate seconds from duration with zero rate.")
        return 0.0  # Avoid division by zero
    try:
        return duration.to_seconds()  # Use built-in method
    except:  # Catch potential errors with built-in method? Unlikely but safe.
        return duration.value / duration.rate


def frames_to_rational_time(frames: int, rate: float) -> otio.opentime.RationalTime:
    """Creates a RationalTime from a frame count at a given rate."""
    if rate <= 0:
        raise ValueError("Frame rate must be positive.")
    # Ensure frames is integer
    return otio.opentime.RationalTime(int(frames), rate)

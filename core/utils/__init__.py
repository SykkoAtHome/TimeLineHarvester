"""
TimelineHarvester Utilities Module

This package provides utility functions used across the TimelineHarvester application.
"""

from .time_utils import (
    ensure_rational_time,
    ensure_non_negative_time,
    add_handle_to_time,
    rescale_time,
    duration_to_seconds,
    frames_to_rational_time
)

from .handle_utils import (
    normalize_handles,
    apply_handles_to_range
)

__all__ = [
    'ensure_rational_time',
    'ensure_non_negative_time',
    'add_handle_to_time',
    'rescale_time',
    'duration_to_seconds',
    'frames_to_rational_time',
    'normalize_handles',
    'apply_handles_to_range'
]
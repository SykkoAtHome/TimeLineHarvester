# utils/__init__.py
"""
TimelineHarvester Utilities Package

Provides common helper functions for time manipulation, handles, etc.
"""

from .time_utils import (
    ensure_rational_time,
    ensure_non_negative_time,
    rescale_time,
    duration_to_seconds,
    frames_to_rational_time
)

from .handle_utils import (
    normalize_handles,
    apply_handles_to_range
)

# Expose functions directly at the package level
__all__ = [
    'ensure_rational_time',
    'ensure_non_negative_time',
    'rescale_time',
    'duration_to_seconds',
    'frames_to_rational_time',
    'normalize_handles',
    'apply_handles_to_range'
]

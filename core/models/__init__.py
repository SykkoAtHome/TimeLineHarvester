"""
Models Module

This module contains class definitions for representing timeline entities, source clips,
and transfer plans. These models provide a clean interface for the rest of the application
to work with timeline data.
"""

from .source_clip import SourceClip
from .timeline_clip import TimelineClip
from .timeline import Timeline
from .transfer_segment import TransferSegment
from .transfer_plan import TransferPlan

__all__ = [
    'SourceClip',
    'TimelineClip',
    'Timeline',
    'TransferSegment',
    'TransferPlan'
]
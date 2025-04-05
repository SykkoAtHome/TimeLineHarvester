"""
TimelineHarvester Core Module

This module provides the core functionality for the TimelineHarvester application,
which analyzes editing timelines (EDL, AAF, XML) to optimize media transfers.
"""

from .models import SourceClip, TimelineClip, Timeline, TransferSegment, TransferPlan
from .analyzer import TimelineAnalyzer
from .file_manager import FileManager
from .timeline_harvester import TimelineHarvester

# Expose main classes at package level
__all__ = [
    'TimelineHarvester',
    'Timeline',
    'TimelineAnalyzer',
    'FileManager',
    'SourceClip',
    'TimelineClip',
    'TransferSegment',
    'TransferPlan'
]
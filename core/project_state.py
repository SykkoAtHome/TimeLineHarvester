# core/project_state.py
"""
Defines the data structures holding the complete state of a TimelineHarvester project.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

# Import necessary data models
from .models import (
    EditFileMetadata,
    EditShot,
    OriginalSourceFile,
    TransferBatch,
    OutputProfile
)
# Import opentime if needed for future state properties
# from opentimelineio import opentime

logger = logging.getLogger(__name__)

@dataclass
class ProjectSettings:
    """Holds all user-configurable settings for the project."""
    project_name: Optional[str] = None
    # Search paths
    source_search_paths: List[str] = field(default_factory=list)
    graded_source_search_paths: List[str] = field(default_factory=list)
    # Lookup strategy
    source_lookup_strategy: str = "basic_name_match"
    # Output profiles (for Online stage)
    output_profiles: List[OutputProfile] = field(default_factory=list)
    # Color Prep settings
    color_prep_start_handles: int = 24
    color_prep_end_handles: int = 24 # Store both, even if they are the same
    color_prep_separator: int = 0
    split_gap_threshold_frames: int = -1
    # Online Prep settings
    online_prep_handles: int = 12
    online_target_resolution: Optional[str] = None # Placeholder
    online_analyze_transforms: bool = False # Placeholder
    online_output_directory: Optional[str] = None

    def __post_init__(self):
        # Add any post-initialization validation if needed
        pass

@dataclass
class ProjectState:
    """Represents the entire state of a TimelineHarvester project session."""
    # Configuration settings
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    # Input data and analysis results
    edit_files: List[EditFileMetadata] = field(default_factory=list)
    edit_shots: List[EditShot] = field(default_factory=list)
    original_sources_cache: Dict[str, OriginalSourceFile] = field(default_factory=dict)

    # Calculation results
    color_transfer_batch: Optional[TransferBatch] = None
    online_transfer_batch: Optional[TransferBatch] = None

    # Session metadata
    is_dirty: bool = False # Flag to track unsaved changes

    def clear_analysis_results(self):
        """Clears results related to analysis and calculation."""
        logger.debug("Clearing analysis results within ProjectState.")
        self.edit_shots = []
        # Source cache could be kept or cleared - debatable.
        # Clearing for now to avoid inconsistencies if paths change.
        self.original_sources_cache = {}
        self.color_transfer_batch = None
        self.online_transfer_batch = None
        # The 'is_dirty' flag is not reset here, that's ProjectManager's responsibility

    def clear_all(self):
        """Clears everything including settings and edit files."""
        logger.debug("Clearing entire ProjectState.")
        self.settings = ProjectSettings() # New, default settings
        self.edit_files = []
        self.clear_analysis_results()
        self.is_dirty = False

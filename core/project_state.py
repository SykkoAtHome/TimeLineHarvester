# core/project_state.py
"""
Defines the data structures holding the complete state of a TimelineHarvester project,
including settings, input data, analysis results, and calculated transfer batches.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# Import necessary data models
from .models import (
    EditFileMetadata,
    EditShot,
    OriginalSourceFile,
    TransferBatch,
    OutputProfile
)

logger = logging.getLogger(__name__)


@dataclass
class ProjectSettings:
    """
    Stores all user-configurable settings for a TimelineHarvester project.

    Attributes:
        project_name: An optional name for the project.
        source_search_paths: List of directories to search for original source media.
        graded_source_search_paths: List of directories to search for graded source media (if applicable).
        source_lookup_strategy: The method used to find source files (e.g., "basic_name_match").
        output_profiles: A list of configurations for generating output files (e.g., transcodes).
        color_prep_start_handles: Default number of handle frames at the start for color prep.
        color_prep_end_handles: Default number of handle frames at the end for color prep.
        color_prep_separator: Number of blank frames to insert between clips in color prep outputs.
        split_gap_threshold_frames: Frame threshold to consider adjacent clips as separate during processing (-1 to disable).
        online_prep_handles: Default number of handle frames for online prep.
        online_target_resolution: Target resolution for online processing (e.g., "1920x1080", currently placeholder).
        online_analyze_transforms: Whether to analyze spatial transforms during online prep (currently placeholder).
        online_output_directory: The base directory for online prep output files.
    """
    project_name: Optional[str] = None
    source_search_paths: List[str] = field(default_factory=list)
    graded_source_search_paths: List[str] = field(default_factory=list)
    source_lookup_strategy: str = "basic_name_match"
    output_profiles: List[OutputProfile] = field(default_factory=list)
    color_prep_start_handles: int = 25
    color_prep_end_handles: int = 25
    color_prep_separator: int = 0
    split_gap_threshold_frames: int = -1
    online_prep_handles: int = 12
    online_target_resolution: Optional[str] = None  # Placeholder for future implementation
    online_analyze_transforms: bool = False  # Placeholder for future implementation
    online_output_directory: Optional[str] = None

    # No __post_init__ needed currently


@dataclass
class ProjectState:
    """
    Represents the entire state of a TimelineHarvester project session,
    aggregating settings, inputs, analysis results, and calculated data.

    Attributes:
        settings: Project-specific configuration settings.
        edit_files: Metadata about the edit timeline files loaded into the project.
        edit_shots: List of individual shots extracted and analyzed from the edit files.
        original_sources_cache: Cache mapping source file paths to verified OriginalSourceFile objects.
        color_transfer_batch: Calculated batch of media needed for color preparation.
        online_transfer_batch: Calculated batch of media needed for online preparation.
        is_dirty: Boolean flag indicating if the project state has unsaved changes.
    """
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    edit_files: List[EditFileMetadata] = field(default_factory=list)
    edit_shots: List[EditShot] = field(default_factory=list)
    original_sources_cache: Dict[str, OriginalSourceFile] = field(default_factory=dict)
    color_transfer_batch: Optional[TransferBatch] = None
    online_transfer_batch: Optional[TransferBatch] = None
    is_dirty: bool = False

    def clear_analysis_results(self):
        """
        Resets the state components derived from timeline analysis and source finding.
        This includes edit shots, the source cache, and calculated transfer batches.
        The `is_dirty` flag is typically managed externally (e.g., by ProjectManager).
        """
        logger.debug("Clearing analysis results (shots, source cache, transfer batches).")
        self.edit_shots = []
        self.original_sources_cache = {}  # Cleared to avoid stale data if inputs/paths change
        self.color_transfer_batch = None
        self.online_transfer_batch = None
        # Note: is_dirty status reflects the *overall project*, changing it here might be incorrect.

    def clear_all(self):
        """
        Resets the entire project state to its default, empty condition.
        This includes settings, loaded edit files, analysis results, and the dirty flag.
        """
        logger.debug("Clearing entire ProjectState (settings, files, analysis results).")
        self.settings = ProjectSettings()  # Reinitialize with defaults
        self.edit_files = []
        self.clear_analysis_results()  # Clear derived data
        self.is_dirty = False  # Reset dirty flag as the state is now default/empty

# core/models.py

# -*- coding: utf-8 -*-
"""
core/models.py

Data Models for the Timeline Harvester application.

Defines the primary data structures using Python's dataclasses
for representing edit files, source media, edit decisions,
output profiles, and transfer batches.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import opentimelineio as otio

# Type Aliases for clarity
RationalTime = otio.opentime.RationalTime
TimeRange = otio.opentime.TimeRange


@dataclass
class EditFileMetadata:
    """
    Metadata about a single input edit file (e.g., EDL, AAF, XML).

    Attributes:
        path: Absolute path to the edit file.
        filename: Base name of the edit file (derived from path).
        format_type: Detected format of the edit file (e.g., 'EDL', 'AAF',
                     'FCPXML', 'OTIO_JSON'). Set during parsing.
    """
    path: str
    filename: str = field(init=False)  # Derived from path during initialization
    format_type: Optional[str] = None  # e.g., 'EDL', 'AAF', 'FCPXML', 'OTIO_JSON'

    # Potential future field: OTIO timeline object, parsed from the edit file.
    # parsed_timeline: Optional[otio.schema.Timeline] = None

    def __post_init__(self):
        """Calculate filename after instance initialization."""
        self.filename = os.path.basename(self.path)


@dataclass
class OriginalSourceFile:
    """
    Represents a unique, original source media file (e.g., camera master).

    Ensures that each distinct source file is represented only once,
    even if referenced multiple times in edits. Designed to be hashable
    based on its path for efficient storage in sets or dictionary keys.

    Attributes:
        path: Full, verified path to the original source media file.
        duration: Duration of the source file, typically determined via
                  media analysis (e.g., ffprobe).
        frame_rate: Frame rate of the source file.
        start_timecode: Starting timecode of the source file.
        is_verified: Flag indicating if the file path and basic metadata
                     have been successfully verified (e.g., file exists,
                     can be read by ffprobe).
        metadata: Dictionary holding additional technical metadata extracted
                  from the file (e.g., resolution, codec, audio channels).
    """
    path: str  # Full path to the *verified* original file

    # --- Fields populated after verification ---
    duration: Optional[RationalTime] = None
    frame_rate: Optional[float] = None
    start_timecode: Optional[RationalTime] = None
    is_verified: bool = False  # True after successful verification
    metadata: Dict[str, Any] = field(default_factory=dict)  # e.g., resolution, codec

    def __hash__(self):
        """Compute hash based on the unique file path."""
        return hash(self.path)

    def __eq__(self, other):
        """Check equality based on the file path."""
        if not isinstance(other, OriginalSourceFile):
            return NotImplemented
        return self.path == other.path


@dataclass
class EditShot:
    """
    Represents a single instance of a media clip used within an edit timeline.

    Captures information about how a specific piece of media (often a proxy
    or mezzanine file) is used at a particular point in the edit.

    Attributes:
        clip_name: Name assigned to the clip within the editing software.
        edit_media_path: Path to the media file as referenced *in the edit*
                         (could be a proxy, mezzanine, or potentially the original).
        edit_media_range: Time range of the `edit_media_path` file that is
                          used by this specific clip instance in the timeline.
        timeline_range: Time range representing the position and duration of this
                        clip *on the main edit timeline*. Optional, but useful
                        for context.
        tape_name: The resolved Tape Name or Reel Name associated with this shot,
                   determined during parsing from edit metadata or filenames.
        edit_metadata: Dictionary containing metadata associated with this clip
                       *within the edit file* (e.g., 'Tape Name', 'Source File'
                       fields if present in EDL/AAF/XML). Note: This dictionary
                       should still contain the raw metadata for potential future use,
                       even if `tape_name` is populated separately.
        found_original_source: A reference to the `OriginalSourceFile` object
                               that this edit shot corresponds to, populated
                               after the source lookup process. Defaults to None.
        lookup_status: String indicating the status of the original source
                       lookup for this shot (e.g., 'pending', 'found',
                       'not_found', 'ambiguous', 'error').
    """
    # --- Information directly from the edit file ---
    clip_name: Optional[str]
    edit_media_path: str
    edit_media_range: TimeRange
    timeline_range: Optional[TimeRange] = None  # Position on the edit timeline
    tape_name: Optional[str] = None  # <<<--- DODANE POLE
    edit_metadata: Dict[str, Any] = field(default_factory=dict)  # Edit-specific metadata

    # --- Fields populated during processing ---
    found_original_source: Optional[OriginalSourceFile] = None  # Link after lookup
    lookup_status: str = "pending"  # Status: 'pending', 'found', 'not_found', 'error'


@dataclass
class OutputProfile:
    """
    Defines the settings for a specific transcoding output format.

    Used to configure how `TransferSegment`s should be transcoded.

    Attributes:
        name: A unique, user-friendly name identifying this profile
              (e.g., "ProResHQ_1080p", "Proxy_H264_720p").
        extension: The file extension to use for output files generated
                   with this profile (e.g., "mov", "mp4", "mxf").
        # TODO: Define detailed transcoding parameters here, potentially using
        #       a dictionary or dedicated class for FFmpeg options, codec settings,
        #       resolution constraints, etc.
        # transcode_settings: Dict[str, Any] = field(default_factory=dict)
    """
    name: str  # User-friendly identifier (e.g., "ProResHQ_1080p")
    extension: str  # File extension for output (e.g., "mov", "mp4")


@dataclass
class TransferSegment:
    """
    Represents a single, continuous time segment of an `OriginalSourceFile`
    that needs to be extracted or transcoded.

    Segments are calculated by consolidating overlapping or adjacent time ranges
    from `EditShot`s that map to the same `OriginalSourceFile`, potentially adding
    handles.

    Attributes:
        original_source: Reference to the `OriginalSourceFile` this segment derives from.
        transfer_source_range: The calculated time range *within the original source file*
                               to be read for transcoding. This range includes any
                               requested handles.
        output_targets: A dictionary mapping `OutputProfile.name` to the planned
                        absolute output file path for the transcoded segment
                        corresponding to that profile. Populated during batch calculation.
        status: Current processing status of this segment (e.g., 'pending',
                'calculated', 'running', 'completed', 'failed').
        error_message: Stores any error message related to the processing
                       (e.g., transcoding failure) of this specific segment.
        segment_id: An optional unique identifier for the segment, often derived
                    from the original source name and potentially a suffix.
        source_edit_shots: A list of the `EditShot` instances that contributed
                           to the creation of this transfer segment. Useful for
                           tracking lineage.
    """
    original_source: OriginalSourceFile
    transfer_source_range: TimeRange  # Range within original_source, including handles
    output_targets: Dict[str, str] = field(default_factory=dict)  # profile.name -> output_path
    status: str = "pending"  # 'pending', 'calculated', 'running', 'completed', 'failed'
    error_message: Optional[str] = None
    segment_id: Optional[str] = None
    source_edit_shots: List[EditShot] = field(default_factory=list)  # Link back to shots


@dataclass
class TransferBatch:
    """
    Container for a complete set of `TransferSegment`s derived from one or more
    edit files, ready for processing (e.g., transcoding).

    Includes configuration used, calculated segments, and any unresolved items
    or errors encountered during the preparation phase.

    Attributes:
        handle_frames: Number of handle frames requested to be added to each
                       side of the used media ranges when calculating segments.
        output_directory: Base directory where all output files for this batch
                          will be generated. Specific subdirectories or filenames
                          are typically derived from this.
        segments: List of `TransferSegment` objects calculated for this batch,
                  representing the work to be done.
        unresolved_shots: List of `EditShot` objects for which a corresponding
                          `OriginalSourceFile` could not be successfully located
                          during the lookup process.
        calculation_errors: List of strings describing errors that occurred
                            during the batch calculation phase (e.g., issues merging
                            time ranges, configuration problems), distinct from
                            segment-specific processing errors.
        source_edit_files: List of `EditFileMetadata` objects representing the
                           input edit files used to generate this batch.
        batch_name: An optional, user-defined name for this batch, useful for
                    identification in logs or UIs.
        output_profiles_used: List of `OutputProfile` objects that were specified
                              for use when calculating this batch's segments and
                              output targets.
    """
    # --- Configuration ---
    handle_frames: int = 0
    output_directory: Optional[str] = None  # Base output directory

    # --- Calculation Results ---
    segments: List[TransferSegment] = field(default_factory=list)
    unresolved_shots: List[EditShot] = field(default_factory=list)
    calculation_errors: List[str] = field(default_factory=list)  # Errors during calculation phase

    # --- Metadata ---
    source_edit_files: List[EditFileMetadata] = field(default_factory=list)
    batch_name: Optional[str] = None  # Optional user-defined name
    output_profiles_used: List[OutputProfile] = field(default_factory=list)

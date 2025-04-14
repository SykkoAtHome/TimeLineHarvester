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
from enum import Enum, auto  # Import Enum and auto

import opentimelineio as otio

# Type Aliases for clarity
RationalTime = otio.opentime.RationalTime
TimeRange = otio.opentime.TimeRange


class MediaType(Enum):
    """Enumeration for detected media types."""
    UNKNOWN = auto()
    VIDEO = auto()
    AUDIO = auto()
    IMAGE = auto()  # Represents a single still image
    IMAGE_SEQUENCE = auto()  # Represents a sequence of images


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
    filename: str = field(init=False)
    format_type: Optional[str] = None

    def __post_init__(self):
        self.filename = os.path.basename(self.path)


@dataclass
class OriginalSourceFile:
    """
    Represents a unique, original source media file (e.g., camera master, image).

    Ensures that each distinct source file is represented only once,
    even if referenced multiple times in edits. Designed to be hashable
    based on its path for efficient storage in sets or dictionary keys.

    Attributes:
        path: Full, verified path to the original source media file or sequence pattern.
        media_type: The detected type of the media (VIDEO, AUDIO, IMAGE, IMAGE_SEQUENCE). <<--- NEW FIELD
        duration: Duration of the source file or sequence.
        frame_rate: Frame rate of the source file or sequence.
        start_timecode: Starting timecode of the source file or sequence.
        is_verified: Flag indicating if the file path and basic metadata
                     have been successfully verified.
        metadata: Dictionary holding additional technical metadata extracted
                  from the file (e.g., resolution, codec, audio channels, sequence info).
        sequence_pattern: If media_type is IMAGE_SEQUENCE, stores the detected pattern. <<--- NEW FIELD
        sequence_frame_range: If media_type is IMAGE_SEQUENCE, stores the detected frame range (start, end). <<--- NEW FIELD
    """
    path: str  # For sequences, this might store the pattern or first file path

    # --- Fields populated after verification ---
    media_type: MediaType = MediaType.UNKNOWN  # <<<--- NEW FIELD
    duration: Optional[RationalTime] = None
    frame_rate: Optional[float] = None
    start_timecode: Optional[RationalTime] = None
    is_verified: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    sequence_pattern: Optional[str] = None  # <<<--- NEW FIELD (For image sequences)
    sequence_frame_range: Optional[tuple[int, int]] = None  # <<<--- NEW FIELD (For image sequences: start, end)

    def __hash__(self):
        # Hash based on path (or pattern for sequences)
        return hash(self.path)

    def __eq__(self, other):
        if not isinstance(other, OriginalSourceFile):
            return NotImplemented
        # Equality based on path (or pattern for sequences)
        return self.path == other.path


@dataclass
class EditShot:
    """
    Represents a single instance of a media clip used within an edit timeline.

    Attributes:
        clip_name: Name assigned to the clip within the editing software.
        edit_media_path: Path/Identifier used in the edit to find the source.
        edit_media_range: Time range of the source media used by this clip.
        timeline_range: Position and duration on the edit timeline.
        tape_name: Resolved Tape Name or Reel Name from parsing.
        edit_metadata: Metadata from the edit file associated with this clip.
        found_original_source: Reference to the corresponding OriginalSourceFile.
        lookup_status: Status of the source lookup process.
    """
    # --- Information directly from the edit file ---
    clip_name: Optional[str]
    edit_media_path: str  # Identifier used in edit
    edit_media_range: TimeRange
    timeline_range: Optional[TimeRange] = None
    tape_name: Optional[str] = None
    edit_metadata: Dict[str, Any] = field(default_factory=dict)

    # --- Fields populated during processing ---
    found_original_source: Optional[OriginalSourceFile] = None
    lookup_status: str = "pending"


@dataclass
class OutputProfile:
    """Defines settings for a specific transcoding output format."""
    name: str
    extension: str


@dataclass
class TransferSegment:
    """
    Represents a continuous time segment of an OriginalSourceFile to transfer.

    Attributes:
        original_source: Reference to the OriginalSourceFile.
        transfer_source_range: Time range within the original source to read (incl. handles).
        output_targets: Dict mapping OutputProfile.name to the output file path.
        status: Current processing status ('pending', 'calculated', 'running', etc.).
        error_message: Error message related to processing this segment.
        segment_id: Optional unique identifier for the segment.
        source_edit_shots: List of EditShots contributing to this segment.
    """
    original_source: OriginalSourceFile
    transfer_source_range: TimeRange
    output_targets: Dict[str, str] = field(default_factory=dict)
    status: str = "pending"
    error_message: Optional[str] = None
    segment_id: Optional[str] = None
    source_edit_shots: List[EditShot] = field(default_factory=list)


@dataclass
class TransferBatch:
    """Container for TransferSegments ready for processing."""
    # --- Configuration ---
    handle_frames: int = 0
    output_directory: Optional[str] = None

    # --- Calculation Results ---
    segments: List[TransferSegment] = field(default_factory=list)
    unresolved_shots: List[EditShot] = field(default_factory=list)
    calculation_errors: List[str] = field(default_factory=list)

    # --- Metadata ---
    source_edit_files: List[EditFileMetadata] = field(default_factory=list)
    batch_name: Optional[str] = None
    output_profiles_used: List[OutputProfile] = field(default_factory=list)

# core/models.py
"""
Data Models for TimelineHarvester

Defines the primary data structures using dataclasses.
"""

import opentimelineio as otio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any  # For type hinting


@dataclass
class EditFileMetadata:
    """Metadata about the input edit file (EDL/AAF/XML)."""
    path: str
    filename: str = field(init=False)  # Will be derived from path
    format_type: Optional[str] = None  # e.g., 'EDL', 'AAF', 'FCPXML', 'OTIO_DETECTED'

    # We'll add the parsed OTIO timeline here later if needed globally
    # parsed_timeline: Optional[otio.schema.Timeline] = None

    def __post_init__(self):
        """Calculate filename after initialization."""
        import os
        self.filename = os.path.basename(self.path)


@dataclass
class OriginalSourceFile:
    """Represents a unique, original source media file (e.g., from camera)."""
    path: str  # Full path to the *verified* original file
    # --- Fields populated after verification (e.g., using ffprobe) ---
    duration: Optional[otio.opentime.RationalTime] = None
    frame_rate: Optional[float] = None
    start_timecode: Optional[otio.opentime.RationalTime] = None
    is_verified: bool = False  # Set to True after successful verification
    metadata: Dict[str, Any] = field(default_factory=dict)  # e.g., resolution, codec

    # Make hashable based on path for easy use in sets/dict keys
    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        if not isinstance(other, OriginalSourceFile):
            return NotImplemented
        return self.path == other.path


@dataclass
class EditShot:
    """Represents a single clip usage within an edit timeline."""
    # --- Information directly from the edit file ---
    clip_name: Optional[str]  # Name of the clip in the edit software
    edit_media_path: str  # Path to the media file referenced *in the edit* (proxy/mezzanine)
    edit_media_range: otio.opentime.TimeRange  # Time range used *from the edit media*
    # Optional: Position on the edit timeline
    timeline_range: Optional[otio.opentime.TimeRange] = None
    # Optional: Metadata from the edit clip (e.g., Tape Name, Source File field)
    edit_metadata: Dict[str, Any] = field(default_factory=dict)

    # --- Fields populated during processing ---
    found_original_source: Optional[OriginalSourceFile] = None  # Link to the found original source
    lookup_status: str = "pending"  # Status: 'pending', 'found', 'not_found', 'error'


@dataclass
class OutputProfile:
    """Defines settings for a specific output format during transcoding."""
    name: str  # User-friendly name (e.g., "ProResHQ_1080p", "Proxy_H264")
    # FFmpeg options will be added later when implementing ffmpeg logic
    # ffmpeg_options: List[str] = field(default_factory=list)
    extension: str  # File extension for output files (e.g., "mov", "mp4")
    # We might add more fields later like target resolution, codec details etc.


@dataclass
class TransferSegment:
    """Represents a single, continuous segment of an original source file to be transcoded."""
    original_source: OriginalSourceFile  # The original source file this segment comes from
    # The calculated time range *from the original source*, including handles
    transfer_source_range: otio.opentime.TimeRange
    # Map: profile.name -> output_file_path (will be populated later)
    output_targets: Dict[str, str] = field(default_factory=dict)
    # --- Fields for tracking ---
    status: str = "pending"  # Transcoding status: 'pending', 'calculated', 'running', 'completed', 'failed'
    error_message: Optional[str] = None
    # Optional: Keep track of which EditShots this segment covers
    source_edit_shots: List[EditShot] = field(default_factory=list)


@dataclass
class TransferBatch:
    """Contains the complete set of segments to be transcoded for a given job."""
    # --- Configuration used to generate this batch ---
    handle_frames: int = 0
    output_directory: Optional[str] = None  # Base directory for all output files

    # --- Results of the calculation ---
    # List of calculated segments to be processed
    segments: List[TransferSegment] = field(default_factory=list)
    # Optional: Store EditShots for which no original source was found
    unresolved_shots: List[EditShot] = field(default_factory=list)
    # Optional: Store errors encountered during calculation (not FFmpeg errors)
    calculation_errors: List[str] = field(default_factory=list)

    # --- Metadata ---
    # Optional: Link back to the edit files used
    source_edit_files: List[EditFileMetadata] = field(default_factory=list)
    # Optional: User-defined name for this batch
    batch_name: Optional[str] = None
    # Optional: Profiles used for this batch calculation
    output_profiles_used: List[OutputProfile] = field(default_factory=list)

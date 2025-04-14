# core/project_manager.py
"""
Manages the project lifecycle, including loading, saving,
and holding the current ProjectState.
"""

import json
import logging
import os
from typing import Optional, List, Dict, Union

import opentimelineio as otio
from PyQt5.QtCore import QCoreApplication
from opentimelineio import opentime

from .models import (
    EditFileMetadata,
    EditShot,
    OriginalSourceFile,
    TransferBatch,
    TransferSegment,
    OutputProfile
)
from .project_state import ProjectState, ProjectSettings

logger = logging.getLogger(__name__)


def time_to_json(otio_time: Optional[Union[otio.opentime.RationalTime, otio.opentime.TimeRange]]) -> Optional[Union[List, Dict]]:
    """Serializes OTIO RationalTime or TimeRange to a JSON-compatible format."""
    if isinstance(otio_time, opentime.RationalTime):
        return [otio_time.value, otio_time.rate]
    elif isinstance(otio_time, opentime.TimeRange):
        return {
            "start_time": [otio_time.start_time.value, otio_time.start_time.rate],
            "duration": [otio_time.duration.value, otio_time.duration.rate]}
    return None


def time_from_json(json_data: Optional[Union[List, Dict]]) -> Optional[Union[otio.opentime.RationalTime, otio.opentime.TimeRange]]:
    """Deserializes JSON data back into OTIO RationalTime or TimeRange."""
    if isinstance(json_data, list) and len(json_data) == 2:
        try:
            rate = json_data[1]
            if rate <= 0:
                logger.warning(f"Cannot create RationalTime from JSON with non-positive rate: {rate}, data: {json_data}")
                return None
            return opentime.RationalTime(value=json_data[0], rate=rate)
        except Exception as e:
            logger.warning(f"Error converting list to RationalTime: {e}, data: {json_data}")
            return None
    elif isinstance(json_data, dict) and "start_time" in json_data and "duration" in json_data:
        try:
            start_time = time_from_json(json_data["start_time"])
            duration = time_from_json(json_data["duration"])
            if isinstance(start_time, opentime.RationalTime) and isinstance(duration, opentime.RationalTime):
                if duration.value < 0:
                    logger.warning(f"Loaded TimeRange with negative duration: {duration}, using 0 instead. Data: {json_data}")
                    duration = opentime.RationalTime(0, duration.rate)
                return opentime.TimeRange(start_time=start_time, duration=duration)
            logger.warning(f"Invalid start/duration types for TimeRange from JSON: start={type(start_time)}, dur={type(duration)}, data={json_data}")
            return None
        except Exception as e:
            logger.warning(f"Error converting dict to TimeRange: {e}, data: {json_data}")
            return None
    return None


class ProjectManager:
    """Handles loading, saving, and managing the ProjectState."""

    def __init__(self):
        self.current_state: ProjectState = ProjectState()
        self.current_project_path: Optional[str] = None
        logger.info("ProjectManager initialized with a new empty state.")

    def get_state(self) -> ProjectState:
        """Returns the currently active ProjectState object."""
        return self.current_state

    def new_project(self):
        """Resets the manager to a new, clean project state."""
        logger.info("Creating new project state.")
        self.current_state = ProjectState()
        self.current_project_path = None
        self.current_state.is_dirty = False

    def mark_dirty(self, dirty: bool = True):
        """Marks the current project state as dirty (modified)."""
        if self.current_state.is_dirty != dirty:
            self.current_state.is_dirty = dirty
            logger.debug(f"Project state dirty flag set to: {dirty}")

    def _deserialize_settings(self, config_data: Dict) -> ProjectSettings:
        """Helper to deserialize the settings part of the project data."""
        settings = ProjectSettings()
        settings.project_name = self.current_state.settings.project_name

        settings.source_lookup_strategy = config_data.get("source_lookup_strategy", "basic_name_match")
        settings.source_search_paths = config_data.get("source_search_paths", [])
        settings.graded_source_search_paths = config_data.get("graded_source_search_paths", [])

        loaded_profiles = []
        profiles_data = config_data.get("output_profiles", [])
        if isinstance(profiles_data, list):
            for p_data in profiles_data:
                if isinstance(p_data, dict):
                    try:
                        loaded_profiles.append(OutputProfile(**p_data))
                    except Exception as e:
                        logger.warning(f"Skipping invalid output profile data during load: {p_data}, Error: {e}")
        settings.output_profiles = loaded_profiles

        settings.color_prep_start_handles = config_data.get("color_prep_start_handles", 25)
        settings.color_prep_end_handles = config_data.get("color_prep_end_handles", settings.color_prep_start_handles)
        settings.color_prep_separator = config_data.get("color_prep_separator", 0)
        settings.split_gap_threshold_frames = config_data.get("split_gap_threshold_frames", -1)
        settings.online_prep_handles = config_data.get("online_prep_handles", 12)
        settings.online_target_resolution = config_data.get("online_target_resolution")
        settings.online_analyze_transforms = config_data.get("online_analyze_transforms", False)
        settings.online_output_directory = config_data.get("online_output_directory")
        return settings

    def _serialize_settings(self, settings: ProjectSettings) -> Dict:
        """Helper to serialize the ProjectSettings object."""
        return {
            "source_lookup_strategy": settings.source_lookup_strategy,
            "source_search_paths": settings.source_search_paths,
            "graded_source_search_paths": settings.graded_source_search_paths,
            "output_profiles": [p.__dict__ for p in settings.output_profiles],
            "color_prep_start_handles": settings.color_prep_start_handles,
            "color_prep_end_handles": settings.color_prep_end_handles,
            "color_prep_separator": settings.color_prep_separator,
            "split_gap_threshold_frames": settings.split_gap_threshold_frames,
            "online_prep_handles": settings.online_prep_handles,
            "online_target_resolution": settings.online_target_resolution,
            "online_analyze_transforms": settings.online_analyze_transforms,
            "online_output_directory": settings.online_output_directory,
        }

    def _deserialize_batch(self, batch_data: Optional[Dict], stage: str, loaded_shots_map: Dict[int, EditShot],
                           current_settings: ProjectSettings) -> Optional[TransferBatch]:
        """Helper to deserialize a TransferBatch, linking to loaded shots and profiles."""
        if not batch_data or not isinstance(batch_data, dict):
            return None

        logger.debug(f"Deserializing transfer batch for stage: {stage}")
        try:
            default_handles = current_settings.color_prep_start_handles if stage == 'color' else current_settings.online_prep_handles
            handles = batch_data.get("handle_frames", default_handles)
            default_output_dir = current_settings.online_output_directory if stage == 'online' else None
            output_dir = batch_data.get("output_directory", default_output_dir)

            profile_names_used = batch_data.get("output_profiles_names", [])
            profiles_used = [p for p in current_settings.output_profiles if p.name in profile_names_used]
            if len(profiles_used) != len(profile_names_used):
                logger.warning(f"Could not find all saved output profiles ({profile_names_used}) in current config for {stage} batch.")

            source_file_paths = batch_data.get("source_edit_files_paths", [])
            source_files = [f for f in self.current_state.edit_files if f.path in source_file_paths]

            batch = TransferBatch(
                batch_name=batch_data.get("batch_name", f"Loaded_Batch_{stage}"),
                handle_frames=handles,
                output_directory=output_dir,
                calculation_errors=batch_data.get("calculation_errors", []),
                output_profiles_used=profiles_used,
                source_edit_files=source_files
            )

            serialized_segments = batch_data.get("segments", [])
            unresolved_indices = set(batch_data.get("unresolved_shots_indices", []))

            source_cache = self.current_state.original_sources_cache

            for i, seg_data in enumerate(serialized_segments):
                if isinstance(seg_data, dict):
                    source_path = seg_data.get("original_source_path")
                    original_source = source_cache.get(source_path) if source_path else None
                    transfer_range = time_from_json(seg_data.get("transfer_source_range"))

                    if not original_source or not isinstance(transfer_range, opentime.TimeRange):
                        msg = f"Segment {i} load error: Missing source link ('{source_path}') or invalid range."
                        logger.warning(msg)
                        batch.calculation_errors.append(msg)
                        continue

                    covered_shots = [loaded_shots_map.get(idx) for idx in seg_data.get("source_edit_shots_indices", [])]
                    covered_shots = [s for s in covered_shots if s is not None]

                    batch.segments.append(TransferSegment(
                        original_source=original_source,
                        transfer_source_range=transfer_range,
                        output_targets=seg_data.get("output_targets", {}),
                        status=seg_data.get("status", "calculated"),
                        error_message=seg_data.get("error_message"),
                        source_edit_shots=covered_shots))

            batch.unresolved_shots = [loaded_shots_map.get(idx) for idx in unresolved_indices]
            batch.unresolved_shots = [s for s in batch.unresolved_shots if s is not None]

            return batch
        except Exception as e:
            logger.error(f"Error deserializing {stage} batch: {e}", exc_info=True)
            return None

    def _serialize_batch(self, batch: Optional[TransferBatch], all_edit_shots: List[EditShot]) -> Optional[Dict]:
        """Helper to serialize a TransferBatch."""
        if not batch:
            return None

        edit_shots_id_map = {id(shot): i for i, shot in enumerate(all_edit_shots)}

        serialized_segments = []
        for seg in batch.segments:
            covered_indices = [edit_shots_id_map.get(id(s_shot)) for s_shot in seg.source_edit_shots if id(s_shot) in edit_shots_id_map]
            covered_indices = [idx for idx in covered_indices if idx is not None]

            serialized_segments.append({
                "original_source_path": seg.original_source.path if seg.original_source else None,
                "transfer_source_range": time_to_json(seg.transfer_source_range),
                "output_targets": seg.output_targets,
                "status": seg.status,
                "error_message": seg.error_message,
                "source_edit_shots_indices": covered_indices})

        unresolved_indices = [edit_shots_id_map.get(id(s_shot)) for s_shot in batch.unresolved_shots if id(s_shot) in edit_shots_id_map]
        unresolved_indices = [idx for idx in unresolved_indices if idx is not None]

        return {
            "batch_name": batch.batch_name,
            "handle_frames": batch.handle_frames,
            "output_directory": batch.output_directory,
            "segments": serialized_segments,
            "unresolved_shots_indices": unresolved_indices,
            "calculation_errors": batch.calculation_errors,
            "output_profiles_names": [p.name for p in batch.output_profiles_used],
            "source_edit_files_paths": [f.path for f in batch.source_edit_files]
        }

    def load_project(self, file_path: str) -> bool:
        """Loads project state from a JSON file into the manager."""
        logger.info(f"Loading project state from: {file_path}")
        if not os.path.exists(file_path):
            logger.error(f"Project file not found: {file_path}")
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)

            new_state = ProjectState()
            new_state.settings.project_name = project_data.get("project_name")
            saved_app_version = project_data.get("app_version", "Unknown")
            logger.info(f"Loading project '{new_state.settings.project_name}', saved with app version {saved_app_version}.")

            new_state.settings = self._deserialize_settings(project_data.get("config", {}))

            new_state.edit_files = []
            for f_data in project_data.get("edit_files", []):
                if isinstance(f_data, dict) and 'path' in f_data:
                    new_state.edit_files.append(EditFileMetadata(path=f_data['path'], format_type=f_data.get('format')))

            analysis_results = project_data.get("analysis_results", {})
            sources_cache_data = analysis_results.get("original_sources_cache", {})
            new_state.original_sources_cache = {}
            for path, source_data in sources_cache_data.items():
                if isinstance(source_data, dict):
                    loaded_rate = source_data.get("frame_rate")
                    loaded_duration = time_from_json(source_data.get("duration"))
                    if loaded_rate and isinstance(loaded_duration, opentime.RationalTime):
                        try:
                            start_tc = time_from_json(source_data.get("start_timecode"))
                            new_state.original_sources_cache[path] = OriginalSourceFile(
                                path=source_data.get("path", path),
                                duration=loaded_duration,
                                frame_rate=float(loaded_rate),
                                start_timecode=start_tc,
                                is_verified=source_data.get("is_verified", False),
                                metadata=source_data.get("metadata", {}))
                        except Exception as e:
                            logger.warning(f"Skipping invalid source cache entry for {path}: {e}")

            edit_shots_data = analysis_results.get("edit_shots", [])
            new_state.edit_shots = []
            loaded_shots_by_index: Dict[int, EditShot] = {}
            for i, shot_data in enumerate(edit_shots_data):
                if isinstance(shot_data, dict):
                    try:
                        edit_range = time_from_json(shot_data.get("edit_media_range"))
                        if not isinstance(edit_range, opentime.TimeRange):
                            continue
                        timeline_range = time_from_json(shot_data.get("timeline_range"))
                        original_source_path = shot_data.get("found_original_source_path")
                        found_original = new_state.original_sources_cache.get(original_source_path) if original_source_path else None

                        shot = EditShot(
                            clip_name=shot_data.get("clip_name"),
                            edit_media_path=shot_data.get("edit_media_path", ""),
                            edit_media_range=edit_range,
                            timeline_range=timeline_range,
                            edit_metadata=shot_data.get("edit_metadata", {}),
                            found_original_source=found_original,
                            lookup_status=shot_data.get("lookup_status", "pending"))

                        if original_source_path and not found_original:
                            shot.lookup_status = 'pending'

                        new_state.edit_shots.append(shot)
                        loaded_shots_by_index[i] = shot
                    except Exception as e:
                        logger.warning(f"Error loading edit shot at index {i}: {e}.")

            new_state.color_transfer_batch = self._deserialize_batch(
                project_data.get("color_prep_results", {}).get("transfer_batch"),
                'color',
                loaded_shots_by_index,
                new_state.settings)

            new_state.online_transfer_batch = self._deserialize_batch(
                project_data.get("online_prep_results", {}).get("transfer_batch"),
                'online',
                loaded_shots_by_index,
                new_state.settings)

            self.current_state = new_state
            self.current_project_path = file_path
            self.current_state.is_dirty = False
            logger.info(f"Project '{self.current_state.settings.project_name}' loaded successfully.")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Failed parsing project JSON '{file_path}': {e}")
            return False
        except Exception as e:
            logger.error(f"Failed loading project '{file_path}': {e}", exc_info=True)
            return False

    def save_project(self, file_path: Optional[str] = None) -> bool:
        """Saves the current project state to a JSON file."""
        save_path = file_path or self.current_project_path
        if not save_path:
            logger.error("Cannot save project: No file path specified for a new project.")
            return False

        logger.info(f"Saving project state to: {save_path}")
        try:
            self.current_state.settings.project_name = os.path.splitext(os.path.basename(save_path))[0]

            project_data = {
                "app_version": QCoreApplication.applicationVersion(),
                "project_name": self.current_state.settings.project_name,
                "config": self._serialize_settings(self.current_state.settings),
                "edit_files": [{'path': f.path, 'format': f.format_type} for f in self.current_state.edit_files],
                "analysis_results": {
                    "edit_shots": [
                        {
                            "clip_name": s.clip_name,
                            "edit_media_path": s.edit_media_path,
                            "edit_media_range": time_to_json(s.edit_media_range),
                            "timeline_range": time_to_json(s.timeline_range),
                            "edit_metadata": s.edit_metadata,
                            "found_original_source_path": s.found_original_source.path if s.found_original_source else None,
                            "lookup_status": s.lookup_status
                        } for s in self.current_state.edit_shots
                    ],
                    "original_sources_cache": {
                        path: {
                            "path": src.path,
                            "duration": time_to_json(src.duration),
                            "frame_rate": src.frame_rate,
                            "start_timecode": time_to_json(src.start_timecode),
                            "is_verified": src.is_verified,
                            "metadata": src.metadata
                        }
                        for path, src in self.current_state.original_sources_cache.items()
                    },
                },
                "color_prep_results": {
                    "transfer_batch": self._serialize_batch(
                        self.current_state.color_transfer_batch,
                        self.current_state.edit_shots
                    ),
                },
                "online_prep_results": {
                    "transfer_batch": self._serialize_batch(
                        self.current_state.online_transfer_batch,
                        self.current_state.edit_shots
                    ),
                }
            }

            output_dir = os.path.dirname(save_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=4, ensure_ascii=False)

            self.current_project_path = save_path
            self.current_state.is_dirty = False
            logger.info(f"Project saved successfully to {save_path}")
            return True

        except TypeError as e:
            logger.error(f"Serialization error saving project: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Failed to save project to {save_path}: {e}", exc_info=True)
            return False

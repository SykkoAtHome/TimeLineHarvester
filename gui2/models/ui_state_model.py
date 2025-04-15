# gui2/models/ui_state_model.py
"""
UI State Model for TimelineHarvester

Manages the state of UI elements across the application to ensure
consistent behavior and appearance.
"""

import logging
from typing import Dict, Any, Set

from PyQt5.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class UIStateModel(QObject):
    """
    Centralized model for managing UI state across the application.

    Emits signals when state changes to allow components to react.
    Uses a dictionary-based approach for flexibility.
    """
    # Signal emitted when any state changes, with key and new value
    stateChanged = pyqtSignal(str, object)

    # Signal for bulk state changes (e.g. during initialization)
    bulkStateChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        # Main state dictionary
        self._state: Dict[str, Any] = {}

        # Track which components are busy/disabled
        self._busy_components: Set[str] = set()

        # Set up initial state
        self._initialize_state()
        logger.debug("UIStateModel initialized")

    def _initialize_state(self):
        """Initialize default UI state values."""
        # Application state
        self._state.update({
            # General application state
            'app_busy': False,
            'current_project_path': None,
            'project_dirty': False,

            # Main views state
            'active_tab_index': 0,  # 0 = Color Prep, 1 = Online Prep

            # Project panel state
            'edit_files': [],
            'source_search_paths': [],
            'graded_source_paths': [],

            # Color prep state
            'color_prep_can_analyze': False,
            'color_prep_can_calculate': False,
            'color_prep_can_export': False,
            'color_handle_frames': 25,
            'color_separator_frames': 0,
            'color_split_threshold': -1,

            # Online prep state
            'online_prep_can_calculate': False,
            'online_prep_can_transcode': False,
            'online_output_directory': '',
            'online_handle_frames': 12,

            # Results state
            'has_analysis_results': False,
            'has_color_segments': False,
            'has_online_segments': False,
        })

    def get(self, key: str, default: Any = None) -> Any:
        """Get a state value by key."""
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set a state value and emit change signal.

        Args:
            key: The state key to update
            value: The new value
        """
        if key not in self._state or self._state[key] != value:
            old_value = self._state.get(key)
            self._state[key] = value
            logger.debug(f"UI State changed: {key} = {value} (was: {old_value})")
            self.stateChanged.emit(key, value)

    def update(self, state_dict: Dict[str, Any]) -> None:
        """
        Update multiple state values at once.

        Args:
            state_dict: Dictionary of {key: value} pairs to update
        """
        changed = False
        for key, value in state_dict.items():
            if key not in self._state or self._state[key] != value:
                self._state[key] = value
                changed = True
                logger.debug(f"UI State bulk update: {key} = {value}")

        if changed:
            self.bulkStateChanged.emit()

    def set_busy(self, component_id: str, is_busy: bool = True) -> None:
        """
        Mark a component as busy or ready.
        Updates the global busy state accordingly.

        Args:
            component_id: Unique identifier for the component
            is_busy: Whether the component is busy
        """
        if is_busy:
            self._busy_components.add(component_id)
        else:
            self._busy_components.discard(component_id)

        # Update global busy state
        global_busy = len(self._busy_components) > 0
        self.set('app_busy', global_busy)

    def is_app_busy(self) -> bool:
        """Returns True if any component is marked as busy."""
        return self.get('app_busy', False)

    def get_all_state(self) -> Dict[str, Any]:
        """Returns a copy of the entire state dictionary."""
        return self._state.copy()

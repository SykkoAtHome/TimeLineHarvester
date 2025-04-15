# gui2/widgets/action_button.py
"""
Action Button Widget

A button that automatically updates its enabled state based on a UI state key.
Also provides visual feedback during operations.
"""

import logging
from typing import Optional, Callable, List, Any

from PyQt5.QtWidgets import QPushButton, QSizePolicy
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QSize, Qt

from ..models.ui_state_model import UIStateModel

logger = logging.getLogger(__name__)


class ActionButton(QPushButton):
    """
    A button that binds to the UI state model to automatically update
    its enabled state.

    Provides:
    - Auto-disabling when the app is busy
    - Auto-enabling/disabling based on a specific state key
    - Visual feedback during operations
    """

    def __init__(self,
                 text: str,
                 ui_state: UIStateModel,
                 state_key: Optional[str] = None,
                 tooltip: Optional[str] = None,
                 on_click: Optional[Callable] = None,
                 auto_disable_when_busy: bool = True,
                 parent=None):
        """
        Initialize the ActionButton.

        Args:
            text: Button text
            ui_state: The UI state model
            state_key: Key in the UI state model to bind for enabled state
            tooltip: Button tooltip text
            on_click: Function to call when clicked
            auto_disable_when_busy: If True, button disables when app is busy
            parent: Parent widget
        """
        super().__init__(text, parent)

        self.ui_state = ui_state
        self.state_key = state_key
        self.auto_disable_when_busy = auto_disable_when_busy
        self._original_text = text
        self._busy = False

        # Set up button properties
        if tooltip:
            self.setToolTip(tooltip)

        # Size policy that allows button to keep a consistent width
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Connect signals
        if on_click:
            self.clicked.connect(on_click)

        # Connect to UI state changes
        self._connect_to_ui_state()

        # Initial update
        self._update_from_ui_state()

    def _connect_to_ui_state(self):
        """Connect to UI state model signals."""
        # Connect to the specific state key if provided
        if self.state_key:
            self.ui_state.stateChanged.connect(self._on_state_changed)

        # Connect to bulk state changes
        self.ui_state.bulkStateChanged.connect(self._update_from_ui_state)

    @pyqtSlot(str, object)
    def _on_state_changed(self, key: str, value: Any):
        """Handle UI state change for a specific key."""
        # Update if the changed key is the one we're watching or the app_busy key
        if key == self.state_key or (self.auto_disable_when_busy and key == 'app_busy'):
            self._update_from_ui_state()

    def _update_from_ui_state(self):
        """Update button state based on the UI state model."""
        # Default is enabled unless a reason to disable
        enabled = True

        # Check app busy state if configured
        if self.auto_disable_when_busy and self.ui_state.get('app_busy', False):
            enabled = False

        # Check our specific state key if configured
        elif self.state_key:
            enabled = bool(self.ui_state.get(self.state_key, False))

        # Update button state
        self.setEnabled(enabled)

    def set_busy(self, busy: bool, busy_text: Optional[str] = None):
        """
        Set the button to a busy state with optional different text.

        Args:
            busy: Whether the button is busy
            busy_text: Text to show while busy (default: "Working...")
        """
        if busy == self._busy:
            return  # No change

        self._busy = busy

        if busy:
            # Store original enabled state
            self._was_enabled = self.isEnabled()

            # Disable and update text
            self.setEnabled(False)
            if busy_text:
                self.setText(busy_text)
            else:
                self.setText("Working...")
        else:
            # Restore original text
            self.setText(self._original_text)

            # Restore enabled state (honoring UI state)
            self._update_from_ui_state()

    def sizeHint(self) -> QSize:
        """Provide a size hint that ensures buttons have consistent width."""
        size = super().sizeHint()
        # Set a minimum width based on text
        min_width = max(size.width(), len(self._original_text) * 10)
        size.setWidth(min_width)
        return size

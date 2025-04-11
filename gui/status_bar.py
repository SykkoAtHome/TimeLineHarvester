# gui/status_bar.py
"""
Status Bar Manager Module

Provides a class to manage messages and progress display
on the application's QStatusBar.
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import QStatusBar, QProgressBar, QLabel
from PyQt5.QtCore import QTimer, Qt # Import QTimer and Qt namespace

logger = logging.getLogger(__name__)

class StatusBarManager:
    """
    Manages the application's status bar, providing methods for displaying
    status messages, temporary messages, and progress indication.
    """

    def __init__(self, status_bar: QStatusBar):
        """
        Initialize the status bar manager.

        Args:
            status_bar: The QStatusBar instance to manage.
        """
        if not isinstance(status_bar, QStatusBar):
            raise TypeError("StatusBarManager requires a QStatusBar instance.")

        self.status_bar = status_bar
        self._persistent_message = "Ready" # Store the last non-temporary message

        # --- Permanent Widgets ---
        # Status message label (takes available space)
        self.status_label = QLabel(self._persistent_message)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter) # Align left
        self.status_bar.addWidget(self.status_label, 1) # Stretch factor 1

        # Progress bar (aligned right, fixed width)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False) # Initially hide percentage text
        self.progress_bar.setMaximumWidth(200)   # Set a max width
        self.progress_bar.setAlignment(Qt.AlignCenter)
        # Add as permanent widget - appears on the right
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.progress_bar.hide() # Hide initially

        logger.info("StatusBarManager initialized.")

    def set_status(self, message: str, temporary: bool = False, timeout: int = 4000):
        """
        Sets the status message displayed in the status bar.

        Args:
            message: The text message to display.
            temporary: If True, use QStatusBar.showMessage for a timed message.
                       If False, set a persistent message on the label.
            timeout: Duration in milliseconds for temporary messages.
        """
        if temporary:
            # Use QStatusBar's built-in temporary message display
            self.status_bar.showMessage(message, timeout)
            logger.info(f"Temporary Status (>{timeout}ms): {message}")
        else:
            # Set the persistent message on our label
            self._persistent_message = message
            self.status_label.setText(self._persistent_message)
            # Clear any previous temporary message shown by QStatusBar
            self.status_bar.clearMessage()
            logger.info(f"Status Set: {message}")

    def show_progress(self, value: int, maximum: int = 100, text: Optional[str] = None):
        """
        Shows and updates the progress bar.

        Args:
            value: Current progress value.
            maximum: Maximum progress value (set to 0 for indeterminate).
            text: Optional text to display on the progress bar (overrides percentage).
        """
        is_indeterminate = (maximum == 0)

        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value if not is_indeterminate else 0) # Value ignored if indeterminate
        self.progress_bar.setTextVisible(text is not None or not is_indeterminate) # Visible if text or determinate

        if text is not None:
            self.progress_bar.setFormat(text)
        elif is_indeterminate:
            self.progress_bar.setFormat("") # No text for indeterminate
        else:
            self.progress_bar.setFormat("%p%") # Show percentage

        if not self.progress_bar.isVisible():
            self.progress_bar.show()
        # Avoid flooding logs with progress updates
        # logger.debug(f"Progress Update: {value}/{maximum}")

    def hide_progress(self):
        """Hides the progress bar and resets its state."""
        if self.progress_bar.isVisible():
            self.progress_bar.hide()
            self.progress_bar.reset() # Resets range, value, format
            self.progress_bar.setTextVisible(False)
            logger.debug("Progress bar hidden and reset.")

    def set_busy(self, busy: bool = True, message: Optional[str] = None):
        """
        Sets the status bar state to indicate processing or readiness.

        Args:
            busy: True to show an indeterminate progress bar and busy message.
                  False to hide progress and show a ready/idle message.
            message: Optional message to display. Defaults to "Processing..." or "Ready."
        """
        if busy:
            busy_msg = message or "Processing..."
            self.set_status(busy_msg, temporary=False) # Set persistent busy message
            self.show_progress(0, 0) # Show indeterminate progress
            logger.info(f"Status set to busy: {busy_msg}")
        else:
            idle_msg = message or self._persistent_message # Restore last persistent or use provided
            # If last persistent was also a busy message, default to "Ready."
            if idle_msg.lower().startswith("processing") or idle_msg.lower().startswith("starting"):
                idle_msg = "Ready."
            self.hide_progress()
            self.set_status(idle_msg, temporary=False) # Set persistent idle message
            logger.info(f"Status set to ready: {idle_msg}")

"""
Status Bar Module

This module defines the StatusBarManager class, which manages the application status bar
by providing methods for displaying status messages and progress information.
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import QStatusBar, QProgressBar, QLabel

# Configure logging
logger = logging.getLogger(__name__)


class StatusBarManager:
    """
    Manager for the application status bar.

    This class provides a simplified interface for displaying status messages
    and progress information in the application status bar.
    """

    def __init__(self, status_bar: QStatusBar):
        """
        Initialize the status bar manager.

        Args:
            status_bar: QStatusBar to manage
        """
        self.status_bar = status_bar

        # Status message label
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label, 1)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMaximumWidth(200)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.progress_bar.hide()

        logger.info("Status bar manager initialized")

    def set_status(self, message: str):
        """
        Set the status message.

        Args:
            message: Status message to display
        """
        self.status_label.setText(message)
        logger.info(f"Status: {message}")

    def show_progress(self, value: int, maximum: int = 100, text: Optional[str] = None):
        """
        Show and update the progress bar.

        Args:
            value: Current progress value
            maximum: Maximum progress value
            text: Optional custom text to display in the progress bar
        """
        # Update progress bar range and value
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)

        # Set custom format if text is provided
        if text:
            self.progress_bar.setFormat(text)
        else:
            self.progress_bar.setFormat("%p%")

        # Ensure the progress bar is visible
        self.progress_bar.show()

    def hide_progress(self):
        """Hide the progress bar."""
        self.progress_bar.hide()

    def set_busy(self, busy: bool = True, message: Optional[str] = None):
        """
        Set the status bar to busy or ready state.

        Args:
            busy: True to show busy indicator, False to show ready
            message: Optional status message to display
        """
        if busy:
            # Display busy indicator (indeterminate progress)
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
            self.progress_bar.show()

            # Set status message if provided
            if message:
                self.set_status(message)
        else:
            # Reset progress bar and hide it
            self.progress_bar.setRange(0, 100)
            self.hide_progress()

            # Set status message if provided, otherwise "Ready"
            self.set_status(message if message else "Ready")

    def show_temporary_message(self, message: str, timeout: int = 3000):
        """
        Show a temporary message in the status bar.

        Args:
            message: Message to display
            timeout: Time in milliseconds before reverting to previous message
        """
        # Store the current message to restore later
        current_message = self.status_label.text()

        # Show the temporary message
        self.set_status(message)

        # Use QTimer to restore the previous message after the timeout
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(timeout, lambda: self.set_status(current_message))
# gui2/services/dialog_service.py
"""
Dialog Service for TimelineHarvester

Provides standardized dialogs for file selection, confirmations, and messages.
Centralizes dialog management for consistent look and user experience.
"""

import logging
import os
from typing import Optional, Tuple, List, Any

from PyQt5.QtWidgets import (
    QWidget, QFileDialog, QMessageBox, QDialog, QApplication
)
from PyQt5.QtCore import Qt

# Import core for getting About content
from core.about import get_about_html

logger = logging.getLogger(__name__)


class DialogService:
    """
    Service for managing dialogs throughout the application.

    Responsibilities:
    - File open/save dialogs
    - Message boxes (info, warning, error)
    - Confirmation dialogs
    - About dialog
    """

    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize the dialog service.

        Args:
            parent: Parent widget for dialogs (usually MainWindow)
        """
        self.parent = parent
        self.last_dirs = {
            'project': os.path.expanduser("~"),
            'edit_files': os.path.expanduser("~"),
            'export': os.path.expanduser("~")
        }

        logger.debug("DialogService initialized")

    def set_parent(self, parent: QWidget):
        """Set the parent widget for dialogs."""
        self.parent = parent

    def get_open_filename(
            self,
            title: str,
            dir_key: str = 'project',
            directory: Optional[str] = None,
            filter: str = "All Files (*)"
    ) -> Optional[str]:
        """
        Show file open dialog and return selected file path.

        Args:
            title: Dialog title
            dir_key: Key for remembering last directory ('project', 'edit_files', 'export')
            directory: Starting directory (if None, use remembered directory)
            filter: File filter string

        Returns:
            Selected file path or None if canceled
        """
        if directory is None:
            directory = self.last_dirs.get(dir_key, os.path.expanduser("~"))

        file_path, _ = QFileDialog.getOpenFileName(
            self.parent, title, directory, filter
        )

        if file_path:
            # Remember directory
            self.last_dirs[dir_key] = os.path.dirname(file_path)
            return file_path

        return None

    def get_open_filenames(
            self,
            title: str,
            dir_key: str = 'edit_files',
            directory: Optional[str] = None,
            filter: str = "All Files (*)"
    ) -> List[str]:
        """
        Show file open dialog for multiple files and return selected file paths.

        Args:
            title: Dialog title
            dir_key: Key for remembering last directory
            directory: Starting directory (if None, use remembered directory)
            filter: File filter string

        Returns:
            List of selected file paths (empty if canceled)
        """
        if directory is None:
            directory = self.last_dirs.get(dir_key, os.path.expanduser("~"))

        file_paths, _ = QFileDialog.getOpenFileNames(
            self.parent, title, directory, filter
        )

        if file_paths:
            # Remember directory of first file
            self.last_dirs[dir_key] = os.path.dirname(file_paths[0])

        return file_paths

    def get_save_filename(
            self,
            title: str,
            dir_key: str = 'project',
            directory: Optional[str] = None,
            filter: str = "All Files (*)",
            default_suffix: Optional[str] = None
    ) -> Optional[str]:
        """
        Show file save dialog and return selected file path.

        Args:
            title: Dialog title
            dir_key: Key for remembering last directory
            directory: Starting directory (if None, use remembered directory)
            filter: File filter string
            default_suffix: Default suffix to add if user doesn't provide one

        Returns:
            Selected file path or None if canceled
        """
        if directory is None:
            directory = self.last_dirs.get(dir_key, os.path.expanduser("~"))

        dialog = QFileDialog(self.parent, title, directory, filter)
        dialog.setAcceptMode(QFileDialog.AcceptSave)

        if default_suffix:
            dialog.setDefaultSuffix(default_suffix)

        if dialog.exec_() == QDialog.Accepted:
            file_path = dialog.selectedFiles()[0]
            # Remember directory
            self.last_dirs[dir_key] = os.path.dirname(file_path)
            return file_path

        return None

    def get_existing_directory(
            self,
            title: str,
            dir_key: str = 'project',
            directory: Optional[str] = None
    ) -> Optional[str]:
        """
        Show dialog to select an existing directory.

        Args:
            title: Dialog title
            dir_key: Key for remembering last directory
            directory: Starting directory (if None, use remembered directory)

        Returns:
            Selected directory path or None if canceled
        """
        if directory is None:
            directory = self.last_dirs.get(dir_key, os.path.expanduser("~"))

        dir_path = QFileDialog.getExistingDirectory(
            self.parent, title, directory,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if dir_path:
            # Remember directory
            self.last_dirs[dir_key] = dir_path
            return dir_path

        return None

    def show_info(self, title: str, message: str):
        """Show information message box."""
        QMessageBox.information(self.parent, title, message)

    def show_warning(self, title: str, message: str):
        """Show warning message box."""
        QMessageBox.warning(self.parent, title, message)

    def show_error(self, title: str, message: str):
        """Show error message box."""
        QMessageBox.critical(self.parent, title, message)

    def confirm(
            self,
            title: str,
            message: str,
            yes_text: str = "Yes",
            no_text: str = "No",
            default_button: QMessageBox.StandardButton = QMessageBox.No
    ) -> bool:
        """
        Show confirmation dialog with Yes/No buttons.

        Args:
            title: Dialog title
            message: Dialog message
            yes_text: Text for 'Yes' button
            no_text: Text for 'No' button
            default_button: Default button (QMessageBox.Yes or QMessageBox.No)

        Returns:
            True if 'Yes' clicked, False if 'No' clicked
        """
        msg_box = QMessageBox(self.parent)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Question)

        yes_button = msg_box.addButton(yes_text, QMessageBox.YesRole)
        no_button = msg_box.addButton(no_text, QMessageBox.NoRole)

        msg_box.setDefaultButton(default_button)

        msg_box.exec_()

        return msg_box.clickedButton() == yes_button

    def confirm_save_changes(self, message: str) -> Optional[bool]:
        """
        Show dialog asking to save changes with Yes/No/Cancel options.

        Args:
            message: Dialog message

        Returns:
            True if 'Yes' clicked, False if 'No' clicked, None if 'Cancel' clicked
        """
        msg_box = QMessageBox(self.parent)
        msg_box.setWindowTitle("Save Changes")
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Question)

        yes_button = msg_box.addButton("Save", QMessageBox.YesRole)
        no_button = msg_box.addButton("Don't Save", QMessageBox.NoRole)
        cancel_button = msg_box.addButton("Cancel", QMessageBox.RejectRole)

        msg_box.setDefaultButton(yes_button)

        msg_box.exec_()

        clicked = msg_box.clickedButton()
        if clicked == yes_button:
            return True
        elif clicked == no_button:
            return False
        else:  # Cancel
            return None

    def show_about_dialog(self):
        """Show about dialog with application information."""
        try:
            about_html = get_about_html()
            QMessageBox.about(self.parent, "About TimelineHarvester", about_html)
        except Exception as e:
            logger.error(f"Error showing about dialog: {e}", exc_info=True)
            # Fallback to simple about dialog
            QMessageBox.about(
                self.parent,
                "About TimelineHarvester",
                "TimelineHarvester\n\nWorkflow tool for preparing media for color grading and online editing."
            )

"""
File Panel Module

This module defines the FilePanel widget, which is responsible for handling
file selection, displaying loaded files, and providing file-related controls.
"""

import os
import logging
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QLabel, QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal

# Configure logging
logger = logging.getLogger(__name__)


class FilePanel(QWidget):
    """
    Panel for file selection and display in the TimelineHarvester application.

    This panel allows users to select timeline files and displays the list of
    currently loaded files.
    """

    # Signal emitted when files are loaded
    filesLoaded = pyqtSignal(list)

    def __init__(self, parent=None):
        """
        Initialize the file panel.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        # Set up the UI
        self.init_ui()

        # Connect signals
        self.connect_signals()

        # Initialize properties
        self.loaded_files = []

        logger.info("File panel initialized")

    def init_ui(self):
        """Set up the user interface."""
        # Main layout
        main_layout = QVBoxLayout(self)

        # Title
        title_label = QLabel("Timeline Files")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title_label)

        # File list group
        self.file_group = QGroupBox("Loaded Files")
        file_layout = QVBoxLayout(self.file_group)

        # File list widget
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        file_layout.addWidget(self.file_list)

        # Button row
        button_layout = QHBoxLayout()

        self.add_button = QPushButton("Add Files...")
        self.remove_button = QPushButton("Remove Selected")
        self.clear_button = QPushButton("Clear All")

        self.remove_button.setEnabled(False)  # Disabled initially
        self.clear_button.setEnabled(False)  # Disabled initially

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.clear_button)

        file_layout.addLayout(button_layout)

        # Add file group to main layout
        main_layout.addWidget(self.file_group)

    def connect_signals(self):
        """Connect widget signals to slots."""
        self.add_button.clicked.connect(self.add_files)
        self.remove_button.clicked.connect(self.remove_selected_files)
        self.clear_button.clicked.connect(self.clear_all_files)

        # Enable/disable remove button based on selection
        self.file_list.itemSelectionChanged.connect(self.update_button_states)

    def update_button_states(self):
        """Update button enabled states based on current selection."""
        has_selection = len(self.file_list.selectedItems()) > 0
        has_files = self.file_list.count() > 0

        self.remove_button.setEnabled(has_selection)
        self.clear_button.setEnabled(has_files)

    def add_files(self):
        """Open file dialog to add timeline files."""
        # Get starting directory
        start_dir = os.path.dirname(self.loaded_files[0]) if self.loaded_files else os.path.expanduser("~")

        # Show file dialog
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Open Timeline File(s)")
        file_dialog.setDirectory(start_dir)
        file_dialog.setNameFilter("Timeline Files (*.edl *.xml *.fcpxml *.aaf);;All Files (*.*)")
        file_dialog.setFileMode(QFileDialog.ExistingFiles)

        if file_dialog.exec_():
            file_paths = file_dialog.selectedFiles()
            if file_paths:
                # Add new files to our loaded files
                for path in file_paths:
                    if path not in self.loaded_files:
                        self.loaded_files.append(path)

                # Update the list display
                self.update_file_list()

                # Emit the signal with all loaded files
                self.filesLoaded.emit(self.loaded_files)

    def remove_selected_files(self):
        """Remove selected files from the list."""
        # Get selected items
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return

        # Remove from loaded files list
        for item in selected_items:
            file_path = item.data(Qt.UserRole)
            if file_path in self.loaded_files:
                self.loaded_files.remove(file_path)

        # Update the list display
        self.update_file_list()

        # Update button states
        self.update_button_states()

    def clear_all_files(self):
        """Clear all files from the list."""
        self.loaded_files = []
        self.update_file_list()
        self.update_button_states()

    def update_file_list(self):
        """Update the list widget with current loaded files."""
        self.file_list.clear()

        for file_path in self.loaded_files:
            item = QListWidgetItem(os.path.basename(file_path))
            item.setData(Qt.UserRole, file_path)  # Store full path as data
            item.setToolTip(file_path)  # Show full path on hover
            self.file_list.addItem(item)

    def set_loaded_files(self, file_paths: List[str]):
        """
        Set the loaded files and update the display.

        Args:
            file_paths: List of file paths to set as loaded
        """
        self.loaded_files = file_paths.copy()
        self.update_file_list()
        self.update_button_states()
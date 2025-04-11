# gui/file_panel.py
"""
File Panel Module

Allows users to add, remove, and view the list of edit files
to be processed by the application.
"""

import os
import logging
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QLabel, QGroupBox, QAbstractItemView
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot # Added pyqtSlot

logger = logging.getLogger(__name__)

class FilePanel(QWidget):
    """
    Panel for selecting and managing edit files (EDL, AAF, XML, etc.).
    Emits a signal when the list of files changes.
    """
    # Signal emitted when the list of files in the panel changes (added, removed, cleared)
    # Argument: The new list of absolute file paths
    filesChanged = pyqtSignal(list)

    def __init__(self, parent=None):
        """Initialize the file panel."""
        super().__init__(parent)
        self._loaded_file_paths: List[str] = [] # Internal storage for absolute paths
        self.init_ui()
        self.connect_signals()
        logger.info("FilePanel initialized.")

    def init_ui(self):
        """Set up the user interface."""
        main_layout = QVBoxLayout(self)
        # Use a more descriptive title related to the step in the workflow
        title_label = QLabel("1. Add Edit Files")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title_label)

        # Group box for the list and buttons
        self.file_group = QGroupBox("Loaded Edit Files (.edl, .xml, .aaf, .fcpxml)")
        file_layout = QVBoxLayout(self.file_group)

        # List widget to display files
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        # Allow selecting multiple files for removal
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        file_layout.addWidget(self.file_list)

        # Horizontal layout for buttons
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Files...")
        self.add_button.setToolTip("Add one or more edit files to the list.")
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.setToolTip("Remove the selected file(s) from the list.")
        self.clear_button = QPushButton("Clear All")
        self.clear_button.setToolTip("Remove all files from the list.")

        # Disable remove/clear buttons initially
        self.remove_button.setEnabled(False)
        self.clear_button.setEnabled(False)

        button_layout.addStretch() # Push buttons to the right (optional)
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.clear_button)
        file_layout.addLayout(button_layout)

        main_layout.addWidget(self.file_group)
        logger.debug("FilePanel UI created.")

    def connect_signals(self):
        """Connect widget signals to internal slots."""
        self.add_button.clicked.connect(self.add_files)
        self.remove_button.clicked.connect(self.remove_selected_files)
        self.clear_button.clicked.connect(self.clear_all_files)
        # Update button states when selection changes or list contents change
        self.file_list.itemSelectionChanged.connect(self.update_button_states)
        self.file_list.model().rowsInserted.connect(self.update_button_states)
        self.file_list.model().rowsRemoved.connect(self.update_button_states)
        logger.debug("FilePanel signals connected.")

    @pyqtSlot()
    def update_button_states(self):
        """Update enabled state of Remove/Clear buttons based on list content/selection."""
        has_selection = len(self.file_list.selectedItems()) > 0
        has_items = self.file_list.count() > 0
        self.remove_button.setEnabled(has_selection)
        self.clear_button.setEnabled(has_items)

    @pyqtSlot()
    def add_files(self):
        """Opens a file dialog to select and add edit files."""
        # Try to get the last directory from the main window if possible
        parent_window = self.window()
        start_dir = getattr(parent_window, 'last_timeline_dir', os.path.expanduser("~"))

        # Configure file dialog
        file_dialog = QFileDialog(self, "Select Edit File(s)") # Set parent
        file_dialog.setDirectory(start_dir)
        file_dialog.setFileMode(QFileDialog.ExistingFiles) # Allow multiple files
        # Define supported file types filter
        file_dialog.setNameFilter(
            "Edit Files (*.edl *.xml *.fcpxml *.aaf);;"
            "EDL (*.edl);;XML (*.xml *.fcpxml);;AAF (*.aaf);;All Files (*.*)"
        )

        if file_dialog.exec_():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                added_count = 0
                # Add only new, valid paths to the internal list
                for path in selected_files:
                    abs_path = os.path.abspath(path)
                    if abs_path not in self._loaded_file_paths:
                        if os.path.exists(abs_path): # Check if file actually exists
                            self._loaded_file_paths.append(abs_path)
                            added_count += 1
                        else:
                            logger.warning(f"Selected file does not exist, skipping: {abs_path}")
                    else:
                        logger.debug(f"Skipping already added file: {abs_path}")

                if added_count > 0:
                    logger.info(f"Added {added_count} new edit file(s).")
                    self._update_list_widget() # Update the visual list
                    self.filesChanged.emit(self._loaded_file_paths[:]) # Emit signal with a copy of the list
                else:
                    logger.info("No new valid files were added.")
            # Update parent window's last directory if files were selected
            if selected_files and hasattr(parent_window, 'last_timeline_dir'):
                 setattr(parent_window, 'last_timeline_dir', os.path.dirname(selected_files[0]))


    @pyqtSlot()
    def remove_selected_files(self):
        """Removes selected files from the list and updates."""
        selected_items = self.file_list.selectedItems()
        if not selected_items: return

        paths_to_remove = {item.data(Qt.UserRole) for item in selected_items} # Use set for efficiency
        original_count = len(self._loaded_file_paths)

        # Create a new list excluding the removed paths
        self._loaded_file_paths = [p for p in self._loaded_file_paths if p not in paths_to_remove]
        removed_count = original_count - len(self._loaded_file_paths)

        if removed_count > 0:
            logger.info(f"Removed {removed_count} selected file(s).")
            self._update_list_widget()
            self.filesChanged.emit(self._loaded_file_paths[:]) # Emit updated list

    @pyqtSlot()
    def clear_all_files(self):
        """Removes all files from the list."""
        if not self._loaded_file_paths: return # Do nothing if already empty
        logger.info("Clearing all edit files from the list.")
        self._loaded_file_paths = []
        self._update_list_widget()
        self.filesChanged.emit(self._loaded_file_paths[:]) # Emit empty list

    def _update_list_widget(self):
        """Updates the QListWidget display from the internal list."""
        self.file_list.clear() # Clear existing items
        # Sort paths for consistent display order? Optional.
        # sorted_paths = sorted(self._loaded_file_paths)
        for file_path in self._loaded_file_paths:
            item = QListWidgetItem(os.path.basename(file_path))
            item.setData(Qt.UserRole, file_path) # Store full path
            item.setToolTip(file_path) # Show full path on hover
            self.file_list.addItem(item)
        self.update_button_states() # Ensure buttons reflect new state
        logger.debug(f"File list UI updated. Items: {len(self._loaded_file_paths)}")

    # --- Public Methods ---
    def get_loaded_files(self) -> List[str]:
        """Returns a copy of the list of currently loaded file paths."""
        return self._loaded_file_paths[:]

    def set_loaded_files(self, file_paths: List[str]):
        """
        Externally sets the list of files (e.g., when loading settings).
        This updates the internal list and the UI display.
        """
        logger.info(f"Setting loaded files externally ({len(file_paths)} files).")
        # Ensure absolute paths and remove duplicates
        processed_paths = sorted(list({os.path.abspath(p) for p in file_paths if os.path.exists(p)}))
        if len(processed_paths) != len(file_paths):
             logger.warning("Some paths provided to set_loaded_files were invalid or duplicates.")
        self._loaded_file_paths = processed_paths
        self._update_list_widget()
        # Note: This method should NOT emit filesChanged to avoid potential loops if called from MainWindow's handler

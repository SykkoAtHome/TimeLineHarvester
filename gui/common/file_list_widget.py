# gui/common/file_list_widget.py
"""
Reusable widget for displaying and managing a list of files or directories.
"""
import os
import logging
from typing import List

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QListWidget, QListWidgetItem, QFileDialog, QLabel,
                             QAbstractItemView)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class FileListWidget(QWidget):
    """A widget showing a list of paths with Add/Remove/Clear buttons."""
    # Signal emitted when the list of paths changes
    pathsChanged = pyqtSignal(list)

    def __init__(self, title: str = "Files", file_filter: str = "All Files (*.*)",
                 select_directory: bool = False, parent=None):
        """
        Initialize the widget.

        Args:
            title: Title to display above the list.
            file_filter: Filter string for the QFileDialog.
            select_directory: If True, use QFileDialog.getExistingDirectory.
                             If False, use QFileDialog.getOpenFileNames.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._paths: List[str] = []
        self._title = title
        self._file_filter = file_filter
        self._select_directory = select_directory
        self.last_browse_dir = os.path.expanduser("~")  # Store last directory

        self._init_ui()
        self._connect_signals()
        logger.debug(f"FileListWidget '{self._title}' initialized.")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)  # No margins for embedding

        # Optional Title Label
        if self._title:
            # Use smaller font for title within panel
            title_label = QLabel(self._title)
            # title_label.setStyleSheet("font-weight: bold;") # Optional bold
            main_layout.addWidget(title_label)

        # List Widget
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        main_layout.addWidget(self.list_widget, 1)  # Allow list to stretch

        # Button Layout
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        add_text = "Add Directory..." if self._select_directory else "Add Files..."
        self.add_button = QPushButton(add_text)
        self.remove_button = QPushButton("Remove Selected")
        self.clear_button = QPushButton("Clear All")
        self.remove_button.setEnabled(False)
        self.clear_button.setEnabled(False)

        button_layout.addStretch()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.clear_button)
        main_layout.addLayout(button_layout)

    def _connect_signals(self):
        self.add_button.clicked.connect(self.add_items)
        self.remove_button.clicked.connect(self.remove_selected_items)
        self.clear_button.clicked.connect(self.clear_all_items)
        self.list_widget.itemSelectionChanged.connect(self._update_button_states)
        self.list_widget.model().rowsInserted.connect(self._update_button_states)
        self.list_widget.model().rowsRemoved.connect(self._update_button_states)

    @pyqtSlot()
    def _update_button_states(self):
        has_selection = len(self.list_widget.selectedItems()) > 0
        has_items = self.list_widget.count() > 0
        self.remove_button.setEnabled(has_selection)
        self.clear_button.setEnabled(has_items)

    @pyqtSlot()
    def add_items(self):
        """Adds directories or files using the appropriate dialog."""
        newly_added_paths = []
        if self._select_directory:
            dir_path = QFileDialog.getExistingDirectory(
                self, f"Select {self._title}", self.last_browse_dir
            )
            if dir_path:
                newly_added_paths.append(os.path.abspath(dir_path))
                self.last_browse_dir = dir_path  # Update last dir
        else:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self, f"Select {self._title}", self.last_browse_dir, self._file_filter
            )
            if file_paths:
                newly_added_paths = [os.path.abspath(p) for p in file_paths]
                self.last_browse_dir = os.path.dirname(file_paths[0])  # Update last dir

        added_count = 0
        if newly_added_paths:
            for path in newly_added_paths:
                if path not in self._paths:
                    if os.path.exists(path):  # Final check
                        self._paths.append(path)
                        added_count += 1
                    else:
                        logger.warning(f"Path selected does not exist: {path}")
                else:
                    logger.debug(f"Path already in list: {path}")

            if added_count > 0:
                logger.info(f"Added {added_count} new path(s) to '{self._title}'.")
                self._update_list_widget()
                self.pathsChanged.emit(self._paths[:])  # Emit full updated list

    @pyqtSlot()
    def remove_selected_items(self):
        """Removes selected items from the list."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items: return

        paths_to_remove = {item.data(Qt.UserRole) for item in selected_items}
        original_count = len(self._paths)
        self._paths = [p for p in self._paths if p not in paths_to_remove]
        removed_count = original_count - len(self._paths)

        if removed_count > 0:
            logger.info(f"Removed {removed_count} path(s) from '{self._title}'.")
            self._update_list_widget()
            self.pathsChanged.emit(self._paths[:])

    @pyqtSlot()
    def clear_all_items(self):
        """Clears all items from the list."""
        if not self._paths: return
        logger.info(f"Clearing all paths from '{self._title}'.")
        self._paths = []
        self._update_list_widget()
        self.pathsChanged.emit(self._paths[:])

    def _update_list_widget(self):
        """Updates the QListWidget from the internal list."""
        self.list_widget.clear()
        # Sort paths for display consistency
        # sorted_paths = sorted(self._paths)
        for path in self._paths:  # Use internal order for now
            item = QListWidgetItem(path)  # Display full path for directories
            # Or display basename for files? Could be configurable.
            # if not self._select_directory: item.setText(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.list_widget.addItem(item)
        self._update_button_states()

    # --- Public Methods ---
    def get_paths(self) -> List[str]:
        """Returns a copy of the current list of paths."""
        return self._paths[:]

    def set_paths(self, paths: List[str]):
        """Sets the list of paths, validates them, and updates the UI."""
        logger.debug(f"Setting paths for '{self._title}'.")
        valid_paths = []
        check_func = os.path.isdir if self._select_directory else os.path.isfile
        for p in paths:
            abs_path = os.path.abspath(p)
            if os.path.exists(abs_path) and check_func(abs_path):
                if abs_path not in valid_paths:  # Avoid duplicates
                    valid_paths.append(abs_path)
            else:
                logger.warning(f"Invalid or non-existent path ignored during set_paths: {p}")

        self._paths = sorted(valid_paths)  # Store sorted valid paths
        self._update_list_widget()
        # Do NOT emit pathsChanged here, as this is usually called when loading state

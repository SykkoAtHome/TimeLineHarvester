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
    """
    A widget showing a list of file or directory paths with controls to add, remove,
    and clear entries.

    Provides a user interface for managing a list of file system paths with standard
    operations like adding, removing and clearing items.
    """
    # Signal emitted when the list of paths changes
    pathsChanged = pyqtSignal(list)

    def __init__(self, title: str = "Files", file_filter: str = "All Files (*.*)",
                 select_directory: bool = False, parent=None):
        """
        Initialize the FileListWidget.

        Args:
            title: Title to display above the list.
            file_filter: Filter string for the file selection dialog.
            select_directory: If True, allows selection of directories instead of files.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._paths: List[str] = []
        self._title = title
        self._file_filter = file_filter
        self._select_directory = select_directory
        self.last_browse_dir = os.path.expanduser("~")
        self.list_widget = None
        self.add_button = None
        self.remove_button = None
        self.clear_button = None

        self._init_ui()
        self._connect_signals()
        logger.debug(f"FileListWidget '{self._title}' initialized.")

    def _init_ui(self):
        """Initialize the user interface components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Title Label
        if self._title:
            title_label = QLabel(self._title)
            main_layout.addWidget(title_label)

        # List Widget
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        main_layout.addWidget(self.list_widget, 1)

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
        """Connect widget signals to their handlers."""
        self.add_button.clicked.connect(self.add_items)
        self.remove_button.clicked.connect(self.remove_selected_items)
        self.clear_button.clicked.connect(self.clear_all_items)
        self.list_widget.itemSelectionChanged.connect(self._update_button_states)
        self.list_widget.model().rowsInserted.connect(self._update_button_states)
        self.list_widget.model().rowsRemoved.connect(self._update_button_states)

    @pyqtSlot()
    def _update_button_states(self):
        """Update button enabled states based on list contents and selection."""
        has_selection = len(self.list_widget.selectedItems()) > 0
        has_items = self.list_widget.count() > 0
        self.remove_button.setEnabled(has_selection)
        self.clear_button.setEnabled(has_items)

    @pyqtSlot()
    def add_items(self):
        """Add directories or files using the appropriate dialog."""
        newly_added_paths = []
        if self._select_directory:
            dir_path = QFileDialog.getExistingDirectory(
                self, f"Select {self._title}", self.last_browse_dir
            )
            if dir_path:
                newly_added_paths.append(os.path.abspath(dir_path))
                self.last_browse_dir = dir_path
        else:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self, f"Select {self._title}", self.last_browse_dir, self._file_filter
            )
            if file_paths:
                newly_added_paths = [os.path.abspath(p) for p in file_paths]
                self.last_browse_dir = os.path.dirname(file_paths[0])

        added_count = 0
        if newly_added_paths:
            for path in newly_added_paths:
                if path not in self._paths:
                    if os.path.exists(path):
                        self._paths.append(path)
                        added_count += 1
                    else:
                        logger.warning(f"Path selected does not exist: {path}")

            if added_count > 0:
                logger.info(f"Added {added_count} new path(s) to '{self._title}'.")
                self._update_list_widget()
                self.pathsChanged.emit(self._paths[:])

    @pyqtSlot()
    def remove_selected_items(self):
        """Remove selected items from the list."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return

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
        """Clear all items from the list."""
        if not self._paths:
            return
        logger.info(f"Clearing all paths from '{self._title}'.")
        self._paths = []
        self._update_list_widget()
        self.pathsChanged.emit(self._paths[:])

    def _update_list_widget(self):
        """Update the QListWidget from the internal paths list."""
        self.list_widget.clear()
        for path in self._paths:
            item = QListWidgetItem(path)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.list_widget.addItem(item)
        self._update_button_states()

    def get_paths(self) -> List[str]:
        """
        Get the current list of paths.

        Returns:
            A copy of the current list of paths.
        """
        return self._paths[:]

    def set_paths(self, paths: List[str]):
        """
        Set the list of paths, validate them, and update the UI.

        Args:
            paths: List of paths to set.
        """
        logger.debug(f"Setting paths for '{self._title}'.")
        valid_paths = []
        check_func = os.path.isdir if self._select_directory else os.path.isfile

        for p in paths:
            abs_path = os.path.abspath(p)
            if os.path.exists(abs_path) and check_func(abs_path):
                if abs_path not in valid_paths:
                    valid_paths.append(abs_path)
            else:
                logger.warning(f"Invalid or non-existent path ignored during set_paths: {p}")

        self._paths = valid_paths
        self._update_list_widget()

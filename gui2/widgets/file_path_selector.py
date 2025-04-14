# gui2/widgets/file_path_selector.py
"""
File Path Selector Widget

A reusable widget for selecting and managing lists of files or directories.
Provides a more organized and modern interface than the previous FileListWidget.
"""

import logging
import os
from typing import List

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QWidget, QListWidget,
    QListWidgetItem, QFileDialog, QLabel, QAbstractItemView,
    QSizePolicy
)

from ..utils.qt_helpers import (
    create_vbox_layout, create_hbox_layout, create_button,
    create_section_label, add_horizontal_spacer
)

logger = logging.getLogger(__name__)


class FilePathSelector(QWidget):
    """
    A reusable widget for selecting and managing a list of file or directory paths.

    Provides a clean interface with list view and common operations (add, remove, clear).
    Supports both file and directory selection modes.
    """
    # Signal emitted when the list of paths changes
    pathsChanged = pyqtSignal(list)

    # Signal emitted when a path is selected in the list
    pathSelected = pyqtSignal(str)

    def __init__(self,
                 title: str = "Files",
                 file_filter: str = "All Files (*.*)",
                 select_directories: bool = False,
                 allow_multiple: bool = True,
                 parent=None):
        """
        Initialize the FilePathSelector.

        Args:
            title: Title to display above the list
            file_filter: Filter string for file selection dialog
            select_directories: If True, selects directories instead of files
            allow_multiple: If True, allows selecting multiple files/directories
            parent: Parent widget
        """
        super().__init__(parent)
        self._paths: List[str] = []
        self._title = title
        self._file_filter = file_filter
        self._select_directories = select_directories
        self._allow_multiple = allow_multiple
        self.last_browse_dir = os.path.expanduser("~")

        self._init_ui()
        self._connect_signals()
        logger.debug(f"FilePathSelector '{self._title}' initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        main_layout = create_vbox_layout(self, margin=0)

        # Top section with title and help text
        header_layout = create_hbox_layout(margin=0)
        title_label = create_section_label(self._title)
        header_layout.addWidget(title_label)

        # Add count label (right-aligned)
        self.count_label = QLabel("0 items")
        self.count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.count_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header_layout.addWidget(self.count_label)

        main_layout.addLayout(header_layout)

        # Optional help text based on mode
        help_text = "Select directories" if self._select_directories else "Select files"
        if not self._allow_multiple:
            help_text += " (single selection)"
        help_label = QLabel(help_text)
        help_label.setStyleSheet("color: gray; font-size: 9pt;")
        main_layout.addWidget(help_label)

        # List Widget
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setSelectionMode(
            QAbstractItemView.ExtendedSelection if self._allow_multiple
            else QAbstractItemView.SingleSelection
        )
        main_layout.addWidget(self.list_widget, 1)  # 1 = stretch factor

        # Buttons Layout
        button_layout = create_hbox_layout(margin=0)

        # Add button
        add_text = "Add Directory..." if self._select_directories else "Add File..."
        if self._allow_multiple:
            add_text = add_text.replace("Add ", "Add ")
        self.add_button = create_button(
            add_text,
            self.add_items,
            "Add new items to the list"
        )

        # Remove button
        self.remove_button = create_button(
            "Remove",
            self.remove_selected_items,
            "Remove selected items from the list"
        )
        self.remove_button.setEnabled(False)

        # Clear button
        self.clear_button = create_button(
            "Clear All",
            self.clear_all_items,
            "Remove all items from the list"
        )
        self.clear_button.setEnabled(False)

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.clear_button)
        add_horizontal_spacer(button_layout)

        main_layout.addLayout(button_layout)

    def _connect_signals(self):
        """Connect widget signals to their handlers."""
        self.list_widget.itemSelectionChanged.connect(self._update_button_states)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.model().rowsInserted.connect(self._update_count_label)
        self.list_widget.model().rowsRemoved.connect(self._update_count_label)

    @pyqtSlot()
    def _update_button_states(self):
        """Update button enabled states based on list contents and selection."""
        has_selection = len(self.list_widget.selectedItems()) > 0
        has_items = self.list_widget.count() > 0
        self.remove_button.setEnabled(has_selection)
        self.clear_button.setEnabled(has_items)

    @pyqtSlot()
    def _update_count_label(self):
        """Update the count label with the current number of items."""
        count = self.list_widget.count()
        self.count_label.setText(f"{count} item{'s' if count != 1 else ''}")

    @pyqtSlot(QListWidgetItem)
    def _on_item_double_clicked(self, item):
        """Handle double-click on an item."""
        path = item.data(Qt.UserRole)
        if path:
            self.pathSelected.emit(path)

    @pyqtSlot()
    def add_items(self):
        """Add directories or files using the appropriate dialog."""
        newly_added_paths = []
        if self._select_directories:
            if self._allow_multiple:
                # Qt doesn't have a native multi-directory selector, so we'll just
                # allow adding one at a time for directories
                dir_path = QFileDialog.getExistingDirectory(
                    self, f"Select {self._title}", self.last_browse_dir
                )
                if dir_path:
                    newly_added_paths.append(os.path.abspath(dir_path))
                    self.last_browse_dir = dir_path
            else:
                dir_path = QFileDialog.getExistingDirectory(
                    self, f"Select {self._title}", self.last_browse_dir
                )
                if dir_path:
                    newly_added_paths = [os.path.abspath(dir_path)]
                    self.last_browse_dir = dir_path
        else:
            if self._allow_multiple:
                file_paths, _ = QFileDialog.getOpenFileNames(
                    self, f"Select {self._title}", self.last_browse_dir, self._file_filter
                )
                if file_paths:
                    newly_added_paths = [os.path.abspath(p) for p in file_paths]
                    if newly_added_paths:
                        self.last_browse_dir = os.path.dirname(newly_added_paths[0])
            else:
                file_path, _ = QFileDialog.getOpenFileName(
                    self, f"Select {self._title}", self.last_browse_dir, self._file_filter
                )
                if file_path:
                    newly_added_paths = [os.path.abspath(file_path)]
                    self.last_browse_dir = os.path.dirname(file_path)

        added_count = 0
        if newly_added_paths:
            for path in newly_added_paths:
                # Skip if already in the list or doesn't exist
                if path in self._paths:
                    continue
                if not os.path.exists(path):
                    logger.warning(f"Path selected does not exist: {path}")
                    continue

                # Add path to our internal list and the list widget
                self._paths.append(path)

                # Create list item
                item = QListWidgetItem(path)
                item.setData(Qt.UserRole, path)
                item.setToolTip(path)
                self.list_widget.addItem(item)
                added_count += 1

            if added_count > 0:
                logger.info(f"Added {added_count} new path(s) to '{self._title}'")
                self._update_button_states()
                self.pathsChanged.emit(self._paths)

    @pyqtSlot()
    def remove_selected_items(self):
        """Remove selected items from the list."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return

        # Build set of paths to remove
        paths_to_remove = {item.data(Qt.UserRole) for item in selected_items}
        original_count = len(self._paths)

        # First remove from internal list
        self._paths = [p for p in self._paths if p not in paths_to_remove]

        # Then remove from list widget (from bottom to top to preserve indices)
        for item in reversed(selected_items):
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)

        removed_count = original_count - len(self._paths)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} path(s) from '{self._title}'")
            self._update_button_states()
            self.pathsChanged.emit(self._paths)

    @pyqtSlot()
    def clear_all_items(self):
        """Clear all items from the list."""
        if not self._paths:
            return

        count = len(self._paths)
        self._paths.clear()
        self.list_widget.clear()

        logger.info(f"Cleared all {count} paths from '{self._title}'")
        self._update_button_states()
        self.pathsChanged.emit(self._paths)

    def get_paths(self) -> List[str]:
        """Get the current list of paths."""
        return self._paths.copy()

    def set_paths(self, paths: List[str]):
        """
        Set the list of paths, validate them, and update the UI.

        Args:
            paths: List of paths to set
        """
        logger.debug(f"Setting paths for '{self._title}'")
        valid_paths = []

        # Clear the existing list
        self.list_widget.clear()
        self._paths.clear()

        # Helper to check if path is valid
        check_func = os.path.isdir if self._select_directories else os.path.isfile

        # Process and validate paths
        for p in paths:
            abs_path = os.path.abspath(p)
            if os.path.exists(abs_path) and check_func(abs_path):
                if abs_path not in valid_paths:
                    valid_paths.append(abs_path)

                    # Add to list widget
                    item = QListWidgetItem(abs_path)
                    item.setData(Qt.UserRole, abs_path)
                    item.setToolTip(abs_path)
                    self.list_widget.addItem(item)
            else:
                logger.warning(f"Invalid or non-existent path ignored: {p}")

        # Update internal list with validated paths
        self._paths = valid_paths

        # Update UI state and emit signal if paths changed
        self._update_button_states()
        self.pathsChanged.emit(self._paths)

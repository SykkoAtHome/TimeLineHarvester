# gui/project_panel.py
"""
Top-level panel in the main window for managing project-wide settings:
- Edit files list
- Original source search paths
- Graded source search paths (for Online stage)
"""
import logging
import os  # Needed for os path operations if used, though maybe not directly
from typing import List, Dict  # Import Dict for type hinting

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QGroupBox, QVBoxLayout, QSplitter
from PyQt5.QtCore import pyqtSignal, pyqtSlot, Qt  # Import Qt namespace

# Import the reusable file list widget
from .common.file_list_widget import FileListWidget

logger = logging.getLogger(__name__)


class ProjectPanel(QWidget):
    """Panel holding project-wide file/path lists using FileListWidget."""

    # Signals to notify MainWindow of changes that might affect project state
    # Emit the list of paths when it changes
    editFilesChanged = pyqtSignal(list)
    originalSourcePathsChanged = pyqtSignal(list)
    gradedSourcePathsChanged = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._connect_signals()
        logger.info("ProjectPanel initialized.")

    def _init_ui(self):
        # Main layout arranges the list widgets horizontally
        main_layout = QHBoxLayout(self)
        # Add some margins around the panel content
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Use a splitter to allow resizing between the list sections
        splitter = QSplitter(Qt.Horizontal)  # Horizontal splitter
        main_layout.addWidget(splitter)  # Add splitter to the main layout

        # --- Edit Files List ---
        # Encapsulate each list in a groupbox for visual separation
        edit_files_group = QGroupBox("Edit Files")
        edit_files_layout = QVBoxLayout(edit_files_group)
        edit_files_layout.setContentsMargins(2, 5, 2, 2)  # Inner margins
        self.edit_files_list = FileListWidget(
            title="",  # Title is handled by QGroupBox now
            file_filter="Edit Files (*.edl *.xml *.fcpxml *.aaf);;All Files (*.*)",
            select_directory=False  # Select files
        )
        edit_files_layout.addWidget(self.edit_files_list)
        splitter.addWidget(edit_files_group)  # Add group to splitter

        # --- Original Source Paths List ---
        original_paths_group = QGroupBox("Original Source Paths")
        original_paths_layout = QVBoxLayout(original_paths_group)
        original_paths_layout.setContentsMargins(2, 5, 2, 2)
        self.original_paths_list = FileListWidget(
            title="",
            select_directory=True  # Select directories
        )
        original_paths_layout.addWidget(self.original_paths_list)
        splitter.addWidget(original_paths_group)

        # --- Graded Source Paths List ---
        graded_paths_group = QGroupBox("Graded Source Paths (Optional)")
        graded_paths_layout = QVBoxLayout(graded_paths_group)
        graded_paths_layout.setContentsMargins(2, 5, 2, 2)
        self.graded_paths_list = FileListWidget(
            title="",
            select_directory=True  # Select directories
        )
        graded_paths_layout.addWidget(self.graded_paths_list)
        splitter.addWidget(graded_paths_group)

        # Set initial sizes for the splitter sections (equal distribution)
        splitter.setSizes([150, 150, 150])  # Adjust as needed

        logger.debug("ProjectPanel UI created with 3 list widgets in a splitter.")

    def _connect_signals(self):
        # Connect the pathChanged signal from each list widget to the corresponding panel signal
        self.edit_files_list.pathsChanged.connect(self.editFilesChanged)
        self.original_paths_list.pathsChanged.connect(self.originalSourcePathsChanged)
        self.graded_paths_list.pathsChanged.connect(self.gradedSourcePathsChanged)
        logger.debug("ProjectPanel signals connected.")

    # --- Public Methods to Get/Set Data ---

    def get_edit_files(self) -> List[str]:
        """Gets the list of edit file paths."""
        return self.edit_files_list.get_paths()

    def set_edit_files(self, paths: List[str]):
        """Sets the list of edit file paths."""
        self.edit_files_list.set_paths(paths)

    def get_original_search_paths(self) -> List[str]:
        """Gets the list of original source search directory paths."""
        return self.original_paths_list.get_paths()

    def set_original_search_paths(self, paths: List[str]):
        """Sets the list of original source search directory paths."""
        self.original_paths_list.set_paths(paths)

    def get_graded_search_paths(self) -> List[str]:
        """Gets the list of graded source search directory paths."""
        return self.graded_paths_list.get_paths()

    def set_graded_search_paths(self, paths: List[str]):
        """Sets the list of graded source search directory paths."""
        self.graded_paths_list.set_paths(paths)

    def clear_panel(self):
        """Clears all lists in the panel."""
        self.edit_files_list.clear_all_items()
        self.original_paths_list.clear_all_items()
        self.graded_paths_list.clear_all_items()
        logger.info("ProjectPanel lists cleared.")

    def load_panel_settings(self, settings: Dict):
        """Loads path lists from a settings dictionary."""
        logger.debug(f"Loading ProjectPanel settings: {settings}")
        self.set_edit_files(settings.get("edit_files", []))
        self.set_original_search_paths(settings.get("original_search_paths", []))
        self.set_graded_search_paths(settings.get("graded_search_paths", []))
        # Update last browse dirs if stored in settings? Maybe later.
        logger.info("ProjectPanel settings loaded.")

    def get_panel_settings(self) -> Dict:
        """Retrieves current path lists as a settings dictionary."""
        settings = {
            "edit_files": self.get_edit_files(),
            "original_search_paths": self.get_original_search_paths(),
            "graded_search_paths": self.get_graded_search_paths()
        }
        logger.debug("Retrieved settings from ProjectPanel.")
        return settings

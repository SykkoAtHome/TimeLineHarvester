# gui/settings_panel.py
"""
Settings Panel Module - Enhanced

Allows configuration for source lookup, handles, output profiles,
and output directory.
"""

import logging
import os
from typing import Optional, List, Dict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton,
    QCheckBox, QSizePolicy, QToolButton, QFileDialog, QListWidget,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox, QDialog, QDialogButtonBox,
    QPlainTextEdit  # For FFmpeg options
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


# --- Simple Dialog for Editing Output Profiles ---
class ProfileEditDialog(QDialog):
    """Dialog to add or edit an output profile."""

    def __init__(self, profile_data: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        self.profile_data = profile_data or {'name': '', 'extension': '', 'ffmpeg_options': []}
        self.setWindowTitle("Edit Output Profile")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.name_edit = QLineEdit(self.profile_data.get('name', ''))
        self.ext_edit = QLineEdit(self.profile_data.get('extension', 'mov'))
        # Use QPlainTextEdit for multiline FFmpeg options
        self.opts_edit = QPlainTextEdit("\n".join(self.profile_data.get('ffmpeg_options', [])))
        self.opts_edit.setPlaceholderText("-c:v prores_ks\n-profile:v hq\n-pix_fmt yuv422p10le\n-c:a copy")
        self.opts_edit.setMinimumHeight(80)

        form_layout.addRow("Profile Name:", self.name_edit)
        form_layout.addRow("File Extension:", self.ext_edit)
        form_layout.addRow("FFmpeg Options (one per line):", self.opts_edit)

        layout.addLayout(form_layout)

        # Standard buttons (OK, Cancel)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_data(self) -> Optional[Dict]:
        """Returns the entered profile data if valid, else None."""
        name = self.name_edit.text().strip()
        ext = self.ext_edit.text().strip().lstrip('.')  # Remove leading dot if present
        # Split options by line, strip whitespace, filter empty lines
        opts_text = self.opts_edit.toPlainText().strip()
        opts = [line.strip() for line in opts_text.splitlines() if line.strip()]

        if not name or not ext or not opts:
            QMessageBox.warning(self, "Input Error", "Profile Name, Extension, and FFmpeg Options cannot be empty.")
            return None

        return {'name': name, 'extension': ext, 'ffmpeg_options': opts}


# --- Settings Panel Class ---
class SettingsPanel(QWidget):
    """Panel for configuring analysis and transfer settings."""
    # Signal remains the same, triggered by the main action button
    createPlanClicked = pyqtSignal()

    # TODO: Add signal if settings change (e.g., profilesUpdated)

    def __init__(self, parent=None):
        super().__init__(parent)
        # --- Internal State ---
        self._source_search_paths: List[str] = []
        self._output_profiles: List[Dict] = self._get_default_profiles()  # List of profile dicts
        self._output_directory: Optional[str] = None

        self.init_ui()
        self.connect_signals()
        self._update_profile_table()  # Populate with defaults
        logger.info("SettingsPanel initialized.")

    def _get_default_profiles(self) -> List[Dict]:
        """Provides some default output profiles."""
        return [
            {'name': 'ProResHQ', 'extension': 'mov',
             'ffmpeg_options': ['-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le', '-c:a', 'pcm_s16le',
                                '-vendor', 'apl0']},
            {'name': 'ProxyMP4', 'extension': 'mp4',
             'ffmpeg_options': ['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a',
                                'aac', '-b:a', '128k']},
            {'name': 'AudioWAV', 'extension': 'wav', 'ffmpeg_options': ['-vn', '-c:a', 'pcm_s16le']},
            # Audio only example
        ]

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        title_label = QLabel("2. Configure Analysis & Transfer")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title_label)

        # --- Source Lookup Settings ---
        source_group = QGroupBox("Original Source Lookup")
        source_layout = QVBoxLayout(source_group)

        # Strategy Selector
        strategy_layout = QHBoxLayout()
        strategy_layout.addWidget(QLabel("Lookup Strategy:"))
        self.strategy_combo = QComboBox()
        # TODO: Populate with actual implemented strategies later
        self.strategy_combo.addItems(["basic_name_match"])  # Add more as implemented
        strategy_layout.addWidget(self.strategy_combo)
        strategy_layout.addStretch()
        source_layout.addLayout(strategy_layout)

        # Search Paths List
        source_layout.addWidget(QLabel("Search Paths (Directories containing originals):"))
        self.path_list_widget = QListWidget()
        self.path_list_widget.setAlternatingRowColors(True)
        self.path_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        source_layout.addWidget(self.path_list_widget)

        # Search Path Buttons
        path_button_layout = QHBoxLayout()
        self.add_path_button = QPushButton("Add Path...")
        self.remove_path_button = QPushButton("Remove Selected")
        self.remove_path_button.setEnabled(False)  # Disable initially
        path_button_layout.addStretch()
        path_button_layout.addWidget(self.add_path_button)
        path_button_layout.addWidget(self.remove_path_button)
        source_layout.addLayout(path_button_layout)
        main_layout.addWidget(source_group)

        # --- Handle Frames Settings ---
        self.handles_group = QGroupBox("Handles (Extra Frames)")
        # ... (Layout and widgets as before) ...
        handles_layout = QFormLayout(self.handles_group)
        self.start_handles_spin = QSpinBox(minimum=0, maximum=1000, value=24, suffix=" frames")
        self.start_handles_spin.setToolTip("Frames added before each segment")
        self.end_handles_spin = QSpinBox(minimum=0, maximum=1000, value=24, suffix=" frames", enabled=False)
        self.end_handles_spin.setToolTip("Frames added after each segment")
        self.same_handles_check = QCheckBox("Use same value for start and end handles", checked=True)
        handles_layout.addRow("Start Handles:", self.start_handles_spin)
        handles_layout.addRow("End Handles:", self.end_handles_spin)
        handles_layout.addRow("", self.same_handles_check)
        main_layout.addWidget(self.handles_group)

        # --- Output Settings ---
        output_group = QGroupBox("Output & Transcode Settings")
        output_layout = QVBoxLayout(output_group)

        # Output Directory
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Output Directory:"))
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Select base directory for transcoded files...")
        self.output_dir_edit.setReadOnly(True)  # User selects via button
        self.browse_dir_button = QPushButton("Browse...")
        dir_layout.addWidget(self.output_dir_edit, 1)  # Stretch line edit
        dir_layout.addWidget(self.browse_dir_button)
        output_layout.addLayout(dir_layout)
        output_layout.addSpacing(10)

        # Output Profiles Table
        output_layout.addWidget(QLabel("Output Profiles:"))
        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(3)
        self.profile_table.setHorizontalHeaderLabels(["Name", "Extension", "FFmpeg Options"])
        self.profile_table.setAlternatingRowColors(True)
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.profile_table.setSelectionMode(QAbstractItemView.SingleSelection)  # Edit one at a time
        self.profile_table.verticalHeader().setVisible(False)
        self.profile_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.profile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.profile_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.profile_table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # Don't allow direct editing
        output_layout.addWidget(self.profile_table)

        # Profile Buttons
        profile_button_layout = QHBoxLayout()
        self.add_profile_button = QPushButton("Add Profile...")
        self.edit_profile_button = QPushButton("Edit Selected...")
        self.remove_profile_button = QPushButton("Remove Selected")
        self.edit_profile_button.setEnabled(False)
        self.remove_profile_button.setEnabled(False)
        profile_button_layout.addStretch()
        profile_button_layout.addWidget(self.add_profile_button)
        profile_button_layout.addWidget(self.edit_profile_button)
        profile_button_layout.addWidget(self.remove_profile_button)
        output_layout.addLayout(profile_button_layout)
        main_layout.addWidget(output_group)

        # --- Action Button ---
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        self.create_plan_button = QPushButton("Calculate Transfer Plan")
        self.create_plan_button.setStyleSheet("font-weight: bold;")
        self.create_plan_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.create_plan_button.setEnabled(False)  # Disabled until analysis is done
        button_layout.addWidget(self.create_plan_button)
        main_layout.addLayout(button_layout)

        main_layout.addStretch(1)  # Push elements towards top
        logger.debug("SettingsPanel UI created.")

    def connect_signals(self):
        # Handles
        self.same_handles_check.stateChanged.connect(self.update_handles_state)
        self.start_handles_spin.valueChanged.connect(self.update_end_handles_if_linked)
        # Search Paths
        self.add_path_button.clicked.connect(self.add_search_path)
        self.remove_path_button.clicked.connect(self.remove_search_path)
        self.path_list_widget.itemSelectionChanged.connect(self.update_path_button_state)
        # Output Directory
        self.browse_dir_button.clicked.connect(self.browse_output_directory)
        # Profiles
        self.add_profile_button.clicked.connect(self.add_profile)
        self.edit_profile_button.clicked.connect(self.edit_profile)
        self.remove_profile_button.clicked.connect(self.remove_profile)
        self.profile_table.itemSelectionChanged.connect(self.update_profile_button_state)
        self.profile_table.itemDoubleClicked.connect(self.edit_profile)  # Double-click to edit
        # Main Action
        self.create_plan_button.clicked.connect(self.createPlanClicked)
        logger.debug("SettingsPanel signals connected.")

    # --- Handlers for UI elements ---

    @pyqtSlot(int)
    def update_handles_state(self, state):
        is_checked = (state == Qt.Checked)
        self.end_handles_spin.setEnabled(not is_checked)
        if is_checked:
            self.end_handles_spin.setValue(self.start_handles_spin.value())

    @pyqtSlot(int)
    def update_end_handles_if_linked(self, value):
        if self.same_handles_check.isChecked():
            self.end_handles_spin.setValue(value)

    @pyqtSlot()
    def update_path_button_state(self):
        self.remove_path_button.setEnabled(len(self.path_list_widget.selectedItems()) > 0)

    @pyqtSlot()
    def update_profile_button_state(self):
        has_selection = len(self.profile_table.selectedItems()) > 0
        self.edit_profile_button.setEnabled(has_selection)
        self.remove_profile_button.setEnabled(has_selection)

    @pyqtSlot()
    def add_search_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory to Search for Originals",
                                                    os.path.expanduser("~"))
        if dir_path and dir_path not in self._source_search_paths:
            self._source_search_paths.append(dir_path)
            self.path_list_widget.addItem(dir_path)
            self.update_path_button_state()
            logger.info(f"Added search path: {dir_path}")

    @pyqtSlot()
    def remove_search_path(self):
        selected_items = self.path_list_widget.selectedItems()
        if not selected_items: return
        for item in selected_items:
            path = item.text()
            if path in self._source_search_paths:
                self._source_search_paths.remove(path)
            self.path_list_widget.takeItem(self.path_list_widget.row(item))
        self.update_path_button_state()
        logger.info(f"Removed {len(selected_items)} search path(s).")

    @pyqtSlot()
    def browse_output_directory(self):
        # Use last known dir or home dir as starting point
        start_dir = self._output_directory or os.path.expanduser("~")
        dir_path = QFileDialog.getExistingDirectory(self, "Select Base Output Directory", start_dir)
        if dir_path:
            self._output_directory = dir_path
            self.output_dir_edit.setText(dir_path)
            logger.info(f"Output directory set to: {dir_path}")

    def _update_profile_table(self):
        """Populates the profile table from the internal list."""
        self.profile_table.setRowCount(len(self._output_profiles))
        for i, profile in enumerate(self._output_profiles):
            name_item = QTableWidgetItem(profile.get('name', ''))
            ext_item = QTableWidgetItem(profile.get('extension', ''))
            # Join options for display, tooltip for full list
            opts_display = " ".join(profile.get('ffmpeg_options', [])[:3]) + (
                "..." if len(profile.get('ffmpeg_options', [])) > 3 else "")
            opts_item = QTableWidgetItem(opts_display)
            opts_item.setToolTip("\n".join(profile.get('ffmpeg_options', [])))

            self.profile_table.setItem(i, 0, name_item)
            self.profile_table.setItem(i, 1, ext_item)
            self.profile_table.setItem(i, 2, opts_item)
        self.profile_table.resizeColumnsToContents()
        self.update_profile_button_state()

    @pyqtSlot()
    def add_profile(self):
        """Opens the dialog to add a new profile."""
        dialog = ProfileEditDialog(parent=self)
        if dialog.exec_():
            new_data = dialog.get_data()
            if new_data:
                # Check for duplicate name
                if any(p['name'] == new_data['name'] for p in self._output_profiles):
                    QMessageBox.warning(self, "Duplicate Name", f"A profile named '{new_data['name']}' already exists.")
                    return
                self._output_profiles.append(new_data)
                self._update_profile_table()
                logger.info(f"Added output profile: {new_data['name']}")

    @pyqtSlot()
    def edit_profile(self):
        """Opens the dialog to edit the selected profile."""
        selected_rows = self.profile_table.selectionModel().selectedRows()
        if not selected_rows: return
        row = selected_rows[0].row()  # Get index of the selected row
        if 0 <= row < len(self._output_profiles):
            profile_to_edit = self._output_profiles[row]
            dialog = ProfileEditDialog(profile_data=profile_to_edit, parent=self)
            if dialog.exec_():
                updated_data = dialog.get_data()
                if updated_data:
                    # Check if name changed and conflicts with another existing profile
                    original_name = profile_to_edit['name']
                    new_name = updated_data['name']
                    if new_name != original_name and any(p['name'] == new_name for p in self._output_profiles):
                        QMessageBox.warning(self, "Duplicate Name", f"A profile named '{new_name}' already exists.")
                        return
                    # Update the profile data in the list
                    self._output_profiles[row] = updated_data
                    self._update_profile_table()
                    logger.info(f"Edited output profile: {updated_data['name']}")

    @pyqtSlot()
    def remove_profile(self):
        """Removes the selected profile."""
        selected_rows = self.profile_table.selectionModel().selectedRows()
        if not selected_rows: return
        row = selected_rows[0].row()
        if 0 <= row < len(self._output_profiles):
            removed_profile = self._output_profiles.pop(row)
            self._update_profile_table()
            logger.info(f"Removed output profile: {removed_profile['name']}")

    # --- Getter Methods for Main Window ---
    def get_start_handles(self) -> int:
        return self.start_handles_spin.value()

    def get_end_handles(self) -> Optional[int]:
        # Consistent API: Return start value if linked
        return self.start_handles_spin.value() if self.same_handles_check.isChecked() else self.end_handles_spin.value()

    def get_search_paths(self) -> List[str]:
        return self._source_search_paths[:]  # Return a copy

    def get_lookup_strategy(self) -> str:
        return self.strategy_combo.currentText()

    def get_output_profiles_config(self) -> List[Dict]:
        # Returns the list of profile dictionaries
        return self._output_profiles[:]  # Return a copy

    def get_output_directory(self) -> Optional[str]:
        # Return the selected directory path, or None if not set
        return self._output_directory if self._output_directory else None

    # --- Setter Methods (e.g., for loading settings) ---
    def load_panel_settings(self, settings: Dict):
        """Loads settings into the panel's UI elements."""
        self.start_handles_spin.setValue(settings.get('start_handles', 24))
        same_handles = settings.get('same_handles', True)
        self.same_handles_check.setChecked(same_handles)
        if not same_handles:
            self.end_handles_spin.setValue(settings.get('end_handles', 24))
        else:  # Ensure end spin updates if linked
            self.end_handles_spin.setValue(self.start_handles_spin.value())
        self.end_handles_spin.setEnabled(not same_handles)  # Set enabled state

        # Load Search Paths
        self._source_search_paths = settings.get('search_paths', [])
        self.path_list_widget.clear()
        self.path_list_widget.addItems(self._source_search_paths)
        self.update_path_button_state()

        # Load Strategy
        strategy = settings.get('lookup_strategy', 'basic_name_match')
        index = self.strategy_combo.findText(strategy)
        if index >= 0: self.strategy_combo.setCurrentIndex(index)

        # Load Output Directory
        output_dir = settings.get('output_directory')
        if output_dir and os.path.isdir(output_dir):  # Check if saved dir still exists
            self._output_directory = output_dir
            self.output_dir_edit.setText(output_dir)
        else:
            self._output_directory = None
            self.output_dir_edit.clear()

        # Load Output Profiles
        profiles = settings.get('output_profiles')
        if isinstance(profiles, list):  # Basic check if it's a list
            self._output_profiles = profiles
        else:
            self._output_profiles = self._get_default_profiles()  # Fallback to defaults
        self._update_profile_table()

        logger.info("SettingsPanel settings loaded.")

    def get_panel_settings(self) -> Dict:
        """Retrieves current settings from the panel's UI elements."""
        settings = {
            'start_handles': self.get_start_handles(),
            'same_handles': self.same_handles_check.isChecked(),
            'end_handles': self.get_end_handles(),
            'search_paths': self.get_search_paths(),
            'lookup_strategy': self.get_lookup_strategy(),
            'output_directory': self.get_output_directory(),
            'output_profiles': self.get_output_profiles_config(),
        }
        logger.info("Retrieved current settings from SettingsPanel.")
        return settings

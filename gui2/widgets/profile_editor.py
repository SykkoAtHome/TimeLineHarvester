# gui2/widgets/profile_editor.py
"""
Profile Editor Widget

Provides a specialized widget for viewing and editing output profiles
used in online preparation.
"""

import logging
from typing import List, Dict, Optional

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget, QTableWidget, QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
    QMessageBox, QLabel
)

from ..utils.qt_helpers import (
    create_vbox_layout, create_hbox_layout, create_button,
    configure_table, create_table_item, show_warning_message
)

logger = logging.getLogger(__name__)


class ProfileEditDialog(QDialog):
    """Dialog for editing a single output profile."""

    def __init__(self, profile_data: Optional[Dict] = None, parent=None):
        """
        Initialize the profile edit dialog.

        Args:
            profile_data: Existing profile data to edit, or None for a new profile
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Edit Output Profile")
        self.setMinimumWidth(350)

        # Store initial data
        self.profile_data = profile_data or {"name": "", "extension": ""}

        self._init_ui()
        self._populate_fields()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = create_vbox_layout(self, margin=10)

        # Create form for editing fields
        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        # Name field
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter profile name")
        form_layout.addRow("Profile Name:", self.name_edit)

        # Extension field
        self.extension_edit = QLineEdit()
        self.extension_edit.setPlaceholderText("Extension without dot (e.g., mp4)")
        form_layout.addRow("File Extension:", self.extension_edit)

        # Add explanation label
        note_label = QLabel(
            "Note: Additional codec and format options will be added in future updates."
        )
        note_label.setWordWrap(True)
        note_label.setStyleSheet("color: gray; font-style: italic; margin-top: 10px;")

        # Add to main layout
        layout.addLayout(form_layout)
        layout.addWidget(note_label)

        # Add buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _populate_fields(self):
        """Populate the form fields with existing data."""
        self.name_edit.setText(self.profile_data.get("name", ""))
        self.extension_edit.setText(self.profile_data.get("extension", ""))

    def get_profile_data(self) -> Dict:
        """
        Get the edited profile data.

        Returns:
            Dictionary with the profile data
        """
        return {
            "name": self.name_edit.text().strip(),
            "extension": self.extension_edit.text().strip().lstrip(".")
        }

    def accept(self):
        """Validate form before accepting."""
        name = self.name_edit.text().strip()
        extension = self.extension_edit.text().strip()

        if not name:
            show_warning_message(self, "Validation Error", "Profile name cannot be empty.")
            self.name_edit.setFocus()
            return

        if not extension:
            show_warning_message(self, "Validation Error", "File extension cannot be empty.")
            self.extension_edit.setFocus()
            return

        # Clean extension (remove leading dot if present)
        if extension.startswith('.'):
            self.extension_edit.setText(extension[1:])

        super().accept()


class ProfileEditor(QWidget):
    """
    Widget for managing output profiles used in online preparation.

    Provides a table view of profiles with add/edit/remove functionality.
    """
    # Signal emitted when profiles are changed
    profilesChanged = pyqtSignal(list)

    def __init__(self, parent=None):
        """
        Initialize the profile editor.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._profiles = []

        self._init_ui()
        self._connect_signals()

        logger.debug("ProfileEditor initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        main_layout = create_vbox_layout(self, margin=0)

        # Create profile table
        self.table = QTableWidget()
        configure_table(
            self.table,
            headers=["Name", "Extension"],
            stretch_columns=[0],
            fixed_columns=[1],
            sort_enabled=True
        )
        main_layout.addWidget(self.table, 1)  # 1 = stretch factor

        # Create button row
        button_layout = create_hbox_layout(margin=0)

        self.add_button = create_button(
            "Add Profile",
            self._on_add_profile,
            "Add a new output profile"
        )
        self.edit_button = create_button(
            "Edit Profile",
            self._on_edit_profile,
            "Edit the selected profile"
        )
        self.remove_button = create_button(
            "Remove Profile",
            self._on_remove_profile,
            "Remove the selected profile"
        )

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addStretch()

        main_layout.addLayout(button_layout)

        # Initial button states
        self.edit_button.setEnabled(False)
        self.remove_button.setEnabled(False)

    def _connect_signals(self):
        """Connect widget signals."""
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)

    def _on_selection_changed(self):
        """Handle table selection change."""
        has_selection = len(self.table.selectedItems()) > 0
        self.edit_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)

    def _on_item_double_clicked(self, item):
        """Handle item double-click."""
        self._on_edit_profile()

    def _on_add_profile(self):
        """Handle add profile button click."""
        dialog = ProfileEditDialog(parent=self)
        if dialog.exec_() == QDialog.Accepted:
            profile_data = dialog.get_profile_data()

            # Check for duplicate name
            if any(p["name"] == profile_data["name"] for p in self._profiles):
                show_warning_message(
                    self,
                    "Duplicate Profile",
                    f"A profile with the name '{profile_data['name']}' already exists."
                )
                return

            # Add to profiles list
            self._profiles.append(profile_data)

            # Add to table
            self._update_table()

            # Emit change signal
            self.profilesChanged.emit(self._profiles)

    def _on_edit_profile(self):
        """Handle edit profile button click."""
        selected_items = self.table.selectedItems()
        if not selected_items:
            return

        # Get selected row
        row = selected_items[0].row()

        # Get profile data
        profile_index = int(self.table.item(row, 0).data(Qt.UserRole))
        profile_data = self._profiles[profile_index]

        # Show edit dialog
        dialog = ProfileEditDialog(profile_data.copy(), parent=self)
        if dialog.exec_() == QDialog.Accepted:
            edited_data = dialog.get_profile_data()

            # Check for duplicate name if changing
            if edited_data["name"] != profile_data["name"] and any(
                    p["name"] == edited_data["name"] for p in self._profiles
            ):
                show_warning_message(
                    self,
                    "Duplicate Profile",
                    f"A profile with the name '{edited_data['name']}' already exists."
                )
                return

            # Update profile
            self._profiles[profile_index] = edited_data

            # Update table
            self._update_table()

            # Emit change signal
            self.profilesChanged.emit(self._profiles)

    def _on_remove_profile(self):
        """Handle remove profile button click."""
        selected_items = self.table.selectedItems()
        if not selected_items:
            return

        # Get selected row
        row = selected_items[0].row()

        # Get profile data
        profile_index = int(self.table.item(row, 0).data(Qt.UserRole))
        profile_name = self._profiles[profile_index]["name"]

        # Confirm removal
        result = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove the profile '{profile_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if result == QMessageBox.Yes:
            # Remove profile
            del self._profiles[profile_index]

            # Update table
            self._update_table()

            # Emit change signal
            self.profilesChanged.emit(self._profiles)

    def _update_table(self):
        """Update the table with current profiles."""
        self.table.setRowCount(len(self._profiles))

        for i, profile in enumerate(self._profiles):
            # Create table items
            name_item = create_table_item(profile["name"])
            name_item.setData(Qt.UserRole, i)  # Store index for lookup

            ext_item = create_table_item(profile["extension"])
            ext_item.setData(Qt.UserRole, i)  # Store index for lookup

            # Add to table
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, ext_item)

    def get_profiles(self) -> List[Dict]:
        """
        Get the current profiles.

        Returns:
            List of profile dictionaries
        """
        return self._profiles.copy()

    def set_profiles(self, profiles: List[Dict]):
        """
        Set the current profiles.

        Args:
            profiles: List of profile dictionaries
        """
        self._profiles = profiles.copy()
        self._update_table()
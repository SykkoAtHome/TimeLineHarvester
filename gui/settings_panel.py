"""
Settings Panel Module

This module defines the SettingsPanel widget, which allows users to configure
parameters for timeline analysis and transfer plan generation.
"""

import logging
from typing import Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton,
    QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal

# Configure logging
logger = logging.getLogger(__name__)


class SettingsPanel(QWidget):
    """
    Panel for configuring analysis and transfer plan settings.

    This panel allows users to set parameters such as FPS, minimum gap duration,
    handle frames, and transfer plan name.
    """

    # Signal emitted when the Create Plan button is clicked
    createPlanClicked = pyqtSignal()

    def __init__(self, parent=None):
        """
        Initialize the settings panel.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        # Set up the UI
        self.init_ui()

        # Connect signals
        self.connect_signals()

        logger.info("Settings panel initialized")

    def init_ui(self):
        """Set up the user interface."""
        # Main layout
        main_layout = QVBoxLayout(self)

        # Title
        title_label = QLabel("Analysis Settings")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title_label)

        # General settings group
        self.general_group = QGroupBox("General Settings")
        general_layout = QFormLayout(self.general_group)

        # FPS setting
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1.0, 120.0)
        self.fps_spin.setValue(24.0)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setDecimals(3)
        self.fps_spin.setToolTip("Default frames per second for files that don't specify it")
        general_layout.addRow("Default FPS:", self.fps_spin)

        # Add general settings group to main layout
        main_layout.addWidget(self.general_group)

        # Gap detection group
        self.gap_group = QGroupBox("Gap Detection")
        gap_layout = QFormLayout(self.gap_group)

        # Min gap duration setting
        self.min_gap_spin = QDoubleSpinBox()
        self.min_gap_spin.setRange(0.0, 3600.0)  # 0 to 1 hour in seconds
        self.min_gap_spin.setValue(5.0)  # 5 seconds default
        self.min_gap_spin.setSingleStep(1.0)
        self.min_gap_spin.setSuffix(" sec")
        self.min_gap_spin.setToolTip("Minimum duration of gaps to detect (in seconds)")
        gap_layout.addRow("Min Gap Duration:", self.min_gap_spin)

        # Add gap detection group to main layout
        main_layout.addWidget(self.gap_group)

        # Handle frames group
        self.handles_group = QGroupBox("Handle Frames")
        handles_layout = QFormLayout(self.handles_group)

        # Start handles setting
        self.start_handles_spin = QSpinBox()
        self.start_handles_spin.setRange(0, 1000)
        self.start_handles_spin.setValue(24)  # Default 24 frames (1 sec at 24fps)
        self.start_handles_spin.setSingleStep(1)
        self.start_handles_spin.setSuffix(" frames")
        self.start_handles_spin.setToolTip("Number of frames to add before each segment")
        handles_layout.addRow("Start Handles:", self.start_handles_spin)

        # End handles setting
        self.end_handles_spin = QSpinBox()
        self.end_handles_spin.setRange(0, 1000)
        self.end_handles_spin.setValue(24)  # Default 24 frames (1 sec at 24fps)
        self.end_handles_spin.setSingleStep(1)
        self.end_handles_spin.setSuffix(" frames")
        self.end_handles_spin.setToolTip("Number of frames to add after each segment")
        handles_layout.addRow("End Handles:", self.end_handles_spin)

        # Checkbox for same handles
        self.same_handles_check = QCheckBox("Use same value for start and end handles")
        self.same_handles_check.setChecked(True)
        handles_layout.addRow("", self.same_handles_check)

        # Add handles group to main layout
        main_layout.addWidget(self.handles_group)

        # Transfer plan group
        self.plan_group = QGroupBox("Transfer Plan")
        plan_layout = QFormLayout(self.plan_group)

        # Plan name setting
        self.plan_name_edit = QLineEdit()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.plan_name_edit.setText(f"TransferPlan_{timestamp}")
        self.plan_name_edit.setToolTip("Name for the transfer plan")
        plan_layout.addRow("Plan Name:", self.plan_name_edit)

        # Add transfer plan group to main layout
        main_layout.addWidget(self.plan_group)

        # Action buttons
        button_layout = QHBoxLayout()

        # Add spacer to push buttons to the right
        button_layout.addStretch(1)

        # Create plan button
        self.create_plan_button = QPushButton("Create Transfer Plan")
        self.create_plan_button.setStyleSheet("font-weight: bold;")
        self.create_plan_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button_layout.addWidget(self.create_plan_button)

        # Add button layout to main layout
        main_layout.addLayout(button_layout)

        # Add stretch to push everything to the top
        main_layout.addStretch(1)

    def connect_signals(self):
        """Connect widget signals to slots."""
        # Connect same handles checkbox to end handles spinbox
        self.same_handles_check.stateChanged.connect(self.update_handles_state)
        self.start_handles_spin.valueChanged.connect(self.update_end_handles)

        # Connect create plan button
        self.create_plan_button.clicked.connect(self.createPlanClicked)

    def update_handles_state(self, state):
        """
        Update the end handles spinbox state based on checkbox.

        Args:
            state: Checkbox state
        """
        if state == Qt.Checked:
            # When checked, sync end handles with start handles
            self.end_handles_spin.setValue(self.start_handles_spin.value())
            self.end_handles_spin.setEnabled(False)
        else:
            # When unchecked, enable end handles spinbox
            self.end_handles_spin.setEnabled(True)

    def update_end_handles(self, value):
        """
        Update end handles value when start handles changes (if linked).

        Args:
            value: New start handles value
        """
        if self.same_handles_check.isChecked():
            self.end_handles_spin.setValue(value)

    def get_fps(self) -> float:
        """
        Get the selected frames per second.

        Returns:
            FPS value
        """
        return self.fps_spin.value()

    def get_min_gap_duration(self) -> float:
        """
        Get the minimum gap duration in seconds.

        Returns:
            Minimum gap duration in seconds
        """
        return self.min_gap_spin.value()

    def get_start_handles(self) -> int:
        """
        Get the number of start handle frames.

        Returns:
            Number of start handle frames
        """
        return self.start_handles_spin.value()

    def get_end_handles(self) -> Optional[int]:
        """
        Get the number of end handle frames.

        Returns:
            Number of end handle frames, or None if using same as start
        """
        if self.same_handles_check.isChecked():
            return None  # Use same as start_handles (defined by API)
        return self.end_handles_spin.value()

    def get_plan_name(self) -> str:
        """
        Get the transfer plan name.

        Returns:
            Transfer plan name
        """
        return self.plan_name_edit.text()
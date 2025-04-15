# gui2/views/color_prep/color_prep_config_panel.py
# -*- coding: utf-8 -*-
"""
Color Preparation Configuration Panel

Contains widgets for configuring color preparation settings like handles,
separators, and split thresholds.
"""

import logging
from typing import Dict, Any, Optional, Tuple

from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import QWidget, QGroupBox, QFormLayout

from ...models.ui_state_model import UIStateModel
from ...services.event_bus_service import EventBusService, EventType, EventData
from ...widgets.time_selector import HandleSelector, TimeSelector
from ...utils.qt_helpers import create_vbox_layout

logger = logging.getLogger(__name__)


class ColorPrepConfigPanel(QWidget):
    """
    Configuration panel for the color preparation workflow.
    """

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """
        Initialize the ColorPrepConfigPanel.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            parent: Parent widget
        """
        super().__init__(parent)

        self.ui_state = ui_state
        self.event_bus = event_bus

        self._init_ui()
        self._connect_signals()
        self._update_from_ui_state()  # Initial population

        logger.debug("ColorPrepConfigPanel initialized")

    def _init_ui(self):
        """Initialize the user interface components."""
        main_layout = create_vbox_layout(self, margin=0)

        config_group = QGroupBox("Configuration")
        form_layout = QFormLayout(config_group)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form_layout.setLabelAlignment(Qt.AlignRight)

        # Handle Selector
        self.handle_selector = HandleSelector()
        form_layout.addRow("Handles:", self.handle_selector)

        # Separator Selector
        self.separator_selector = TimeSelector(
            label="Segment Separator Gap:",
            minimum=0,
            maximum=1000,
            suffix="frames",
            tooltip="Insert black gap between segments in exported list"
        )
        form_layout.addRow(self.separator_selector)

        # Split Gap Threshold Selector
        self.split_gap_selector = TimeSelector(
            label="Split Gap Threshold:",
            minimum=-1,
            maximum=99999,
            suffix="frames",
            special_value_text="Disabled",
            tooltip="Split segments if gap exceeds threshold (-1 to disable)"
        )
        form_layout.addRow(self.split_gap_selector)

        main_layout.addWidget(config_group)

    def _connect_signals(self):
        """Connect widget signals to handlers."""
        self.handle_selector.handleValuesChanged.connect(self._on_handles_changed)
        self.separator_selector.valueChanged.connect(self._on_separator_changed)
        self.split_gap_selector.valueChanged.connect(self._on_split_gap_changed)

        # Connect to UI state changes for external updates
        self.ui_state.stateChanged.connect(self._on_state_changed)
        self.ui_state.bulkStateChanged.connect(self._update_from_ui_state)

    @pyqtSlot(int, int)
    def _on_handles_changed(self, start_handles: int, end_handles: int):
        """Handle changes in the handle selector."""
        # Update UI state directly (this might be redundant if using event bus)
        # self.ui_state.set('color_handle_frames', start_handles)
        # self.ui_state.set('color_end_handle_frames', end_handles)
        # self.ui_state.set('color_same_handles', start_handles == end_handles)

        # Publish events for each potential change
        self.event_bus.publish(EventData(
            EventType.SETTINGS_CHANGED,
            setting="color_prep_handles",
            value=(start_handles, end_handles)
        ))

    @pyqtSlot(int)
    def _on_separator_changed(self, value: int):
        """Handle changes in the separator selector."""
        self.event_bus.publish(EventData(
            EventType.SETTINGS_CHANGED,
            setting="color_prep_separator",
            value=value
        ))

    @pyqtSlot(int)
    def _on_split_gap_changed(self, value: int):
        """Handle changes in the split gap selector."""
        self.event_bus.publish(EventData(
            EventType.SETTINGS_CHANGED,
            setting="split_gap_threshold",
            value=value
        ))

    @pyqtSlot(str, object)
    def _on_state_changed(self, key: str, value: Any):
        """Handle specific UI state changes."""
        if key in ['color_handle_frames', 'color_end_handle_frames', 'color_same_handles',
                   'color_separator_frames', 'color_split_threshold']:
            self._update_from_ui_state()

    def _update_from_ui_state(self):
        """Update widgets from the UI state model."""
        # Block signals to prevent loops
        self.handle_selector.blockSignals(True)
        self.separator_selector.blockSignals(True)
        self.split_gap_selector.blockSignals(True)

        start_h = self.ui_state.get('color_handle_frames', 25)
        end_h = self.ui_state.get('color_end_handle_frames', start_h)
        linked = self.ui_state.get('color_same_handles', start_h == end_h)

        self.handle_selector.set_values(start_h, end_h)
        self.handle_selector.set_linked(linked)
        self.separator_selector.set_value(self.ui_state.get('color_separator_frames', 0))
        self.split_gap_selector.set_value(self.ui_state.get('color_split_threshold', -1))

        # Unblock signals
        self.handle_selector.blockSignals(False)
        self.separator_selector.blockSignals(False)
        self.split_gap_selector.blockSignals(False)

    def reset_to_defaults(self):
        """Reset settings to default values."""
        # This will trigger signals which update the UI state via the event bus
        self.handle_selector.set_values(25, 25)
        self.handle_selector.set_linked(True)
        self.separator_selector.set_value(0)
        self.split_gap_selector.set_value(-1)

    def load_settings(self, settings: Dict[str, Any]):
        """Load settings from a dictionary."""
        start_h = settings.get('color_prep_start_handles', 25)
        end_h = settings.get('color_prep_end_handles', start_h)
        linked = settings.get('color_prep_same_handles', start_h == end_h)
        self.handle_selector.set_values(start_h, end_h)
        self.handle_selector.set_linked(linked)
        self.separator_selector.set_value(settings.get('color_prep_separator', 0))
        self.split_gap_selector.set_value(settings.get('split_gap_threshold_frames', -1))

    def get_settings(self) -> Dict[str, Any]:
        """Get current settings as a dictionary."""
        start_h, end_h = self.handle_selector.get_values()
        return {
            'color_prep_start_handles': start_h,
            'color_prep_end_handles': end_h,
            'color_prep_same_handles': self.handle_selector.link_checkbox.isChecked(),
            'color_prep_separator': self.separator_selector.value(),
            'split_gap_threshold_frames': self.split_gap_selector.value(),
        }

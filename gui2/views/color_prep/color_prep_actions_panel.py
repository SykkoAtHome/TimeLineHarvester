# gui2/views/color_prep/color_prep_actions_panel.py
# -*- coding: utf-8 -*-
"""
Color Preparation Actions Panel

Contains buttons to trigger actions within the color preparation workflow.
"""

import logging
from typing import Dict, Any

from PyQt5.QtWidgets import QWidget

from ...models.ui_state_model import UIStateModel
from ...services.event_bus_service import EventBusService, EventType, EventData
from ...widgets.action_button import ActionButton
from ...utils.qt_helpers import create_hbox_layout

logger = logging.getLogger(__name__)


class ColorPrepActionsPanel(QWidget):
    """
    Panel containing action buttons for the color preparation workflow.
    """

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """
        Initialize the ColorPrepActionsPanel.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            parent: Parent widget
        """
        super().__init__(parent)

        self.ui_state = ui_state
        self.event_bus = event_bus

        self._init_ui()

        logger.debug("ColorPrepActionsPanel initialized")

    def _init_ui(self):
        """Initialize the user interface components."""
        main_layout = create_hbox_layout(self, margin=0, spacing=10)

        # Analyze Sources Button
        self.analyze_button = ActionButton(
            text="1. Analyze Sources",
            ui_state=self.ui_state,
            state_key="color_prep_can_analyze",
            tooltip="Parse edit files and find original sources",
            on_click=lambda: self._publish_event(EventType.ANALYZE_SOURCES_REQUESTED)
        )
        main_layout.addWidget(self.analyze_button)

        # Calculate Segments Button
        self.calculate_button = ActionButton(
            text="2. Calculate Segments",
            ui_state=self.ui_state,
            state_key="color_prep_can_calculate",
            tooltip="Calculate segments needed for color grading",
            on_click=lambda: self._publish_event(EventType.CALCULATE_COLOR_REQUESTED)
        )
        main_layout.addWidget(self.calculate_button)

        # Export Button
        self.export_button = ActionButton(
            text="3. Export EDL/XML...",
            ui_state=self.ui_state,
            state_key="color_prep_can_export",
            tooltip="Export timeline list for color grading",
            on_click=lambda: self._publish_event(EventType.EXPORT_COLOR_REQUESTED)
        )
        main_layout.addWidget(self.export_button)

        # Add stretch to push buttons to the left
        main_layout.addStretch()

    def _publish_event(self, event_type: str):
        """Helper method to publish events."""
        logger.info(f"Publishing event: {event_type}")
        self.event_bus.publish(EventData(event_type))

# gui2/views/color_prep/color_prep_results_view.py
# -*- coding: utf-8 -*-
"""
Color Preparation Results View

Displays the results of the color preparation workflow, including
analysis, segments, errors, and timeline visualization.
"""

import logging

from ..workflows.workflow_results_view import WorkflowResultsView
from ...models.ui_state_model import UIStateModel
from ...services.event_bus_service import EventBusService

logger = logging.getLogger(__name__)


class ColorPrepResultsView(WorkflowResultsView):
    """
    Specialized results view for the color preparation workflow.
    """

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """
        Initialize the ColorPrepResultsView.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            parent: Parent widget
        """
        super().__init__(ui_state, event_bus, workflow='color', parent=parent)
        logger.debug("ColorPrepResultsView initialized")

# gui2/views/workflows/workflow_step_view.py
"""
Workflow Step View

Base class for individual workflow step views (analysis, calculation, export).
"""

import logging
from typing import Optional, Callable, Dict, Any

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from ...models.ui_state_model import UIStateModel
from ...services.event_bus_service import EventBusService
from ...widgets.action_button import ActionButton

logger = logging.getLogger(__name__)


class WorkflowStepView(QWidget):
    """
    Base class for workflow step views.

    Provides common functionality for workflow step views:
    - Step title
    - Action button
    - Progress indicator
    - State management

    Subclasses should implement specific functionality for their step.
    """

    # Signal for step action
    actionTriggered = pyqtSignal()

    def __init__(
            self,
            ui_state: UIStateModel,
            event_bus: EventBusService,
            step_title: str,
            action_text: str,
            state_key: str,
            parent=None
    ):
        """
        Initialize the workflow step view.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            step_title: Title of this workflow step
            action_text: Text for the action button
            state_key: Key in UI state for button enabled state
            parent: Parent widget
        """
        super().__init__(parent)

        self.ui_state = ui_state
        self.event_bus = event_bus
        self.step_title = step_title
        self.action_text = action_text
        self.state_key = state_key

        # Initialize UI
        self._init_ui()

        logger.debug(f"WorkflowStepView '{step_title}' initialized")

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Step title
        title_label = QLabel(self.step_title)
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Action button row
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 5, 0, 5)

        # Action button using ActionButton widget
        self.action_button = ActionButton(
            self.action_text,
            self.ui_state,
            self.state_key,
            on_click=self._on_action_button_clicked
        )
        button_layout.addWidget(self.action_button)

        # Add spacer to push button to the left
        button_layout.addStretch()

        layout.addLayout(button_layout)

        # Status message (optional, for progress/status)
        self.status_label = QLabel("")
        self.status_label.setVisible(False)  # Hide initially
        layout.addWidget(self.status_label)

    @pyqtSlot()
    def _on_action_button_clicked(self):
        """Handle action button click."""
        logger.debug(f"Action button clicked for step '{self.step_title}'")
        self.actionTriggered.emit()

    def set_busy(self, busy: bool, message: Optional[str] = None):
        """
        Set the busy state of this step.

        Args:
            busy: Whether this step is busy
            message: Optional status message to display
        """
        if busy:
            self.action_button.set_busy(True, "Working...")
            if message:
                self.status_label.setText(message)
                self.status_label.setVisible(True)
        else:
            self.action_button.set_busy(False)
            if not message:
                self.status_label.setVisible(False)
            else:
                self.status_label.setText(message)
                self.status_label.setVisible(True)

    def update_status(self, message: Optional[str] = None):
        """
        Update the status message.

        Args:
            message: Status message to display, or None to hide
        """
        if message:
            self.status_label.setText(message)
            self.status_label.setVisible(True)
        else:
            self.status_label.setVisible(False)


class AnalysisStepView(WorkflowStepView):
    """Workflow step view for source analysis."""

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService, parent=None):
        """Initialize the analysis step view."""
        super().__init__(
            ui_state,
            event_bus,
            step_title="1. Source Analysis",
            action_text="Analyze Sources",
            state_key="color_prep_can_analyze",
            parent=parent
        )


class CalculationStepView(WorkflowStepView):
    """Workflow step view for segment calculation."""

    def __init__(
            self,
            ui_state: UIStateModel,
            event_bus: EventBusService,
            workflow: str = 'color',
            parent=None
    ):
        """
        Initialize the calculation step view.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            workflow: Workflow type ('color' or 'online')
            parent: Parent widget
        """
        self.workflow = workflow
        state_key = f"{workflow}_prep_can_calculate"

        super().__init__(
            ui_state,
            event_bus,
            step_title=f"2. Calculate Segments",
            action_text=f"Calculate {workflow.capitalize()} Segments",
            state_key=state_key,
            parent=parent
        )


class ExportStepView(WorkflowStepView):
    """Workflow step view for export."""

    def __init__(
            self,
            ui_state: UIStateModel,
            event_bus: EventBusService,
            workflow: str = 'color',
            parent=None
    ):
        """
        Initialize the export step view.

        Args:
            ui_state: UI state model
            event_bus: Event bus service
            workflow: Workflow type ('color' or 'online')
            parent: Parent widget
        """
        self.workflow = workflow
        state_key = f"{workflow}_prep_can_export"

        if workflow == 'color':
            title = "3. Export Timeline"
            action_text = "Export EDL/XML..."
        else:
            title = "3. Transcode Media"
            action_text = "Start Transcoding"

        super().__init__(
            ui_state,
            event_bus,
            step_title=title,
            action_text=action_text,
            state_key=state_key,
            parent=parent
        )
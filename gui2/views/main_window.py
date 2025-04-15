# gui2/views/main_window.py
"""
Main Window for TimelineHarvester

Container for all application views and central UI component.
Minimal logic, primarily responsible for layout and navigation.
"""

import logging
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QStatusBar, QToolBar, QAction
)

from ..controllers.application_controller import ApplicationController
from ..controllers.project_controller import ProjectController  # Add ProjectController import
from ..models.ui_state_model import UIStateModel
from ..services.dialog_service import DialogService
from ..services.event_bus_service import EventBusService, EventType, EventData

# Import views
from .project_view import ProjectView
from .workspace_view import WorkspaceView

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """
    Main application window that serves as a container for all views.

    Responsibilities:
    - Create and organize application layout
    - Set up menu and toolbar
    - Connect event handlers for global operations
    - Delegate functionality to controllers and other views
    """

    def __init__(
            self,
            app_controller: ApplicationController,
            ui_state: UIStateModel,
            event_bus: EventBusService,
            dialog_service: DialogService,
            project_controller: Optional[ProjectController] = None  # Add ProjectController parameter
    ):
        """Initialize the main window with required services and controllers."""
        super().__init__()

        # Store references to services and controllers
        self.app_controller = app_controller
        self.project_controller = project_controller  # Store ProjectController reference
        self.ui_state = ui_state
        self.event_bus = event_bus
        self.dialog_service = dialog_service

        # Set window properties
        self.setWindowTitle("TimelineHarvester")
        self.setMinimumSize(1200, 800)

        # Initialize UI components
        self._init_ui()
        self._create_actions()
        self._create_menu()
        self._create_toolbar()
        self._connect_signals()

        logger.debug("MainWindow initialized")

        # Publish the APP_READY event when initialization is complete
        self.event_bus.publish(EventData(EventType.APP_READY))

    def _init_ui(self):
        """Initialize the main UI components and layout."""
        # Create the central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Create the project view (top panel)
        self.project_view = ProjectView(self.ui_state, self.event_bus)
        main_layout.addWidget(self.project_view)

        # Create workspace view (tabbed interface for workflows)
        self.workspace_view = WorkspaceView(self.ui_state, self.event_bus)
        main_layout.addWidget(self.workspace_view, 1)  # Give it stretch priority

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        logger.debug("MainWindow UI layout created")

    def _create_actions(self):
        """Create actions for menus and toolbars."""
        # File menu actions
        self.action_new = QAction("&New Project", self)
        self.action_new.setShortcut("Ctrl+N")
        self.action_new.setStatusTip("Create a new project")

        self.action_open = QAction("&Open Project...", self)
        self.action_open.setShortcut("Ctrl+O")
        self.action_open.setStatusTip("Open an existing project")

        self.action_save = QAction("&Save Project", self)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.setStatusTip("Save the current project")

        self.action_save_as = QAction("Save Project &As...", self)
        self.action_save_as.setStatusTip("Save the current project with a new name")

        self.action_exit = QAction("E&xit", self)
        self.action_exit.setShortcut("Ctrl+Q")
        self.action_exit.setStatusTip("Exit the application")

        # Help menu actions
        self.action_about = QAction("&About", self)
        self.action_about.setStatusTip("Show information about TimelineHarvester")

    def _create_menu(self):
        """Create the application menu bar."""
        # Main menu bar
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.action_exit)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.action_about)

    def _create_toolbar(self):
        """Create the application toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Add actions to toolbar
        toolbar.addAction(self.action_new)
        toolbar.addAction(self.action_open)
        toolbar.addAction(self.action_save)

    def _connect_signals(self):
        """Connect UI signals to handlers."""
        # Connect file actions
        self.action_new.triggered.connect(self._on_new_project)
        self.action_open.triggered.connect(self._on_open_project)
        self.action_save.triggered.connect(self._on_save_project)
        self.action_save_as.triggered.connect(self._on_save_project_as)
        self.action_exit.triggered.connect(self.close)

        # Connect help actions
        self.action_about.triggered.connect(self._on_show_about)

        # Subscribe to events
        self.event_bus.subscribe(EventType.PROJECT_LOADED, self._on_project_loaded)

        # Connect to UI state changes
        self.ui_state.stateChanged.connect(self._on_ui_state_changed)

    @pyqtSlot()
    def _on_new_project(self):
        """Handle 'New Project' action."""
        if self.ui_state.get('project_dirty', False):
            save_changes = self.dialog_service.confirm_save_changes("Save changes before creating a new project?")
            if save_changes is None:  # Cancelled
                return
            elif save_changes:  # Yes
                if not self._on_save_project():  # If save failed
                    return

        # Use project_controller instead of app_controller
        if self.project_controller:
            self.project_controller.new_project()
        else:
            # Fallback to app_controller if project_controller not available
            self.app_controller.new_project()

    @pyqtSlot()
    def _on_open_project(self):
        """Handle 'Open Project' action."""
        if self.ui_state.get('project_dirty', False):
            save_changes = self.dialog_service.confirm_save_changes("Save changes before opening a project?")
            if save_changes is None:  # Cancelled
                return
            elif save_changes:  # Yes
                if not self._on_save_project():  # If save failed
                    return

        # Show open project dialog
        file_path = self.dialog_service.get_open_filename(
            "Open Project",
            filter="TimelineHarvester Projects (*.thp);;All Files (*)"
        )

        if file_path:
            # Use project_controller instead of app_controller
            if self.project_controller:
                self.project_controller.load_project(file_path)
            else:
                # Fallback to app_controller if project_controller not available
                self.app_controller.load_project(file_path)

    @pyqtSlot()
    def _on_save_project(self) -> bool:
        """Handle 'Save Project' action."""
        current_path = self.ui_state.get('current_project_path')

        if not current_path:
            return self._on_save_project_as()

        # Use project_controller instead of app_controller
        if self.project_controller:
            return self.project_controller.save_project(current_path)
        else:
            # Fallback to app_controller if project_controller not available
            # Note: This will fail if app_controller doesn't have save_project method
            return self.app_controller.save_project(current_path)

    @pyqtSlot()
    def _on_save_project_as(self) -> bool:
        """Handle 'Save Project As' action."""
        file_path = self.dialog_service.get_save_filename(
            "Save Project As",
            filter="TimelineHarvester Projects (*.thp);;All Files (*)"
        )

        if file_path:
            # Use project_controller instead of app_controller
            if self.project_controller:
                return self.project_controller.save_project(file_path)
            else:
                # Fallback to app_controller if project_controller not available
                # Note: This will fail if app_controller doesn't have save_project method
                return self.app_controller.save_project(file_path)

        return False

    @pyqtSlot()
    def _on_show_about(self):
        """Handle 'About' action."""
        self.dialog_service.show_about_dialog()

    @pyqtSlot(EventData)
    def _on_project_loaded(self, event_data: EventData):
        """Handle project loaded event."""
        # Update window title
        project_path = event_data.project_path
        self._update_window_title(project_path)

        # Update status bar
        if project_path:
            self.status_bar.showMessage(f"Project loaded: {project_path}")
        else:
            self.status_bar.showMessage("New project created")

    @pyqtSlot(str, object)
    def _on_ui_state_changed(self, key: str, value: object):
        """Handle UI state changes."""
        # Update save action enabled state
        if key == 'project_dirty':
            self.action_save.setEnabled(value and self.ui_state.get('current_project_path') is not None)

        # Update window title when project path changes
        elif key == 'current_project_path':
            self._update_window_title(value)

    def _update_window_title(self, project_path: Optional[str]):
        """Update the window title based on project state."""
        base_title = "TimelineHarvester"
        is_dirty = self.ui_state.get('project_dirty', False)

        if project_path:
            import os
            filename = os.path.basename(project_path)
            dirty_indicator = "*" if is_dirty else ""
            self.setWindowTitle(f"{filename}{dirty_indicator} - {base_title}")
        else:
            dirty_indicator = "*" if is_dirty else ""
            self.setWindowTitle(f"Untitled{dirty_indicator} - {base_title}")

    def closeEvent(self, event):
        """Handle window close event."""
        if self.ui_state.get('project_dirty', False):
            save_changes = self.dialog_service.confirm_save_changes("Save changes before exiting?")
            if save_changes is None:  # Cancelled
                event.ignore()
                return
            elif save_changes:  # Yes
                if not self._on_save_project():
                    event.ignore()
                    return

        # Application is closing, notify controllers
        self.event_bus.publish(EventData(EventType.APP_CLOSING))
        event.accept()

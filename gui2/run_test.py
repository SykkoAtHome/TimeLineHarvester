#!/usr/bin/env python3
# gui2/run_test.py
"""
Test script for GUI2 development

Creates a minimal application instance to test the new GUI components.
This script can be run directly to test the GUI2 implementation.
"""
try:
    import opentimelineio as otio
    from opentimelineio import opentime
except Exception as e:
    print(f"CRITICAL ERROR: Failed to load OpenTimelineIO. Cannot continue.", file=sys.stderr)

import sys
import logging
import os

# Ensure parent directory (project root) is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(name)s.%(funcName)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("gui2_test")

# Import Qt
try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
except ImportError:
    logger.critical("Failed to import PyQt5. Make sure it's installed.")
    sys.exit(1)

# Import facade
try:
    from core.timeline_harvester_facade import TimelineHarvesterFacade
except ImportError:
    logger.critical("Failed to import core modules. Check your project structure.")
    sys.exit(1)

# Import GUI2 modules
try:
    # Import models
    from gui2.models.ui_state_model import UIStateModel

    # Import services
    from gui2.services.event_bus_service import EventBusService
    from gui2.services.dialog_service import DialogService
    from gui2.services.state_update_service import StateUpdateService

    # Import controllers
    from gui2.controllers.application_controller import ApplicationController
    from gui2.controllers.project_controller import ProjectController

    # Import views
    from gui2.views.main_window import MainWindow
except ImportError as e:
    logger.critical(f"Failed to import GUI2 modules: {e}")
    sys.exit(1)


def main():
    """Main function to initialize and run the GUI test."""
    logger.info("Starting GUI2 test")

    # Create QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("TimelineHarvester-GUI2-Test")

    try:
        # Initialize core components
        facade = TimelineHarvesterFacade()
        logger.info("Core Facade initialized")

        # Initialize models
        ui_state = UIStateModel()

        # Initialize services
        event_bus = EventBusService()
        dialog_service = DialogService()
        state_update = StateUpdateService(facade, ui_state)

        # Initialize controllers
        app_controller = ApplicationController(facade, event_bus, ui_state)
        project_controller = ProjectController(facade, ui_state, event_bus, state_update)

        # Initialize main window
        window = MainWindow(app_controller, ui_state, event_bus, dialog_service)
        dialog_service.set_parent(window)  # Set parent for dialogs

        logger.info("GUI components initialized")

        # Show the window
        window.show()

        # Start the event loop
        logger.info("Starting event loop")
        return app.exec_()

    except Exception as e:
        logger.critical(f"Error initializing GUI: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    # Configure high DPI scaling
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    sys.exit(main())

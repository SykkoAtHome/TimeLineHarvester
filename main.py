# main.py
#!/usr/bin/env python3
# main.py - Application entry point
import sys
import logging
import os

from core.about import TLH_VERSION

# Determine application directory
if getattr(sys, 'frozen', False):
    app_dir = os.path.dirname(sys.executable)
else:
    app_dir = os.path.dirname(os.path.abspath(__file__))

# Configure logging
log_file_path = os.path.join(app_dir, "timelineharvester.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(name)s.%(funcName)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("main")

logger.info("-" * 50)
logger.info("Starting TimelineHarvester application")
logger.info(f"Python Version: {sys.version}")
logger.info(f"App Directory: {app_dir}")
logger.info(f"Logging to file: {log_file_path}")

# Import OpenTimelineIO first to ensure it's available and will not crash PyQt
try:
    logger.info("Importing opentimelineio...")
    import opentimelineio as otio
    from opentimelineio import opentime

    logger.info(f"OpenTimelineIO import successful. Version: {otio.__version__}")
except Exception as e:
    logger.critical(f"CRITICAL: Failed to import OpenTimelineIO: {e}", exc_info=True)
    print(f"CRITICAL ERROR: Failed to load OpenTimelineIO. Cannot continue.", file=sys.stderr)
    sys.exit(1)  # Exit early if essential OTIO fails

# Import PyQt5
try:
    logger.info("Importing PyQt5...")
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import qVersion, QCoreApplication, Qt

    logger.info(f"PyQt5 imported successfully. Qt Version: {qVersion()}")
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import PyQt5: {str(e)}", exc_info=True)
    print(f"CRITICAL ERROR: Failed to import PyQt5: {str(e)}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during PyQt5 import: {str(e)}", exc_info=True)
    print(f"CRITICAL ERROR: PyQt5 import error: {str(e)}", file=sys.stderr)
    sys.exit(1)

# Import application modules (CORE)
try:
    logger.info("Importing CORE application modules...")
    from core.timeline_harvester_facade import TimelineHarvesterFacade
    logger.info("Core Facade imported successfully.")
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import CORE modules: {str(e)}", exc_info=True)
    error_message = f"Failed to load CORE modules: {str(e)}"
    try:
        QMessageBox.critical(None, "Application Load Error", error_message)
    except:
        print(f"CRITICAL ERROR: {error_message}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during CORE module import: {str(e)}", exc_info=True)
    error_message = f"Unexpected error loading CORE modules: {str(e)}"
    try:
        QMessageBox.critical(None, "Application Load Error", error_message)
    except:
        print(f"CRITICAL ERROR: {error_message}", file=sys.stderr)
    sys.exit(1)

# Import GUI2 components
try:
    logger.info("Importing GUI2 modules...")
    # GUI2 Models
    from gui2.models.ui_state_model import UIStateModel
    # GUI2 Services
    from gui2.services.event_bus_service import EventBusService
    from gui2.services.dialog_service import DialogService
    from gui2.services.state_update_service import StateUpdateService
    from gui2.services.threading_service import ThreadingService
    # GUI2 Controllers
    from gui2.controllers.application_controller import ApplicationController
    from gui2.controllers.project_controller import ProjectController
    from gui2.controllers.workflow_controller import WorkflowController
    # GUI2 Views
    from gui2.views.main_window import MainWindow as MainWindowGUI2 # Alias to avoid name clash
    from gui2.views.color_prep.color_prep_view import ColorPrepView
    from gui2.views.online_prep.online_prep_view import OnlinePrepView

    logger.info("GUI2 modules imported successfully.")
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import GUI2 modules: {str(e)}", exc_info=True)
    error_message = f"Failed to load GUI2 modules: {str(e)}"
    try:
        QMessageBox.critical(None, "Application Load Error", error_message)
    except:
        print(f"CRITICAL ERROR: {error_message}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during GUI2 module import: {str(e)}", exc_info=True)
    error_message = f"Unexpected error loading GUI2 modules: {str(e)}"
    try:
        QMessageBox.critical(None, "Application Load Error", error_message)
    except:
        print(f"CRITICAL ERROR: {error_message}", file=sys.stderr)
    sys.exit(1)


def main():
    """Main application entry point."""
    logger.info("Main function started")

    # Set application attributes
    QCoreApplication.setOrganizationName("TimelineHarvesterOrg")
    QCoreApplication.setApplicationName("TimelineHarvester")
    QCoreApplication.setApplicationVersion(TLH_VERSION)

    # Create QApplication
    app_instance = QApplication.instance() or QApplication(sys.argv)

    try:
        # --- Initialize Core Components ---
        harvester_core = TimelineHarvesterFacade()
        logger.info("Core Facade engine initialized")

        # --- Initialize GUI2 Infrastructure ---
        logger.info("Initializing GUI2 infrastructure...")
        # Models
        ui_state = UIStateModel()
        # Services
        event_bus = EventBusService()
        dialog_service = DialogService()
        state_update = StateUpdateService(harvester_core, ui_state)
        threading_service = ThreadingService(ui_state, event_bus)
        # Controllers
        app_controller = ApplicationController(harvester_core, event_bus, ui_state)
        project_controller = ProjectController(harvester_core, ui_state, event_bus, state_update)
        workflow_controller = WorkflowController(
            harvester_core, ui_state, event_bus, state_update, dialog_service, threading_service
        )
        logger.info("GUI2 infrastructure initialized.")

        # --- Create and show GUI2 main window ---
        logger.info("Creating GUI2 main window...")
        window = MainWindowGUI2(
            app_controller,
            ui_state,
            event_bus,
            dialog_service,
            project_controller  # Pass the project_controller to MainWindow
        )
        dialog_service.set_parent(window) # Important for dialogs

        # --- Add actual workflow views to the workspace ---
        # Replace placeholders in WorkspaceView
        color_prep_view = ColorPrepView(ui_state, event_bus)
        online_prep_view = OnlinePrepView(ui_state, event_bus)
        window.workspace_view.replace_placeholder_tabs(color_prep_view, online_prep_view)

        logger.info("Main window created")
        window.show()
        logger.info("Main window displayed. Starting event loop")

        # Start application event loop
        exit_code = app_instance.exec_()
        logger.info(f"Event loop finished. Exit code: {exit_code}")
        return exit_code
    except Exception as e:
        logger.critical(f"Unhandled runtime exception: {str(e)}", exc_info=True)
        try:
            QMessageBox.critical(None, "Critical Runtime Error",
                                 f"An unexpected error occurred:\n\n{str(e)}\n\n"
                                 f"See log:\n{log_file_path}")
        except Exception as msg_err:
            print(f"CRITICAL RUNTIME ERROR: {e}. Cannot show GUI error message: {msg_err}", file=sys.stderr)
            print(f"Log file: {log_file_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Configure high DPI scaling
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    exit_status = main()
    logger.info(f"Application exiting with status: {exit_status}")
    logging.shutdown()
    sys.exit(exit_status)

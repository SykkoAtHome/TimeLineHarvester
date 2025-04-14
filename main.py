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

# Import OpenTimelineIO first to ensure it's available
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

# Import application modules
try:
    logger.info("Importing application modules...")
    from core.timeline_harvester_facade import TimelineHarvesterFacade
    from gui.main_window import MainWindow

    logger.info("Application modules imported successfully.")
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import application modules: {str(e)}", exc_info=True)
    error_message = f"Failed to load application modules: {str(e)}"
    try:
        QMessageBox.critical(None, "Application Load Error", error_message)
    except:
        print(f"CRITICAL ERROR: {error_message}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during module import: {str(e)}", exc_info=True)
    error_message = f"Unexpected error loading application modules: {str(e)}"
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
        # Initialize core components
        harvester_core = TimelineHarvesterFacade()
        logger.info("Core Facade engine initialized")

        # Create and show main window
        window = MainWindow(harvester_core)
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

# main.py - Test Dummy OTIO Import First (Corrected - Final)
import sys
import logging
import os

# --- Determine App Directory FIRST ---
if getattr(sys, 'frozen', False):
    app_dir = os.path.dirname(sys.executable)
else:
    app_dir = os.path.dirname(os.path.abspath(__file__))

# --- Logging Setup ---
# Define log_file_path at the global scope
log_file_path = os.path.join(app_dir, "timelineharvester.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(name)s.%(funcName)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("DummyImportTest")

logger.info("-" * 50)
logger.info("--- Testing Dummy OTIO Import First ---")
logger.info(f"Python Version: {sys.version}")
logger.info(f"App Directory: {app_dir}")
logger.info(f"Logging to file: {log_file_path}")

# --- DUMMY IMPORT OTIO FIRST ---
otio_dummy_loaded = False
try:
    logger.info("Attempting DUMMY import of opentimelineio...")
    import opentimelineio as otio
    from opentimelineio import opentime

    _dummy_time = opentime.RationalTime(0, 25)  # Simple access test
    logger.info(f"DUMMY import of opentimelineio successful. Version: {otio.__version__}")
    otio_dummy_loaded = True
except Exception as e:
    logger.critical(f"CRITICAL: DUMMY import of opentimelineio FAILED: {e}", exc_info=True)
    print(f"CRITICAL ERROR: Failed to load OpenTimelineIO. Cannot continue.", file=sys.stderr)
    sys.exit(1)  # Exit early if essential OTIO fails

# --- Attempt to import PyQt5 SECOND ---
pyqt_loaded = False
pyqt_error_message = ""
try:
    logger.info("Attempting to import PyQt5...")
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import qVersion, QCoreApplication, Qt

    logger.info(f"PyQt5 imported successfully. Qt Version: {qVersion()}")
    pyqt_loaded = True
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import PyQt5 (after dummy OTIO): {str(e)}", exc_info=True)
    pyqt_error_message = f"Failed to import PyQt5: {str(e)}"
    print(f"CRITICAL ERROR (PyQt5):\n{pyqt_error_message}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during PyQt5 import (after dummy OTIO): {str(e)}", exc_info=True)
    pyqt_error_message = f"Unexpected error during PyQt5 import: {str(e)}"
    print(f"CRITICAL ERROR (PyQt5 during import):\n{pyqt_error_message}", file=sys.stderr)
    sys.exit(1)

# --- Attempt to import Core Facade and GUI THIRD ---
core_gui_loaded = False
core_gui_error_message = ""
# No need to check pyqt_loaded again, we exited if it failed
try:
    logger.info("Attempting to import Core Facade and GUI...")
    from core.timeline_harvester_facade import TimelineHarvesterFacade
    from gui.main_window import MainWindow

    logger.info("Core Facade and GUI modules imported successfully.")
    core_gui_loaded = True
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import Core/GUI (after dummy OTIO): {str(e)}", exc_info=True)
    core_gui_error_message = f"Failed to load application modules (Core/GUI): {str(e)}"
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during Core/GUI import (after dummy OTIO): {str(e)}", exc_info=True)
    core_gui_error_message = f"Unexpected error loading application modules: {str(e)}"


# --- Main Application Function ---
def main():
    logger.info("Main function started.")
    # Re-check imports for safety before proceeding
    if not otio_dummy_loaded:
        logger.error("Sanity Check Failed: OTIO initial load failed.")
        print(f"INTERNAL ERROR: OTIO load state lost.", file=sys.stderr)
        return 1
    if not pyqt_loaded:
        logger.error("Sanity Check Failed: PyQt5 not loaded.")
        print(f"INTERNAL ERROR: PyQt5 load state lost.", file=sys.stderr)
        return 1
    if not core_gui_loaded:
        logger.error("Core/GUI failed to load.")
        try:
            QMessageBox.critical(None, "Application Load Error", core_gui_error_message)
        except Exception as msg_err:
            print(f"CRITICAL ERROR (Core/GUI):\n{core_gui_error_message}", file=sys.stderr)
            print(f"(Could not display GUI error message: {msg_err})", file=sys.stderr)
        return 1

    logger.info("All essential modules loaded successfully (with dummy OTIO import).")

    # Set application attributes
    QCoreApplication.setOrganizationName("TimelineHarvesterOrg")
    QCoreApplication.setApplicationName("TimelineHarvester")
    QCoreApplication.setApplicationVersion("2.0.0")

    # Create QApplication
    app_instance = QApplication.instance() or QApplication(sys.argv)

    try:
        logger.info("Initializing application components...")
        # Instantiate the facade (it was already imported successfully)
        harvester_core = TimelineHarvesterFacade()
        logger.info("Core Facade engine initialized.")
        # Instantiate the main window (it was already imported successfully)
        window = MainWindow(harvester_core)
        logger.info("Main window created.")
        window.show()
        logger.info("Main window displayed. Starting event loop.")
        exit_code = app_instance.exec_()
        logger.info(f"Event loop finished. Exit code: {exit_code}")
        return exit_code
    except Exception as e:
        logger.critical(f"Unhandled runtime exception: {str(e)}", exc_info=True)
        try:
            # Use the globally defined log_file_path
            QMessageBox.critical(None, "Critical Runtime Error",
                                 f"An unexpected error occurred:\n\n{str(e)}\n\n"
                                 f"See log:\n{log_file_path}")  # Reference global variable
        except Exception as msg_err:
            print(f"CRITICAL RUNTIME ERROR: {e}. Cannot show GUI error message: {msg_err}", file=sys.stderr)
            # Use the globally defined log_file_path
            print(f"Log file: {log_file_path}", file=sys.stderr)  # Reference global variable
        return 1


# --- Script Execution Guard ---
if __name__ == "__main__":
    logger.info("Script execution started.")
    # Optional High DPI scaling attributes
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    exit_status = main()
    logger.info(f"--- Application Exiting (Status: {exit_status}) ---")
    logging.shutdown()
    sys.exit(exit_status)

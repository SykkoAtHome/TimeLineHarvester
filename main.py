# main.py - Step 3e: Test Standard Import Order with Facade
import sys
import logging
import os

# --- Determine App Directory FIRST ---
if getattr(sys, 'frozen', False):
    app_dir = os.path.dirname(sys.executable)
else:
    app_dir = os.path.dirname(os.path.abspath(__file__))

# --- Logging Setup ---
log_file_path = os.path.join(app_dir, "timelineharvester_app_standard_order.log")
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG for testing
    format='%(asctime)s - %(levelname)s - [%(name)s.%(funcName)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("StandardOrderTest")  # New logger name

logger.info("-" * 50)
logger.info("--- Testing Standard Import Order with Facade ---")
logger.info(f"App Directory: {app_dir}")

# --- Attempt to import PyQt5 FIRST ---
pyqt_loaded = False
pyqt_error_message = ""
try:
    logger.info("Attempting to import PyQt5...")
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import qVersion, QCoreApplication, Qt

    logger.info(f"PyQt5 imported successfully. Qt Version: {qVersion()}")
    pyqt_loaded = True
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import PyQt5: {str(e)}", exc_info=True)
    pyqt_error_message = f"Failed to import PyQt5: {str(e)}"
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during PyQt5 import: {str(e)}", exc_info=True)
    pyqt_error_message = f"Unexpected error during PyQt5 import: {str(e)}"

# --- Attempt to import Core Facade and GUI SECOND ---
core_gui_loaded = False
core_gui_error_message = ""
if pyqt_loaded:  # Only proceed if PyQt loaded
    try:
        logger.info("Attempting to import Core Facade and GUI...")
        from core.timeline_harvester_facade import TimelineHarvesterFacade
        # Import MainWindow AFTER facade and AFTER PyQt5
        from gui.main_window import MainWindow

        logger.info("Core Facade and GUI modules imported successfully.")
        core_gui_loaded = True
    except ImportError as e:
        logger.critical(f"CRITICAL: Failed to import Core/GUI: {str(e)}", exc_info=True)
        core_gui_error_message = f"Failed to load application modules (Core/GUI): {str(e)}"
    except Exception as e:
        logger.critical(f"CRITICAL: Unexpected error during Core/GUI import: {str(e)}", exc_info=True)
        core_gui_error_message = f"Unexpected error loading application modules: {str(e)}"


# --- Main Application Function ---
def main():
    logger.info("Main function started.")
    # Check import results
    if not pyqt_loaded:
        logger.error("PyQt5 failed to load. Cannot start GUI.")
        print(f"CRITICAL ERROR (PyQt5):\n{pyqt_error_message}", file=sys.stderr)
        return 1
    if not core_gui_loaded:
        logger.error("Core/GUI failed to load. Cannot start application.")
        # Try to show error using QMessageBox since PyQt *might* be loaded
        try:
            QMessageBox.critical(None, "Application Load Error", core_gui_error_message)
        except:
            print(f"CRITICAL ERROR (Core/GUI):\n{core_gui_error_message}", file=sys.stderr)
        return 1

    logger.info("All essential modules loaded successfully.")

    # Set application attributes
    QCoreApplication.setOrganizationName("TimelineHarvesterOrg")
    QCoreApplication.setApplicationName("TimelineHarvester")
    QCoreApplication.setApplicationVersion("2.0.0")

    # Create QApplication
    app_instance = QApplication.instance() or QApplication(sys.argv)

    try:
        logger.info("Initializing application components...")
        harvester_core = TimelineHarvesterFacade()
        logger.info("Core Facade engine initialized.")
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
            QMessageBox.critical(None, "Critical Runtime Error",
                                 f"An unexpected error occurred:\n\n{str(e)}\n\nSee log:\n{log_file_path}")
        except:
            print(f"CRITICAL RUNTIME ERROR: {e}.", file=sys.stderr)
        return 1


# --- Script Execution Guard ---
if __name__ == "__main__":
    logger.info("Script execution started.")
    if hasattr(Qt, 'AA_EnableHighDpiScaling'): QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'): QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    exit_status = main()
    logger.info(f"--- Application Exiting (Status: {exit_status}) ---")
    logging.shutdown()
    sys.exit(exit_status)

# main.py (Full Application - Test Import Order - Corrected)
import sys
import logging
import os

# --- Determine App Directory FIRST ---
if getattr(sys, 'frozen', False):
    # If running as a bundled app (e.g., PyInstaller)
    app_dir = os.path.dirname(sys.executable)
else:
    # If running as a script
    app_dir = os.path.dirname(os.path.abspath(__file__))

# --- Logging Setup ---
log_file_path = os.path.join(app_dir, "timelineharvester_MAIN_ImportOrderTest.log") # Use a distinct log file name
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, mode='w', encoding='utf-8'), # Overwrite log for test
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TimelineHarvesterApp") # Use main logger name
logger.info("-" * 50)
logger.info("--- Starting TimelineHarvester Application (Full - Import Order Test) ---")
logger.info(f"Python Version: {sys.version}")
logger.info(f"Application Directory: {app_dir}") # Log the determined directory
logger.info(f"Logging to file: {log_file_path}")


# --- SWAPPED IMPORT ORDER ---
modules_loaded = True
module_error_message = ""
has_pyqt = False # Assume False initially

try:
    # --- Try importing Core/GUI FIRST ---
    logger.info("Attempting to import Core and GUI modules FIRST...")
    from core.timeline_harvester import TimelineHarvester
    from gui.main_window import MainWindow
    logger.info("Core and GUI modules imported successfully.")
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import core or GUI modules: {str(e)}", exc_info=True)
    modules_loaded = False
    module_error_message = f"Failed to load application modules:\n\n{str(e)}" # ... rest of message
except Exception as e:
     logger.critical(f"CRITICAL: Unexpected error during core/GUI import: {str(e)}", exc_info=True)
     modules_loaded = False
     module_error_message = f"Unexpected error loading application modules:\n\n{str(e)}" # ... rest of message

# --- Import PyQt5 SECOND ---
try:
    logger.info("Attempting to import PyQt5 SECOND...")
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import qVersion
    logger.info(f"PyQt5 imported successfully. Qt Version: {qVersion()}")
    has_pyqt = True # Mark PyQt as loaded successfully
except ImportError as e:
    logger.critical(f"CRITICAL: Failed to import PyQt5 (even second): {str(e)}.", exc_info=True)
    # Update error message ONLY if core/gui loaded successfully before
    if modules_loaded:
         module_error_message = f"Failed to import PyQt5:\n\n{str(e)}"
    modules_loaded = False # Mark overall loading as failed if Qt fails
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error during PyQt5 import (second attempt): {str(e)}", exc_info=True)
    if modules_loaded:
         module_error_message = f"Unexpected error during PyQt5 import:\n\n{str(e)}"
    modules_loaded = False


# --- Main Application Function ---
def main():
    # --- Crucial: Create QApplication AFTER importing PyQt ---
    # It might rely on things set up during import.
    # Check if PyQt actually loaded before creating QApplication
    if not has_pyqt:
         logger.critical("PyQt5 failed to load. Cannot start GUI application.")
         print("CRITICAL ERROR: PyQt5 failed to load. Cannot start GUI application.", file=sys.stderr)
         # Print previous error if available
         if module_error_message:
             print(module_error_message, file=sys.stderr)
         return 1

    app_instance = QApplication.instance() or QApplication(sys.argv)

    if not modules_loaded:
        # ... (Error handling for module loading failure) ...
        logger.error(f"Modules failed to load. Error:\n{module_error_message}")
        try: QMessageBox.critical(None, "Module Load Error", module_error_message)
        except Exception as msg_err: print(f"CRITICAL ERROR: {module_error_message}", file=sys.stderr); print(f"(Could not display GUI error message: {msg_err})", file=sys.stderr)
        return 1

    logger.info("Initializing application components...")
    app_instance.setApplicationName("TimelineHarvester")
    app_instance.setApplicationVersion("1.0.0")

    try:
        harvester = TimelineHarvester()
        logger.info("Core TimelineHarvester engine initialized.")
        window = MainWindow(harvester)
        logger.info("Main application window created.")
        window.show()
        logger.info("Main window displayed. Starting Qt event loop.")
        exit_code = app_instance.exec_()
        logger.info(f"Application event loop finished. Exit code: {exit_code}")
        return exit_code
    except Exception as e:
        # ... (Runtime error handling as before) ...
        logger.critical(f"Unhandled exception during runtime: {str(e)}", exc_info=True)
        try: QMessageBox.critical(None, "Critical Runtime Error", f"An unexpected error occurred:\n\n{str(e)}\n\nSee log:\n{log_file_path}")
        except: print(f"CRITICAL ERROR: {e}. Cannot show GUI.", file=sys.stderr)
        return 1

# --- Script Execution Guard ---
if __name__ == "__main__":
    exit_status = main()
    logger.info(f"--- TimelineHarvester Application Exiting (Status: {exit_status}) ---")
    sys.exit(exit_status)
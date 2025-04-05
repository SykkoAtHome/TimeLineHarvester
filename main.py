#!/usr/bin/env python3
"""
TimelineHarvester - Main Application

This module serves as the entry point for the TimelineHarvester application,
which analyzes editing timelines (EDL, AAF, XML) to optimize media transfers.

The application helps to identify source file usage in editing projects and
creates optimized transfer plans with only the necessary media segments.
"""

import sys
import logging
import os

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("timelineharvester.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("TimelineHarvester")
logger.info("Starting TimelineHarvester application")

# Import PyQt5 for GUI
try:
    from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QMessageBox
    from PyQt5.QtCore import Qt

    logger.info("PyQt5 imported successfully")
    has_pyqt = True
except ImportError as e:
    logger.error(f"Failed to import PyQt5: {str(e)}")
    print("Error: PyQt5 is required but not installed. Please install it with 'pip install PyQt5'")
    sys.exit(1)

# Try to import core functionality
try:
    from core.timeline_harvester import TimelineHarvester

    logger.info("Core module imported successfully")
    has_core = True
except ImportError as e:
    logger.error(f"Failed to import core module: {str(e)}")
    has_core = False


    # Define a stub class for testing UI
    class TimelineHarvester:
        """Stub implementation for UI testing"""

        def __init__(self):
            logger.info("Using stub TimelineHarvester for testing")

# Try to import GUI modules
try:
    from gui.main_window import MainWindow

    logger.info("GUI modules imported successfully")
    has_gui = True
except ImportError as e:
    logger.error(f"Failed to import GUI modules: {str(e)}")
    has_gui = False


def main():
    """
    Main entry point for the TimelineHarvester application.
    Initializes the GUI and starts the application.
    """
    logger.info("Initializing application")

    # Create the application
    app = QApplication(sys.argv)
    app.setApplicationName("TimelineHarvester")
    app.setApplicationVersion("1.0.0")

    # Initialize the core TimelineHarvester engine
    try:
        harvester = TimelineHarvester()
        logger.info("Core engine initialized")
    except Exception as e:
        logger.error(f"Failed to initialize core engine: {str(e)}")
        harvester = None

    # Create and show the main window
    if has_gui and harvester:
        try:
            # Use full GUI if available
            window = MainWindow(harvester)
            logger.info("Main window created")
            window.show()
            logger.info("Main window displayed")
        except Exception as e:
            logger.error(f"Failed to create main window: {str(e)}")
            # Fall back to simple window
            show_simple_window(app, str(e))
    else:
        # Show simplified window for testing
        show_simple_window(app)

    # Start the event loop
    return app.exec_()


def show_simple_window(app, error_message=None):
    """
    Show a simple window when the full GUI is not available.

    Args:
        app: QApplication instance
        error_message: Optional error message to display
    """
    window = QMainWindow()
    window.setWindowTitle("TimelineHarvester")
    window.setMinimumSize(800, 600)

    # Central widget
    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout(central)

    # Application title
    title = QLabel("TimelineHarvester")
    title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet("font-size: 24px; font-weight: bold; margin: 20px;")
    layout.addWidget(title)

    # Status message
    if not has_core:
        status = QLabel("Core module not available. Please check installation.")
    elif not has_gui:
        status = QLabel("GUI modules not available. Please check installation.")
    else:
        status = QLabel("Application initialized in fallback mode.")
    status.setAlignment(Qt.AlignCenter)
    status.setStyleSheet("font-size: 14px; margin: 10px;")
    layout.addWidget(status)

    # Error message if provided
    if error_message:
        error = QLabel(f"Error: {error_message}")
        error.setAlignment(Qt.AlignCenter)
        error.setStyleSheet("font-size: 12px; color: red; margin: 10px;")
        layout.addWidget(error)

    # Show the window
    window.show()
    logger.info("Simple window displayed")


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"Unhandled exception: {str(e)}", exc_info=True)
        print(f"Critical error: {str(e)}")

        if has_pyqt:
            # Show error message box if PyQt is available
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Critical Error",
                                 f"An unhandled exception occurred:\n\n{str(e)}\n\nSee log for details.")

        sys.exit(1)
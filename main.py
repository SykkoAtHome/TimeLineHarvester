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

# Import PyQt5 for GUI
from PyQt5.QtWidgets import QApplication

# Import our GUI components
from gui.main_window import MainWindow

# Import core functionality
from core.timeline_harvester import TimelineHarvester


def main():
    """
    Main entry point for the TimelineHarvester application.
    Initializes the GUI and starts the application.
    """
    logger.info("Starting TimelineHarvester application")

    # Create the application
    app = QApplication(sys.argv)
    app.setApplicationName("TimelineHarvester")
    app.setApplicationVersion("1.0.0")

    # Initialize the core TimelineHarvester engine
    harvester = TimelineHarvester()

    # Create and show the main window
    window = MainWindow(harvester)
    window.show()

    # Start the event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
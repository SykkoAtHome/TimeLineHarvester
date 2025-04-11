# gui/__init__.py
"""
TimelineHarvester GUI Package

Contains PyQt5 user interface components.
"""

# Optionally expose key classes at the package level
from .main_window import MainWindow
from .file_panel import FilePanel
from .settings_panel import SettingsPanel
from .results_panel import ResultsPanel
from .status_bar import StatusBarManager

__all__ = [
    'MainWindow',
    'FilePanel',
    'SettingsPanel',
    'ResultsPanel',
    'StatusBarManager'
]
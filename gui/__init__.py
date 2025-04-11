# gui/__init__.py
"""
TimelineHarvester GUI Package
"""
from .main_window import MainWindow
from .common.file_list_widget import FileListWidget
from .project_panel import ProjectPanel
from .color_prep_tab import ColorPrepTabWidget
from .online_prep_tab import OnlinePrepTabWidget
# results_display might be needed later
from .status_bar import StatusBarManager

__all__ = [
    'MainWindow',
    'FileListWidget',
    'ProjectPanel',
    'ColorPrepTabWidget',
    'OnlinePrepTabWidget',
    'StatusBarManager',
    # Add ProfileEditDialog if kept in settings_panel or moved to common
]
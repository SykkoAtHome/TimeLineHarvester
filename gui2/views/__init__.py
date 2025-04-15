# gui2/views/__init__.py
"""
Views package for TimelineHarvester GUI2.

Contains UI component views following the MVC architecture.
"""

# Import views for convenience
from .main_window import MainWindow
from .project_view import ProjectView
from .workspace_view import WorkspaceView

# For easier imports
__all__ = [
    'MainWindow',
    'ProjectView',
    'WorkspaceView'
]
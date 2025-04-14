# gui2/widgets/tables/unresolved_items_table.py
"""
Unresolved Items Table Widget

Specialized table for displaying error items and unresolved shots.
"""

import logging
from typing import List, Dict, Any, Optional

from PyQt5.QtWidgets import QTableWidgetItem
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

from .base_table import BaseTableWidget

logger = logging.getLogger(__name__)


class UnresolvedItemsTable(BaseTableWidget):
    """
    Table widget for displaying unresolved items and errors.

    Features:
    - Display of clip names and error messages
    - Status-based row coloring
    - Filtering
    """
    # Column indices constants for easy reference
    COL_NAME = 0
    COL_EDIT_MEDIA_ID = 1
    COL_STATUS = 2
    COL_EDIT_RANGE = 3

    def __init__(self, parent=None):
        """Initialize the UnresolvedItemsTable."""
        # Define columns
        headers = [
            "Clip Name", "Edit Media ID", "Lookup Status", "Edit Range"
        ]

        column_keys = [
            "name", "proxy_path", "status", "edit_range"
        ]

        # Columns to stretch (text fields)
        stretch_columns = [
            self.COL_EDIT_MEDIA_ID,
            self.COL_EDIT_RANGE
        ]

        # Columns with fixed width (status)
        fixed_columns = [
            self.COL_STATUS
        ]

        super().__init__(
            headers,
            column_keys,
            stretch_columns,
            fixed_columns,
            with_filter=True,
            parent=parent
        )

        logger.debug("UnresolvedItemsTable initialized")

    def get_row_color(self, row_data: Dict[str, Any]) -> QColor:
        """
        Get the background color for a row based on its status.

        Override from base class to customize row coloring for unresolved items.

        Args:
            row_data: Dictionary containing row data

        Returns:
            QColor to use for the row background
        """
        status_lower = row_data.get('status', '').lower()

        # Check for different error types
        if 'not found' in status_lower or 'not_found' in status_lower:
            return QColor(255, 200, 200)  # Light red for not found
        elif 'error' in status_lower:
            return QColor(255, 160, 122)  # Salmon for errors
        elif 'pending' in status_lower:
            return QColor(255, 255, 200)  # Light yellow for pending
        else:
            return QColor(255, 255, 255)  # White default

    def get_selected_items(self) -> List[Dict[str, Any]]:
        """
        Get the data for selected unresolved items.

        Returns:
            List of dictionaries for selected items
        """
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        selected_data = []
        for row in selected_rows:
            if 0 <= row < len(self._rows_data):
                # Get the original data for this row
                original_index = int(self.table.item(row, 0).data(Qt.UserRole))
                if 0 <= original_index < len(self._rows_data):
                    selected_data.append(self._rows_data[original_index])

        return selected_data

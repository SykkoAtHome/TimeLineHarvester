# gui2/widgets/tables/base_table.py
"""
Base Table Widget

Provides a foundation for specialized table widgets with common
functionality like sorting, filtering, and styling.
"""

import logging
from typing import List, Dict, Any, Optional

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QWidget,
    QLabel, QLineEdit, QComboBox
)

from ...utils.qt_helpers import create_vbox_layout, create_hbox_layout

logger = logging.getLogger(__name__)


class BaseTableWidget(QWidget):
    """
    Base class for specialized table widgets.

    Provides common functionality like:
    - Sorting
    - Filtering
    - Column visibility
    - Row coloring
    - Selection handling
    """
    # Signal emitted when selection changes
    selectionChanged = pyqtSignal(list)  # list of selected row data

    # Signal emitted when a row is double-clicked
    rowDoubleClicked = pyqtSignal(dict)  # dict of row data

    def __init__(self,
                 headers: List[str],
                 column_keys: List[str],
                 stretch_columns: Optional[List[int]] = None,
                 fixed_columns: Optional[List[int]] = None,
                 with_filter: bool = False,
                 parent=None):
        """
        Initialize the BaseTableWidget.

        Args:
            headers: Column header texts
            column_keys: Keys to extract data from row dictionaries
            stretch_columns: Indices of columns that should stretch
            fixed_columns: Indices of columns that should have fixed width
            with_filter: Whether to include a filter input
            parent: Parent widget
        """
        super().__init__(parent)

        # Store configuration
        self._headers = headers
        self._column_keys = column_keys
        self._stretch_columns = stretch_columns or []
        self._fixed_columns = fixed_columns or []
        self._with_filter = with_filter

        # Row data storage (list of dicts)
        self._rows_data = []

        # Status color mapping
        self._status_colors = {
            "found": QColor(200, 255, 200),  # Light green
            "not_found": QColor(255, 200, 200),  # Light red
            "error": QColor(255, 160, 122),  # Light red
            "pending": QColor(255, 255, 200),  # Light yellow
            "completed": QColor(200, 255, 200),  # Light green
            "failed": QColor(255, 200, 200),  # Light red
            "running": QColor(173, 216, 230),  # Light blue
            "calculated": QColor(255, 255, 200)  # Light yellow
        }

        # Set up UI
        self._init_ui()
        self._connect_signals()

        logger.debug(f"BaseTableWidget initialized with {len(headers)} columns")

    def _init_ui(self):
        """Initialize the user interface."""
        main_layout = create_vbox_layout(self, margin=0)

        # Add filter controls if enabled
        if self._with_filter:
            filter_layout = create_hbox_layout(margin=0)

            filter_layout.addWidget(QLabel("Filter:"))
            self.filter_input = QLineEdit()
            self.filter_input.setPlaceholderText("Filter by text...")
            filter_layout.addWidget(self.filter_input)

            # Optional: Add column selector for filtering
            filter_layout.addWidget(QLabel("Column:"))
            self.filter_column_combo = QComboBox()
            self.filter_column_combo.addItem("All Columns")
            self.filter_column_combo.addItems(self._headers)
            filter_layout.addWidget(self.filter_column_combo)

            main_layout.addLayout(filter_layout)

        # Create the table widget
        self.table = QTableWidget()
        self.table.setColumnCount(len(self._headers))
        self.table.setHorizontalHeaderLabels(self._headers)

        # Configure table appearance
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setSortingEnabled(True)

        # Configure header
        header = self.table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)

        # Set column resize modes
        for i in range(len(self._headers)):
            if i in self._stretch_columns:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
            elif i in self._fixed_columns:
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(i, QHeaderView.Interactive)

        main_layout.addWidget(self.table)

        # Add count label (number of visible rows / total rows)
        self.count_label = QLabel("0 items")
        self.count_label.setAlignment(Qt.AlignRight)
        main_layout.addWidget(self.count_label)

    def _connect_signals(self):
        """Connect widget signals."""
        # Connect selection signal
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Connect double-click signal
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)

        # Connect filter signal if enabled
        if self._with_filter:
            # Use timer to avoid filtering on every keystroke
            self.filter_timer = QTimer()
            self.filter_timer.setSingleShot(True)
            self.filter_timer.timeout.connect(self._apply_filter)

            self.filter_input.textChanged.connect(self._on_filter_changed)
            self.filter_column_combo.currentIndexChanged.connect(self._apply_filter)

    @pyqtSlot()
    def _on_selection_changed(self):
        """Handle selection change in the table."""
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

        self.selectionChanged.emit(selected_data)

    @pyqtSlot(QTableWidgetItem)
    def _on_item_double_clicked(self, item):
        """Handle double-click on an item."""
        row = item.row()
        if 0 <= row < self.table.rowCount():
            # Get the original data for this row
            original_index = int(self.table.item(row, 0).data(Qt.UserRole))
            if 0 <= original_index < len(self._rows_data):
                self.rowDoubleClicked.emit(self._rows_data[original_index])

    @pyqtSlot(str)
    def _on_filter_changed(self, text):
        """Handle filter text change."""
        # Restart the timer to delay filtering
        self.filter_timer.start(300)  # 300ms delay

    def _apply_filter(self):
        """Apply the current filter to the table."""
        if not self._with_filter:
            return

        filter_text = self.filter_input.text().lower()
        filter_column = self.filter_column_combo.currentIndex() - 1  # -1 means "All Columns"

        for row in range(self.table.rowCount()):
            if not filter_text:
                # Show all rows if filter is empty
                self.table.setRowHidden(row, False)
                continue

            row_visible = False

            if filter_column < 0:
                # Search all columns
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item and filter_text in item.text().lower():
                        row_visible = True
                        break
            else:
                # Search only the selected column
                item = self.table.item(row, filter_column)
                if item and filter_text in item.text().lower():
                    row_visible = True

            self.table.setRowHidden(row, not row_visible)

        # Update count label
        visible_count = sum(1 for row in range(self.table.rowCount())
                            if not self.table.isRowHidden(row))
        total_count = len(self._rows_data)

        if visible_count != total_count:
            self.count_label.setText(f"{visible_count} of {total_count} items")
        else:
            self.count_label.setText(f"{total_count} items")

    def clear(self):
        """Clear the table content."""
        self.table.clearContents()
        self.table.setRowCount(0)
        self._rows_data = []
        self.count_label.setText("0 items")

    def get_row_color(self, row_data: Dict[str, Any]) -> QColor:
        """
        Get the background color for a row based on its status.

        Override in subclasses to customize row coloring.

        Args:
            row_data: Dictionary containing row data

        Returns:
            QColor to use for the row background
        """
        status = row_data.get('status', '').lower()
        return self._status_colors.get(status, QColor(255, 255, 255))  # White default

    def create_table_item(self, text: str, row_index: int, tooltip: Optional[str] = None,
                          alignment: int = Qt.AlignLeft) -> QTableWidgetItem:
        """
        Create a QTableWidgetItem with the given properties.

        Args:
            text: Item text
            row_index: Original index in the data list (stored as UserRole)
            tooltip: Optional tooltip text
            alignment: Text alignment

        Returns:
            Configured QTableWidgetItem
        """
        item = QTableWidgetItem(str(text))
        item.setData(Qt.UserRole, row_index)  # Store original index

        if tooltip:
            item.setToolTip(tooltip)

        item.setTextAlignment(alignment | Qt.AlignVCenter)

        return item

    def populate_table(self, data: List[Dict[str, Any]]):
        """
        Populate the table with the provided data.

        Args:
            data: List of dictionaries, each representing a row
        """
        # Store the data
        self._rows_data = data

        # Disable sorting temporarily for better performance
        self.table.setSortingEnabled(False)

        # Clear existing rows
        self.table.clearContents()
        self.table.setRowCount(len(data))

        # Populate the table
        for row_index, row_data in enumerate(data):
            # Get row color based on status
            row_color = self.get_row_color(row_data)

            # Create and add items for each column
            for col_index, key in enumerate(self._column_keys):
                # Get the value for this cell (handle nested keys)
                value = self._get_nested_value(row_data, key)

                # Create the item
                alignment = Qt.AlignRight if isinstance(value, (int, float)) else Qt.AlignLeft
                item = self.create_table_item(
                    str(value) if value is not None else "N/A",
                    row_index,
                    tooltip=str(value) if value is not None else None,
                    alignment=alignment
                )

                # Set background color
                item.setBackground(QBrush(row_color))

                # Add to table
                self.table.setItem(row_index, col_index, item)

        # Re-enable sorting
        self.table.setSortingEnabled(True)

        # Update count label
        self.count_label.setText(f"{len(data)} items")

        # Apply filter if active
        if self._with_filter and self.filter_input.text():
            self._apply_filter()

    def _get_nested_value(self, data: Dict[str, Any], key: str) -> Any:
        """
        Get a value from a nested dictionary using dot notation.

        Example: get_nested_value({'a': {'b': 'c'}}, 'a.b') returns 'c'

        Args:
            data: Dictionary to get value from
            key: Key using dot notation for nested access

        Returns:
            The value, or None if not found
        """
        if '.' not in key:
            return data.get(key, None)

        parts = key.split('.')
        value = data

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part, None)
                if value is None:
                    return None
            else:
                return None

        return value

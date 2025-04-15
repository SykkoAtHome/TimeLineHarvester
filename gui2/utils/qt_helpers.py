# gui2/utils/qt_helpers.py
"""
Qt Helper Utilities for TimelineHarvester

Provides common Qt-related utilities to simplify and standardize
UI component creation and interaction.
"""

import logging
from typing import Optional, Callable, List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QWidget, QLayout, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QSpacerItem, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView
)

logger = logging.getLogger(__name__)


# --- Layout Helpers ---

def create_vbox_layout(parent: Optional[QWidget] = None,
                       margin: int = 0,
                       spacing: int = 5) -> QVBoxLayout:
    """Create a vertical box layout with standard margins and spacing."""
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


def create_hbox_layout(parent: Optional[QWidget] = None,
                       margin: int = 0,
                       spacing: int = 5) -> QHBoxLayout:
    """Create a horizontal box layout with standard margins and spacing."""
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


def create_form_layout(parent: Optional[QWidget] = None,
                       margin: int = 0,
                       spacing: int = 5) -> QFormLayout:
    """Create a form layout with standard margins and spacing."""
    layout = QFormLayout(parent)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return layout


def add_horizontal_spacer(layout: QLayout, stretch: int = 1) -> None:
    """Add a horizontal spacer to the layout."""
    layout.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))


def add_vertical_spacer(layout: QLayout, stretch: int = 1) -> None:
    """Add a vertical spacer to the layout."""
    layout.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))


# --- Widget Helpers ---

def create_separator(horizontal: bool = True) -> QFrame:
    """Create a horizontal or vertical separator line."""
    separator = QFrame()
    if horizontal:
        separator.setFrameShape(QFrame.HLine)
    else:
        separator.setFrameShape(QFrame.VLine)
    separator.setFrameShadow(QFrame.Sunken)
    return separator


def create_section_label(text: str) -> QLabel:
    """Create a formatted label for section headers."""
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def create_button(text: str,
                  on_click: Optional[Callable] = None,
                  tooltip: Optional[str] = None) -> QPushButton:
    """Create a button with standard formatting."""
    button = QPushButton(text)
    if tooltip:
        button.setToolTip(tooltip)
    if on_click:
        button.clicked.connect(on_click)
    return button


# --- Dialog Helpers ---

def show_info_message(parent: QWidget, title: str, message: str) -> None:
    """Show an information message dialog."""
    QMessageBox.information(parent, title, message)


def show_warning_message(parent: QWidget, title: str, message: str) -> None:
    """Show a warning message dialog."""
    QMessageBox.warning(parent, title, message)


def show_error_message(parent: QWidget, title: str, message: str) -> None:
    """Show an error message dialog."""
    QMessageBox.critical(parent, title, message)


def show_confirm_dialog(parent: QWidget,
                        title: str,
                        message: str,
                        yes_text: str = "Yes",
                        no_text: str = "No") -> bool:
    """
    Show a confirmation dialog with Yes/No buttons.

    Returns:
        True if Yes was clicked, False if No was clicked
    """
    result = QMessageBox.question(
        parent, title, message,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No
    )
    return result == QMessageBox.Yes


# --- Table Helpers ---

def configure_table(table: QTableWidget,
                    headers: List[str],
                    stretch_columns: List[int] = None,
                    fixed_columns: List[int] = None,
                    sort_enabled: bool = True) -> None:
    """
    Configure a QTableWidget with standard settings.

    Args:
        table: The table widget to configure
        headers: List of header strings
        stretch_columns: List of column indices that should stretch
        fixed_columns: List of column indices that should be fixed width
        sort_enabled: Whether sorting should be enabled
    """
    # Set column headers
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)

    # Configure table appearance
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.ExtendedSelection)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(True)
    table.setSortingEnabled(sort_enabled)

    # Configure header
    header = table.horizontalHeader()
    header.setSectionsMovable(True)
    header.setSectionsClickable(True)

    # Set column resize modes
    for i in range(len(headers)):
        if stretch_columns and i in stretch_columns:
            header.setSectionResizeMode(i, QHeaderView.Stretch)
        elif fixed_columns and i in fixed_columns:
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        else:
            header.setSectionResizeMode(i, QHeaderView.Interactive)


def create_table_item(text: str,
                      tooltip: Optional[str] = None,
                      background_color: Optional[QColor] = None,
                      text_alignment: int = Qt.AlignLeft) -> QTableWidgetItem:
    """
    Create a QTableWidgetItem with standard formatting.

    Args:
        text: The text to display
        tooltip: Optional tooltip text
        background_color: Optional background color
        text_alignment: Text alignment (Qt.AlignLeft, Qt.AlignRight, etc.)

    Returns:
        Configured QTableWidgetItem
    """
    item = QTableWidgetItem(text)
    if tooltip:
        item.setToolTip(tooltip)
    if background_color:
        item.setBackground(QBrush(background_color))
    item.setTextAlignment(text_alignment | Qt.AlignVCenter)
    return item

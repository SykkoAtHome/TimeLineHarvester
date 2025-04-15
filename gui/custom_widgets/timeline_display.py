# gui/custom_widgets/timeline_display.py
"""
Timeline Display Widget for TimelineHarvester

Provides a visual representation of segments on a timeline, showing handles
and gaps between segments. Used in the Calculated Segments tab.
"""

import logging
from typing import List, Dict, Optional, Tuple, Any

from PyQt5.QtCore import Qt, QRectF, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QLabel)

logger = logging.getLogger(__name__)


class TimelineDisplayWidget(QFrame):
    """
    Widget for displaying a visual representation of segments on a timeline.
    Shows segments with handles and gaps according to provided segment data.

    This implementation uses direct QPainter drawing to create a visual
    representation of a transfer timeline with segments placed sequentially.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)

        # Set up the layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        # Create a label for messages when no data
        self.message_label = QLabel("No segments to display")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("color: gray; font-style: italic;")
        self.layout.addWidget(self.message_label)

        # Set a frame style for visual boundary
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)

        # Default frame rate for time conversions
        self.frame_rate = 25.0

        # Stores the current segment data
        self.segments = []

        # Timeline visual parameters
        self.separator_frames = 0
        self.padding = 10  # Pixels of padding around the timeline
        self.row_height = 40
        self.min_segment_width = 5  # Minimum pixel width for very short segments
        self.segment_color = QColor(150, 220, 150)  # Light green for segment body
        self.handle_color = QColor(130, 170, 255)  # Light blue for handles
        self.separator_color = QColor(30, 30, 30)  # Near black for gaps
        self.text_color = QColor(0, 0, 0)  # Black text
        self.border_color = QColor(80, 80, 80)  # Dark gray border

        # Set background color
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), QColor(240, 240, 240))
        self.setPalette(p)

        logger.debug("TimelineDisplayWidget initialized")

    def clear(self):
        """Clear the timeline display."""
        self.segments = []
        self.message_label.setVisible(True)
        self.update()  # Request repaint
        logger.debug("Timeline display cleared")

    def set_frame_rate(self, rate: float):
        """Set the frame rate for time calculations."""
        if rate > 0:
            self.frame_rate = rate
            logger.debug(f"Timeline frame rate set to {rate} fps")
            # Redraw if we have segments
            if self.segments:
                self.update()

    def update_timeline(self, segments: List[Dict[str, Any]], separator_frames: int = 0):
        """
        Update the timeline with segment data.

        Args:
            segments: List of segment dictionaries with required data
            separator_frames: Number of frames for gaps between segments (0 = no gaps)
        """
        self.clear()

        if not segments:
            logger.debug("No segments provided for timeline display")
            return

        # Store parameters
        self.segments = sorted(segments, key=lambda s: s.get('start_sec', 0))
        self.separator_frames = separator_frames

        # Hide message label when we have data
        self.message_label.setVisible(False)

        # Request repaint
        self.update()

        logger.debug(f"Timeline updated with {len(segments)} segments")

    def paintEvent(self, event):
        """Override paintEvent to draw the timeline."""
        super().paintEvent(event)

        # If no segments, no need to draw
        if not self.segments:
            return

        # Calculate available space
        available_width = self.width() - (self.padding * 2)
        available_height = self.height() - (self.padding * 2)

        # Set up painter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Calculate total timeline duration for scaling
        total_duration = 0
        for segment in self.segments:
            duration_sec = segment.get('duration_sec', 0)
            if duration_sec > 0:
                total_duration += duration_sec

        # Add separator durations if needed
        separator_sec = self.separator_frames / self.frame_rate if self.frame_rate > 0 else 0
        if separator_sec > 0 and len(self.segments) > 1:
            total_duration += separator_sec * (len(self.segments) - 1)

        # Calculate scale factor (pixels per second)
        if total_duration <= 0:
            scale_factor = 100.0  # Default
        else:
            scale_factor = available_width / total_duration

        # Calculate vertical positioning
        y_pos = self.padding
        timeline_height = min(self.row_height, available_height)

        # Start position for the first segment
        x_pos = self.padding

        # Draw segments sequentially
        for i, segment in enumerate(self.segments):
            # Extract segment data
            segment_id = segment.get('segment_id', f"Segment {i + 1}")
            duration_sec = segment.get('duration_sec', 0)
            handle_start_sec = segment.get('handle_start_sec', 0)
            handle_end_sec = segment.get('handle_end_sec', 0)

            # Skip invalid segments
            if duration_sec <= 0:
                continue

            # Calculate segment width in pixels
            segment_width = max(self.min_segment_width, int(duration_sec * scale_factor))

            # Calculate handle widths
            handle_start_width = int(handle_start_sec * scale_factor)
            handle_end_width = int(handle_end_sec * scale_factor)

            # Ensure handles don't take more than 40% of total width
            max_handle_width = int(segment_width * 0.4)
            if handle_start_width + handle_end_width > max_handle_width:
                # Scale down proportionally
                proportion = max_handle_width / (handle_start_width + handle_end_width)
                handle_start_width = int(handle_start_width * proportion)
                handle_end_width = int(handle_end_width * proportion)

            # Ensure at least 1px for handles if they exist
            if handle_start_sec > 0 and handle_start_width < 1:
                handle_start_width = 1
            if handle_end_sec > 0 and handle_end_width < 1:
                handle_end_width = 1

            # Calculate body width
            body_width = segment_width - handle_start_width - handle_end_width

            # Set up pens and brushes
            border_pen = QPen(self.border_color)
            border_pen.setWidth(1)

            # Draw segment with handles

            # 1. Start handle (if exists)
            if handle_start_width > 0:
                handle_rect = QRectF(x_pos, y_pos, handle_start_width, timeline_height)
                painter.setPen(border_pen)
                painter.setBrush(QBrush(self.handle_color))
                painter.drawRect(handle_rect)

            # 2. Main segment body
            body_x = x_pos + handle_start_width
            body_rect = QRectF(body_x, y_pos, body_width, timeline_height)
            painter.setPen(border_pen)
            painter.setBrush(QBrush(self.segment_color))
            painter.drawRect(body_rect)

            # 3. End handle (if exists)
            if handle_end_width > 0:
                end_x = body_x + body_width
                handle_rect = QRectF(end_x, y_pos, handle_end_width, timeline_height)
                painter.setPen(border_pen)
                painter.setBrush(QBrush(self.handle_color))
                painter.drawRect(handle_rect)

            # 4. Draw segment name
            painter.setPen(self.text_color)
            font = QFont("Arial", 8)
            painter.setFont(font)

            # Center text in the segment
            text_rect = QRectF(x_pos, y_pos, segment_width, timeline_height)
            text_rect.adjust(5, 0, -5, 0)
            painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, segment_id)

            # Move x position for next segment (including separator if needed)
            x_pos += segment_width

            # Add separator gap if not the last segment
            if i < len(self.segments) - 1 and separator_sec > 0:
                separator_width = int(separator_sec * scale_factor)
                if separator_width > 0:
                    separator_rect = QRectF(x_pos, y_pos, separator_width, timeline_height)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(self.separator_color))
                    painter.drawRect(separator_rect)
                    x_pos += separator_width

        # Clean up
        painter.end()

    def resizeEvent(self, event):
        """Handle resize events to recalculate scaling."""
        super().resizeEvent(event)
        # Request repaint to adjust scaling
        self.update()
# gui2/widgets/timeline_display.py
"""
Timeline Display Widget

Provides a visual representation of segments on a timeline, showing
handles and gaps between segments.
"""

import logging
from typing import List, Dict, Optional, Tuple, Any

from PyQt5.QtCore import Qt, QRectF, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QScrollArea, QWidget

logger = logging.getLogger(__name__)


class TimelineSegment:
    """Data class representing a segment on the timeline."""

    def __init__(self,
                 segment_id: str,
                 start_time: float,
                 duration: float,
                 handle_start: float = 0.0,
                 handle_end: float = 0.0,
                 status: str = "pending"):
        """
        Initialize a timeline segment.

        Args:
            segment_id: Identifier for the segment
            start_time: Start time in seconds
            duration: Duration in seconds
            handle_start: Start handle duration in seconds
            handle_end: End handle duration in seconds
            status: Status of the segment (e.g., "pending", "completed")
        """
        self.segment_id = segment_id
        self.start_time = start_time
        self.duration = duration
        self.handle_start = handle_start
        self.handle_end = handle_end
        self.status = status

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TimelineSegment':
        """Create a TimelineSegment from a dictionary."""
        return cls(
            segment_id=data.get('segment_id', f"Segment {id(data)}"),
            start_time=data.get('start_sec', 0.0),
            duration=data.get('duration_sec', 0.0),
            handle_start=data.get('handle_start_sec', 0.0),
            handle_end=data.get('handle_end_sec', 0.0),
            status=data.get('status', 'pending')
        )


class TimelineDisplayWidget(QFrame):
    """
    Widget for displaying a visual representation of segments on a timeline.

    Shows segments with handles and gaps, with proper scaling and
    visibility controls.
    """
    # Signal emitted when a segment is clicked
    segmentClicked = pyqtSignal(str)  # segment_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMinimumWidth(300)

        # Set up the layout
        self._init_ui()

        # Set a frame style for visual boundary
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)

        # Default frame rate for time conversions
        self.frame_rate = 25.0

        # Stores the current segment data
        self.segments: List[TimelineSegment] = []

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

        # Status colors
        self.status_colors = {
            "completed": QColor(120, 220, 120),  # Green
            "running": QColor(120, 180, 250),  # Blue
            "pending": QColor(200, 200, 200),  # Light gray
            "failed": QColor(250, 120, 120),  # Red
            "default": QColor(180, 180, 180)  # Gray
        }

        # Set background color
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), QColor(240, 240, 240))
        self.setPalette(p)

        logger.debug("TimelineDisplayWidget initialized")

    def _init_ui(self):
        """Initialize the user interface components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Create a label for messages when no data
        self.message_label = QLabel("No segments to display")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.message_label)

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

    def set_separator_frames(self, frames: int):
        """Set the number of separator frames between segments."""
        self.separator_frames = max(0, frames)
        if self.segments:
            self.update()  # Request repaint if we have segments

    def add_segment(self, segment: TimelineSegment):
        """Add a single segment to the timeline."""
        self.segments.append(segment)
        self.message_label.setVisible(False)
        self.update()  # Request repaint

    def update_timeline(self, segments_data: List[Dict[str, Any]], separator_frames: int = 0):
        """
        Update the timeline with segment data.

        Args:
            segments_data: List of segment dictionaries with required data
            separator_frames: Number of frames for gaps between segments
        """
        self.clear()

        if not segments_data:
            logger.debug("No segments provided for timeline display")
            return

        # Set separator frames
        self.separator_frames = separator_frames

        # Convert dictionaries to TimelineSegment objects
        self.segments = [TimelineSegment.from_dict(data) for data in segments_data]

        # Sort segments by start time
        self.segments.sort(key=lambda s: s.start_time)

        # Hide message label when we have data
        self.message_label.setVisible(False)

        # Request repaint
        self.update()

        logger.debug(f"Timeline updated with {len(segments_data)} segments")

    def mousePressEvent(self, event):
        """Handle mouse press events to detect segment clicks."""
        if not self.segments:
            return super().mousePressEvent(event)

        # Calculate segment positions
        x_positions = self._calculate_segment_positions()

        # Check if click is within a segment
        for i, segment in enumerate(self.segments):
            if i < len(x_positions):
                seg_x_start, seg_width = x_positions[i]
                seg_y = self.padding

                # Check if click is within segment bounds
                if (seg_x_start <= event.x() <= seg_x_start + seg_width and
                        seg_y <= event.y() <= seg_y + self.row_height):
                    # Emit segment clicked signal
                    self.segmentClicked.emit(segment.segment_id)
                    break

        super().mousePressEvent(event)

    def _calculate_segment_positions(self) -> Tuple[List[Tuple[int, int]], float]:
        """
        Calculate x positions and widths for all segments.

        Returns:
            Tuple containing:
            - List of tuples (x_position, width) for each segment
            - Scale factor used for calculations (pixels per second)
        """
        if not self.segments:
            return [], 100.0  # Default scale factor

        # Calculate available space
        available_width = self.width() - (self.padding * 2)

        # Calculate total timeline duration for scaling
        total_duration = 0.0
        for segment in self.segments:
            if segment.duration > 0:
                total_duration += segment.duration

        # Add separator durations if needed
        separator_sec = self.separator_frames / self.frame_rate if self.frame_rate > 0 else 0
        if separator_sec > 0 and len(self.segments) > 1:
            total_duration += separator_sec * (len(self.segments) - 1)

        # Calculate scale factor (pixels per second)
        if total_duration <= 0:
            scale_factor = 100.0  # Default
        else:
            scale_factor = available_width / total_duration

        # Calculate positions
        positions = []
        x_pos = self.padding

        for i, segment in enumerate(self.segments):
            # Skip invalid segments
            if segment.duration <= 0:
                continue

            # Calculate segment width in pixels
            segment_width = max(self.min_segment_width, int(segment.duration * scale_factor))

            # Store position and width
            positions.append((x_pos, segment_width))

            # Move x position for next segment
            x_pos += segment_width

            # Add separator gap if not the last segment
            if i < len(self.segments) - 1 and separator_sec > 0:
                separator_width = int(separator_sec * scale_factor)
                if separator_width > 0:
                    x_pos += separator_width

        return positions, scale_factor

    def paintEvent(self, event):
        """Override paintEvent to draw the timeline."""
        super().paintEvent(event)

        # If no segments, no need to draw
        if not self.segments:
            return

        # Get segment positions and scale factor
        positions, scale_factor = self._calculate_segment_positions()
        if not positions:
            return

        # Calculate available space
        available_width = self.width() - (self.padding * 2)

        # Calculate total timeline duration for scaling
        total_duration = 0.0
        for segment in self.segments:
            if segment.duration > 0:
                total_duration += segment.duration

        # Add separator durations if needed
        separator_sec = self.separator_frames / self.frame_rate if self.frame_rate > 0 else 0
        if separator_sec > 0 and len(self.segments) > 1:
            total_duration += separator_sec * (len(self.segments) - 1)

        # Calculate scale factor (pixels per second)
        if total_duration <= 0:
            scale_factor = 100.0  # Default
        else:
            scale_factor = available_width / total_duration

        # Set up painter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Calculate vertical positioning
        y_pos = self.padding
        timeline_height = min(self.row_height, self.height() - (self.padding * 2))

        # Draw segments
        for i, segment in enumerate(self.segments):
            if i >= len(positions):
                break  # Safety check

            x_pos, segment_width = positions[i]

            # Skip invalid segments
            if segment.duration <= 0:
                continue

            # Calculate handle widths
            handle_start_width = int(segment.handle_start * scale_factor)
            handle_end_width = int(segment.handle_end * scale_factor)

            # Ensure handles don't take more than 40% of total width
            max_handle_width = int(segment_width * 0.4)
            if handle_start_width + handle_end_width > max_handle_width:
                # Scale down proportionally
                proportion = max_handle_width / (handle_start_width + handle_end_width)
                handle_start_width = int(handle_start_width * proportion)
                handle_end_width = int(handle_end_width * proportion)

            # Ensure at least 1px for handles if they exist
            if segment.handle_start > 0 and handle_start_width < 1:
                handle_start_width = 1
            if segment.handle_end > 0 and handle_end_width < 1:
                handle_end_width = 1

            # Calculate body width
            body_width = segment_width - handle_start_width - handle_end_width

            # Set up pens and brushes
            border_pen = QPen(self.border_color)
            border_pen.setWidth(1)

            # Get status color
            status_color = self.status_colors.get(
                segment.status.lower(),
                self.status_colors["default"]
            )

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
            painter.setBrush(QBrush(status_color))
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
            painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, segment.segment_id)

            # Draw separator if not the last segment
            if i < len(self.segments) - 1 and self.separator_frames > 0:
                separator_sec = self.separator_frames / self.frame_rate
                separator_width = int(separator_sec * scale_factor)

                if separator_width > 0:
                    separator_x = x_pos + segment_width
                    separator_rect = QRectF(
                        separator_x, y_pos,
                        separator_width, timeline_height
                    )
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(self.separator_color))
                    painter.drawRect(separator_rect)

        # Clean up
        painter.end()

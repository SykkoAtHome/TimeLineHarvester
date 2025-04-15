# gui2\services\event_bus_service.py
# gui2/services/event_bus_service.py
# -*- coding: utf-8 -*-
"""
Event Bus Service for TimelineHarvester

Provides a centralized event system for communication between components
without direct coupling.
"""

import logging
from typing import Dict, Set, Callable

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot # Import pyqtSlot just in case needed elsewhere, but not using it here

logger = logging.getLogger(__name__)


class EventType:
    """Enum-like class defining event types."""
    # Project events
    PROJECT_LOADED = "project_loaded"
    PROJECT_SAVED = "project_saved"
    PROJECT_CLOSED = "project_closed"
    PROJECT_MODIFIED = "project_modified" # Likely handled by SETTINGS_CHANGED

    # --- Workflow Action Requests (UI -> Controller) ---
    ANALYZE_SOURCES_REQUESTED = "analyze_sources_requested"
    CALCULATE_COLOR_REQUESTED = "calculate_color_requested"
    EXPORT_COLOR_REQUESTED = "export_color_requested"
    CALCULATE_ONLINE_REQUESTED = "calculate_online_requested"
    TRANSCODE_ONLINE_REQUESTED = "transcode_online_requested"

    # --- Background Task Events (Controller/Service -> UI/Other) ---
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    TASK_FINISHED = "task_finished"
    TASK_ERROR = "task_error"

    # Analysis events (Results of background task)
    ANALYSIS_STARTED = "analysis_started" # Could use TASK_STARTED
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_FAILED = "analysis_failed" # Could use TASK_ERROR

    # Color preparation events (Results of background task)
    COLOR_CALCULATION_STARTED = "color_calculation_started" # Could use TASK_STARTED
    COLOR_CALCULATION_COMPLETED = "color_calculation_completed"
    COLOR_CALCULATION_FAILED = "color_calculation_failed" # Could use TASK_ERROR
    COLOR_EXPORT_COMPLETED = "color_export_completed"
    COLOR_EXPORT_FAILED = "color_export_failed" # Could use TASK_ERROR

    # Online preparation events (Results of background task)
    ONLINE_CALCULATION_STARTED = "online_calculation_started" # Could use TASK_STARTED
    ONLINE_CALCULATION_COMPLETED = "online_calculation_completed"
    ONLINE_CALCULATION_FAILED = "online_calculation_failed" # Could use TASK_ERROR
    TRANSCODE_STARTED = "transcode_started" # Could use TASK_STARTED
    TRANSCODE_PROGRESS = "transcode_progress" # TASK_PROGRESS specific?
    TRANSCODE_COMPLETED = "transcode_completed"
    TRANSCODE_FAILED = "transcode_failed" # Could use TASK_ERROR

    # UI events
    TAB_CHANGED = "tab_changed"
    SETTINGS_CHANGED = "settings_changed" # For any setting modification

    # General application events
    APP_READY = "app_ready"
    APP_CLOSING = "app_closing"


class EventData:
    """Base class for typed event data."""

    def __init__(self, event_type: str, **kwargs):
        self.event_type = event_type
        self.__dict__.update(kwargs)

    def __str__(self):
        # Limit output length for potentially large data
        MAX_ATTR_LEN = 100
        attrs_list = []
        for k, v in self.__dict__.items():
            if k != 'event_type':
                v_str = str(v)
                if len(v_str) > MAX_ATTR_LEN:
                    v_str = f"{v_str[:MAX_ATTR_LEN]}..."
                attrs_list.append(f'{k}={v_str}')
        attrs = ', '.join(attrs_list)
        return f"{self.event_type}({attrs})"


class EventBusService(QObject):
    """
    Service for publishing and subscribing to application events.

    Uses Qt signals/slots mechanism for reliable event delivery
    with the flexibility of a publish/subscribe pattern.
    """
    # Signal used internally to dispatch events
    _eventSignal = pyqtSignal(str, object)

    def __init__(self):
        super().__init__()
        # Map of event types to set of handler IDs
        self._subscribers: Dict[str, Set[int]] = {}
        # Map of handler IDs to callable handlers
        self._handlers: Dict[int, Callable] = {}
        # Counter for generating unique handler IDs
        self._next_handler_id = 1

        # Connect internal signal to dispatch method
        self._eventSignal.connect(self._dispatch_event)
        logger.debug("EventBusService initialized")

    def subscribe(self, event_type: str, handler: Callable[[EventData], None]) -> int:
        """
        Subscribe to an event type with a handler function.

        Args:
            event_type: Type of event to subscribe to
            handler: Callback function that accepts an EventData parameter

        Returns:
            Handler ID that can be used to unsubscribe
        """
        handler_id = self._next_handler_id
        self._next_handler_id += 1

        if event_type not in self._subscribers:
            self._subscribers[event_type] = set()

        self._subscribers[event_type].add(handler_id)
        self._handlers[handler_id] = handler

        logger.debug(f"Subscribed to event '{event_type}' with handler ID {handler_id}")
        return handler_id

    def unsubscribe(self, handler_id: int) -> bool:
        """
        Unsubscribe a handler by its ID.

        Args:
            handler_id: The ID returned from subscribe()

        Returns:
            True if successfully unsubscribed, False if the ID wasn't found
        """
        if handler_id not in self._handlers:
            logger.warning(f"Attempted to unsubscribe unknown handler ID {handler_id}")
            return False

        # Remove from handlers map
        handler = self._handlers.pop(handler_id)

        # Remove from all events it was subscribed to
        for event_type, subscribers in self._subscribers.items():
            if handler_id in subscribers:
                subscribers.remove(handler_id)
                logger.debug(f"Unsubscribed handler ID {handler_id} from event '{event_type}'")

        return True

    def publish(self, event_data: EventData) -> None:
        """
        Publish an event to all subscribers.

        Args:
            event_data: EventData object containing event type and data
        """
        event_type = event_data.event_type
        # --- CHANGE: Log only the event type ---
        logger.debug(f"Publishing event type: {event_type}")
        # Use Qt signal to dispatch event (ensures thread-safety if needed)
        self._eventSignal.emit(event_type, event_data)

    @pyqtSlot(str, object) # Keep pyqtSlot here as it's connected to a signal
    def _dispatch_event(self, event_type: str, event_data: EventData) -> None:
        """
        Internal method that dispatches events to handlers.
        Connected to _eventSignal.
        """
        if event_type not in self._subscribers:
            return # Simply return if no subscribers

        # Get a copy of subscribers to handle case where handlers subscribe/unsubscribe during iteration
        subscriber_ids = list(self._subscribers[event_type])

        for handler_id in subscriber_ids:
            if handler_id in self._handlers:  # Check if still registered
                try:
                    self._handlers[handler_id](event_data)
                except Exception as e:
                    logger.error(f"Error in event handler for '{event_type}' (handler ID: {handler_id}): {e}", exc_info=True)

    def clear_all_subscriptions(self) -> None:
        """Clear all subscriptions (useful during shutdown)."""
        self._subscribers.clear()
        self._handlers.clear()
        logger.debug("Cleared all event subscriptions")

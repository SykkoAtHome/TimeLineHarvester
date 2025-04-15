# gui2\services\threading_service.py
# gui2/services/threading_service.py
"""
Threading Service for TimelineHarvester

Provides a standardized way to run operations in background threads
to keep the UI responsive during long-running tasks.
"""

import logging
import traceback
from typing import Callable, Dict, Any, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, Qt

from ..models.ui_state_model import UIStateModel
from .event_bus_service import EventBusService, EventType, EventData

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.

    These signals allow communication between the worker thread
    and the main application thread.
    """
    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str, str)  # error message, traceback
    result = pyqtSignal(object)  # any return value
    progress = pyqtSignal(int, str)  # percent, message


class Worker(QObject):
    """
    Worker thread for executing background tasks.

    This worker runs a function in a separate thread and
    emits signals for progress, completion, and errors.
    """

    def __init__(
            self,
            fn: Callable,
            task_id: str,
            *args,
            **kwargs
    ):
        """
        Initialize the worker.

        Args:
            fn: The function to call in the thread
            task_id: Unique identifier for this task
            *args: Arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function
        """
        super().__init__()

        # Store constructor arguments
        self.fn = fn
        self.task_id = task_id
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        # Flag to signal worker to abort
        self._abort = False

    @pyqtSlot()
    def run(self):
        """Execute the function in the worker thread."""
        logger.debug(f"Starting worker thread for task {self.task_id}")

        # Emit the started signal
        self.signals.started.emit()

        # Define progress callback that worker function can call
        def progress_callback(percent: int, message: str = ""):
            if self._abort:
                raise InterruptedError("Task was aborted")
            self.signals.progress.emit(percent, message)

        # Add progress callback to kwargs if the function expects it
        # (Check if 'progress_callback' is expected by fn if necessary)
        try:
            # Check if function accepts 'progress_callback' kwarg
            import inspect
            sig = inspect.signature(self.fn)
            if 'progress_callback' in sig.parameters:
                self.kwargs['progress_callback'] = progress_callback
            else:
                # If function doesn't accept it, remove it from kwargs to avoid TypeError
                self.kwargs.pop('progress_callback', None)
        except Exception as e:
            logger.warning(f"Could not inspect function signature for task {self.task_id}: {e}. "
                           f"Assuming 'progress_callback' is accepted.")
            # Fallback: Assume it accepts it, might raise TypeError later if not.
            self.kwargs['progress_callback'] = progress_callback

        try:
            # Call the function
            result = self.fn(*self.args, **self.kwargs)

            # Check if aborted before emitting result
            if self._abort:
                logger.info(f"Task {self.task_id} was aborted during execution")
                return

            # Emit the result
            self.signals.result.emit(result)

        except InterruptedError:
            logger.info(f"Task {self.task_id} was interrupted")
            # No result signal emitted for interrupted tasks

        except Exception as e:
            # Log the error
            logger.error(f"Error in worker thread for task {self.task_id}: {e}", exc_info=True)

            # Get the traceback for detailed error reporting
            tb = traceback.format_exc()

            # Emit the error signal
            self.signals.error.emit(str(e), tb)

        finally:
            # Always emit finished signal
            self.signals.finished.emit()
            logger.debug(f"Worker thread for task {self.task_id} finished")

    def abort(self):
        """Signal the worker to abort execution."""
        logger.info(f"Aborting task {self.task_id}")
        self._abort = True


class ThreadingService(QObject):
    """
    Service for managing background operations in separate threads.

    Responsibilities:
    - Create worker threads for background tasks
    - Manage thread lifecycle
    - Update UI state during thread execution
    - Emit events for thread completion/error
    """

    def __init__(self, ui_state: UIStateModel, event_bus: EventBusService):
        """
        Initialize the threading service.

        Args:
            ui_state: UI state model to update during thread execution
            event_bus: Event bus for publishing thread-related events
        """
        super().__init__()

        self.ui_state = ui_state
        self.event_bus = event_bus

        # Store active threads
        self.threads: Dict[str, QThread] = {}
        self.workers: Dict[str, Worker] = {}

        logger.debug("ThreadingService initialized")

    def run_task(
            self,
            task_id: str,
            fn: Callable,
            *args,
            on_result: Optional[Callable] = None,
            on_error: Optional[Callable] = None,
            on_finished: Optional[Callable] = None,
            event_on_result: Optional[str] = None,
            **kwargs
    ) -> bool:
        """
        Run a function in a background thread.

        Args:
            task_id: Unique identifier for this task
            fn: The function to run in the background
            *args: Arguments to pass to the function
            on_result: Optional callback to handle the result
            on_error: Optional callback to handle errors
            on_finished: Optional callback called when thread finishes
            event_on_result: Optional event type to emit with result
            **kwargs: Keyword arguments to pass to the function

        Returns:
            True if task was started, False if another task with same ID is running
        """
        # Check if task with this ID is already running
        if task_id in self.threads and self.threads[task_id].isRunning():
            logger.warning(f"Task {task_id} is already running")
            return False

        # Clean up previous thread for this task if it exists
        self._cleanup_task(task_id)

        # Create new thread and worker
        thread = QThread()
        worker = Worker(fn, task_id, *args, **kwargs)

        # Move worker to thread
        worker.moveToThread(thread)

        # Connect thread started signal to worker run method
        thread.started.connect(worker.run)

        # Connect worker signals
        worker.signals.started.connect(lambda: self._on_task_started(task_id))
        worker.signals.progress.connect(lambda p, m: self._on_task_progress(task_id, p, m))
        worker.signals.result.connect(lambda result: self._on_task_result(task_id, result, on_result, event_on_result))
        worker.signals.error.connect(lambda err, tb: self._on_task_error(task_id, err, tb, on_error))
        worker.signals.finished.connect(lambda: self._on_task_finished(task_id, on_finished))

        # Store the thread and worker
        self.threads[task_id] = thread
        self.workers[task_id] = worker

        # Start the thread
        thread.start()

        logger.info(f"Started background task {task_id}")
        return True

    def abort_task(self, task_id: str) -> bool:
        """
        Abort a running task.

        Args:
            task_id: ID of the task to abort

        Returns:
            True if the task was found and aborted, False otherwise
        """
        if task_id in self.workers and task_id in self.threads:
            worker = self.workers[task_id]
            thread = self.threads[task_id]

            if thread.isRunning():
                # Signal the worker to abort
                worker.abort()

                # Wait for thread to finish with a timeout
                if not thread.wait(2000):  # 2 seconds timeout
                    logger.warning(f"Thread for task {task_id} did not finish in time after abort")
                    # Terminate the thread as a last resort
                    thread.terminate()
                    thread.wait()

                logger.info(f"Task {task_id} aborted")

                # Update UI state
                self.ui_state.set_busy(f"task_{task_id}", False)

                return True

        logger.warning(f"Cannot abort task {task_id} - not found or not running")
        return False

    def is_task_running(self, task_id: str) -> bool:
        """
        Check if a task is currently running.

        Args:
            task_id: ID of the task to check

        Returns:
            True if the task is running, False otherwise
        """
        return (task_id in self.threads and
                self.threads[task_id].isRunning())

    def _cleanup_task(self, task_id: str):
        """
        Clean up resources for a task.

        Args:
            task_id: ID of the task to clean up
        """
        if task_id in self.threads:
            thread = self.threads[task_id]

            # Ensure thread is stopped
            if thread.isRunning():
                # --- CHANGE: Log level changed from WARNING to DEBUG ---
                logger.debug(f"Cleaning up task {task_id} that is still running (will wait)")
                thread.quit()
                if not thread.wait(1000):  # Wait a bit longer perhaps
                    logger.warning(f"Thread {task_id} did not quit gracefully, forcing termination.")
                    thread.terminate()
                    thread.wait()  # Wait after termination

            # Delete the thread
            thread.deleteLater()
            del self.threads[task_id]

        if task_id in self.workers:
            # Ensure worker object is cleaned up too if needed
            # worker = self.workers[task_id]
            # worker.deleteLater() # Might be needed if worker has complex resources
            del self.workers[task_id]

    def _on_task_started(self, task_id: str):
        """Handle task started event."""
        # Update UI state to indicate task is running
        self.ui_state.set_busy(f"task_{task_id}", True)

        # Emit event
        self.event_bus.publish(EventData(
            EventType.TASK_STARTED,
            task_id=task_id
        ))

    def _on_task_progress(self, task_id: str, percent: int, message: str):
        """Handle task progress event."""
        # Log progress
        logger.debug(f"Task {task_id} progress: {percent}% - {message}")

        # Emit event
        self.event_bus.publish(EventData(
            EventType.TASK_PROGRESS,
            task_id=task_id,
            percent=percent,
            message=message
        ))

    def _on_task_result(
            self,
            task_id: str,
            result: Any,
            on_result: Optional[Callable],
            event_on_result: Optional[str]
    ):
        """Handle task result event."""
        # Call result callback if provided
        if on_result is not None:
            try:
                on_result(result)
            except Exception as e:
                logger.error(f"Error in result callback for task {task_id}: {e}", exc_info=True)

        # Emit event with result if event type provided
        if event_on_result:
            self.event_bus.publish(EventData(
                event_on_result,
                task_id=task_id,
                result=result  # Keep result in event for handlers that need it
            ))

    def _on_task_error(
            self,
            task_id: str,
            error_message: str,
            traceback: str,
            on_error: Optional[Callable]
    ):
        """Handle task error event."""
        # Log error
        logger.error(f"Task {task_id} failed: {error_message}\n{traceback}")

        # Call error callback if provided
        if on_error is not None:
            try:
                on_error(error_message, traceback)
            except Exception as e:
                logger.error(f"Error in error callback for task {task_id}: {e}", exc_info=True)

        # Emit event
        self.event_bus.publish(EventData(
            EventType.TASK_ERROR,
            task_id=task_id,
            error=error_message,
            traceback=traceback
        ))

    def _on_task_finished(self, task_id: str, on_finished: Optional[Callable]):
        """Handle task finished event."""
        # Update UI state
        self.ui_state.set_busy(f"task_{task_id}", False)

        # Call finished callback if provided
        if on_finished is not None:
            try:
                on_finished()
            except Exception as e:
                logger.error(f"Error in finished callback for task {task_id}: {e}", exc_info=True)

        # Emit event
        self.event_bus.publish(EventData(
            EventType.TASK_FINISHED,
            task_id=task_id
        ))

        # Clean up resources
        self._cleanup_task(task_id)

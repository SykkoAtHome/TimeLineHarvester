# gui2/controllers/workflow_controller.py
"""
Workflow Controller for TimelineHarvester

Manages workflow operations like analysis, calculation, export, and transcoding.
Coordinates between the UI, event bus, and core facade.
"""

import logging
import os
from typing import Optional, Dict, Any, List, Callable

from PyQt5.QtCore import QObject, pyqtSlot

from core.timeline_harvester_facade import TimelineHarvesterFacade
from ..models.ui_state_model import UIStateModel
from ..services.event_bus_service import EventBusService, EventType, EventData
from ..services.state_update_service import StateUpdateService
from ..services.dialog_service import DialogService
from ..services.threading_service import ThreadingService

logger = logging.getLogger(__name__)


class WorkflowController(QObject):
    """
    Controller for workflow operations.

    Responsibilities:
    - Run source analysis
    - Calculate segments for color and online workflows
    - Export files for color grading
    - Transcode files for online editing
    """

    def __init__(
            self,
            facade: TimelineHarvesterFacade,
            ui_state: UIStateModel,
            event_bus: EventBusService,
            state_update: StateUpdateService,
            dialog_service: DialogService,
            threading_service: ThreadingService
    ):
        """
        Initialize with required dependencies.

        Args:
            facade: Core facade for business logic
            ui_state: UI state model for tracking UI state
            event_bus: Event bus for communication
            state_update: Service for updating UI state from core state
            dialog_service: Service for showing dialogs
            threading_service: Service for running tasks in background threads
        """
        super().__init__()

        self.facade = facade
        self.ui_state = ui_state
        self.event_bus = event_bus
        self.state_update = state_update
        self.dialog_service = dialog_service
        self.threading_service = threading_service

        # Last used directories for file dialogs
        self.last_export_dir = os.path.expanduser("~")

        # Connect to events
        self._connect_to_events()

        logger.debug("WorkflowController initialized")

    def _connect_to_events(self):
        """Connect to relevant events from the event bus."""
        # Connect to workflow action events
        self.event_bus.subscribe(EventType.ANALYZE_SOURCES_REQUESTED, self._on_analyze_sources_requested)
        self.event_bus.subscribe(EventType.CALCULATE_COLOR_REQUESTED, self._on_calculate_color_requested)
        self.event_bus.subscribe(EventType.EXPORT_COLOR_REQUESTED, self._on_export_color_requested)
        self.event_bus.subscribe(EventType.CALCULATE_ONLINE_REQUESTED, self._on_calculate_online_requested)
        self.event_bus.subscribe(EventType.TRANSCODE_ONLINE_REQUESTED, self._on_transcode_online_requested)

    @pyqtSlot(EventData)
    def _on_analyze_sources_requested(self, event_data: EventData):
        """Handle analyze sources requested event."""
        self.analyze_sources()

    @pyqtSlot(EventData)
    def _on_calculate_color_requested(self, event_data: EventData):
        """Handle calculate color requested event."""
        self.calculate_segments('color')

    @pyqtSlot(EventData)
    def _on_export_color_requested(self, event_data: EventData):
        """Handle export color requested event."""
        self.export_color()

    @pyqtSlot(EventData)
    def _on_calculate_online_requested(self, event_data: EventData):
        """Handle calculate online requested event."""
        self.calculate_segments('online')

    @pyqtSlot(EventData)
    def _on_transcode_online_requested(self, event_data: EventData):
        """Handle transcode online requested event."""
        self.transcode_online()

    def analyze_sources(self) -> bool:
        """
        Run source analysis in a background thread.

        Returns:
            True if analysis was started, False otherwise
        """
        # Check if source analysis can be run
        if not self.ui_state.get('color_prep_can_analyze', False):
            self.dialog_service.show_warning(
                "Cannot Analyze Sources",
                "Please add edit files and source search paths before analyzing."
            )
            return False

        # Check if already running
        if self.threading_service.is_task_running('analyze_sources'):
            self.dialog_service.show_info(
                "Already Running",
                "Source analysis is already running."
            )
            return False

        # Create background task for source analysis
        self.threading_service.run_task(
            task_id='analyze_sources',
            fn=self._run_source_analysis,
            on_result=self._on_analysis_result,
            on_error=self._on_analysis_error,
            event_on_result=EventType.ANALYSIS_COMPLETED
        )

        logger.info("Source analysis started")
        return True

    def calculate_segments(self, stage: str) -> bool:
        """
        Calculate segments for the specified stage.

        Args:
            stage: 'color' or 'online'

        Returns:
            True if calculation was started, False otherwise
        """
        # Check if calculation can be run
        can_calculate_key = f'{stage}_prep_can_calculate'
        if not self.ui_state.get(can_calculate_key, False):
            error_message = "Please analyze sources first."
            if stage == 'online':
                error_message = "Please set output directory and profiles, and analyze sources first."

            self.dialog_service.show_warning(
                f"Cannot Calculate {stage.capitalize()} Segments",
                error_message
            )
            return False

        # Check if already running
        task_id = f'calculate_{stage}'
        if self.threading_service.is_task_running(task_id):
            self.dialog_service.show_info(
                "Already Running",
                f"{stage.capitalize()} segment calculation is already running."
            )
            return False

        # Create background task for calculation
        self.threading_service.run_task(
            task_id=task_id,
            fn=self._run_calculation,
            stage=stage,
            on_result=lambda result: self._on_calculation_result(result, stage),
            on_error=lambda err, tb: self._on_calculation_error(err, tb, stage),
            event_on_result=f"{stage.upper()}_CALCULATION_COMPLETED"
        )

        logger.info(f"{stage.capitalize()} segment calculation started")
        return True

    def export_color(self) -> bool:
        """
        Export color preparation data to a file.

        Returns:
            True if export was successful, False otherwise
        """
        # Check if export can be run
        if not self.ui_state.get('color_prep_can_export', False):
            self.dialog_service.show_warning(
                "Cannot Export",
                "Please calculate color segments first."
            )
            return False

        # Get filename for export
        proj_path = self.ui_state.get('current_project_path')
        default_dir = self.last_export_dir
        if proj_path:
            default_dir = os.path.dirname(proj_path)

        # Determine default filename
        proj_name = "UntitledProject"
        if proj_path:
            proj_name = os.path.splitext(os.path.basename(proj_path))[0]
        default_filename = f"{proj_name}_TRANSFER"

        # Show save dialog
        file_path = self.dialog_service.get_save_filename(
            "Export for Color",
            dir_key='export',
            directory=os.path.join(default_dir, default_filename),
            filter="AAF Files (*.aaf);;XML Files (*.xml);;EDL Files (*.edl);;All Files (*)"
        )

        if not file_path:
            logger.debug("Export canceled by user")
            return False

        # Remember export directory
        self.last_export_dir = os.path.dirname(file_path)

        # Run export in background thread
        self.threading_service.run_task(
            task_id='export_color',
            fn=self._run_export,
            stage='color',
            file_path=file_path,
            on_result=self._on_export_result,
            on_error=self._on_export_error,
            event_on_result=EventType.COLOR_EXPORT_COMPLETED
        )

        logger.info(f"Color export started to {file_path}")
        return True

    def transcode_online(self) -> bool:
        """
        Transcode files for online editing.

        Returns:
            True if transcoding was started, False otherwise
        """
        # Check if transcode can be run
        if not self.ui_state.get('online_prep_can_transcode', False):
            self.dialog_service.show_warning(
                "Cannot Transcode",
                "Please calculate online segments first."
            )
            return False

        # Check if already running
        if self.threading_service.is_task_running('transcode_online'):
            self.dialog_service.show_info(
                "Already Running",
                "Online transcoding is already running."
            )
            return False

        # Ask for confirmation
        state = self.facade.get_project_state_snapshot()
        output_dir = state.settings.online_output_directory or "unknown directory"
        segment_count = 0
        profile_count = 0

        if state.online_transfer_batch:
            segment_count = len(state.online_transfer_batch.segments)
            profile_count = len(state.settings.output_profiles)

        estimated_files = segment_count * profile_count

        confirmed = self.dialog_service.confirm(
            "Confirm Transcode",
            f"Start transcoding approximately {estimated_files} file(s) "
            f"for the online stage to:\n{output_dir}\n\n"
            f"This process may take a significant amount of time.\nProceed?",
            yes_text="Start Transcoding",
            no_text="Cancel"
        )

        if not confirmed:
            logger.debug("Transcoding canceled by user")
            return False

        # Run transcoding in background thread
        self.threading_service.run_task(
            task_id='transcode_online',
            fn=self._run_transcode,
            on_result=self._on_transcode_result,
            on_error=self._on_transcode_error,
            event_on_result=EventType.TRANSCODE_COMPLETED
        )

        logger.info("Online transcoding started")
        return True

    # --- Background Task Methods ---

    def _run_source_analysis(self, progress_callback: Callable[[int, str], None]) -> Dict[str, Any]:
        """
        Run source analysis in a background thread.

        Args:
            progress_callback: Function to call with progress updates

        Returns:
            Dictionary with analysis results
        """
        progress_callback(0, "Starting source analysis...")

        # Call facade to run source analysis
        success = self.facade.run_source_analysis()

        progress_callback(50, "Processing analysis results...")

        if not success:
            raise RuntimeError("Source analysis failed. Check logs for details.")

        # Get analysis results
        analysis_summary = self.facade.get_edit_shots_summary()
        found_count = sum(1 for s in analysis_summary if s.get('status') == 'found')
        total_count = len(analysis_summary)

        progress_callback(100, f"Analysis complete. Found {found_count}/{total_count} sources.")

        # Return results
        return {
            'analysis_summary': analysis_summary,
            'unresolved_summary': self.facade.get_unresolved_shots_summary(),
            'found_count': found_count,
            'total_count': total_count
        }

    def _run_calculation(
            self,
            stage: str,
            progress_callback: Callable[[int, str], None]
    ) -> Dict[str, Any]:
        """
        Run segment calculation in a background thread.

        Args:
            stage: 'color' or 'online'
            progress_callback: Function to call with progress updates

        Returns:
            Dictionary with calculation results
        """
        progress_callback(0, f"Starting {stage} segment calculation...")

        # Call facade to run calculation
        success = self.facade.run_calculation(stage=stage)

        progress_callback(50, "Processing calculation results...")

        if not success:
            raise RuntimeError(f"{stage.capitalize()} calculation failed. Check logs for details.")

        # Get calculation results
        segments_summary = self.facade.get_transfer_segments_summary(stage=stage)

        progress_callback(100, f"Calculation complete. Generated {len(segments_summary)} segments.")

        # Return results
        return {
            'segments_summary': segments_summary,
            'unresolved_summary': self.facade.get_unresolved_shots_summary(),
            'segment_count': len(segments_summary)
        }

    def _run_export(
            self,
            stage: str,
            file_path: str,
            progress_callback: Callable[[int, str], None]
    ) -> Dict[str, Any]:
        """
        Run export in a background thread.

        Args:
            stage: 'color' or 'online'
            file_path: Path to export file
            progress_callback: Function to call with progress updates

        Returns:
            Dictionary with export results
        """
        progress_callback(0, f"Starting {stage} export to {os.path.basename(file_path)}...")

        # Call facade to run export
        success = self.facade.run_export(stage, file_path)

        if not success:
            raise RuntimeError(f"{stage.capitalize()} export failed. Check logs for details.")

        progress_callback(100, f"Export complete: {os.path.basename(file_path)}")

        # Return results
        return {
            'file_path': file_path,
            'success': success
        }

    def _run_transcode(
            self,
            progress_callback: Callable[[int, str], None]
    ) -> Dict[str, Any]:
        """
        Run transcode in a background thread.

        Args:
            progress_callback: Function to call with progress updates

        Returns:
            Dictionary with transcode results
        """
        try:
            # Facade run_online_transcoding method expects a similar progress callback
            # but we need to adapt it to match both signatures
            def facade_progress_callback(current: int, total: int, message: str):
                # Convert to percent
                percent = int((current / total) * 100) if total > 0 else 0
                # Call our progress callback
                progress_callback(percent, message)

            # Call facade to run transcode
            self.facade.run_online_transcoding(facade_progress_callback)

            # Get updated segment status
            segments_summary = self.facade.get_transfer_segments_summary(stage='online')

            # Count completed segments
            completed_count = sum(1 for s in segments_summary if s.get('status') == 'completed')
            total_count = len(segments_summary)

            # Return results
            return {
                'segments_summary': segments_summary,
                'completed_count': completed_count,
                'total_count': total_count
            }

        except Exception as e:
            logger.error(f"Error during transcode: {e}", exc_info=True)
            raise

    # --- Task Result Handlers ---

    def _on_analysis_result(self, result: Dict[str, Any]):
        """Handle analysis task result."""
        # Update UI state with analysis results
        self.state_update.update_edit_shots_data()
        self.state_update.update_unresolved_shots_data()

        # Show success message
        found_count = result.get('found_count', 0)
        total_count = result.get('total_count', 0)

        self.dialog_service.show_info(
            "Analysis Complete",
            f"Found {found_count} out of {total_count} original sources."
        )

    def _on_analysis_error(self, error_message: str, traceback: str):
        """Handle analysis task error."""
        self.dialog_service.show_error(
            "Analysis Failed",
            f"Error during source analysis:\n\n{error_message}"
        )

    def _on_calculation_result(self, result: Dict[str, Any], stage: str):
        """Handle calculation task result."""
        # Update UI state with calculation results
        self.state_update.update_transfer_segments_data(stage)
        self.state_update.update_unresolved_shots_data()

        # Show success message
        segment_count = result.get('segment_count', 0)

        self.dialog_service.show_info(
            "Calculation Complete",
            f"Generated {segment_count} segments for {stage} preparation."
        )

    def _on_calculation_error(self, error_message: str, traceback: str, stage: str):
        """Handle calculation task error."""
        self.dialog_service.show_error(
            f"{stage.capitalize()} Calculation Failed",
            f"Error during {stage} segment calculation:\n\n{error_message}"
        )

    def _on_export_result(self, result: Dict[str, Any]):
        """Handle export task result."""
        file_path = result.get('file_path', 'unknown file')

        self.dialog_service.show_info(
            "Export Complete",
            f"Successfully exported to:\n{file_path}"
        )

    def _on_export_error(self, error_message: str, traceback: str):
        """Handle export task error."""
        self.dialog_service.show_error(
            "Export Failed",
            f"Error during export:\n\n{error_message}"
        )

    def _on_transcode_result(self, result: Dict[str, Any]):
        """Handle transcode task result."""
        completed_count = result.get('completed_count', 0)
        total_count = result.get('total_count', 0)

        self.dialog_service.show_info(
            "Transcoding Complete",
            f"Transcoded {completed_count} out of {total_count} segments successfully."
        )

        # Update UI state with transcode results
        self.state_update.update_transfer_segments_data('online')

    def _on_transcode_error(self, error_message: str, traceback: str):
        """Handle transcode task error."""
        self.dialog_service.show_error(
            "Transcoding Failed",
            f"Error during online transcoding:\n\n{error_message}"
        )
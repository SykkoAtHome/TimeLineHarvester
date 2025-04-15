# core/processing/export_service.py
"""
Service responsible for exporting calculated TransferBatch data
to standard edit list formats (EDL, FCPXML, etc.).
"""

import logging

from .. import exporter  # Import the exporter module
# Import project state and the exporter module
from ..project_state import ProjectState

logger = logging.getLogger(__name__)


class ExportService:
    """Handles exporting TransferBatches to files."""

    def __init__(self, state: ProjectState):
        """
        Initializes the service with the project state.

        Args:
            state: The ProjectState object containing the data to export.
        """
        if not isinstance(state, ProjectState):
            raise TypeError("ExportService requires a valid ProjectState instance.")
        self.state = state
        logger.debug("ExportService initialized.")

    def export_batch(self, stage: str, output_path: str) -> bool:
        """
        Exports the calculated TransferBatch for the specified stage to a file.

        Args:
            stage: The stage to export ('color' or 'online').
            output_path: The full path for the output file (e.g., *.xml, *.aaf).

        Returns:
            True if the export was successful, False otherwise.

        Raises:
            ValueError: If the specified stage has no calculated batch or if
                        the batch contains no segments.
        """
        logger.info(f"Starting export for stage '{stage}' to '{output_path}'...")

        batch_to_export = None
        separator_frames = 0
        project_name = self.state.settings.project_name or "UntitledProject"
        desired_timeline_name = f"{project_name}_TRANSFER"

        if stage == 'color':
            batch_to_export = self.state.color_transfer_batch
            separator_frames = self.state.settings.color_prep_separator
            # timeline_name = f"{timeline_base_name}_ColorPrep_Export"
        elif stage == 'online':
            # Exporting the online batch might be different
            batch_to_export = self.state.online_transfer_batch
            separator_frames = 0  # Typically no separators needed for online pull lists
            # timeline_name = f"{timeline_base_name}_OnlinePrep_Export"
            logger.warning("Exporting the 'online' batch. Timeline name will follow project convention.")
        else:
            logger.error(f"Invalid stage specified for export: '{stage}'.")
            raise ValueError(f"Invalid export stage: {stage}")

        # --- Validate Batch Data ---
        if not batch_to_export:
            msg = f"Cannot export stage '{stage}': Transfer batch has not been calculated yet."
            logger.error(msg)
            raise ValueError(msg)

        if not batch_to_export.segments:
            if batch_to_export.calculation_errors:
                error_summary = "; ".join(batch_to_export.calculation_errors)
                msg = f"Cannot export stage '{stage}': Batch contains no segments (Calculation errors: {error_summary})."
                logger.error(msg)
                raise ValueError(msg)
            else:
                msg = f"Cannot export stage '{stage}': Calculated batch is empty (no segments found)."
                logger.warning(msg)
                raise ValueError(msg)

        # --- Call Exporter ---
        try:
            logger.info(
                f"Calling exporter.export_transfer_batch for {len(batch_to_export.segments)} segments with timeline name '{desired_timeline_name}'.")
            success = exporter.export_transfer_batch(
                transfer_batch=batch_to_export,
                output_path=output_path,
                timeline_name=desired_timeline_name,
                export_format_adapter_name=None,
                adapter_options=None,
                separator_frames=separator_frames
            )
            if success:
                logger.info(f"Successfully exported stage '{stage}' to: {output_path}")
            else:
                logger.error(f"Export failed for stage '{stage}' (check exporter logs).")
            return success
        except Exception as e:
            logger.error(f"An unexpected error occurred during export for stage '{stage}': {e}", exc_info=True)
            return False

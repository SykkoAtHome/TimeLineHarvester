# core/processing/export_service.py
"""
Service responsible for exporting calculated TransferBatch data
to standard edit list formats (EDL, FCPXML, etc.).
"""

import logging
import os
from typing import Optional

# Import project state and the exporter module
from ..project_state import ProjectState
from .. import exporter  # Import the exporter module

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
            stage: The stage to export (currently only 'color' is meaningful).
            output_path: The full path for the output file (e.g., *.edl, *.xml).

        Returns:
            True if the export was successful, False otherwise.

        Raises:
            ValueError: If the specified stage has no calculated batch or if
                        the batch contains no segments.
        """
        logger.info(f"Starting export for stage '{stage}' to '{output_path}'...")

        batch_to_export = None
        separator_frames = 0
        timeline_base_name = self.state.settings.project_name or "ExportedTimeline"

        if stage == 'color':
            batch_to_export = self.state.color_transfer_batch
            separator_frames = self.state.settings.color_prep_separator
            # Use a specific name for the color prep timeline
            timeline_name = f"{timeline_base_name}_ColorPrep_Export"
        elif stage == 'online':
            # Exporting the online batch might be different (e.g., no separators?)
            # For now, let's assume it might be needed, but maybe with 0 separator
            batch_to_export = self.state.online_transfer_batch
            separator_frames = 0  # Typically no separators needed for online pull lists
            timeline_name = f"{timeline_base_name}_OnlinePrep_Export"
            # You might want to disallow exporting online if it doesn't make sense
            # logger.warning("Exporting the 'online' batch might not be standard practice.")
        else:
            logger.error(f"Invalid stage specified for export: '{stage}'.")
            raise ValueError(f"Invalid export stage: {stage}")

        # --- Validate Batch Data ---
        if not batch_to_export:
            msg = f"Cannot export stage '{stage}': Transfer batch has not been calculated yet."
            logger.error(msg)
            raise ValueError(msg)

        if not batch_to_export.segments:
            # Check if there were calculation errors that might explain the empty batch
            if batch_to_export.calculation_errors:
                error_summary = "; ".join(batch_to_export.calculation_errors)
                msg = f"Cannot export stage '{stage}': Batch contains no segments (Calculation errors: {error_summary})."
                logger.error(msg)
                raise ValueError(msg)
            else:
                msg = f"Cannot export stage '{stage}': Calculated batch is empty (no segments found)."
                logger.warning(msg)
                # Depending on requirements, maybe allow exporting an empty file?
                # For now, treat it as an error condition for export.
                raise ValueError(msg)

        # --- Call Exporter ---
        try:
            logger.info(f"Calling exporter.export_transfer_batch for {len(batch_to_export.segments)} segments.")
            success = exporter.export_transfer_batch(
                transfer_batch=batch_to_export,
                output_path=output_path,
                timeline_name=timeline_name,
                # Let the exporter determine adapter from extension by default
                export_format_adapter_name=None,
                adapter_options=None,  # Add options later if needed
                separator_frames=separator_frames
            )
            if success:
                logger.info(f"Successfully exported stage '{stage}' to: {output_path}")
            else:
                logger.error(f"Export failed for stage '{stage}' (check exporter logs).")
            return success
        except Exception as e:
            logger.error(f"An unexpected error occurred during export for stage '{stage}': {e}", exc_info=True)
            # Re-raise or return False? Returning False is safer for the caller.
            return False

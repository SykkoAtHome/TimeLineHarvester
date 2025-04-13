# -*- coding: utf-8 -*-
"""
utils/executable_finder.py

Provides a utility function to locate external executable files
needed by the application, such as ffmpeg and ffprobe.
"""

import logging
import os
import shutil  # For shutil.which (system PATH search)
import sys     # For PyInstaller bundle detection (sys.frozen, sys._MEIPASS)
from typing import Optional

logger = logging.getLogger(__name__)

# List of common subdirectories to check within application structure
# (both bundled and non-bundled scenarios)
_COMMON_EXECUTABLE_SUBFOLDERS = ["ffmpeg_bin", "bin", "lib"]


def find_executable(name: str) -> Optional[str]:
    """
    Robustly locates an external executable by its name (e.g., "ffmpeg").

    It searches in the following order:
    1.  **Bundled App (PyInstaller):** Checks the main bundle directory (`_MEIPASS`)
        and then common subdirectories within the bundle
        (e.g., `ffmpeg_bin/`, `bin/`).
    2.  **Relative Subfolder (Non-Bundled):** Checks common subdirectories
        (e.g., `ffmpeg_bin/`, `bin/`) relative to the application's
        likely root directory (assumed to be one level above the `utils` directory).
    3.  **System PATH:** Uses `shutil.which` to search the system's PATH environment
        variable.

    Args:
        name: The base name of the executable (e.g., "ffmpeg", "ffprobe").
              The appropriate platform-specific suffix (like ".exe") will be added.

    Returns:
        The absolute path to the found executable, or None if it could not be
        located in any of the searched locations.
    """
    executable_name = f"{name}.exe" if os.name == 'nt' else name
    found_path: Optional[str] = None

    # --- 1. Check if running as a bundled application (PyInstaller) ---
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundle_dir = sys._MEIPASS
        logger.debug("Running bundled, checking PyInstaller directory: %s", bundle_dir)

        # Check base bundle directory first
        exe_path = os.path.join(bundle_dir, executable_name)
        if os.path.exists(exe_path):
            found_path = exe_path
            # No need for info log here, this is the expected primary location in a bundle
        else:
            # Check common subdirectories within the bundle
            for subfolder in _COMMON_EXECUTABLE_SUBFOLDERS:
                exe_path = os.path.join(bundle_dir, subfolder, executable_name)
                if os.path.exists(exe_path):
                    found_path = exe_path
                    logger.info("Found bundled '%s' in subfolder: %s", name, subfolder)
                    break  # Found in a subfolder, stop searching bundle

        if not found_path:
             logger.warning(
                 "'%s' not found within the PyInstaller bundle directory (%s) or its subfolders (%s).",
                 executable_name, bundle_dir, ', '.join(_COMMON_EXECUTABLE_SUBFOLDERS)
             )
             # Fallback to PATH check below is possible if desired, but often
             # bundled apps should contain all dependencies.

    # --- 2. Check conventional subfolders relative to script (if not bundled) ---
    if not found_path and not getattr(sys, 'frozen', False):
        try:
            # Assume this utility is in core/utils, find the root directory
            # This might be fragile if the directory structure changes significantly.
            app_root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            # __file__ might not be defined (e.g., interactive interpreter)
            app_root_dir = os.getcwd()
            logger.warning("Could not determine application root directory from __file__, using CWD: %s", app_root_dir)

        logger.debug("Not bundled, checking relative subfolders under: %s", app_root_dir)
        for subfolder in _COMMON_EXECUTABLE_SUBFOLDERS:
            exe_path = os.path.join(app_root_dir, subfolder, executable_name)
            if os.path.exists(exe_path):
                found_path = exe_path
                logger.info("Found '%s' in relative subfolder: %s", name, subfolder)
                break # Found, stop searching relative folders

    # --- 3. Fallback to system PATH ---
    if not found_path:
        logger.debug("'%s' not found in specific locations, checking system PATH.", name)
        exe_path_in_path = shutil.which(name)
        if exe_path_in_path:
            found_path = exe_path_in_path
            logger.info("Found '%s' executable in system PATH: %s", name, found_path)
        else:
            # This is the final failure point
            logger.error(
                "Executable '%s' could not be located in bundle, relative subfolders (%s), or system PATH.",
                name, ', '.join(_COMMON_EXECUTABLE_SUBFOLDERS)
            )
            return None # Explicitly return None if not found

    # Return the validated, absolute path
    return os.path.abspath(found_path)

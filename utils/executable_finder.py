import logging
import os
import shutil  # For shutil.which (fallback PATH search)
import sys  # Needed for sys.frozen and sys._MEIPASS
from typing import Optional

logger = logging.getLogger(__name__)


def find_executable(name: str) -> Optional[str]:
    """
    Attempts to find an executable (e.g., "ffmpeg", "ffprobe") robustly.
    1. Checks if running as a bundled app (PyInstaller) and looks inside.
    2. Checks for a conventional subfolder (e.g., 'ffmpeg_bin') relative to the script/bundle.
    3. Falls back to checking the system PATH.

    Args:
        name: Name of the executable (without .exe on Windows).

    Returns:
        Absolute path to the executable or None if not found.
    """
    executable_name = f"{name}.exe" if os.name == 'nt' else name
    found_path = None

    # --- 1. Check if bundled (PyInstaller) ---
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundle_dir = sys._MEIPASS
        logger.debug(f"Running bundled, checking base bundle dir: {bundle_dir}")
        exe_path = os.path.join(bundle_dir, executable_name)
        if os.path.exists(exe_path):
            found_path = exe_path
        else:
            # Check common subdirectories within the bundle
            for subfolder in ['bin', 'ffmpeg_bin', 'lib', '.']:  # '.' is the bundle dir itself again
                exe_path = os.path.join(bundle_dir, subfolder, executable_name)
                if os.path.exists(exe_path):
                    found_path = exe_path
                    logger.info(f"Found bundled '{name}' in subfolder '{subfolder}'.")
                    break  # Stop after first find in subfolders
            if not found_path:
                logger.warning(
                    f"'{executable_name}' not found in PyInstaller bundle directory: {bundle_dir} or common subfolders.")
                # Decide whether to fallback to PATH check even when bundled (usually not recommended)
                # found_path = shutil.which(name) # Optional PATH fallback

    # --- 2. Check conventional subfolder relative to script (if not bundled) ---
    if not found_path and not getattr(sys, 'frozen', False):
        # Determine the base directory of the application (where main.py likely is)
        # Be careful with __file__ if this util is deep in packages
        try:
            # Assuming this util might be called from different depths
            # A more robust way might involve passing app base path or using project structure assumptions
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Go up one level from core/utils
            # Alternatively, if always called relative to main.py's location:
            # script_dir = os.path.dirname(os.path.abspath(sys.argv[0])) # Path of the script that was run
        except NameError:  # __file__ might not be defined in some contexts (e.g. interactive)
            script_dir = os.getcwd()

        relative_subfolder = "ffmpeg_bin"  # Conventional name
        exe_path = os.path.join(script_dir, relative_subfolder, executable_name)
        logger.debug(f"Not bundled, checking relative subfolder: {exe_path}")
        if os.path.exists(exe_path):
            found_path = exe_path
            logger.info(f"Found '{name}' in relative subfolder '{relative_subfolder}'.")

    # --- 3. Fallback to system PATH ---
    if not found_path:
        logger.debug(f"'{name}' not found in bundle or relative subfolder, checking system PATH.")
        exe_path = shutil.which(name)
        if exe_path:
            found_path = exe_path
            logger.info(f"Found '{name}' executable in system PATH.")
        else:
            logger.error(
                f"Executable '{name}' could not be located in bundle, relative subfolder ('ffmpeg_bin'), or system PATH.")
            return None  # Explicitly return None if not found anywhere

    # Return the absolute path
    return os.path.abspath(found_path)
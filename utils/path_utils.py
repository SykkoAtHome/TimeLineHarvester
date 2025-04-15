# utils/path_utils.py
"""
Path Utilities Module

Provides functions for path normalization, serialization, and comparison
across different operating systems.
"""
import os
import logging
from typing import List, Set, Optional

logger = logging.getLogger(__name__)


def normalize_path_for_storage(path: str) -> str:
    """
    Normalizes a path for storage in a platform-independent format.

    Converts paths to use forward slashes (/) regardless of platform,
    which is a common convention for cross-platform storage.

    Args:
        path: The path to normalize

    Returns:
        The normalized path using forward slashes
    """
    if not path:
        return path

    # First use os.path.normpath to handle ../ and ./ components
    normalized = os.path.normpath(path)

    # Then convert backslashes to forward slashes for storage
    universal = normalized.replace('\\', '/')

    return universal


def normalize_path_for_system(path: str) -> str:
    """
    Normalizes a path for use on the current operating system.

    Args:
        path: The path to normalize

    Returns:
        The normalized path using the system's path separator
    """
    if not path:
        return path

    # First convert to universal format
    universal = path.replace('\\', '/')

    # Then use os.path.normpath to convert to system format
    system_path = os.path.normpath(universal)

    return system_path


def path_variants(path: str) -> List[str]:
    """
    Generates variations of a path for flexible matching.

    Args:
        path: The source path

    Returns:
        List of path variations that might match the same file
    """
    if not path:
        return []

    result = set()

    # Original path
    result.add(path)

    # Normalized system path
    system_path = normalize_path_for_system(path)
    result.add(system_path)

    # Universal path (forward slashes)
    universal_path = normalize_path_for_storage(path)
    result.add(universal_path)

    # Try with alternate slashes
    alt_slashes = path.replace('\\', '/') if '\\' in path else path.replace('/', '\\')
    result.add(alt_slashes)

    # Try lowercase on Windows (case-insensitive filesystem)
    if os.name == 'nt':
        result.add(path.lower())
        result.add(system_path.lower())
        result.add(universal_path.lower())

    # Remove any duplicates and empty strings
    result.discard('')

    return list(result)


def find_matching_path(path: str, paths_dict: dict) -> Optional[str]:
    """
    Finds a matching path in a dictionary by trying various path formats.

    Args:
        path: The path to find a match for
        paths_dict: Dictionary with paths as keys

    Returns:
        The matching key from the dictionary, or None if no match found
    """
    if not path or not paths_dict:
        return None

    # Try direct match first
    if path in paths_dict:
        return path

    # Try various path variants
    variants = path_variants(path)
    for variant in variants:
        if variant in paths_dict:
            logger.debug(f"Found path match: '{path}' as '{variant}'")
            return variant

    # No match found
    return None
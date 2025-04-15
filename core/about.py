# core/about.py
"""
Generates HTML content for the About dialog.
"""

import sys
import os
import base64
import logging
from typing import Optional
from PyQt5.QtCore import QCoreApplication, qVersion
import opentimelineio as otio

logger = logging.getLogger(__name__)

TLH_VERSION = "0.1"  # Application version constant


def _get_image_base64(relative_img_path: str) -> Optional[str]:
    """Reads an image file and returns its Base64 encoded data URL."""
    try:
        # Calculate path relative to this script's location
        core_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(core_dir)
        img_path = os.path.join(project_root, relative_img_path.replace('/', os.sep))

        if not os.path.exists(img_path):
            logger.warning(f"Image file not found: {img_path}")
            return None

        logger.debug(f"Reading image for Base64 encoding from: {img_path}")
        with open(img_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

        mime_type = "image/png" if relative_img_path.lower().endswith(".png") else "image/jpeg"
        return f"data:{mime_type};base64,{encoded_string}"
    except Exception as e:
        logger.error(f"Failed to read or encode image '{relative_img_path}': {e}", exc_info=True)
        return None


def get_about_html() -> str:
    """
    Generates the HTML content string for the About dialog, retrieving
    version information dynamically.
    """
    app_version = TLH_VERSION  # Default
    try:
        qt_app_version = QCoreApplication.applicationVersion()
        if qt_app_version:
            app_version = qt_app_version
        else:
            logger.warning("QCoreApplication.applicationVersion() returned empty, using constant.")
    except Exception as e:
        logger.error(f"Error getting application version from Qt: {e}")

    try:
        qt_version_str = qVersion()
    except Exception:
        qt_version_str = "N/A"

    try:
        otio_version_str = otio.__version__
    except Exception:
        otio_version_str = "N/A"

    try:
        python_version = sys.version.split()[0]
    except Exception:
        python_version = "N/A"

    # Get LinkedIn logo Base64 data
    linkedin_logo_base64 = _get_image_base64('gui/imgs/linkedin-48.png')
    linkedin_img_html = ""
    if linkedin_logo_base64:
        # Display small inline image, adjust size as needed
        linkedin_img_html = f'<img src="{linkedin_logo_base64}" alt="LI" width="20" height="20" style="vertical-align: middle; margin-right: 5px;">'
    else:
        linkedin_img_html = "[LI] "  # Text fallback

    # Build HTML content
    html_content = f"""
    <html><head><style> a {{ text-decoration: none; color: #0077B5; }} </style></head><body>
    <h2>TimelineHarvester</h2>
    <p><b>Version:</b> {app_version}</p>
    <p>Workflow tool for preparing media for color grading and online editing.</p>
    <hr>
    <p><b>Core Libraries:</b></p>
    <ul>
        <li>Python: {python_version}</li>
        <li>Qt: {qt_version_str}</li>
        <li>OpenTimelineIO: {otio_version_str}</li>
    </ul>
    <hr>
    <p>{linkedin_img_html}<a href="https://www.linkedin.com/in/tluchowski/" target="_blank">Connect on LinkedIn</a></p>
    <hr>
    <p><i>Powered by OpenTimelineIO and FFmpeg/FFprobe.</i></p>
    </body></html>
    """
    return html_content.strip()

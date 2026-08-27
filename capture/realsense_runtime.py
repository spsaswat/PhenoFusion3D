"""Version gate for the RealSense binding used by both capture backends.

The L515 and D405 share exactly one supported wheel in this project.  Keep the
check separate from camera enumeration so an off-pin venv fails immediately
without opening a USB device.
"""

from __future__ import annotations

import importlib
from importlib import metadata
from types import ModuleType
from typing import Optional


REQUIRED_PYREALSENSE_VERSION = "2.54.2.5684"


def installed_version() -> Optional[str]:
    """Return the installed wheel version, or ``None`` when it is absent."""

    try:
        return metadata.version("pyrealsense2")
    except metadata.PackageNotFoundError:
        return None


def validate_version(version: Optional[str] = None) -> str:
    """Require the exact L515/D405-compatible wheel without importing it."""

    actual = installed_version() if version is None else version
    if actual is None:
        raise RuntimeError(
            "pyrealsense2 is not installed in the project venv. Required: "
            f"pyrealsense2=={REQUIRED_PYREALSENSE_VERSION}."
        )
    if actual != REQUIRED_PYREALSENSE_VERSION:
        raise RuntimeError(
            "Incompatible pyrealsense2 in the project venv: "
            f"found {actual}, required {REQUIRED_PYREALSENSE_VERSION}. "
            "Newer releases cannot enumerate the L515. The camera was not "
            "opened and the gantry was not moved."
        )
    return actual


def import_realsense() -> ModuleType:
    """Validate the wheel, then import it lazily."""

    validate_version()
    try:
        return importlib.import_module("pyrealsense2")
    except ImportError as exc:
        raise RuntimeError(
            "Camera capture is offline because pyrealsense2 could not "
            f"initialise: {exc}. The GUI and processing of existing datasets "
            "remain available."
        ) from exc

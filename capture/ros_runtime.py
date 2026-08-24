"""Utilities for running ROS 1 outside the PyQt process.

ROS Noetic on the lab Ubuntu 20.04 machines belongs to the system Python
(normally ``/usr/bin/python3``).  The GUI may use a newer virtualenv, so it
must never import rospy directly.  These helpers locate a suitable interpreter
without importing ROS and provide the small JSON protocol used by the child
processes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable


EVENT_PREFIX = "PHENOFUSION_JSON "
ROS_PYTHON_ENV = "PHENOFUSION_ROS_PYTHON"


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        normalised = os.path.normcase(os.path.abspath(value))
        if normalised not in seen and os.path.isfile(value):
            seen.add(normalised)
            result.append(value)
    return result


def candidate_ros_pythons() -> list[str]:
    """Return likely ROS interpreters, with explicit/system Python first."""
    configured = os.environ.get(ROS_PYTHON_ENV, "").strip()
    project_ros_python = str(
        Path(__file__).resolve().parents[1] / ".venv-ros" / "bin" / "python"
    )
    system_python = "/usr/bin/python3" if os.name != "nt" else ""
    path_python = shutil.which("python3") or ""
    return _dedupe(
        (configured, project_ros_python, system_python, path_python, sys.executable)
    )


def ros_environment_available() -> bool:
    """Cheap ROS probe which deliberately never imports ``rospy``."""
    configured = os.environ.get(ROS_PYTHON_ENV, "").strip()
    if configured and os.path.isfile(configured):
        return True
    project_ros_python = (
        Path(__file__).resolve().parents[1] / ".venv-ros" / "bin" / "python"
    )
    if project_ros_python.is_file():
        return True
    if os.name != "nt" and Path("/opt/ros/noetic").exists():
        return True
    if os.environ.get("ROS_DISTRO") or os.environ.get("ROS_MASTER_URI"):
        return True
    try:
        return importlib.util.find_spec("rospy") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def helper_path(filename: str) -> str:
    return str(Path(__file__).resolve().with_name(filename))


def parse_event(line: str) -> dict | None:
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        value = json.loads(line[len(EVENT_PREFIX):])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None

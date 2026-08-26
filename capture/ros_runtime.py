"""Resolve the existing lab ROS runtime without modifying the machine.

The GUI intentionally runs in its own Python virtual environment.  ROS Noetic
on the lab computer normally belongs to the system Python, so importing
``rospy`` directly from the GUI venv is unreliable even when the gantry is
working.  This module finds an existing interpreter/environment that can
import the ROS modules needed by the gantry helper.

Nothing in this module installs, removes, or upgrades packages.
"""

from __future__ import annotations

import glob
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


CONTROL_MODULES: Tuple[str, ...] = (
    "rospy",
    "geometry_msgs.msg",
    "sensor_msgs.msg",
)


@dataclass(frozen=True)
class RosRuntime:
    """A Python interpreter and environment capable of running ROS code."""

    interpreter: str
    env: Dict[str, str]
    description: str


def _candidate_interpreters() -> List[str]:
    """Return existing Python interpreters, preferring the current one."""

    candidates = [sys.executable, "/usr/bin/python3", shutil.which("python3")]
    result: List[str] = []
    seen = set()
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        real = os.path.realpath(candidate)
        if real in seen:
            continue
        seen.add(real)
        result.append(candidate)
    return result


def _workspace_setup_files() -> List[str]:
    """Find explicitly configured and conventional catkin setup files."""

    roots: List[Path] = []
    explicit = os.environ.get("PHENOFUSION_ROS_WS")
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.name == "setup.bash":
            return [str(explicit_path)] if explicit_path.is_file() else []
        roots.append(explicit_path)

    home = Path.home()
    roots.extend(home / name for name in ("catkin_ws", "ros_ws", "workspace", "ws"))

    result: List[str] = []
    seen = set()
    for root in roots:
        for relative in ("devel/setup.bash", "install/setup.bash"):
            candidate = root / relative
            if candidate.is_file():
                value = str(candidate)
                if value not in seen:
                    seen.add(value)
                    result.append(value)
    return result


def _ros_setup_files() -> List[str]:
    """Find installed ROS 1 distribution setup scripts."""

    setups = [path for path in glob.glob("/opt/ros/*/setup.bash")
              if os.path.isfile(path)]
    return sorted(setups, key=lambda path: ("noetic" not in path, path))


def _setup_groups() -> List[Tuple[str, ...]]:
    """Setup-script combinations, most complete first."""

    distros = _ros_setup_files()
    workspaces = _workspace_setup_files()
    groups: List[Tuple[str, ...]] = []
    groups.extend((distro, workspace)
                  for distro in distros for workspace in workspaces)
    groups.extend((workspace,) for workspace in workspaces)
    groups.extend((distro,) for distro in distros)
    return groups


def ros_is_installed() -> bool:
    """Whether this Linux machine appears to have a ROS 1 installation."""

    return bool(
        os.environ.get("ROS_DISTRO")
        or os.environ.get("ROS_PACKAGE_PATH")
        or _ros_setup_files()
        or shutil.which("roscore")
    )


def _environment_after_sourcing(scripts: Sequence[str]) -> Optional[Dict[str, str]]:
    """Return the environment produced by sourcing existing setup scripts."""

    source = " && ".join(f". {shlex.quote(script)}" for script in scripts)
    command = f"{source} && env -0"
    try:
        completed = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", command],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    environment: Dict[str, str] = {}
    for item in completed.stdout.split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        environment[key.decode(errors="replace")] = value.decode(errors="replace")
    return environment or None


def _candidate_environments() -> Iterable[Tuple[str, Dict[str, str]]]:
    yield "current environment", dict(os.environ)
    for scripts in _setup_groups():
        environment = _environment_after_sourcing(scripts)
        if environment is not None:
            label = " + ".join(scripts)
            yield label, environment


def _probe_imports(interpreter: str, environment: Dict[str, str],
                   modules: Sequence[str]) -> Dict[str, str]:
    """Return ``{module: error}`` for imports that fail."""

    code = (
        "import importlib, json\n"
        f"names = {list(modules)!r}\n"
        "errors = {}\n"
        "for name in names:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except BaseException as exc:\n"
        "        errors[name] = f'{type(exc).__name__}: {exc}'\n"
        "print(json.dumps(errors))\n"
    )
    try:
        completed = subprocess.run(
            [interpreter, "-c", code],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"<interpreter>": str(exc)}
    if completed.returncode != 0:
        detail = (completed.stderr.strip().splitlines()
                  or [f"exit status {completed.returncode}"])[-1]
        return {"<interpreter>": detail}
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"<interpreter>": "import probe returned no result"}


def choose_runtime(modules: Sequence[str] = CONTROL_MODULES) -> RosRuntime:
    """Find an existing runtime able to import all requested ROS modules."""

    attempts: List[str] = []
    for environment_name, environment in _candidate_environments():
        for interpreter in _candidate_interpreters():
            failures = _probe_imports(interpreter, environment, modules)
            if not failures:
                return RosRuntime(
                    interpreter=interpreter,
                    env=environment,
                    description=f"{interpreter} ({environment_name})",
                )
            details = ", ".join(
                f"{name}: {error}" for name, error in sorted(failures.items())
            )
            attempts.append(f"  - {interpreter} [{environment_name}]: {details}")

    guidance = (
        "Source /opt/ros/noetic/setup.bash and the gantry catkin workspace "
        "before launching. If the workspace is in a non-standard location, "
        "set PHENOFUSION_ROS_WS=/path/to/workspace. Do not pip-install rospy."
    )
    raise RuntimeError(
        "No existing Python/ROS environment can run the gantry helper.\n"
        + "\n".join(attempts)
        + "\n"
        + guidance
    )


_runtime_cache: Dict[Tuple[str, ...], RosRuntime] = {}
_runtime_lock = threading.Lock()


def resolve(modules: Sequence[str] = CONTROL_MODULES,
            refresh: bool = False) -> RosRuntime:
    """Resolve and cache a compatible existing ROS runtime."""

    key = tuple(modules)
    with _runtime_lock:
        if not refresh and key in _runtime_cache:
            return _runtime_cache[key]
    runtime = choose_runtime(modules)
    with _runtime_lock:
        _runtime_cache[key] = runtime
    return runtime


def forget() -> None:
    """Clear cached runtime choices after the operator changes ROS setup."""

    with _runtime_lock:
        _runtime_cache.clear()

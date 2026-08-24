"""
capture/ros_runtime.py
----------------------
Finds a Python that can actually talk to ROS on this machine, and caches
the answer.

The GUI runs in the app's venv, which on a lab rig routinely cannot
`import rospy` at all -- rospy comes from /opt/ros via PYTHONPATH but its
pure-Python dependencies (rospkg, catkin_pkg, ...) were apt-installed for
the system Python instead. The app used to do all its ROS work in-process
with that venv, so it judged the gantry by an interpreter that could not
reach ROS, and reported "cannot import rospkg" no matter what the gantry
was doing.

Everything ROS-facing now goes through the interpreter this module
picks -- the gantry panel, the hardware probe and the stakeholder capture
script alike -- so the UI's verdict matches what the capture will do.

Selection is by probe, never by guesswork: each candidate interpreter is
asked to import the required modules, under the current environment and
under whatever ROS/catkin setup.bash files exist. A failure reports every
interpreter tried, exactly what each was missing, and the command that
fixes it.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("phenofusion.ros_runtime")

# Modules any ROS-facing helper needs. The gantry's own message package
# is deliberately absent: without it go-to/go-home degrade, but jog,
# stop and position read-back still work.
CONTROL_MODULES = ["rospy", "rosgraph", "geometry_msgs", "sensor_msgs",
                   "std_msgs"]

# ROS's own Python packages are NEVER installed by this app. They come
# from the ROS distro (apt) and a catkin workspace, and pip-installing
# anything named after them either does nothing useful or actively breaks
# the install -- the PyPI package called "rospy" is an unrelated shim.
# When one of these is missing the answer is always to run under an
# interpreter that already has it, which is exactly what this module
# looks for.
_ROS_PROVIDED = {
    "rospy", "rosgraph", "rospkg", "catkin_pkg", "roslib", "rosnode",
    "rostopic", "genpy", "genmsg", "empy", "defusedxml", "netifaces",
    "gnupg", "yaml",
    "geometry_msgs", "sensor_msgs", "std_msgs", "actionlib_msgs",
}

# Modules that only a sourced catkin workspace can provide.
_WORKSPACE_MODULES = {"position_controller_ros"}

# App-side dependencies, which do belong in the venv. pyrealsense2 is
# deliberately suggested WITHOUT a version: the lab rig is pinned to
# 2.54 and must not be moved off it.
_APP_PROVIDED = {
    "cv2": "opencv-python-headless",
    "numpy": "numpy",
    "pyrealsense2": "pyrealsense2",
}


@dataclass(frozen=True)
class RosRuntime:
    """An interpreter, the environment to run it in, and how it was found."""
    interpreter: str
    env: Dict[str, str]
    description: str


# ------------------------------------------------------- interpreter choice

def _candidate_interpreters() -> List[str]:
    """Interpreters that might be able to run ROS code, best first.

    The app's own venv is tried first (it has pyrealsense2/cv2), then the
    system python, which on a ROS box is the one apt installed rospy's
    dependencies for.
    """
    candidates = [sys.executable, "/usr/bin/python3", shutil.which("python3")]
    ordered: List[str] = []
    seen = set()
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        ordered.append(path)
    return ordered


def _setup_bash_scripts() -> List[List[str]]:
    """Sets of setup.bash files worth sourcing, most complete first.

    A catkin workspace's devel/setup.bash is what provides
    position_controller_ros; /opt/ros/<distro>/setup.bash provides rospy
    and the core message packages.
    """
    distro_setups = []
    for distro in ("noetic", "melodic"):
        path = f"/opt/ros/{distro}/setup.bash"
        if os.path.isfile(path):
            distro_setups.append(path)

    workspace_setups = []
    explicit = os.environ.get("PHENOFUSION_ROS_WS")
    search_roots = [explicit] if explicit else []
    home = os.path.expanduser("~")
    search_roots += [os.path.join(home, name) for name in
                     ("catkin_ws", "ros_ws", "ws", "workspace")]
    for root in search_roots:
        if not root:
            continue
        candidate = os.path.join(root, "devel", "setup.bash")
        if os.path.isfile(candidate):
            workspace_setups.append(candidate)

    combinations: List[List[str]] = []
    for distro in distro_setups:
        for workspace in workspace_setups:
            combinations.append([distro, workspace])
    combinations += [[s] for s in workspace_setups]
    combinations += [[s] for s in distro_setups]
    return combinations


def ros_is_installed() -> bool:
    """Is there a ROS install on this machine at all?

    Filesystem-only, so it is safe to call while building the UI.
    """
    return bool(_setup_bash_scripts())


def _env_after_sourcing(setup_scripts: List[str]) -> Optional[Dict[str, str]]:
    """The environment left behind by sourcing those setup.bash files."""
    sourcing = " && ".join(f". {shlex.quote(s)}" for s in setup_scripts)
    command = (f"{sourcing} && "
               "python3 -c 'import json,os; print(json.dumps(dict(os.environ)))'")
    try:
        done = subprocess.run(["bash", "-c", command], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.debug("sourcing %s failed: %s", setup_scripts, e)
        return None
    if done.returncode != 0:
        log.debug("sourcing %s exited %d: %s",
                  setup_scripts, done.returncode, done.stderr.strip()[:200])
        return None
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def _probe_imports(interpreter: str, modules: List[str],
                   env: Dict[str, str]) -> Dict[str, str]:
    """{module: error} for every module this interpreter cannot import."""
    probe = (
        "import json, sys\n"
        f"modules = {modules!r}\n"
        "failures = {}\n"
        "for name in modules:\n"
        "    try:\n"
        "        __import__(name)\n"
        "    except BaseException as e:\n"
        "        failures[name] = '%s: %s' % (type(e).__name__, e)\n"
        "print(json.dumps(failures))\n"
    )
    try:
        done = subprocess.run([interpreter, "-c", probe], capture_output=True,
                              text=True, timeout=120, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"<interpreter>": f"could not run {interpreter}: {e}"}
    if done.returncode != 0:
        return {"<interpreter>": (done.stderr.strip().splitlines() or
                                  [f"exit {done.returncode}"])[-1]}
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"<interpreter>": "probe produced no result"}


def _fix_hint(interpreter: str, failures: Dict[str, str]) -> str:
    """What would make this interpreter able to import what is missing.

    ROS packages are never suggested for installation -- they are
    provided by the ROS distro and the catkin workspace, so the fix is to
    source them (or to let this module pick the interpreter that already
    has them).
    """
    missing = set(failures)
    hints = []

    workspace = sorted(missing & _WORKSPACE_MODULES)
    if workspace:
        hints.append(
            f"source your catkin workspace's devel/setup.bash so "
            f"{', '.join(workspace)} is importable (or set "
            "PHENOFUSION_ROS_WS=/path/to/your_ws before launching)")

    ros_missing = sorted(missing & _ROS_PROVIDED)
    if ros_missing:
        hints.append(
            f"{', '.join(ros_missing)} comes from your ROS install -- "
            "'source /opt/ros/noetic/setup.bash' before launching. Do NOT "
            "pip-install these")

    app_missing = sorted({_APP_PROVIDED[m] for m in missing
                          if m in _APP_PROVIDED})
    if app_missing:
        hints.append(f"{interpreter} -m pip install " + " ".join(app_missing))

    return "; ".join(hints)


def choose_runtime_for(modules: List[str]) -> RosRuntime:
    """Pick a runtime able to import every module in `modules`.

    Raises RuntimeError naming every interpreter tried and exactly what
    each one was missing -- 'cannot import rospkg' with no further detail
    is the single most common way this fails on the rig.
    """
    log.info("resolving a runtime for: %s", ", ".join(modules))

    environments: List[Tuple[str, Dict[str, str]]] = [
        ("current environment", dict(os.environ))
    ]
    for setups in _setup_bash_scripts():
        sourced = _env_after_sourcing(setups)
        if sourced:
            environments.append(
                (" + ".join(os.path.basename(os.path.dirname(s)) or s
                            for s in setups), sourced))

    report: List[str] = []
    for env_name, env in environments:
        for interpreter in _candidate_interpreters():
            failures = _probe_imports(interpreter, modules, env)
            if not failures:
                description = f"{interpreter} ({env_name})"
                log.info("ROS runtime resolved: %s", description)
                return RosRuntime(interpreter, env, description)
            missing = ", ".join(f"{m} ({e})" for m, e in sorted(failures.items()))
            hint = _fix_hint(interpreter, failures)
            report.append(f"  - {interpreter} [{env_name}]: missing {missing}"
                          + (f"\n      fix: {hint}" if hint else ""))
            log.info("runtime preflight: %s [%s] missing %s",
                     interpreter, env_name, ", ".join(sorted(failures)))

    raise RuntimeError(
        "No Python on this machine can import "
        + ", ".join(modules)
        + " -- they must ALL be importable by the SAME interpreter. Tried:\n"
        + "\n".join(report)
    )


# ------------------------------------------------------------------ cache

_cache: Dict[Tuple[str, ...], RosRuntime] = {}
_cache_lock = threading.Lock()


def resolve(modules: Optional[List[str]] = None,
            refresh: bool = False) -> RosRuntime:
    """A runtime able to import `modules`, resolved once and remembered.

    Probing costs a second or so, and the hardware poll asks repeatedly,
    so the answer is cached per module set. `refresh=True` re-probes --
    the right thing after the user has installed something.
    """
    required = list(modules or CONTROL_MODULES)
    key = tuple(required)
    with _cache_lock:
        if not refresh and key in _cache:
            return _cache[key]
    runtime = choose_runtime_for(required)
    with _cache_lock:
        _cache[key] = runtime
    return runtime


def forget() -> None:
    """Drop cached resolutions (after an install, or on user request)."""
    with _cache_lock:
        _cache.clear()

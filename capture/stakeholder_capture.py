"""
capture/stakeholder_capture.py
------------------------------
Runs the stakeholder's own capture program as the capture backend.

`rospy_thread_fin_1.py` is the script the lab actually trusts. Rather
than re-implement its loop and then argue about parity, this backend
executes that file unmodified as a subprocess and puts the UI around it:
it picks an interpreter that can satisfy the script's imports, streams
its output into the log and the progress bar, forwards Stop as Ctrl-C,
and rearranges the frames it wrote into the layout the rest of the app
loads.

Nothing in the script is patched, templated or re-typed. If the
stakeholder edits it, this backend runs the edited version.

The script hardcodes its own capture parameters (velocity 0.038 m/s,
end position 0.78 m, D405 serial, 1280x720 @ 30). Those are reported to
the UI via `script_parameters()` so the panel can show what will
actually be used instead of pretending its own spin-boxes apply.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

from capture.base import CaptureBackend, CaptureParams

log = logging.getLogger("phenofusion.stakeholder")

SCRIPT_NAME = "rospy_thread_fin_1.py"

# Where the script may live, most-preferred first. The repo root copy is
# the one the lab edits; stakeholder_reference/ is the pristine copy.
_SCRIPT_SEARCH_DIRS = (
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "stakeholder_reference"),
)

# Missing pure-Python ROS dependencies that pip can fix, mapped to the
# install that fixes them. rospy itself is NEVER pip-installable -- the
# PyPI package of that name is an unrelated shim.
_PIP_FIXABLE = {
    "rospkg": "rospkg",
    "catkin_pkg": "catkin_pkg",
    "yaml": "PyYAML",
    "defusedxml": "defusedxml",
    "netifaces": "netifaces",
    "empy": "empy",
    "gnupg": "python-gnupg",
    "numpy": "numpy",
    "cv2": "opencv-python-headless",
    "pyrealsense2": "pyrealsense2",
}

# Modules that only a sourced catkin workspace can provide.
_WORKSPACE_MODULES = {"position_controller_ros"}


def find_script() -> str:
    """Absolute path to the stakeholder script."""
    for directory in _SCRIPT_SEARCH_DIRS:
        candidate = os.path.join(directory, SCRIPT_NAME)
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError(
        f"The stakeholder capture script {SCRIPT_NAME} was not found in "
        f"{' or '.join(_SCRIPT_SEARCH_DIRS)}. Put it back in the repo root "
        "and try again."
    )


def script_imports(script_path: str) -> List[str]:
    """Top-level modules the script imports, read from the script itself.

    Parsed rather than hardcoded so that editing the stakeholder script's
    imports cannot silently desynchronise this backend's preflight.
    """
    with open(script_path, "r", errors="replace") as f:
        source = f.read()
    modules = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return sorted(modules)


def script_parameters(script_path: str) -> Dict[str, str]:
    """The capture settings the script hardcodes, for display in the UI.

    Best-effort and read-only: anything not recognised is simply omitted.
    """
    with open(script_path, "r", errors="replace") as f:
        source = f.read()
    # Drop commented-out lines first: the script keeps old settings around
    # as comments (an earlier "current_position >= 0.006" among them), and
    # matching one of those would report the wrong end position.
    source = "\n".join(line for line in source.splitlines()
                        if not line.lstrip().startswith("#"))
    found: Dict[str, str] = {}
    patterns = {
        "camera serial":  r"^serial_number\s*=\s*['\"]([^'\"]+)['\"]",
        "velocity (m/s)": r"^\s*velocity\s*=\s*([0-9.]+)",
        "end position (m)": r"current_position\s*>=\s*([0-9.]+)",
        "output folder":  r"^save_fold_p\s*=\s*['\"]([^'\"]+)['\"]",
    }
    for label, pattern in patterns.items():
        match = re.search(pattern, source, re.MULTILINE)
        if match:
            found[label] = match.group(1)
    streams = re.findall(
        r"^config\.enable_stream\(rs\.stream\.(\w+),\s*(\d+),\s*(\d+),"
        r"[^,]+,\s*(\d+)\)", source, re.MULTILINE)
    for kind, width, height, fps in streams:
        found[f"{kind} stream"] = f"{width}x{height} @ {fps}"
    return found


# ------------------------------------------------------- interpreter choice

def _candidate_interpreters() -> List[str]:
    """Interpreters that might be able to run the script, best first.

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
    """The command that would make this interpreter able to run it."""
    pip_targets = sorted({_PIP_FIXABLE[m] for m in failures
                          if m in _PIP_FIXABLE})
    workspace = sorted(set(failures) & _WORKSPACE_MODULES)
    hints = []
    if pip_targets:
        hints.append(f"{interpreter} -m pip install "
                     + " ".join(pip_targets))
    if workspace:
        hints.append(
            f"source your catkin workspace's devel/setup.bash so "
            f"{', '.join(workspace)} is on PYTHONPATH (or set "
            "PHENOFUSION_ROS_WS=/path/to/your_ws before launching the app)")
    if "rospy" in failures and "rospy" not in _PIP_FIXABLE:
        hints.append("source /opt/ros/noetic/setup.bash before launching "
                     "(never 'pip install rospy' -- that is an unrelated "
                     "package)")
    return "; ".join(hints)


def choose_runtime(script_path: str) -> Tuple[str, Dict[str, str], str]:
    """Pick (interpreter, environment, description) able to run the script.

    Raises RuntimeError naming every interpreter tried and exactly what
    each one was missing -- 'cannot import rospkg' with no further detail
    is the single most common way this fails on the rig.
    """
    modules = script_imports(script_path)
    log.info("stakeholder script imports: %s", ", ".join(modules))

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
                log.info("stakeholder script will run with %s", description)
                return interpreter, env, description
            missing = ", ".join(f"{m} ({e})" for m, e in sorted(failures.items()))
            hint = _fix_hint(interpreter, failures)
            report.append(f"  - {interpreter} [{env_name}]: missing {missing}"
                          + (f"\n      fix: {hint}" if hint else ""))
            log.info("stakeholder preflight: %s [%s] missing %s",
                     interpreter, env_name, ", ".join(sorted(failures)))

    raise RuntimeError(
        f"No Python on this machine can run {os.path.basename(script_path)} "
        "-- it needs ROS, the gantry's message package and the RealSense "
        "SDK all importable by the SAME interpreter. Tried:\n"
        + "\n".join(report)
    )


# ==================================================================== backend

class StakeholderScriptCapture(CaptureBackend):
    """Capture by running `rospy_thread_fin_1.py` unmodified."""

    name = "stakeholder"

    # The script prints the gantry position once per loop; that is the
    # only progress signal it offers.
    _POSITION_LINE = re.compile(r"^-?\d+\.?\d*(e-?\d+)?$")

    def __init__(self):
        super().__init__()
        self._process: Optional[subprocess.Popen] = None
        self._recent_output: List[str] = []
        self._script_path: Optional[str] = None

    # ------------------------------------------------------------- the run

    def _run(self, params: CaptureParams,
             on_progress: Callable[[int, int], None]) -> int:
        script = find_script()
        self._script_path = script

        interpreter, env, description = choose_runtime(script)
        settings = script_parameters(script)
        self._notice(
            f"Running the stakeholder script {os.path.basename(script)} "
            f"with {description}. It uses its own settings: "
            + ", ".join(f"{k} {v}" for k, v in settings.items())
            + ". The panel's velocity/end-position fields do not apply to "
            "this backend."
        )
        log.info("stakeholder script settings: %s", settings)

        # The script writes to './data/test_plant_<ts>/' relative to the
        # working directory, so give it this run's own directory to
        # scribble in and collect what it produced afterwards.
        work_dir = os.path.join(self.out_dir, "stakeholder_run")
        os.makedirs(work_dir, exist_ok=True)

        end_position = settings.get("end position (m)")
        try:
            target = float(end_position) if end_position else 0.0
        except ValueError:
            target = 0.0

        log.info("launching: %s %s (cwd=%s)", interpreter, script, work_dir)
        # start_new_session so Stop can Ctrl-C the whole script, including
        # anything it spawns, without touching the GUI process.
        self._process = subprocess.Popen(
            [interpreter, "-u", script],
            cwd=work_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True,
        )

        frames_seen = self._pump_output(self._process, on_progress, target)
        returncode = self._process.wait()
        log.info("stakeholder script exited with %d after %d reported "
                 "positions", returncode, frames_seen)

        collected = self._collect_output(work_dir)

        if returncode != 0 and not self._stop_flag:
            tail = "\n".join(self._recent_output[-12:])
            raise RuntimeError(
                f"The stakeholder script exited with code {returncode}. "
                f"{collected} frame(s) were saved to {self.out_dir}.\n"
                f"Its last output was:\n{tail}"
            )
        if self._stop_flag:
            self._notice(
                "Stopped. The stakeholder script buffers RGB frames in RAM "
                "and only writes them when the pass completes, so an "
                "interrupted run keeps its depth frames but loses the "
                "unwritten RGB ones. Let a pass finish for a full dataset."
            )
        return collected

    # ------------------------------------------------------------ plumbing

    def _pump_output(self, process: subprocess.Popen,
                     on_progress: Callable[[int, int], None],
                     target_position_m: float) -> int:
        """Forward the script's stdout to the log and drive the progress
        bar from the positions it prints."""
        positions = 0
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip("\n")
            if not line:
                continue
            self._recent_output.append(line)
            del self._recent_output[:-200]

            if self._POSITION_LINE.match(line.strip()):
                positions += 1
                try:
                    position = float(line)
                except ValueError:
                    position = 0.0
                # Percent of the way to the script's own end position.
                if target_position_m > 0:
                    on_progress(min(int(100 * position / target_position_m), 100),
                                100)
                else:
                    on_progress(positions, 0)
                if positions % 25 == 0:
                    log.info("gantry at %.4f m (%d positions reported)",
                             position, positions)
            else:
                log.info("[%s] %s", SCRIPT_NAME, line)

            if self._stop_flag:
                break
        return positions

    def stop(self) -> None:
        """Ctrl-C the script, exactly as running it in a terminal would."""
        super().stop()
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            log.info("sending SIGINT to the stakeholder script")
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
        except (OSError, ProcessLookupError) as e:
            log.warning("could not interrupt the script: %s", e)
            return
        # Give rospy a moment to unwind, then insist.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.1)
        if process.poll() is None:
            log.warning("script ignored SIGINT; terminating")
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    # ------------------------------------------------------------- results

    def _collect_output(self, work_dir: str) -> int:
        """Move what the script wrote into the layout the app loads.

        The script writes flat `rgb_<position>.png` / `depth_<position>.png`
        into its own timestamped folder. The loaders here expect
        `rgb/<i>.png` and `depth/<i>.png`, so the files are renamed into
        place (moved, not copied -- a pass is hundreds of megabytes) and
        the position each index came from is preserved in session.json.
        """
        produced = self._script_output_dir(work_dir)
        if produced is None:
            log.warning("the script produced no output folder under %s",
                        work_dir)
            return 0

        for name in ("kd_intrinsics.txt", "kdc_intrinsics.txt"):
            source = os.path.join(produced, name)
            if os.path.isfile(source):
                shutil.move(source, os.path.join(self.out_dir, name))

        positions = self._indexed_positions(produced)
        moved = 0
        for index, (position_key, files) in enumerate(positions):
            for kind in ("rgb", "depth"):
                source = files.get(kind)
                if source is None:
                    continue
                shutil.move(source,
                            os.path.join(self.out_dir, kind, f"{index}.png"))
            # The script encodes position as micrometres in the filename.
            self._record_position(index, position_key / 1e6)
            moved += 1

        leftovers = os.listdir(produced) if os.path.isdir(produced) else []
        if not leftovers:
            os.rmdir(produced)
            parent = os.path.dirname(produced)
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
            if os.path.isdir(work_dir) and not os.listdir(work_dir):
                os.rmdir(work_dir)
        else:
            log.info("left %d unrecognised file(s) in %s",
                     len(leftovers), produced)

        log.info("collected %d frame(s) from the stakeholder run into %s",
                 moved, self.out_dir)
        return moved

    @staticmethod
    def _script_output_dir(work_dir: str) -> Optional[str]:
        data_dir = os.path.join(work_dir, "data")
        if not os.path.isdir(data_dir):
            return None
        candidates = [os.path.join(data_dir, name)
                      for name in os.listdir(data_dir)
                      if name.startswith("test_plant_")]
        candidates = [c for c in candidates if os.path.isdir(c)]
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)

    @staticmethod
    def _indexed_positions(produced: str):
        """[(position_key, {'rgb': path, 'depth': path}), ...] in gantry
        order -- the script names files by position, not by frame index."""
        by_position: Dict[int, Dict[str, str]] = {}
        pattern = re.compile(r"^(rgb|depth)_(-?\d+)\.png$")
        for name in os.listdir(produced):
            match = pattern.match(name)
            if not match:
                continue
            kind, position = match.group(1), int(match.group(2))
            by_position.setdefault(position, {})[kind] = \
                os.path.join(produced, name)
        return sorted(by_position.items())

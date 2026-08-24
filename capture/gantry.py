"""Non-blocking bridge from the PyQt gantry panel to ROS 1.

All rospy imports and ROS callbacks live in the helper process. This keeps the
GUI responsive even when the lab ROS environment is missing or slow to import.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

from capture.ros_runtime import (
    candidate_ros_pythons,
    helper_path,
    parse_event,
    ros_environment_available,
)


def _ros_importable() -> bool:
    """Compatibility name for the old probe; no ROS module is imported."""
    return ros_environment_available()


class GantryController(QObject):
    position_changed = pyqtSignal(float)
    error = pyqtSignal(str)
    ready_changed = pyqtSignal(bool)

    DEFAULT_POS_MIN_M = 0.0
    DEFAULT_POS_MAX_M = 5.0
    HOME_POSITION_M = 0.005
    HOME_VELOCITY_MPS = 0.2

    TOPIC_CMD_VEL = "/cmd_vel"
    TOPIC_JOINT_STATES = "/joint_states"
    TOPIC_GOTO_GOAL = "/go_to_position_server/goal"

    def __init__(
        self,
        pos_min_m: Optional[float] = None,
        pos_max_m: Optional[float] = None,
    ):
        super().__init__()
        self.pos_min_m = (
            pos_min_m if pos_min_m is not None else self.DEFAULT_POS_MIN_M
        )
        self.pos_max_m = (
            pos_max_m if pos_max_m is not None else self.DEFAULT_POS_MAX_M
        )
        self._current_position_m = 0.0
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._ready = False
        self._startup_timer: threading.Timer | None = None

    def is_available(self) -> bool:
        return ros_environment_available()

    def current_position_m(self) -> float:
        return self._current_position_m

    def start_jog(self, velocity_mps: float) -> None:
        self._send({"command": "jog", "velocity_mps": float(velocity_mps)})

    def stop(self) -> None:
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            self._write(process, {"command": "stop"})

    def go_to(self, position_m: float, velocity_mps: float = 0.2) -> None:
        clamped = max(self.pos_min_m, min(self.pos_max_m, float(position_m)))
        if clamped != position_m:
            self.error.emit(
                f"Position {position_m:.3f} m clamped to "
                f"[{self.pos_min_m:.3f}, {self.pos_max_m:.3f}] m -> "
                f"{clamped:.3f} m"
            )
        self._send(
            {
                "command": "goto",
                "position_m": clamped,
                "velocity_mps": float(velocity_mps),
            }
        )

    def go_home(self) -> None:
        self._send(
            {
                "command": "home",
                "position_m": self.HOME_POSITION_M,
                "velocity_mps": self.HOME_VELOCITY_MPS,
            }
        )

    def shutdown(self) -> None:
        with self._process_lock:
            process = self._process
            self._process = None
            timer = self._startup_timer
            self._startup_timer = None
            self._ready = False
        if timer is not None:
            timer.cancel()
        if process is None:
            return
        if process.poll() is None:
            self._write(process, {"command": "shutdown"})
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        self.ready_changed.emit(False)

    def _send(self, command: dict) -> None:
        process = self._ensure_process()
        if process is not None:
            self._write(process, command)

    def _ensure_process(self) -> subprocess.Popen[str] | None:
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                return self._process
            interpreters = candidate_ros_pythons()
            if not ros_environment_available() or not interpreters:
                self.error.emit(
                    "ROS Noetic was not detected. Source /opt/ros/noetic/setup.bash "
                    "and the gantry workspace before launching PhenoFusion3D."
                )
                return None

            interpreter = interpreters[0]
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            try:
                process = subprocess.Popen(
                    [interpreter, "-u", helper_path("ros_gantry_process.py")],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                )
            except OSError as exc:
                self.error.emit(f"Could not start ROS gantry helper: {exc}")
                return None

            self._process = process
            self._ready = False
            threading.Thread(
                target=self._read_output, args=(process,), daemon=True
            ).start()
            timeout_s = float(os.environ.get("PHENOFUSION_ROS_TIMEOUT", "10"))
            self._startup_timer = threading.Timer(
                max(1.0, timeout_s), self._startup_timed_out, args=(process,)
            )
            self._startup_timer.daemon = True
            self._startup_timer.start()
            return process

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        recent_output: list[str] = []
        for line in process.stdout:
            line = line.rstrip()
            event = parse_event(line)
            if event is None:
                if line:
                    recent_output.append(line)
                    recent_output = recent_output[-3:]
                continue
            kind = event.get("event")
            if kind == "ready":
                with self._process_lock:
                    if self._process is process:
                        self._ready = True
                        if self._startup_timer is not None:
                            self._startup_timer.cancel()
                            self._startup_timer = None
                self.ready_changed.emit(True)
            elif kind == "position":
                position = float(event.get("position_m", 0.0))
                self._current_position_m = position
                self.position_changed.emit(position)
            elif kind == "error":
                self.error.emit(str(event.get("message", "ROS gantry helper failed")))

        return_code = process.wait()
        with self._process_lock:
            if self._process is process:
                self._process = None
                was_ready = self._ready
                self._ready = False
                if self._startup_timer is not None:
                    self._startup_timer.cancel()
                    self._startup_timer = None
            else:
                was_ready = False
        if was_ready:
            self.ready_changed.emit(False)
        if return_code and recent_output:
            self.error.emit(
                "ROS gantry helper exited (%d): %s"
                % (return_code, "; ".join(recent_output))
            )

    def _startup_timed_out(self, process: subprocess.Popen[str]) -> None:
        with self._process_lock:
            if self._process is not process or self._ready or process.poll() is not None:
                return
        self.error.emit(
            "ROS gantry helper did not become ready in time. rospy or the ROS "
            "master may be unavailable; the GUI remains usable."
        )
        try:
            process.terminate()
        except OSError:
            pass

    def _write(self, process: subprocess.Popen[str], command: dict) -> None:
        with self._write_lock:
            try:
                if process.stdin is None or process.poll() is not None:
                    raise BrokenPipeError("helper is not running")
                process.stdin.write(json.dumps(command) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self.error.emit(f"Could not send gantry command: {exc}")

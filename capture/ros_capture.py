"""ROS + RealSense capture backend implemented through a child process.

The lab's ROS Noetic installation and the PyQt virtualenv can use different
Python versions. Importing rospy in the GUI process therefore caused startup
hangs and could prevent an otherwise working RealSense camera from opening.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from typing import Callable

from capture.base import CaptureBackend, CaptureParams
from capture.ros_runtime import (
    candidate_ros_pythons,
    helper_path,
    parse_event,
    ros_environment_available,
)


def ros_available() -> bool:
    """Probe for ROS without importing rospy."""
    return ros_environment_available()


class RosCaptureError(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class RosCapture(CaptureBackend):
    name = "ros"
    KNOWN_SERIALS = ("128422272123", "017322071325", "f1230450")

    def __init__(self, serial_number: str | None = None):
        super().__init__()
        configured = [
            value.strip()
            for value in os.environ.get("PHENOFUSION_CAMERA_SERIALS", "").split(",")
            if value.strip()
        ]
        preferred = ([serial_number] if serial_number else configured) or list(
            self.KNOWN_SERIALS
        )
        self.serial_numbers = list(dict.fromkeys(preferred))
        self.failure_stage: str | None = None
        self.frames_captured = 0
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def _run(
        self,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
    ) -> int:
        interpreters = candidate_ros_pythons()
        if not ros_available() or not interpreters:
            self.failure_stage = "ros_unavailable"
            raise RosCaptureError(
                self.failure_stage,
                "ROS Noetic was not detected. Source /opt/ros/noetic/setup.bash "
                "and the gantry workspace, or select RealSense Only.",
            )

        failures: list[str] = []
        for interpreter in interpreters:
            try:
                return self._run_helper(interpreter, params, on_progress)
            except RosCaptureError as exc:
                self.failure_stage = exc.stage
                failures.append(f"{interpreter}: {exc}")
                if exc.stage not in {
                    "import_ros",
                    "import_camera",
                }:
                    break

        raise RosCaptureError(
            self.failure_stage or "startup",
            "ROS capture could not start. " + " | ".join(failures),
        )

    def _run_helper(
        self,
        interpreter: str,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
    ) -> int:
        command = [
            interpreter,
            "-u",
            helper_path("ros_capture_process.py"),
            "--output", str(self.out_dir),
            "--width", str(params.width),
            "--height", str(params.height),
            "--fps", str(params.fps),
            "--velocity", str(params.velocity_mps),
            "--end-position", str(params.end_position_m),
        ]
        serial_numbers = (
            [params.camera_serial] if params.camera_serial else self.serial_numbers
        )
        for serial_number in serial_numbers:
            command.extend(("--serial", serial_number))
        if params.camera_serial:
            command.append("--strict-serial")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        with self._process_lock:
            self._process = process

        lines: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line.rstrip())
            lines.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        startup_timeout = float(os.environ.get("PHENOFUSION_ROS_TIMEOUT", "10"))
        startup_deadline = time.monotonic() + max(1.0, startup_timeout)
        ready = False
        completed_frames: int | None = None
        child_error: RosCaptureError | None = None
        recent_output: list[str] = []

        try:
            while True:
                if self._stop_flag and process.poll() is None:
                    self._signal_stop(process)
                if not ready and time.monotonic() >= startup_deadline:
                    raise RosCaptureError(
                        "startup_timeout",
                        f"ROS helper did not become ready within {startup_timeout:g}s; "
                        "it may be stuck importing rospy or waiting for ROS master.",
                    )
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None:
                        line = None
                    else:
                        continue
                if line is None:
                    if process.poll() is None:
                        continue
                    break

                event = parse_event(line)
                if event is None:
                    if line:
                        recent_output.append(line)
                        recent_output = recent_output[-5:]
                    continue
                kind = event.get("event")
                if kind == "ready":
                    ready = True
                    if self.session is not None:
                        self.session.camera_serial = str(event.get("serial", ""))
                        self.session.camera_model = str(event.get("model", ""))
                        self.session.width = int(event.get("width", self.session.width))
                        self.session.height = int(event.get("height", self.session.height))
                        self.session.fps = int(event.get("fps", self.session.fps))
                elif kind == "frame":
                    index = int(event.get("index", 0))
                    position = float(event.get("position_m", 0.0))
                    self.frames_captured = max(self.frames_captured, index + 1)
                    if self.session is not None:
                        self.session.n_frames = self.frames_captured
                    self._record_position(index, position)
                    on_progress(index + 1, 0)
                elif kind == "complete":
                    completed_frames = int(event.get("frames", 0))
                elif kind == "error":
                    child_error = RosCaptureError(
                        str(event.get("stage", "helper")),
                        str(event.get("message", "ROS helper failed")),
                    )

            if child_error is not None:
                raise child_error
            if completed_frames is not None and process.returncode == 0:
                return completed_frames
            detail = "; ".join(recent_output) or f"exit code {process.returncode}"
            raise RosCaptureError(
                "process_exit", f"ROS helper exited before completion: {detail}"
            )
        finally:
            self._terminate_process(process)
            with self._process_lock:
                if self._process is process:
                    self._process = None

    def stop(self) -> None:
        super().stop()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            self._signal_stop(process)

    @staticmethod
    def _signal_stop(process: subprocess.Popen[str]) -> None:
        try:
            process.send_signal(signal.SIGINT)
        except (OSError, ValueError):
            try:
                process.terminate()
            except OSError:
                pass

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        RosCapture._signal_stop(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

"""Client for the out-of-process ROS gantry helper."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from capture.ros_runtime import resolve


AGENT_PATH = str(Path(__file__).with_name("ros_agent.py"))
HOME_POSITION_M = 0.005
HOME_VELOCITY_MPS = 0.15


class RosAgentClient:
    """Start the ROS helper and expose non-blocking gantry commands."""

    START_TIMEOUT_S = 20.0

    def __init__(
        self,
        on_position: Optional[Callable[[float], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self._on_position = on_position
        self._on_error = on_error
        self._write_lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._seen_position = threading.Event()
        self._stopping = False
        self._startup_error: Optional[str] = None
        self._stderr = deque(maxlen=100)
        self._position = 0.0

        self.goto_available = False
        self.runtime_description = "not started"

    # ---------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Resolve an existing ROS runtime and start its helper process."""

        runtime = resolve()
        self.runtime_description = runtime.description
        environment = dict(runtime.env)
        environment["PYTHONUNBUFFERED"] = "1"
        self._prepare_node_address(environment)
        self._check_master(environment)

        self._ready.clear()
        self._seen_position.clear()
        self._stderr.clear()
        self._startup_error = None
        self._stopping = False

        try:
            process = subprocess.Popen(
                [runtime.interpreter, "-u", AGENT_PATH],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=environment,
            )
        except OSError as exc:
            raise RuntimeError(
                f"Could not launch the ROS gantry helper with "
                f"{runtime.interpreter}: {exc}"
            ) from exc

        self._process = process
        threading.Thread(
            target=self._read_stdout,
            args=(process,),
            name="gantry-ros-output",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._read_stderr,
            args=(process,),
            name="gantry-ros-errors",
            daemon=True,
        ).start()

        if not self._ready.wait(self.START_TIMEOUT_S):
            detail = self._stderr_detail()
            self.shutdown()
            raise RuntimeError(
                "The ROS gantry helper did not become ready within "
                f"{self.START_TIMEOUT_S:.0f} seconds. Check ROS_MASTER_URI, "
                "the machine hostname/ROS_IP, and the gantry driver."
                + (f" Last helper output: {detail}" if detail else "")
            )
        if self._startup_error:
            error = self._startup_error
            self.shutdown()
            raise RuntimeError(
                f"{error} (runtime: {self.runtime_description})"
            )

    def is_running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def shutdown(self) -> None:
        """Stop the gantry and close the helper. Safe to call repeatedly."""

        process = self._process
        if process is None:
            return
        self._stopping = True
        self._send({"cmd": "stop"})
        self._send({"cmd": "quit"})
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        finally:
            with self._write_lock:
                if self._process is process:
                    self._process = None
            self._ready.clear()

    # ------------------------------------------------------------ commands

    def jog(self, velocity_mps: float) -> bool:
        return self._send({"cmd": "jog", "velocity": float(velocity_mps)})

    def stop(self) -> bool:
        return self._send({"cmd": "stop"})

    def goto(self, position_m: float,
             velocity_mps: float = HOME_VELOCITY_MPS) -> bool:
        return self._send({
            "cmd": "goto",
            "position": float(position_m),
            "velocity": float(velocity_mps),
        })

    def home(self) -> bool:
        return self._send({"cmd": "home"})

    # Names used by the combined camera + gantry capture backend.
    def start_moving(self, velocity_mps: float) -> None:
        if not self.jog(velocity_mps):
            raise RuntimeError("ROS gantry helper is not running")

    def stop_moving(self) -> None:
        self.stop()

    def go_home(self) -> bool:
        return self.home()

    # --------------------------------------------------------------- state

    def position(self) -> float:
        return self._position

    def wait_for_position(self, timeout_s: float) -> bool:
        """Wait until the live /joint_states subscription produces data."""

        return self._seen_position.wait(timeout_s)

    # ----------------------------------------------------------- internals

    @staticmethod
    def _prepare_node_address(environment: dict) -> None:
        """Avoid advertising an unresolvable hostname to a local master."""

        if environment.get("ROS_HOSTNAME") or environment.get("ROS_IP"):
            return
        uri = environment.get("ROS_MASTER_URI", "http://localhost:11311")
        host = urlparse(uri).hostname or "localhost"
        if host in {"localhost", "127.0.0.1", "::1"}:
            environment["ROS_HOSTNAME"] = "localhost"

    @staticmethod
    def _check_master(environment: dict) -> None:
        uri = environment.get("ROS_MASTER_URI", "http://localhost:11311")
        parsed = urlparse(uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 11311
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return
        except OSError as exc:
            raise RuntimeError(
                f"ROS master is not reachable at {uri}: {exc}. Start the "
                "lab roscore/gantry driver or set ROS_MASTER_URI before "
                "launching the app."
            ) from exc

    def _send(self, payload: dict) -> bool:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _read_stdout(self, process: subprocess.Popen) -> None:
        if process.stdout is None:
            return
        try:
            for raw in process.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    message = json.loads(raw)
                except ValueError:
                    self._stderr.append(raw)
                    continue
                self._dispatch(message)
        finally:
            if not self._ready.is_set():
                self._startup_error = (
                    "The ROS gantry helper exited before reporting ready."
                )
                self._ready.set()
            elif not self._stopping and self._on_error is not None:
                self._on_error("The ROS gantry helper stopped unexpectedly.")

    def _read_stderr(self, process: subprocess.Popen) -> None:
        if process.stderr is None:
            return
        for raw in process.stderr:
            raw = raw.strip()
            if raw:
                self._stderr.append(raw)

    def _dispatch(self, message: dict) -> None:
        event = message.get("event")
        if event == "ready":
            self.goto_available = bool(message.get("goto"))
            self._ready.set()
        elif event == "position":
            self._position = float(message.get("value", 0.0))
            self._seen_position.set()
            if self._on_position is not None:
                self._on_position(self._position)
        elif event in {"warning", "error"}:
            message_text = str(message.get("message", "Unknown ROS error"))
            if message.get("fatal"):
                self._startup_error = message_text
                self._ready.set()
            elif self._on_error is not None:
                self._on_error(message_text)

    def _stderr_detail(self) -> str:
        return " | ".join(list(self._stderr)[-3:])

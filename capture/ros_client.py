"""
capture/ros_client.py
---------------------
Talks to `capture/ros_agent.py` running as a separate process.

Everything ROS-facing in the app goes through here, so there is exactly
one place that knows how the helper is launched, addressed and shut
down -- and one runtime doing ROS work, the same one that runs the
stakeholder capture script.

Deliberately Qt-free: `capture/gantry.py` wraps this in a QObject for the
panel, while the self-test and the built-in capture loop use it directly.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("phenofusion.ros_client")

AGENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ros_agent.py")

HOME_POSITION_M = 0.005          # matches the stakeholder script's go_home()
HOME_VELOCITY_MPS = 0.2


class RosAgentClient:
    """A running `ros_agent.py`, with the gantry commands it accepts.

    `start()` blocks until the agent reports ready (or fails); every
    command after that is a non-blocking write of one JSON line, so a
    Stop reaches the axis immediately rather than after a round-trip.
    """

    # Resolving an interpreter probes several of them, and rospy's init
    # has internal waits with no timeout of their own.
    START_TIMEOUT_S = 60.0

    def __init__(self,
                 on_position: Optional[Callable[[float], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self._on_position = on_position
        self._on_error = on_error

        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._seen_position = threading.Event()
        self._outcome: dict = {}

        self._position = 0.0
        self.goto_available = False
        self.runtime_description = "not started"

    # ---------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Launch the agent and wait for it to report ready.

        Raises RuntimeError with the reason and its fix.
        """
        from capture.gantry import ros_preflight
        from capture.ros_runtime import resolve

        problem = ros_preflight()
        if problem is not None:
            raise RuntimeError(problem)

        runtime = resolve()
        self.runtime_description = runtime.description

        env = dict(runtime.env)
        # The node address settled by the preflight is what makes
        # registration reachable -- carry it into the child.
        for name in ("ROS_MASTER_URI", "ROS_HOSTNAME", "ROS_IP"):
            if name in os.environ:
                env[name] = os.environ[name]

        log.info("starting the ROS helper: %s %s [%s]",
                 runtime.interpreter, AGENT_PATH, runtime.description)
        try:
            process = subprocess.Popen(
                [runtime.interpreter, "-u", AGENT_PATH],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, env=env,
            )
        except OSError as e:
            raise RuntimeError(
                f"Could not launch the ROS helper with "
                f"{runtime.interpreter}: {e}") from e

        self._process = process
        threading.Thread(target=self._read, args=(process,),
                         name="ros-agent-reader", daemon=True).start()

        if not self._ready.wait(self.START_TIMEOUT_S):
            self.shutdown()
            raise RuntimeError(
                f"The ROS helper did not become ready within "
                f"{int(self.START_TIMEOUT_S)}s. It was run with "
                f"{runtime.description}. See phenofusion3d.log.")
        if "error" in self._outcome:
            self.shutdown()
            raise RuntimeError(f"{self._outcome['error']} "
                               f"(ROS runtime: {runtime.description})")

    def is_running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def is_shutdown(self) -> bool:
        return not self.is_running()

    def shutdown(self) -> None:
        """Stop the axis and end the agent. Idempotent."""
        process = self._process
        if process is None:
            return
        self._send({"cmd": "stop"})
        self._send({"cmd": "quit"})
        try:
            process.wait(timeout=5.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        with self._lock:
            self._process = None
        self._ready.clear()

    # ------------------------------------------------------------ commands

    def jog(self, velocity_mps: float) -> bool:
        return self._send({"cmd": "jog", "velocity": float(velocity_mps)})

    def stop(self) -> bool:
        return self._send({"cmd": "stop"})

    def goto(self, position_m: float,
             velocity_mps: float = HOME_VELOCITY_MPS) -> bool:
        return self._send({"cmd": "goto", "position": float(position_m),
                           "velocity": float(velocity_mps)})

    def home(self) -> bool:
        return self._send({"cmd": "home"})

    # ------------------------------------------------------------- state

    def position(self) -> float:
        return self._position

    def wait_alive(self, timeout_s: float) -> bool:
        """True once the driver has actually published a position."""
        return self._seen_position.wait(timeout_s)

    # ---- names the capture loop uses ----
    def start_moving(self, velocity_mps: float) -> None:
        self.jog(velocity_mps)

    def stop_moving(self) -> None:
        self.stop()

    def go_home(self) -> None:
        self.home()

    # ----------------------------------------------------------- internals

    def _send(self, payload: dict) -> bool:
        process = self._process
        if process is None or process.poll() is not None:
            return False
        try:
            with self._lock:
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()
            log.debug("-> agent %s", payload)
            return True
        except (OSError, ValueError) as e:
            log.warning("writing to the ROS helper failed: %s", e)
            return False

    def _read(self, process) -> None:
        """Turn the agent's JSON lines into callbacks."""
        try:
            for raw in process.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    message = json.loads(raw)
                except ValueError:
                    log.info("[ros_agent] %s", raw)
                    continue
                self._dispatch(message)
        except Exception as e:
            log.debug("agent reader ended: %s", e)
        finally:
            self._finish(process)

    def _dispatch(self, message: dict) -> None:
        event = message.get("event")
        if event == "position":
            self._position = float(message.get("value", 0.0))
            self._seen_position.set()
            if self._on_position is not None:
                self._on_position(self._position)
        elif event == "ready":
            self.goto_available = bool(message.get("goto"))
            log.info("ROS helper ready as node %s (go-to %s)",
                     message.get("node"),
                     "available" if self.goto_available else "disabled")
            self._ready.set()
        elif event == "error":
            text = str(message.get("message"))
            log.warning("[ros_agent] %s", text)
            if message.get("fatal"):
                self._outcome["error"] = text
                self._ready.set()
            elif self._on_error is not None:
                self._on_error(text)
        elif event == "ack":
            log.debug("agent ack: %s", message.get("cmd"))

    def _finish(self, process) -> None:
        stderr = ""
        try:
            stderr = (process.stderr.read() or "").strip()
        except Exception:
            pass
        if stderr:
            log.warning("ROS helper stderr: %s", stderr[-2000:])
        if not self._ready.is_set():
            self._outcome["error"] = (
                "The ROS helper exited before it was ready."
                + (f" Its error was: {stderr.splitlines()[-1]}"
                   if stderr else ""))
            self._ready.set()

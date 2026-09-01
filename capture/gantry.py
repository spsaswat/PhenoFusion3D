"""Qt-facing gantry controller for the Linux lab rig.

The working gantry protocol is unchanged from the ``gantry`` branch:
``/cmd_vel`` drives motion, ``/joint_states`` reports position, and
``/go_to_position_server/goal`` handles absolute moves. ROS itself runs in a
small helper process under the lab's existing ROS interpreter, keeping the GUI
virtualenv independent from ROS Noetic's Python version.
"""

from __future__ import annotations

import importlib.util
import threading
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from capture.base import MILLIMETRES_PER_METRE
from capture.ros_runtime import ros_is_installed


def _ros_importable() -> bool:
    """Compatibility probe for diagnostics; control does not depend on it."""

    return importlib.util.find_spec("rospy") is not None


class GantryController(QObject):
    """Non-blocking Qt wrapper around the out-of-process ROS helper."""

    position_changed = pyqtSignal(float)
    error = pyqtSignal(str)

    DEFAULT_POS_MIN_M = 0.0
    DEFAULT_POS_MAX_M = 5.0
    HOME_POSITION_M = 0.005
    HOME_VELOCITY_MPS = 0.15

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

        self._lock = threading.Lock()
        self._client = None
        self._start_thread: Optional[threading.Thread] = None
        self._start_attempted = False
        self._start_error: Optional[str] = None
        self._current_position_m = 0.0
        self._pending_action = None
        self._pending_stop = False
        self._shutting_down = False

    # ---------------------------------------------------------- public API

    def is_available(self) -> bool:
        """Whether ROS is installed on the machine, not in the GUI venv."""

        if self._connected() is not None:
            return True
        return ros_is_installed()

    def current_position_m(self) -> float:
        return self._current_position_m

    @pyqtSlot(float)
    def update_position_from_capture(self, position_m: float) -> None:
        """Publish feedback received by the combined capture connection."""
        self._handle_position(float(position_m))

    def start_jog(self, velocity_mps: float) -> None:
        """Move at a signed velocity until :meth:`stop` is called."""

        with self._lock:
            client = self._connected()
            if client is None:
                self._pending_action = ("jog", float(velocity_mps))
        if client is None:
            self._begin_start()
            return
        if not client.jog(velocity_mps):
            self._handle_disconnect()

    def stop(self) -> None:
        """Stop safely; this never starts a new ROS connection."""

        with self._lock:
            self._pending_action = None
            client = self._connected()
            if client is None and self._start_thread is not None:
                self._pending_stop = True
        if client is not None:
            if not client.stop():
                self._handle_disconnect()
            return

    def go_to(
        self,
        position_m: float,
        velocity_mps: float = HOME_VELOCITY_MPS,
    ) -> None:
        clamped = max(self.pos_min_m, min(self.pos_max_m, float(position_m)))
        if clamped != position_m:
            self.error.emit(
                f"Position {position_m * MILLIMETRES_PER_METRE:.1f} mm "
                "clamped to "
                f"[{self.pos_min_m * MILLIMETRES_PER_METRE:.1f}, "
                f"{self.pos_max_m * MILLIMETRES_PER_METRE:.1f}] mm -> "
                f"{clamped * MILLIMETRES_PER_METRE:.1f} mm"
            )

        with self._lock:
            client = self._connected()
            if client is None:
                self._pending_action = ("goto", clamped, float(velocity_mps))
        if client is None:
            self._begin_start()
            return
        if not client.goto_available:
            self.error.emit(
                "Go-to/go-home require position_controller_ros. Source the "
                "gantry catkin workspace before launching. Jog and stop "
                "remain available."
            )
            return
        if not client.goto(clamped, velocity_mps):
            self._handle_disconnect()

    def go_home(self) -> None:
        self.go_to(self.HOME_POSITION_M, self.HOME_VELOCITY_MPS)

    def shutdown(self) -> None:
        """Stop the axis and close the ROS helper. Idempotent."""

        with self._lock:
            self._shutting_down = True
            client, self._client = self._client, None
        if client is not None:
            client.shutdown()

    # ----------------------------------------------------------- internals

    def _connected(self):
        client = self._client
        if client is not None and client.is_running():
            return client
        return None

    def _handle_disconnect(self) -> None:
        with self._lock:
            self._client = None
            self._start_attempted = False
        self.error.emit(
            "The ROS gantry helper stopped unexpectedly; try the command again."
        )

    def _begin_start(self) -> None:
        """Resolve and connect to ROS without blocking the Qt event loop."""

        with self._lock:
            if self._shutting_down:
                return
            if self._start_thread is not None and self._start_thread.is_alive():
                self.error.emit("Connecting to the gantry; try again when ready.")
                return
            self._start_attempted = True
            self._start_error = None
            self._start_thread = threading.Thread(
                target=self._start_worker,
                name="gantry-ros-start",
                daemon=True,
            )
            self._start_thread.start()
        self.error.emit(
            "Connecting to the gantry; the command is queued until ROS is ready."
        )

    def _start_worker(self) -> None:
        from capture.ros_client import RosAgentClient

        client = RosAgentClient(
            on_position=self._handle_position,
            on_error=self.error.emit,
        )
        error: Optional[str] = None
        try:
            client.start()
        except Exception as exc:
            error = str(exc)

        queued_goto_unavailable = False
        with self._lock:
            shutting_down = self._shutting_down
            pending_stop = self._pending_stop
            pending_action = self._pending_action
            self._pending_stop = False
            self._pending_action = None
            self._start_error = error
            self._start_thread = None
            if error is None and not shutting_down:
                self._client = client
            else:
                self._client = None
            # Connection failures are retryable after roscore/workspace fixes.
            if error is not None:
                self._start_attempted = False

            # Command ordering is protected by the state lock. If Stop was
            # pressed while connecting, the queued move was cleared and only
            # a stop is sent. Otherwise the original user command runs once.
            if error is None and not shutting_down:
                if pending_stop:
                    client.stop()
                elif pending_action is not None:
                    command, *values = pending_action
                    if command == "jog":
                        client.jog(values[0])
                    elif command == "goto" and client.goto_available:
                        client.goto(values[0], values[1])
                    elif command == "goto":
                        queued_goto_unavailable = True

        if shutting_down:
            if error is None:
                client.shutdown()
            return
        if error is not None:
            self.error.emit(error)
            return
        if queued_goto_unavailable:
            self.error.emit(
                "Go-to/go-home require position_controller_ros. Source the "
                "gantry catkin workspace before launching. Jog and stop "
                "remain available."
            )
        self.error.emit(
            f"Gantry connected using {client.runtime_description}. Ready."
        )

    def _handle_position(self, position_m: float) -> None:
        self._current_position_m = position_m
        self.position_changed.emit(position_m)

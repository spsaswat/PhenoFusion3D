"""
capture/gantry.py
-----------------
Standalone gantry controller for the lab Linux rig.

Wraps the same ROS topics the capture loop drives
(see capture/ros_capture.py and stakeholder_reference/rospy_thread_fin_1.py)
but exposed as a long-lived `QObject` that the UI can drive directly --
jog, stop, go-to-position, go-home, and live position read-back.

`rospy` and `position_controller_ros.msg` are imported lazily so this
module is importable on Windows / any host where ROS isn't present
(`is_available()` simply returns False there).
"""

from __future__ import annotations

import importlib.util
import threading
import time
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal


def _ros_importable() -> bool:
    return importlib.util.find_spec("rospy") is not None


class GantryController(QObject):
    """
    Singleton-style gantry controller. Safe to instantiate on any OS;
    ROS-dependent calls only fire on hosts where rospy is importable
    AND init succeeded. On other hosts every action no-ops and emits
    `error` once so the UI can show a friendly badge.
    """

    # Live position from /joint_states, in metres.
    position_changed = pyqtSignal(float)
    # Human-readable error from the controller (no rospy, init failed,
    # publish failed, etc.) -- the panel shows it as a status string.
    error            = pyqtSignal(str)

    # Safety clamp on `go_to(...)`. Catches typo'd values without
    # blocking legitimate captures (capture panel max is 5 m).
    DEFAULT_POS_MIN_M: float = 0.0
    DEFAULT_POS_MAX_M: float = 5.0
    HOME_POSITION_M:   float = 0.005    # matches stakeholder go_home()
    HOME_VELOCITY_MPS: float = 0.2

    # rospy topic names -- centralised so swaps are one-liners.
    TOPIC_CMD_VEL:      str = "/cmd_vel"
    TOPIC_JOINT_STATES: str = "/joint_states"
    TOPIC_GOTO_GOAL:    str = "/go_to_position_server/goal"

    def __init__(self,
                 pos_min_m: Optional[float] = None,
                 pos_max_m: Optional[float] = None):
        super().__init__()
        self.pos_min_m = pos_min_m if pos_min_m is not None else self.DEFAULT_POS_MIN_M
        self.pos_max_m = pos_max_m if pos_max_m is not None else self.DEFAULT_POS_MAX_M

        self._init_lock = threading.Lock()
        self._initialised = False
        self._init_attempted = False
        self._init_error: Optional[str] = None

        # Populated by _init_ros() on first use.
        self._rospy = None
        self._cmd_vel_pub = None
        self._goto_pub = None
        self._joint_sub = None
        self._Twist = None
        self._GotoActionGoal = None
        self._Header = None
        self._GoalID = None
        self._goto_available = False

        self._current_position_m: float = 0.0

    # ---------------------------------------------------------- public API

    def is_available(self) -> bool:
        """True iff rospy is importable AND `init_node` has succeeded
        (or hasn't been attempted yet but is expected to). The UI uses
        this to decide whether to enable the panel."""
        if not _ros_importable():
            return False
        if not self._init_attempted:
            return True            # optimistic: try on first call
        return self._initialised

    def current_position_m(self) -> float:
        return self._current_position_m

    # ---- motion ----

    def start_jog(self, velocity_mps: float) -> None:
        """Publish a Twist with linear.x = velocity (signed). Caller is
        responsible for calling stop() when done (or use hold-to-move)."""
        if not self._ensure_initialised():
            return
        try:
            msg = self._Twist()
            msg.linear.x = float(velocity_mps)
            self._cmd_vel_pub.publish(msg)
        except Exception as e:
            self.error.emit(f"jog failed: {e}")

    def stop(self) -> None:
        """Publish a zero Twist. Always safe to call -- silently no-ops
        if the controller never initialised."""
        if not self._initialised or self._cmd_vel_pub is None:
            return
        try:
            self._cmd_vel_pub.publish(self._Twist())
        except Exception as e:
            self.error.emit(f"stop failed: {e}")

    def go_to(self,
              position_m: float,
              velocity_mps: float = 0.2) -> None:
        """Send an absolute-position goal via /go_to_position_server/goal."""
        if not self._ensure_initialised():
            return
        if not self._goto_available:
            self.error.emit("Go-to / Go-home unavailable: "
                            "position_controller_ros msgs not installed.")
            return
        clamped = max(self.pos_min_m, min(self.pos_max_m, float(position_m)))
        if clamped != position_m:
            self.error.emit(
                f"Position {position_m:.3f} m clamped to "
                f"[{self.pos_min_m:.3f}, {self.pos_max_m:.3f}] m -> {clamped:.3f} m"
            )
        try:
            msg = self._GotoActionGoal()
            msg.header = self._Header()
            msg.goal_id = self._GoalID()
            msg.goal.position = float(clamped)
            msg.goal.velocity = float(velocity_mps)
            self._goto_pub.publish(msg)
        except Exception as e:
            self.error.emit(f"go_to failed: {e}")

    def go_home(self) -> None:
        self.go_to(self.HOME_POSITION_M, self.HOME_VELOCITY_MPS)

    # ---- shutdown ----

    def shutdown(self) -> None:
        """Publish a final zero Twist and unregister the subscriber.
        Idempotent. Call from the main window's close handler."""
        try:
            self.stop()
        except Exception:
            pass
        if self._joint_sub is not None:
            try:
                self._joint_sub.unregister()
            except Exception:
                pass
            self._joint_sub = None

    # ----------------------------------------------------------- internals

    def _ensure_initialised(self) -> bool:
        with self._init_lock:
            if self._initialised:
                return True
            if self._init_attempted:
                if self._init_error:
                    self.error.emit(self._init_error)
                return False
            self._init_attempted = True
            return self._init_ros()

    def _init_ros(self) -> bool:
        """One-shot ROS init. Returns True on success, False on any
        failure (which is also reported through `error`)."""
        if not _ros_importable():
            self._init_error = (
                "rospy not importable on this machine. The gantry panel "
                "is only functional on the lab Linux rig."
            )
            self.error.emit(self._init_error)
            return False

        try:
            import rospy
            from geometry_msgs.msg import Twist
            from sensor_msgs.msg import JointState
        except Exception as e:
            self._init_error = f"ROS core msgs unavailable: {e}"
            self.error.emit(self._init_error)
            return False

        self._rospy = rospy
        self._Twist = Twist

        # Optional position-controller msgs -- without them, jog/stop
        # still work but go_to/go_home are disabled gracefully.
        try:
            from position_controller_ros.msg import GotoActionGoal
            from std_msgs.msg import Header
            from actionlib_msgs.msg import GoalID
            self._GotoActionGoal = GotoActionGoal
            self._Header = Header
            self._GoalID = GoalID
            self._goto_available = True
        except Exception as e:
            self._goto_available = False
            self.error.emit(
                f"position_controller_ros msgs not found ({e}); "
                f"jog and stop available, go-to / go-home disabled."
            )

        # init_node is process-global. RosCapture also calls init_node;
        # the second caller will hit ROSException, which is fine.
        try:
            try:
                rospy.init_node('phenofusion_gantry',
                                anonymous=True, disable_signals=True)
            except rospy.exceptions.ROSException:
                pass

            self._cmd_vel_pub = rospy.Publisher(
                self.TOPIC_CMD_VEL, Twist, queue_size=10
            )
            if self._goto_available:
                self._goto_pub = rospy.Publisher(
                    self.TOPIC_GOTO_GOAL, self._GotoActionGoal, queue_size=10
                )
            self._joint_sub = rospy.Subscriber(
                self.TOPIC_JOINT_STATES, JointState, self._on_joint_states
            )

            # Give subscribers a beat to discover our publishers --
            # without this the very first cmd_vel can be silently dropped.
            time.sleep(0.3)
        except Exception as e:
            self._init_error = f"ROS init failed: {e}"
            self.error.emit(self._init_error)
            return False

        self._initialised = True
        return True

    def _on_joint_states(self, msg) -> None:
        # rospy callback runs on its own thread. Qt queues the signal
        # emission across threads automatically because GantryController
        # is a QObject living on the main thread.
        try:
            if msg.position:
                pos = float(msg.position[0])
                self._current_position_m = pos
                self.position_changed.emit(pos)
        except Exception:
            pass

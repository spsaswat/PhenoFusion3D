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
import logging
import os
import socket
import threading
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

from PyQt5.QtCore import QObject, pyqtSignal

log = logging.getLogger("phenofusion.gantry")

DEFAULT_MASTER_URI = "http://localhost:11311"


def _reinstall_log_handlers() -> None:
    """rospy.init_node() steals the root logger's handlers; restore ours.
    Best-effort -- never let a logging problem break the gantry."""
    try:
        from logging_setup import reinstall_handlers
        reinstall_handlers()
    except Exception:
        pass


def _ros_importable() -> bool:
    return importlib.util.find_spec("rospy") is not None


def ros_master_uri() -> str:
    return os.environ.get("ROS_MASTER_URI", DEFAULT_MASTER_URI)


def ros_master_reachable(timeout_s: float = 1.5) -> Tuple[bool, str]:
    """Bounded TCP probe of the ROS master (roscore).

    `rospy.init_node()` retries master registration FOREVER when the
    master is down, so it must never be called before this probe says
    the master is actually there. Returns (ok, detail-string).
    """
    uri = ros_master_uri()
    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11311
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            log.debug("ROS master reachable at %s (%.0f ms)",
                      uri, (time.monotonic() - t0) * 1000)
            return True, uri
    except OSError as e:
        log.warning("ROS master NOT reachable at %s: %s", uri, e)
        return False, f"{uri} ({e})"


def ros_preflight(timeout_s: float = 1.5) -> Optional[str]:
    """Bounded checks that ROS init can succeed. Returns an error string
    describing the problem (and its fix), or None when clear.

    Two known forever-hangs in rospy are covered:
      - init_node retries master registration endlessly when roscore is
        down  -> TCP-probe ROS_MASTER_URI first;
      - init_node spins waiting for the node's own XML-RPC server when
        the node address doesn't resolve -> resolve it first.
    """
    reachable, detail = ros_master_reachable(timeout_s)
    if not reachable:
        return (
            f"ROS master not reachable at {detail}. "
            "Start roscore (and 'source /opt/ros/noetic/setup.bash') "
            "on this machine, then try again."
        )

    node_addr = (os.environ.get("ROS_HOSTNAME")
                 or os.environ.get("ROS_IP")
                 or socket.gethostname())
    try:
        socket.getaddrinfo(node_addr, None)
        log.debug("node address '%s' resolves", node_addr)
    except OSError as e:
        log.error("node address '%s' does not resolve: %s", node_addr, e)
        return (
            f"This machine's ROS node address '{node_addr}' does not "
            f"resolve ({e}) -- rospy would hang forever starting its "
            f"node server. Fix: add '127.0.0.1 {node_addr}' to "
            "/etc/hosts, or launch with ROS_HOSTNAME=localhost, "
            "then try again."
        )
    return None


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

    # Watchdog for the background ROS init. rospy.init_node has internal
    # waits WITHOUT timeouts (e.g. it spins forever if the node's own
    # XML-RPC server can't start because the hostname doesn't resolve),
    # so we bound the whole init ourselves.
    INIT_TIMEOUT_S: float = 15.0

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
        # ROS init runs on this daemon thread, NEVER on the Qt main
        # thread -- rospy.init_node can block indefinitely (e.g. pip-shim
        # rospy + no roscore) and must not freeze the GUI event loop.
        self._init_thread: Optional[threading.Thread] = None
        # Which step of _init_ros is currently running -- shown in the
        # panel while connecting and in the timeout error, so a hang
        # points at the exact culprit.
        self._init_stage: str = "idle"

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
            log.debug("jog: publishing cmd_vel %.4f m/s", velocity_mps)
            msg = self._Twist()
            msg.linear.x = float(velocity_mps)
            self._cmd_vel_pub.publish(msg)
        except Exception as e:
            log.exception("jog failed")
            self.error.emit(f"jog failed: {e}")

    def stop(self) -> None:
        """Publish a zero Twist. Always safe to call -- silently no-ops
        if the controller never initialised."""
        if not self._initialised or self._cmd_vel_pub is None:
            return
        try:
            log.debug("stop: publishing zero cmd_vel")
            self._cmd_vel_pub.publish(self._Twist())
        except Exception as e:
            log.exception("stop failed")
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
            log.info("go_to: %.3f m @ %.3f m/s", clamped, velocity_mps)
            msg = self._GotoActionGoal()
            msg.header = self._Header()
            msg.goal_id = self._GoalID()
            msg.goal.position = float(clamped)
            msg.goal.velocity = float(velocity_mps)
            self._goto_pub.publish(msg)
        except Exception as e:
            log.exception("go_to failed")
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
        """Non-blocking. True iff ROS is fully initialised right now.

        The first call kicks off init on a background thread and returns
        False (that first command is intentionally dropped -- the user
        clicks again once the panel reports the connection). This method
        must stay cheap: it runs on the Qt main thread on every click.
        """
        with self._init_lock:
            if self._initialised:
                return True

            if not _ros_importable():
                if not self._init_attempted:
                    self._init_attempted = True
                    self._init_error = (
                        "rospy not importable on this machine. The gantry "
                        "panel is only functional on the lab Linux rig."
                    )
                    log.warning(self._init_error)
                self.error.emit(self._init_error)
                return False

            if self._init_thread is not None and self._init_thread.is_alive():
                log.debug("gantry command ignored: ROS init still in "
                          "progress (stage: %s)", self._init_stage)
                self.error.emit(
                    f"Connecting to ROS ({self._init_stage})... "
                    "try again in a moment."
                )
                return False

            if self._init_attempted:
                if self._init_error:
                    self.error.emit(self._init_error)
                return False

            self._init_attempted = True
            log.info("starting ROS init on background thread "
                     "(ROS_MASTER_URI=%s)", ros_master_uri())
            self.error.emit("Connecting to ROS master... command dropped, "
                            "try again once connected.")
            self._init_thread = threading.Thread(
                target=self._init_worker, name="gantry-ros-init", daemon=True
            )
            self._init_thread.start()
            return False

    def _init_worker(self) -> None:
        """Background-thread wrapper around `_init_ros()`. Runs the init
        on an inner thread bounded by INIT_TIMEOUT_S -- rospy has
        internal waits with no timeout, and a hung init must not leave
        the panel saying 'connecting' forever. Publishes the outcome
        under the lock and reports it through `error` (which the panel
        renders as its status line)."""
        result: dict = {}

        def _run() -> None:
            try:
                result["v"] = self._init_ros()
            except Exception as e:                   # belt and braces
                log.exception("unexpected failure during ROS init")
                result["v"] = (False, False, f"ROS init failed: {e}")

        inner = threading.Thread(target=_run,
                                 name="gantry-ros-init-inner", daemon=True)
        inner.start()
        inner.join(self.INIT_TIMEOUT_S)

        if "v" in result:
            ok, retryable, err = result["v"]
        else:
            stage = self._init_stage
            log.error("ROS init timed out after %.0fs, stuck at stage: %s "
                      "(master=%s). Likely hostname-resolution trouble -- "
                      "rospy waits forever for its own XML-RPC server if "
                      "the machine's hostname doesn't resolve. Check "
                      "/etc/hosts, or launch with ROS_IP=127.0.0.1 / "
                      "ROS_HOSTNAME=localhost.",
                      self.INIT_TIMEOUT_S, stage, ros_master_uri())
            ok, retryable, err = False, True, (
                f"ROS init timed out after {int(self.INIT_TIMEOUT_S)}s "
                f"(stuck at: {stage}). The master answered the port probe "
                "but node registration never completed. Common fix: "
                "'export ROS_HOSTNAME=localhost' (or add this machine's "
                "hostname to /etc/hosts), restart the app, and try again. "
                "See phenofusion3d.log."
            )

        with self._init_lock:
            self._initialised = ok
            self._init_error = None if ok else err
            if not ok and retryable:
                # e.g. roscore wasn't running -- let the next click retry
                # instead of requiring an app restart.
                self._init_attempted = False
            self._init_thread = None

        if ok:
            log.info("ROS init complete; gantry ready")
            self.error.emit("Gantry connected to ROS. Ready.")
        else:
            log.error("ROS init failed: %s", err)
            self.error.emit(err)

    def _init_ros(self) -> Tuple[bool, bool, Optional[str]]:
        """One-shot ROS init, run on the background init thread.
        Returns (ok, retryable, error_message)."""
        # Fail fast on the known rospy forever-hangs (master down,
        # unresolvable node hostname) BEFORE importing rospy or calling
        # init_node.
        self._init_stage = "ROS preflight (master probe + hostname)"
        problem = ros_preflight()
        if problem is not None:
            return False, True, problem

        self._init_stage = "importing rospy"
        try:
            import rospy
            from geometry_msgs.msg import Twist
            from sensor_msgs.msg import JointState
        except Exception as e:
            log.exception("importing rospy / core msgs failed")
            hint = ""
            # /opt/ros rospy found via PYTHONPATH, but its pure-Python
            # deps were apt-installed for the SYSTEM python (3.8) and are
            # invisible to this venv's newer interpreter. Those deps ARE
            # official PyPI packages (unlike 'rospy' itself), so pip is
            # the right fix here.
            if (isinstance(e, ModuleNotFoundError) and e.name in
                    ("rospkg", "catkin_pkg", "yaml", "defusedxml",
                     "netifaces", "gnupg", "empy")):
                hint = (
                    " -- rospy's Python deps are missing from the venv. Run: "
                    "pip install rospkg catkin_pkg PyYAML defusedxml netifaces "
                    "(then click again; no restart needed)."
                )
            return False, True, f"ROS core msgs unavailable: {e}{hint}"

        rospy_path = getattr(rospy, "__file__", "?")
        log.info("rospy imported from: %s", rospy_path)
        if rospy_path != "?" and "/opt/ros/" not in rospy_path:
            log.warning(
                "rospy was imported from site-packages, not /opt/ros -- "
                "this looks like the unofficial PyPI 'rospy' shim "
                "(pip install rospy). If the gantry misbehaves, run "
                "'pip uninstall rospy rosgraph roslib' in the app venv and "
                "use the system ROS install instead ('source "
                "/opt/ros/noetic/setup.bash' before launching)."
            )

        self._rospy = rospy
        self._Twist = Twist

        # Optional position-controller msgs -- without them, jog/stop
        # still work but go_to/go_home are disabled gracefully.
        self._init_stage = "importing position_controller_ros msgs"
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
            log.warning("position_controller_ros msgs not found: %s", e)
            self.error.emit(
                f"position_controller_ros msgs not found ({e}); "
                f"jog and stop available, go-to / go-home disabled."
            )

        # init_node is process-global. RosCapture also calls init_node;
        # the second caller will hit ROSException, which is fine.
        try:
            self._init_stage = "rospy.init_node (node registration)"
            t0 = time.monotonic()
            try:
                rospy.init_node('phenofusion_gantry',
                                anonymous=True, disable_signals=True)
                # init_node replaces the root logger's handlers with
                # rospy's own -- put ours back or the app stops logging
                # to phenofusion3d.log from here on.
                _reinstall_log_handlers()
                log.info("rospy.init_node ok (%.0f ms)",
                         (time.monotonic() - t0) * 1000)
            except rospy.exceptions.ROSException:
                _reinstall_log_handlers()
                log.info("rospy node already initialised in this process")

            self._init_stage = "creating publishers/subscriber"
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
            log.debug("publishers/subscriber created (%s, %s, %s)",
                      self.TOPIC_CMD_VEL, self.TOPIC_GOTO_GOAL,
                      self.TOPIC_JOINT_STATES)

            # Give subscribers a beat to discover our publishers --
            # without this the very first cmd_vel can be silently dropped.
            time.sleep(0.3)
        except Exception as e:
            log.exception("ROS init failed")
            return False, False, f"ROS init failed: {e}"

        self._init_stage = "done"
        return True, False, None

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

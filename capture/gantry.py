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

# Signature of the last master-probe failure, so a repeated
# failure is logged once at WARNING and then at DEBUG.
_last_master_failure: Optional[str] = None
# Last logged node-address decision, so the repeating preflight
# announces it once instead of every few seconds.
_last_node_address: Optional[str] = None
# Which of ROS_HOSTNAME / ROS_IP this app set itself (if any), so a
# value we pinned is not later mistaken for one the user exported.
_node_address_source: Optional[str] = None


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


_LOOPBACK_HOSTS = frozenset({
    "localhost", "127.0.0.1", "::1", "ip6-localhost", "ip6-loopback",
})


def _local_ip_towards(host: str, port: int) -> Optional[str]:
    """The address this machine would use to reach (host, port).

    That is exactly the address the master has to call back on. UDP
    connect() only fixes a route -- nothing is sent.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((host, port))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return None


def configure_ros_node_address() -> str:
    """Pin the address rospy advertises to the master. Returns a
    one-line description of what was chosen and why.

    Node registration is the step that most often half-works: init_node
    registers whatever address rospy derives from the machine's
    hostname, and from then on the master's callbacks -- and every peer
    connecting to our publishers -- are sent there. On a box whose
    hostname resolves to something unreachable (a VM's
    *.myguest.virtualbox.org name, a stale /etc/hosts line, an
    IPv6-only answer) registration appears to succeed but nothing ever
    connects, which the UI can only show as a hang.

    Policy, applied before rospy is imported:
      - an explicit ROS_IP / ROS_HOSTNAME from the user always wins;
      - master on this machine    -> ROS_HOSTNAME=localhost, so
        registration is pure loopback with no name resolution at all;
      - master on another machine -> ROS_IP = this machine's address on
        the route to that master, so the master can call back.
    """
    global _node_address_source
    for var in ("ROS_HOSTNAME", "ROS_IP"):
        value = os.environ.get(var)
        if value:
            if _node_address_source == var:
                return f"{var}={value} (pinned by this app)"
            return f"{var}={value} (set in the environment; left alone)"

    parsed = urlparse(ros_master_uri())
    master_host = parsed.hostname or "localhost"
    master_port = parsed.port or 11311

    if master_host in _LOOPBACK_HOSTS:
        os.environ["ROS_HOSTNAME"] = "localhost"
        _node_address_source = "ROS_HOSTNAME"
        log.info("ROS master is on this machine; pinned "
                 "ROS_HOSTNAME=localhost for node registration")
        return ("ROS_HOSTNAME=localhost (master is local; avoids "
                "registering an unreachable hostname)")

    local_ip = _local_ip_towards(master_host, master_port)
    if local_ip:
        os.environ["ROS_IP"] = local_ip
        _node_address_source = "ROS_IP"
        log.info("ROS master is remote (%s); pinned ROS_IP=%s so it can "
                 "call back", master_host, local_ip)
        return (f"ROS_IP={local_ip} (address this machine reaches the "
                f"master {master_host} on)")

    log.warning("could not work out this machine's address towards the "
                "ROS master at %s; leaving rospy to guess", master_host)
    return (f"could not determine this machine's address towards "
            f"{master_host}; rospy will guess from the hostname")


def ros_master_reachable(timeout_s: float = 1.5) -> Tuple[bool, str]:
    """Bounded TCP probe of the ROS master (roscore).

    `rospy.init_node()` retries master registration FOREVER when the
    master is down, so it must never be called before this probe says
    the master is actually there. Returns (ok, detail-string).
    """
    global _last_master_failure
    uri = ros_master_uri()
    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11311
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            log.debug("ROS master reachable at %s (%.0f ms)",
                      uri, (time.monotonic() - t0) * 1000)
            _last_master_failure = None
            return True, uri
    except OSError as e:
        # The UI re-probes every few seconds; logging every identical
        # failure at WARNING buries everything else in the log file.
        signature = f"{uri}|{e}"
        if signature != _last_master_failure:
            log.warning("ROS master NOT reachable at %s: %s "
                        "(further identical probes logged at DEBUG)", uri, e)
            _last_master_failure = signature
        else:
            log.debug("ROS master still NOT reachable at %s: %s", uri, e)
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
    # Decide what address we will register under BEFORE rospy is
    # imported -- rospy reads ROS_HOSTNAME / ROS_IP out of the
    # environment when it registers the node.
    choice = configure_ros_node_address()
    global _last_node_address
    if choice != _last_node_address:          # preflight runs every few seconds
        log.info("ROS node address: %s", choice)
        _last_node_address = choice

    reachable, detail = ros_master_reachable(timeout_s)
    if not reachable:
        return (
            f"ROS master not reachable at {detail}. "
            "Start roscore (and 'source /opt/ros/noetic/setup.bash') "
            "on this machine, then try again. If the gantry's roscore "
            "runs on another machine, point the app at it with "
            "'export ROS_MASTER_URI=http://<that-machine>:11311' before "
            "launching."
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
    The gantry panel's controller: a Qt wrapper around `RosAgentClient`.

    ROS never runs inside the GUI process. That is what makes the panel
    work on a rig whose app venv cannot import rospy (the "cannot import
    rospkg" failure): the helper runs under whichever Python on the
    machine actually can -- the same one that runs the stakeholder
    capture script. It also means rospy cannot steal Qt's logging or
    signal handlers, and a wedged ROS call cannot freeze the event loop.

    Safe to construct anywhere. When no runtime can be resolved, every
    action no-ops and `error` carries the reason and its fix.
    """

    # Live position from /joint_states, in metres.
    position_changed = pyqtSignal(float)
    # Human-readable status/error for the panel's status line.
    error            = pyqtSignal(str)

    # Safety clamp on `go_to(...)`. Catches typo'd values without
    # blocking legitimate captures (capture panel max is 5 m).
    DEFAULT_POS_MIN_M: float = 0.0
    DEFAULT_POS_MAX_M: float = 5.0
    HOME_POSITION_M:   float = 0.005    # matches stakeholder go_home()
    HOME_VELOCITY_MPS: float = 0.2

    def __init__(self,
                 pos_min_m: Optional[float] = None,
                 pos_max_m: Optional[float] = None):
        super().__init__()
        self.pos_min_m = pos_min_m if pos_min_m is not None else self.DEFAULT_POS_MIN_M
        self.pos_max_m = pos_max_m if pos_max_m is not None else self.DEFAULT_POS_MAX_M

        self._lock = threading.Lock()
        self._client = None                 # RosAgentClient once connected
        self._start_thread: Optional[threading.Thread] = None
        self._start_error: Optional[str] = None
        self._start_attempted = False
        self._current_position_m: float = 0.0

    # ---------------------------------------------------------- public API

    def is_available(self) -> bool:
        """Whether the panel should be enabled. Optimistic before the
        first attempt -- the helper decides, not a guess made here."""
        with self._lock:
            if not self._start_attempted:
                return True
            return self._connected() or self._start_error is None

    def current_position_m(self) -> float:
        return self._current_position_m

    # ---- motion ----

    def start_jog(self, velocity_mps: float) -> None:
        """Move at a signed velocity until stop() is called."""
        client = self._connected()
        if client is None:
            self._begin_start()
            return
        if not client.jog(velocity_mps):
            self._on_disconnected()

    def stop(self) -> None:
        """Halt the axis. Always safe to call, and never starts the
        helper: a stop with nothing running is a no-op, not an error."""
        client = self._connected()
        if client is not None and not client.stop():
            self._on_disconnected()

    def go_to(self, position_m: float, velocity_mps: float = 0.2) -> None:
        clamped = max(self.pos_min_m, min(self.pos_max_m, float(position_m)))
        if clamped != position_m:
            self.error.emit(
                f"Position {position_m:.3f} m clamped to "
                f"[{self.pos_min_m:.3f}, {self.pos_max_m:.3f}] m -> {clamped:.3f} m"
            )
        client = self._connected()
        if client is None:
            self._begin_start()
            return
        if not client.goto_available:
            self.error.emit(
                "Go-to / go-home need the position_controller_ros message "
                "package, which the ROS runtime cannot import. Source your "
                "catkin workspace's devel/setup.bash (or set "
                "PHENOFUSION_ROS_WS) before launching. Jog and stop work.")
            return
        if not client.goto(clamped, velocity_mps):
            self._on_disconnected()

    def go_home(self) -> None:
        self.go_to(self.HOME_POSITION_M, self.HOME_VELOCITY_MPS)

    # ---- shutdown ----

    def shutdown(self) -> None:
        """Stop the axis and end the helper. Idempotent."""
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.shutdown()

    # ----------------------------------------------------------- internals

    def _connected(self):
        """The live client, or None."""
        client = self._client
        if client is not None and client.is_running():
            return client
        return None

    def _on_disconnected(self) -> None:
        with self._lock:
            self._client = None
            self._start_attempted = False       # allow a restart
        self.error.emit("The ROS helper stopped unexpectedly; "
                        "click again to restart it.")

    def _begin_start(self) -> None:
        """Kick off connection on a background thread and report back.

        Non-blocking: this runs on the Qt main thread for every button
        press. The first command is dropped; the panel says so and the
        user clicks again once it reports ready.
        """
        with self._lock:
            if self._start_thread is not None and self._start_thread.is_alive():
                self.error.emit("Connecting to ROS... try again in a moment.")
                return
            if self._start_attempted:
                if self._start_error:
                    self.error.emit(self._start_error)
                return
            self._start_attempted = True
            self._start_thread = threading.Thread(
                target=self._start_worker, name="gantry-agent-start",
                daemon=True)
            self._start_thread.start()
        self.error.emit("Starting the ROS helper... command dropped, try "
                        "again once it reports ready.")

    def _start_worker(self) -> None:
        """Bring the helper up. Off the Qt thread: resolving a runtime
        probes interpreters and rospy's init has unbounded waits."""
        from capture.ros_client import RosAgentClient

        client = RosAgentClient(on_position=self._handle_position,
                                on_error=self.error.emit)
        error: Optional[str] = None
        try:
            client.start()
        except RuntimeError as e:
            error = str(e)
        except Exception as e:                       # belt and braces
            log.exception("starting the ROS helper failed")
            error = f"Could not start the ROS helper: {e}"

        with self._lock:
            self._start_error = error
            self._client = None if error else client
            if error is not None:
                # Retryable: the usual causes (roscore not up yet, a
                # workspace not sourced) are fixed without restarting the
                # app, so the next click should try again.
                self._start_attempted = False
            self._start_thread = None

        if error is None:
            log.info("gantry helper ready (%s)", client.runtime_description)
            self.error.emit("Gantry connected to ROS. Ready.")
        else:
            log.error("gantry helper failed: %s", error)
            self.error.emit(error)

    def _handle_position(self, position_m: float) -> None:
        self._current_position_m = position_m
        self.position_changed.emit(position_m)

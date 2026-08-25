"""
capture/simulation.py
---------------------
Stand-ins for the two pieces of lab hardware, plus the probes that
decide whether the real thing is present.

Why this exists: the rig is often without the D405 (USB passthrough) or
without the gantry driver, and the app still has to be demonstrable and
testable end to end. A simulated run produces exactly the same on-disk
layout as a real one, so everything downstream can be exercised.

A simulated run is ALWAYS announced -- `SimCamera` / `SimGantry` set the
`simulated` flag that the capture reports to the UI, which shows a
"SIMULATED" badge. Simulated frames are also visibly synthetic (a
rendered gradient scene with a frame counter burned in), so nobody can
mistake them for plant data.
"""

from __future__ import annotations

import gc
import json
import logging
import math
import os
import subprocess
import threading
import time
from typing import Optional, Tuple

import numpy as np

log = logging.getLogger("phenofusion.sim")


# --------------------------------------------------------------- detection

_rs_context = None
_rs_context_lock = threading.Lock()


def _realsense_context(rs, rebuild: bool = False):
    """One shared librealsense context, reused across probes.

    Building a fresh context costs ~106 ms; querying an existing one
    costs ~2 ms, which is what makes probing every few seconds
    affordable.

    A cached context is supposed to track device arrival itself, but it
    only does so where librealsense's hotplug notifications actually get
    delivered -- inside a VM, or over some USB stacks, they do not, and
    the cached context then reports "no devices" forever even after the
    camera is plugged in. `rebuild=True` throws the stale context away
    and enumerates from scratch.
    """
    global _rs_context
    with _rs_context_lock:
        if _rs_context is None or rebuild:
            _rs_context = rs.context()
        return _rs_context


def release_camera() -> None:
    """Drop the shared context so ANOTHER PROCESS can open the camera.

    The context above lives for the whole session, which is what makes
    probing every few seconds cheap. The cost is that this process keeps
    a claim on the device -- and librealsense built with
    FORCE_RSUSB_BACKEND (the build this project pins, see
    docs/L515_SETUP.md) talks to the camera through libusb, which claims
    the USB interface exclusively. A second process then cannot open it:

        RuntimeError: ... Device or resource busy

    That is exactly what the stakeholder script hits when it runs as a
    subprocess while the GUI still holds a probe context. So every code
    path that is about to hand the camera to someone else calls this
    first. The next probe rebuilds the context lazily, and the ~106 ms
    that costs does not matter next to a capture run.

    Safe to call when there is no context, no camera, or no
    pyrealsense2 at all.
    """
    global _rs_context
    with _rs_context_lock:
        if _rs_context is None:
            return
        _rs_context = None
    # The context object is gone, but the device handles it produced may
    # still be held by an unreferenced cycle; libusb only releases the
    # interface when they are finalised.
    gc.collect()
    log.debug("released the shared RealSense context")


def _query_devices(rs, rebuild: bool = False):
    ctx = _realsense_context(rs, rebuild=rebuild)
    return list(ctx.query_devices())


def usb_diagnosis() -> str:
    """Why librealsense sees no camera, judged from the OS's own view of
    the USB bus. Returns '' when there is nothing useful to add.

    The RealSense SDK can only report what the kernel exposes, so
    'no camera connected' has very different fixes depending on whether
    the device reached the machine at all. Linux-only (sysfs); silent
    everywhere else.
    """
    try:
        if not os.path.isdir("/sys/bus/usb/devices"):
            return ""

        # Every USB device currently on the bus, minus the root hubs.
        intel_devices = []
        n_devices = 0
        for entry in sorted(os.listdir("/sys/bus/usb/devices")):
            base = os.path.join("/sys/bus/usb/devices", entry)
            try:
                with open(os.path.join(base, "idVendor")) as f:
                    vendor = f.read().strip()
                with open(os.path.join(base, "idProduct")) as f:
                    product = f.read().strip()
            except OSError:
                continue                      # interfaces, not devices
            if vendor == "1d6b":              # Linux Foundation root hub
                continue
            n_devices += 1
            if vendor == "8086":              # Intel -- RealSense's vendor id
                intel_devices.append(f"{vendor}:{product}")

        if intel_devices:
            # The camera reached the kernel but librealsense cannot open
            # it -- almost always the udev rules.
            return (
                f" -- an Intel USB device ({', '.join(intel_devices)}) IS on "
                "this machine's USB bus, so the camera is plugged in but "
                "librealsense cannot open it. Install the udev rules: "
                "'sudo cp /usr/lib/udev/rules.d/99-realsense-libusb.rules "
                "/etc/udev/rules.d/ && sudo udevadm control --reload-rules "
                "&& sudo udevadm trigger', then replug the camera."
            )

        # No Intel device on the bus. Does this machine even have a port
        # the D405 could enumerate on?
        has_usb3 = False
        controllers = []
        for entry in sorted(os.listdir("/sys/bus/pci/devices")):
            try:
                with open(os.path.join("/sys/bus/pci/devices", entry,
                                       "class")) as f:
                    cls = f.read().strip()
            except OSError:
                continue
            if not cls.startswith("0x0c03"):
                continue                      # not a USB controller
            if cls == "0x0c0330":
                has_usb3 = True
                controllers.append("USB 3 (xHCI)")
            elif cls == "0x0c0320":
                controllers.append("USB 2 (EHCI)")
            elif cls == "0x0c0310":
                controllers.append("USB 1.1 (OHCI)")
            else:
                controllers.append("USB 1.1 (UHCI)")

        virt = _virtualisation()
        if virt and not has_usb3:
            return (
                f" -- no USB device of any kind is attached to this "
                f"{virt} virtual machine (it exposes only "
                f"{', '.join(sorted(set(controllers))) or 'no USB controller'}"
                "), so the D405 is not being passed through from the host. "
                "On the host: install the VirtualBox Extension Pack, set "
                "the VM's USB controller to USB 3.0 (xHCI), add a device "
                "filter for 'Intel(R) RealSense(TM) Depth Camera', then "
                "attach the camera via Devices > USB while the VM runs."
            )
        if virt:
            return (
                f" -- this is a {virt} virtual machine and no Intel device "
                "is on its USB bus; pass the D405 through from the host "
                "(Devices > USB), then re-detect."
            )
        if not has_usb3:
            return (
                " -- this machine exposes no USB 3 (xHCI) controller "
                f"({', '.join(sorted(set(controllers))) or 'none found'}); "
                "the D405 needs a USB 3 port."
            )
        if n_devices == 0:
            return (" -- no USB devices at all are on this machine's bus; "
                    "check the cable and the port.")
        return (f" -- {n_devices} USB device(s) are on the bus but none is "
                "an Intel RealSense; check the cable (it must be a data "
                "cable, not charge-only) and try another USB 3 port.")
    except Exception:                          # diagnosis must never throw
        return ""


def _virtualisation() -> str:
    """'VirtualBox', 'KVM', ... or '' on bare metal."""
    try:
        with open("/sys/class/dmi/id/product_name") as f:
            name = f.read().strip()
        if name and name.lower() not in ("", "unknown"):
            for known in ("VirtualBox", "VMware", "KVM", "QEMU", "Hyper-V",
                          "Virtual Machine"):
                if known.lower() in name.lower():
                    return known
    except OSError:
        pass
    return ""


def no_camera_message(detail: str) -> str:
    """The one place the 'no camera' wording lives, so the badge, the
    capture backends and the self-test all say the same thing."""
    return (
        f"No Intel RealSense camera was found ({detail}). PhenoFusion3D "
        "asks the RealSense SDK for RGB-D devices directly, not for "
        "ordinary webcam indexes -- confirm the camera streams depth in "
        "'realsense-viewer' (or 'rs-enumerate-devices'). If it does not "
        "appear there either, the problem is below the app: USB "
        "passthrough, cable, port, or the librealsense udev rules."
    )


def detect_camera() -> Tuple[bool, str]:
    """(present, detail). Fast: `query_devices()` returns immediately.

    Never call `pipeline.start()` to probe -- it blocks ~15 s while
    HOLDING the GIL when no camera is attached, which freezes the GUI.
    """
    try:
        import pyrealsense2 as rs
    except ImportError:
        return False, ("pyrealsense2 is not installed -- run "
                       "'pip install pyrealsense2' in the app's venv")
    try:
        devices = _query_devices(rs)
        if not devices:
            # The cached context may simply have missed a hotplug; pay
            # the ~106 ms rebuild before believing "no camera".
            devices = _query_devices(rs, rebuild=True)
    except Exception as e:
        return False, f"RealSense query failed: {e}"
    if not devices:
        return False, "no RealSense camera connected" + usb_diagnosis()
    names = []
    for dev in devices:
        try:
            names.append(dev.get_info(rs.camera_info.name))
        except Exception:
            names.append("RealSense device")
    return True, ", ".join(names)


def detect_gantry(timeout_s: float = 3.0) -> Tuple[bool, str]:
    """(present, detail). Requires a reachable ROS master AND somebody
    actually publishing /joint_states -- a master with no gantry driver
    is not a usable gantry.

    Answered by whichever interpreter can really talk to ROS. This
    process often cannot: the app's venv gets rospy from /opt/ros via
    PYTHONPATH while rospy's own dependencies were apt-installed for the
    system Python, so `import rospy` here dies on rospkg even with the
    gantry running perfectly. Falling back to the resolved runtime is
    what makes the answer match what the capture will actually do.
    """
    from capture.gantry import ros_preflight, ros_master_uri

    problem = ros_preflight()
    if problem is not None:
        return False, problem

    try:
        import rosgraph                                  # noqa: F401
    except Exception as e:
        return _detect_gantry_via_runtime(timeout_s, f"{e}")

    # getSystemState is XML-RPC over a socket with NO timeout of its own.
    # This probe runs on the hardware-poll thread AND inside
    # get_backend("auto") on the capture thread, so an unbounded call
    # here shows up as the app hanging with no error at all.
    #
    # It is bounded with a throwaway thread rather than
    # socket.setdefaulttimeout(), which is process-global and would put a
    # timeout on rospy's own long-lived sockets opened in the same window.
    result: dict = {}

    def _query() -> None:
        try:
            import rosgraph
            master = rosgraph.Master("/phenofusion_probe")
            result["publishers"] = dict(master.getSystemState()[0])
        except Exception as e:                    # noqa: BLE001
            result["error"] = e

    thread = threading.Thread(target=_query, name="gantry-probe", daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return False, (f"the ROS master at {ros_master_uri()} accepted the "
                       f"connection but did not answer within "
                       f"{timeout_s:.0f}s")
    if "error" in result:
        return False, f"could not query ROS master: {result['error']}"

    publishers = result.get("publishers") or {}
    if not publishers.get("/joint_states"):
        return False, ("no node is publishing /joint_states -- roscore is "
                       "up but the gantry driver is not running")
    return True, "publishers: " + ", ".join(publishers["/joint_states"])


def _detect_gantry_via_runtime(timeout_s: float, why: str) -> Tuple[bool, str]:
    """Ask the ROS-capable interpreter, because this one is not."""
    log.debug("this interpreter cannot query ROS (%s); using the resolved "
              "runtime instead", why)
    try:
        from capture.ros_runtime import resolve
        runtime = resolve()
    except RuntimeError as e:
        return False, str(e)

    agent = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "ros_agent.py")
    try:
        done = subprocess.run([runtime.interpreter, "-u", agent, "--probe"],
                              capture_output=True, text=True,
                              timeout=max(timeout_s, 10.0), env=runtime.env)
    except subprocess.TimeoutExpired:
        return False, (f"the ROS probe ({runtime.description}) did not "
                       f"answer within {max(timeout_s, 10.0):.0f}s")
    except OSError as e:
        return False, f"could not run the ROS probe: {e}"

    try:
        report = json.loads((done.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        detail = (done.stderr or done.stdout or "no output").strip()
        return False, f"the ROS probe failed: {detail.splitlines()[-1][:200]}"

    return bool(report.get("driver")), str(report.get("detail", ""))


# ------------------------------------------------------------------ camera

class SimCamera:
    """Synthetic RGB-D source with the same interface the capture loop
    uses for the real camera."""

    simulated = True
    label = "simulated camera"

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30):
        self.width = int(width)
        self.height = int(height)
        self.fps = max(1, int(fps))
        self._i = 0
        self._t_next = 0.0
        # Precompute the static part of the scene once -- generating a
        # 1280x720 image per frame from scratch would dominate the loop.
        self._base_rgb, self._base_depth = self._render_scene()

    # -- lifecycle --
    def start(self) -> None:
        self._t_next = time.monotonic()
        log.info("simulated camera started (%dx%d @ %d fps)",
                 self.width, self.height, self.fps)

    def stop(self) -> None:
        log.info("simulated camera stopped after %d frames", self._i)

    # -- frames --
    def wait_for_frames(self) -> Tuple[np.ndarray, np.ndarray]:
        """Block until the next frame is due, then return (color, depth).
        Paced to `fps` so a simulated scan takes realistic wall time."""
        self._t_next += 1.0 / self.fps
        delay = self._t_next - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            self._t_next = time.monotonic()

        # Shift the scene sideways so successive frames differ the way a
        # moving gantry's would.
        shift = (self._i * 3) % self.width
        color = np.roll(self._base_rgb, shift, axis=1)
        depth = np.roll(self._base_depth, shift, axis=1)
        self._stamp(color)
        self._i += 1
        return color, depth

    def intrinsics(self) -> dict:
        """Plausible D405-like intrinsics in the app's on-disk format."""
        fx = fy = self.width * 0.5
        return {
            "K": [[fx, 0, self.width / 2.0],
                  [0, fy, self.height / 2.0],
                  [0, 0, 1]],
            "dist": [0.0, 0.0, 0.0, 0.0, 0.0],
            "height": self.height,
            "width": self.width,
        }

    # -- internals --
    def _render_scene(self):
        h, w = self.height, self.width
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

        # A few "plants": vertical green blobs at fixed x positions.
        depth = np.full((h, w), 1200, np.uint16)          # backdrop ~1.2 m
        rgb = np.zeros((h, w, 3), np.uint8)
        rgb[..., 0] = 60      # dim blue-grey backdrop (BGR)
        rgb[..., 1] = 55
        rgb[..., 2] = 50

        for k, cx in enumerate(np.linspace(w * 0.15, w * 0.85, 4)):
            spread = w * 0.05
            blob = np.exp(-((xx - cx) ** 2) / (2 * spread ** 2))
            # taller in the middle of the frame
            height_mask = np.clip((yy - h * 0.25) / (h * 0.75), 0, 1)
            leaf = blob * height_mask
            rgb[..., 1] = np.clip(rgb[..., 1] + leaf * 170, 0, 255).astype(np.uint8)
            rgb[..., 0] = np.clip(rgb[..., 0] + leaf * 30, 0, 255).astype(np.uint8)
            depth = np.where(leaf > 0.25,
                             (700 + 120 * math.sin(k)) * np.ones_like(depth),
                             depth).astype(np.uint16)

        # Sensor-like noise so quality metrics see something realistic.
        rng = np.random.default_rng(0)
        depth = np.clip(depth.astype(np.int32)
                        + rng.integers(-6, 7, depth.shape), 1, 65535).astype(np.uint16)
        return rgb, depth

    def _stamp(self, img) -> None:
        """Burn 'SIMULATED' + frame number into the corner so the output
        can never be mistaken for real plant data."""
        try:
            import cv2
        except ImportError:
            return
        cv2.putText(img, "SIMULATED  frame %d" % self._i, (24, 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 255), 2, cv2.LINE_AA)


# ------------------------------------------------------------------ gantry

class SimGantry:
    """Simulated linear axis: integrates the commanded velocity so the
    capture loop's end-position logic behaves exactly as on hardware."""

    simulated = True
    label = "simulated gantry"

    def __init__(self, start_position_m: float = 0.0):
        self._lock = threading.Lock()
        self._pos = float(start_position_m)
        self._vel = 0.0
        self._t = time.monotonic()

    def start(self) -> None:
        with self._lock:
            self._t = time.monotonic()
        log.info("simulated gantry started at %.3f m", self._pos)

    def wait_alive(self, timeout_s: float) -> bool:
        return True

    def is_shutdown(self) -> bool:
        return False

    def _advance(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._pos += self._vel * (now - self._t)
            self._t = now

    def start_moving(self, velocity_mps: float) -> None:
        self._advance()
        with self._lock:
            self._vel = float(velocity_mps)

    def stop_moving(self) -> None:
        self._advance()
        with self._lock:
            self._vel = 0.0

    def position(self) -> float:
        self._advance()
        with self._lock:
            return self._pos

    def go_home(self) -> None:
        self._advance()
        with self._lock:
            self._pos = 0.005
            self._vel = 0.0
        log.info("simulated gantry homed")

    def shutdown(self) -> None:
        self.stop_moving()

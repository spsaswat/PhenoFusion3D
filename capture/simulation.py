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

import logging
import math
import threading
import time
from typing import Optional, Tuple

import numpy as np

log = logging.getLogger("phenofusion.sim")


# --------------------------------------------------------------- detection

_rs_context = None
_rs_context_lock = threading.Lock()


def _realsense_context(rs):
    """One shared librealsense context, reused across probes.

    Building a fresh context costs ~106 ms; querying an existing one
    costs ~2 ms. The context tracks device arrival/removal itself, so
    reusing it still notices a camera plugged in while the app runs --
    which is what makes continuous auto-detection affordable.
    """
    global _rs_context
    with _rs_context_lock:
        if _rs_context is None:
            _rs_context = rs.context()
        return _rs_context


def detect_camera() -> Tuple[bool, str]:
    """(present, detail). Fast: `query_devices()` returns immediately.

    Never call `pipeline.start()` to probe -- it blocks ~15 s while
    HOLDING the GIL when no camera is attached, which freezes the GUI.
    """
    try:
        import pyrealsense2 as rs
    except ImportError:
        return False, "pyrealsense2 is not installed"
    try:
        devices = list(_realsense_context(rs).query_devices())
    except Exception as e:
        return False, f"RealSense query failed: {e}"
    if not devices:
        return False, "no RealSense camera connected"
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
    is not a usable gantry."""
    from capture.gantry import ros_preflight, _ros_importable

    if not _ros_importable():
        return False, "rospy is not importable"
    problem = ros_preflight()
    if problem is not None:
        return False, problem

    try:
        import rospy
        from sensor_msgs.msg import JointState
    except Exception as e:
        return False, f"ROS msgs unavailable: {e}"

    # rospy.wait_for_message needs an initialised node; if the app hasn't
    # initialised one yet, report based on the publisher count instead.
    try:
        import rosgraph
        master = rosgraph.Master("/phenofusion_probe")
        _, _, _ = master.getSystemState()
        pubs = dict(master.getSystemState()[0])
        if "/joint_states" not in pubs or not pubs["/joint_states"]:
            return False, "no node is publishing /joint_states"
        return True, "publishers: " + ", ".join(pubs["/joint_states"])
    except Exception as e:
        return False, f"could not query ROS master: {e}"


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

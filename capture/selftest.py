"""
capture/selftest.py
-------------------
Test the camera and the gantry independently.

Quick Scan exercises both at once, which is what a real plant scan does.
When it misbehaves you need to know WHICH half is at fault, so each piece
also has a self-test:

    camera_self_test()  grabs a short burst of frames and reports
                        resolution, frame rate and depth validity
    gantry_self_test()  jogs a few centimetres and reports the distance
                        actually measured on /joint_states

Both fall back to simulated hardware when the real thing is absent, and
both say so in their report -- `SelfTestResult.simulated`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

log = logging.getLogger("phenofusion.selftest")


@dataclass
class SelfTestResult:
    subject: str                  # "camera" or "gantry"
    ok: bool
    simulated: bool
    headline: str                 # one-line verdict for the UI
    details: List[str] = field(default_factory=list)

    def as_text(self) -> str:
        tag = "SIMULATED" if self.simulated else "REAL"
        status = "PASS" if self.ok else "FAIL"
        lines = [f"[{status}] {self.subject} ({tag}): {self.headline}"]
        lines += [f"  - {d}" for d in self.details]
        return "\n".join(lines)


# ------------------------------------------------------------------ camera

def camera_self_test(n_frames: int = 30,
                     width: int = 1280,
                     height: int = 720,
                     fps: int = 30,
                     allow_sim: bool = True) -> SelfTestResult:
    """Grab `n_frames` and report what actually came back."""
    from capture.simulation import detect_camera, SimCamera
    from capture.ros_capture import RealCamera

    present, detail = detect_camera()
    if present:
        camera = RealCamera(None, width, height, fps)
        simulated = False
    elif allow_sim:
        camera = SimCamera(width, height, fps)
        simulated = True
    else:
        return SelfTestResult("camera", False, False,
                              f"no camera detected ({detail})")

    details = [f"source: {camera.label}"]
    if simulated:
        details.append(f"real camera not found: {detail}")

    try:
        camera.start()
    except Exception as e:
        return SelfTestResult("camera", False, simulated,
                              f"could not start the camera: {e}", details)

    try:
        t0 = time.monotonic()
        got = 0
        dropped = 0
        valid_fracs = []
        shape = None
        for _ in range(n_frames):
            frames = camera.wait_for_frames()
            if frames is None:
                dropped += 1
                continue
            color, depth = frames
            got += 1
            shape = color.shape
            d = np.asarray(depth)
            valid_fracs.append(float(np.count_nonzero(d) / d.size))
        elapsed = time.monotonic() - t0
    except Exception as e:
        return SelfTestResult("camera", False, simulated,
                              f"failed while streaming: {e}", details)
    finally:
        camera.stop()

    if got == 0:
        return SelfTestResult("camera", False, simulated,
                              "no frames were returned", details)

    measured_fps = got / elapsed if elapsed > 0 else 0.0
    validity = 100.0 * (sum(valid_fracs) / len(valid_fracs))
    details += [
        f"frames: {got} received, {dropped} dropped",
        f"resolution: {shape[1]}x{shape[0]}" if shape else "resolution: ?",
        f"measured rate: {measured_fps:.1f} fps (requested {fps})",
        f"depth validity: {validity:.1f}% of pixels non-zero",
    ]
    ok = got >= max(1, n_frames // 2) and validity > 5.0
    headline = (f"{got} frames at {measured_fps:.1f} fps, "
                f"{validity:.0f}% valid depth")
    return SelfTestResult("camera", ok, simulated, headline, details)


# ------------------------------------------------------------------ gantry

def gantry_self_test(distance_m: float = 0.05,
                     velocity_mps: float = 0.038,
                     allow_sim: bool = True) -> SelfTestResult:
    """Jog the axis a short distance and verify the reported position
    actually changes. Always stops the axis before returning."""
    from capture.simulation import detect_gantry, SimGantry
    from capture.ros_capture import RealGantry

    present, detail = detect_gantry()
    if present:
        gantry = RealGantry()
        simulated = False
    elif allow_sim:
        gantry = SimGantry()
        simulated = True
    else:
        return SelfTestResult("gantry", False, False,
                              f"no gantry detected ({detail})")

    details = [f"source: {gantry.label}"]
    if simulated:
        details.append(f"real gantry not found: {detail}")

    try:
        gantry.start()
    except Exception as e:
        return SelfTestResult("gantry", False, simulated,
                              f"could not connect to the gantry: {e}", details)

    try:
        if not gantry.wait_alive(8.0):
            return SelfTestResult(
                "gantry", False, simulated,
                "connected, but no position was published on /joint_states "
                "within 8s -- the driver is not running", details)

        start_pos = gantry.position()
        details.append(f"start position: {start_pos:+.4f} m")

        # Time-box the move so a stalled axis can't spin here forever.
        timeout_s = (distance_m / max(velocity_mps, 1e-6)) * 3.0 + 5.0
        t0 = time.monotonic()
        gantry.start_moving(velocity_mps)
        try:
            while time.monotonic() - t0 < timeout_s:
                if abs(gantry.position() - start_pos) >= distance_m:
                    break
                time.sleep(0.05)
        finally:
            gantry.stop_moving()

        time.sleep(0.3)                      # let the last message land
        end_pos = gantry.position()
        moved = abs(end_pos - start_pos)
        details += [
            f"end position: {end_pos:+.4f} m",
            f"commanded {velocity_mps:.3f} m/s for {distance_m*100:.0f} cm",
            f"measured travel: {moved*100:.1f} cm in "
            f"{time.monotonic()-t0:.1f}s",
        ]
        ok = moved >= distance_m * 0.5
        headline = (f"moved {moved*100:.1f} cm"
                    if ok else
                    f"only moved {moved*100:.1f} cm of the requested "
                    f"{distance_m*100:.0f} cm")
        return SelfTestResult("gantry", ok, simulated, headline, details)
    finally:
        try:
            gantry.stop_moving()
        except Exception:
            pass
        gantry.shutdown()

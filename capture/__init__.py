"""
capture/
--------
RGB-D capture backends. Use `get_backend()` to pick automatically based
on what's installed on the host machine.
"""

from __future__ import annotations

from capture.base import CaptureBackend, CaptureParams, CaptureSession
from capture.ros_capture import ros_available


def get_backend(prefer: str = "auto") -> CaptureBackend:
    """
    prefer:
        "auto"        -- the stakeholder script when a real gantry is
                         there, else RealSense-only
        "stakeholder" -- run rospy_thread_fin_1.py as the backend
        "ros"         -- the built-in port of that loop (raises on Windows)
        "realsense"   -- camera-only
    """
    prefer = (prefer or "auto").lower()

    if prefer in ("quickscan", "quick_scan", "sim"):
        # Camera + gantry together, simulating whichever is absent.
        from capture.ros_capture import QuickScanCapture
        return QuickScanCapture()

    if prefer in ("stakeholder", "script"):
        from capture.stakeholder_capture import StakeholderScriptCapture
        return StakeholderScriptCapture()

    if prefer == "ros":
        from capture.ros_capture import RosCapture
        return RosCapture()

    if prefer == "realsense":
        from capture.realsense_capture import RealSenseCapture
        return RealSenseCapture()

    if prefer == "auto":
        # Real hardware always wins. Prefer the full ROS + gantry rig, and
        # only step down when the gantry genuinely isn't usable: rospy
        # being importable -- or even a reachable master -- is not enough,
        # because with no driver publishing /joint_states the ROS backend
        # can only fail.
        import logging
        log = logging.getLogger("phenofusion.capture")
        if ros_available():
            from capture.simulation import detect_gantry
            gantry_ok, gantry_detail = detect_gantry()
            if gantry_ok:
                # With a real gantry, run the stakeholder's own program --
                # it is the capture the lab trusts.
                log.info("auto backend: real ROS gantry available (%s); "
                         "using the stakeholder script", gantry_detail)
                from capture.stakeholder_capture import StakeholderScriptCapture
                return StakeholderScriptCapture()
            log.warning("auto backend: gantry unusable (%s); falling back "
                        "to camera-only capture.", gantry_detail)
        from capture.realsense_capture import RealSenseCapture
        return RealSenseCapture()

    raise ValueError(f"Unknown backend preference: {prefer!r}")


__all__ = [
    "CaptureBackend",
    "CaptureParams",
    "CaptureSession",
    "get_backend",
    "ros_available",
]

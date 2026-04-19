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
        "auto"        -- ROS if available, else RealSense-only
        "ros"         -- ROS + gantry (raises on Windows)
        "realsense"   -- camera-only
    """
    prefer = (prefer or "auto").lower()

    if prefer == "ros":
        from capture.ros_capture import RosCapture
        return RosCapture()

    if prefer == "realsense":
        from capture.realsense_capture import RealSenseCapture
        return RealSenseCapture()

    if prefer == "auto":
        if ros_available():
            from capture.ros_capture import RosCapture
            return RosCapture()
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

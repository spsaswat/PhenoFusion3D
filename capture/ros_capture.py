"""
capture/ros_capture.py
----------------------
ROS + RealSense + gantry capture backend.

Thin adapter around the stakeholder-provided
`stakeholder_reference/rospy_thread_fin_1.py`. The capture loop, ROS
topics, velocity command, and intrinsics save logic are kept identical
to the working stakeholder script -- we only:

  - wrap them in a class so the QThread worker can drive them
  - import rospy / pyrealsense2 / cv2 lazily so this module is importable on
    Windows (where ROS is unavailable) without OpenCV until the ROS backend runs
  - parameterise velocity / end position / FPS / serial number
  - write to our standard output layout
        <out>/rgb/<idx>.png, <out>/depth/<idx>.png
        <out>/kdc_intrinsics.txt, <out>/kd_intrinsics.txt
        <out>/session.json   (records frame_idx -> gantry position)

The frame->position map in session.json preserves per-frame gantry
positions (which are lost when we rename frames to 0.png, 1.png, ...)
and unlocks exact known-pose reconstruction downstream.
"""

from __future__ import annotations

import json
import os
from typing import Callable

import numpy as np

from capture.base import CaptureBackend, CaptureParams
from capture.ros_runtime import ros_is_installed


def ros_available() -> bool:
    """True when ROS is installed on the machine, independent of the UI venv."""
    return ros_is_installed()


class RosCapture(CaptureBackend):
    name = "ros"

    # D405 serial used in the stakeholder script
    DEFAULT_SERIAL = "128422272123"

    def __init__(self, serial_number: str | None = None):
        super().__init__()
        self.serial_number = serial_number or self.DEFAULT_SERIAL

    def _run(
        self,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
    ) -> int:
        if not ros_available():
            raise RuntimeError(
                "ROS is not installed or sourced on this machine. Source the "
                "lab ROS distribution and gantry workspace before launching."
            )

        # Camera packages stay in the GUI venv. ROS runs under the lab's
        # existing compatible interpreter through RosAgentClient.
        from capture.ros_client import RosAgentClient
        try:
            import pyrealsense2 as rs
        except ImportError as e:
            raise RuntimeError(
                "pyrealsense2 is not installed. Install with "
                "'pip install pyrealsense2'."
            ) from e
        try:
            import cv2
        except ImportError as e:
            raise RuntimeError(
                "opencv-python is required for the ROS capture backend. "
                "Install with 'pip install opencv-python' or "
                "'opencv-python-headless'."
            ) from e
        self._cv2 = cv2

        # ------------------ RealSense pipeline (mirrors stakeholder) -------
        pipeline = rs.pipeline()
        config = rs.config()
        try:
            config.enable_device(self.serial_number)
        except Exception:
            pass
        config.enable_stream(rs.stream.color, params.width, params.height, rs.format.bgr8, params.fps)
        config.enable_stream(rs.stream.depth, params.width, params.height, rs.format.z16,  params.fps)

        profile = pipeline.start(config)
        align = rs.align(rs.stream.color)

        try:
            depth_sensor = profile.get_device().first_depth_sensor()
            try:
                depth_sensor.set_option(rs.option.visual_preset, 4)  # high-accuracy on D405
            except Exception:
                pass

            self._save_intrinsics(profile, rs)

            # Warm-up (matches stakeholder)
            for _ in range(2):
                pipeline.wait_for_frames()
                pipeline.wait_for_frames()

            # ------------------ ROS gantry helper --------------------------
            self._current_position = 0.0

            def update_position(position_m):
                self._current_position = position_m

            gantry = RosAgentClient(on_position=update_position)
            gantry.start()
            if not gantry.wait_for_position(8.0):
                gantry.shutdown()
                raise RuntimeError(
                    "ROS is connected, but the gantry driver did not publish "
                    "/joint_states within 8 seconds. Start the gantry driver "
                    "before capture."
                )

            # ------------------ capture loop -------------------------------
            i = 0
            try:
                while gantry.is_running() and not self._stop_flag:
                    gantry.start_moving(params.velocity_mps)
                    self._capture_one(pipeline, align, i)
                    self._record_position(i, self._current_position)
                    i += 1
                    on_progress(i, 0)  # unknown total -> 0

                    if self._current_position != 0.0 and self._current_position >= params.end_position_m:
                        gantry.stop_moving()
                        break

                    # Stakeholder calls capture_images twice per loop -- replicate
                    self._capture_one(pipeline, align, i)
                    self._record_position(i, self._current_position)
                    i += 1
                    on_progress(i, 0)

                if not self._stop_flag and not gantry.is_running():
                    raise RuntimeError(
                        "The ROS gantry helper stopped during capture."
                    )
            finally:
                gantry.stop_moving()
                gantry.shutdown()

            return i
        finally:
            try:
                pipeline.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ I/O
    def _capture_one(self, pipeline, align, idx: int) -> None:
        frames = pipeline.wait_for_frames()
        aligned = align.process(frames)

        depth_frame = aligned.get_depth_frame()
        color_frame = aligned.get_color_frame()
        if not depth_frame or not color_frame:
            return

        depth_img = np.asanyarray(depth_frame.get_data())
        color_img = np.asanyarray(color_frame.get_data())

        self._cv2.imwrite(os.path.join(self.out_dir, "rgb",   f"{idx}.png"), color_img)
        self._cv2.imwrite(os.path.join(self.out_dir, "depth", f"{idx}.png"), depth_img)

    def _save_intrinsics(self, profile, rs) -> None:
        for stream_kind, fname in (
            (rs.stream.depth, "kd_intrinsics.txt"),
            (rs.stream.color, "kdc_intrinsics.txt"),
        ):
            try:
                vsp = rs.video_stream_profile(profile.get_stream(stream_kind))
                intr = vsp.get_intrinsics()
                payload = {
                    "K": [
                        [intr.fx, 0,       intr.ppx],
                        [0,       intr.fy, intr.ppy],
                        [0,       0,       1],
                    ],
                    "dist": list(intr.coeffs),
                    "height": intr.height,
                    "width":  intr.width,
                }
                with open(os.path.join(self.out_dir, fname), "w") as f:
                    json.dump(payload, f, indent=4)
            except Exception as e:
                print(f"[ros_capture] WARNING: failed to save {fname}: {e}")

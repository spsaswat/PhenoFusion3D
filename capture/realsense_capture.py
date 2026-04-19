"""
capture/realsense_capture.py
----------------------------
Camera-only capture backend using pyrealsense2 directly.

Used on Windows / dev machines where ROS isn't available, or as a quick
sanity check that the camera is producing valid frames before attaching
the gantry.

Captures frames for `params.duration_s` seconds (or until stop() is called)
and writes to:
    <out_root>/<timestamp>/rgb/0.png, 1.png, ...
    <out_root>/<timestamp>/depth/0.png, 1.png, ...
    <out_root>/<timestamp>/kdc_intrinsics.txt
    <out_root>/<timestamp>/kd_intrinsics.txt
    <out_root>/<timestamp>/session.json

Imports of pyrealsense2 are deferred to _run() so this module can be
imported on machines where the SDK isn't installed (e.g. CI).
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable

import cv2
import numpy as np

from capture.base import CaptureBackend, CaptureParams


class RealSenseCapture(CaptureBackend):
    name = "realsense"

    def _run(
        self,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
    ) -> int:
        try:
            import pyrealsense2 as rs
        except ImportError as e:
            raise RuntimeError(
                "pyrealsense2 is not installed. Install with "
                "'pip install pyrealsense2' (Windows / Linux x86_64)."
            ) from e

        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(
            rs.stream.color, params.width, params.height, rs.format.bgr8, params.fps
        )
        config.enable_stream(
            rs.stream.depth, params.width, params.height, rs.format.z16, params.fps
        )

        profile = pipeline.start(config)

        try:
            # Match stakeholder rospy_thread_fin_1.py: high-accuracy preset on D405
            depth_sensor = profile.get_device().first_depth_sensor()
            try:
                depth_sensor.set_option(rs.option.visual_preset, 4)
            except Exception:
                pass

            # Save intrinsics (color + depth streams)
            self._save_intrinsics(profile, rs)

            # Align depth to color (same as stakeholder)
            align = rs.align(rs.stream.color)

            # Warm-up
            for _ in range(5):
                pipeline.wait_for_frames()

            # Estimate total frames for progress reporting
            total_estimate = int(params.duration_s * params.fps) if params.duration_s > 0 else 0
            t_start = time.time()
            i = 0

            while not self._stop_flag:
                if params.duration_s > 0 and (time.time() - t_start) >= params.duration_s:
                    break

                frames = pipeline.wait_for_frames()
                aligned = align.process(frames)

                depth_frame = aligned.get_depth_frame()
                color_frame = aligned.get_color_frame()
                if not depth_frame or not color_frame:
                    continue

                depth_img = np.asanyarray(depth_frame.get_data())
                color_img = np.asanyarray(color_frame.get_data())

                cv2.imwrite(os.path.join(self.out_dir, "rgb",   f"{i}.png"), color_img)
                cv2.imwrite(os.path.join(self.out_dir, "depth", f"{i}.png"), depth_img)

                i += 1
                on_progress(i, total_estimate or i)

            return i
        finally:
            try:
                pipeline.stop()
            except Exception:
                pass

    # ---------------------------------------------------------------- helpers
    def _save_intrinsics(self, profile, rs) -> None:
        """Mirror the stakeholder format for kdc_intrinsics.txt + kd_intrinsics.txt."""
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
                print(f"[realsense_capture] WARNING: failed to save {fname}: {e}")

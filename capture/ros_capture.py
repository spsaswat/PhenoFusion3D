"""
capture/ros_capture.py
----------------------
ROS + RealSense + gantry capture backend.

Thin adapter around the gantry control script
`rospy_thread_fin_1.py`. The capture loop, ROS
topics, velocity command, and intrinsics save logic are kept identical
to the working stakeholder script -- we only:

  - wrap them in a class so the QThread worker can drive them
  - import rospy / pyrealsense2 / cv2 lazily so this module is importable on
    Windows (where ROS is unavailable) without OpenCV until the ROS backend runs
  - parameterise velocity / end position / FPS / serial number
  - buffer copied frames while the gantry moves, then write to our standard
    output layout only after camera acquisition and gantry motion have stopped
        <out>/rgb/<idx>.png, <out>/depth/<idx>.png
        <out>/kdc_intrinsics.txt, <out>/kd_intrinsics.txt
        <out>/session.json   (records frame_idx -> gantry position)

The frame->position map in session.json preserves per-frame gantry
positions (which are lost when we rename frames to 0.png, 1.png, ...)
and unlocks exact known-pose reconstruction downstream.
"""

from __future__ import annotations

import math
import time
from typing import Callable

from capture.base import (
    CaptureBackend,
    CaptureParams,
    MILLIMETRES_PER_METRE,
    capture_buffer_limit_bytes,
    ensure_capture_capacity,
)
from capture.realsense_runtime import import_realsense
from capture.ros_runtime import ros_is_installed


def ros_available() -> bool:
    """True when ROS is installed on the machine, independent of the UI venv."""
    return ros_is_installed()


class RosCapture(CaptureBackend):
    name = "ros"
    STALL_TIMEOUT_S = 5.0
    POSITION_PROGRESS_EPSILON_M = 0.0001
    HOME_TIMEOUT_S = 15.0
    HOME_TOLERANCE_M = 0.01

    def __init__(self, serial_number: str | None = None):
        super().__init__()
        self.serial_number = serial_number
        self._gantry = None

    def stop(self) -> None:
        """Request capture shutdown and stop ROS motion immediately."""
        super().stop()
        gantry = self._gantry
        if gantry is not None:
            try:
                gantry.stop_moving()
            except Exception:
                pass

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
        from capture.ros_client import HOME_POSITION_M, RosAgentClient
        from capture.realsense_capture import CaptureFrameBuffer, RealSenseCapture

        rs = import_realsense()
        try:
            import cv2
        except ImportError as e:
            raise RuntimeError(
                "opencv-python is required for the ROS capture backend. "
                "Install with 'pip install opencv-python' or "
                "'opencv-python-headless'."
            ) from e
        self._cv2 = cv2

        # Use the same dynamic device selection and profile fallback as the
        # camera-only backend. Serial selection remains optional and may be
        # supplied through PHENOFUSION_CAMERA_SERIAL.
        camera = RealSenseCapture(serial_number=self.serial_number)
        camera.session = self.session
        camera.out_dir = self.out_dir
        device = camera._select_device(rs)
        pipeline = rs.pipeline()
        profile, color_format = camera._start_pipeline(
            pipeline, device, rs, params
        )
        align = rs.align(rs.stream.color)
        gantry = None
        frame_buffer = None
        endpoint_reached = False
        buffer_limit_reached = False
        motion_started = False

        try:
            try:
                camera._apply_visual_preset(profile, rs)
                camera._update_session_from_profile(profile, rs)
                intrinsics = camera._read_intrinsics(profile, rs)

                actual_width = (
                    self.session.width if self.session is not None else params.width
                )
                actual_height = (
                    self.session.height if self.session is not None else params.height
                )
                actual_fps = (
                    self.session.fps if self.session is not None else params.fps
                )
                buffer_limit = capture_buffer_limit_bytes(
                    self.out_dir, params.max_buffer_gib
                )
                frame_buffer = CaptureFrameBuffer(buffer_limit)

                # Warm-up (matches stakeholder)
                for _ in range(camera.WARMUP_FRAMES):
                    pipeline.wait_for_frames()

                # ------------------ ROS gantry helper ----------------------
                self._current_position = 0.0

                def update_position(position_m):
                    self._current_position = position_m
                    self._report_position(position_m)

                gantry = RosAgentClient(on_position=update_position)
                self._gantry = gantry
                gantry.start()
                if not gantry.wait_for_position(8.0):
                    raise RuntimeError(
                        "ROS is connected, but the gantry driver did not publish "
                        "/joint_states within 8 seconds. Start the gantry driver "
                        "before capture."
                    )
                if params.velocity_mps <= 0:
                    raise RuntimeError("Gantry capture velocity must be positive.")
                if self._current_position >= params.end_position_m:
                    raise RuntimeError(
                        "Gantry is already at "
                        f"{self._current_position * MILLIMETRES_PER_METRE:.1f} "
                        "mm, at or beyond the "
                        f"{params.end_position_m * MILLIMETRES_PER_METRE:.1f} "
                        "mm capture "
                        "endpoint. Return it home before starting another pass."
                    )

                travel_s = (
                    params.end_position_m - self._current_position
                ) / params.velocity_mps
                estimated_frames = math.ceil(travel_s * actual_fps)
                buffer_limit = ensure_capture_capacity(
                    self.out_dir,
                    params,
                    estimated_frames,
                    actual_width,
                    actual_height,
                )
                frame_buffer.limit_bytes = min(
                    frame_buffer.limit_bytes, buffer_limit
                )

                # ------------------ capture loop ---------------------------
                i = 0
                last_progress_position = self._current_position
                last_progress_at = time.monotonic()
                while gantry.is_running() and not self._stop_flag:
                    position = self._current_position
                    if position >= params.end_position_m:
                        endpoint_reached = True
                        break
                    if (
                        position
                        >= last_progress_position
                        + self.POSITION_PROGRESS_EPSILON_M
                    ):
                        last_progress_position = position
                        last_progress_at = time.monotonic()
                    elif time.monotonic() - last_progress_at >= self.STALL_TIMEOUT_S:
                        raise RuntimeError(
                            "Gantry position did not advance for "
                            f"{self.STALL_TIMEOUT_S:.0f} seconds; capture was "
                            "stopped before the frame buffer could grow without bound."
                        )

                    gantry.start_moving(params.velocity_mps)
                    motion_started = True
                    for _ in range(2):
                        frame_pair = self._capture_one(
                            pipeline, align, color_format, rs
                        )
                        if frame_pair is not None:
                            if not frame_buffer.append(frame_pair):
                                buffer_limit_reached = True
                                if self.session is not None:
                                    self.session.termination_reason = "buffer_limit"
                                break
                            self._record_position(i, self._current_position)
                            i += 1
                            on_progress(i, 0)  # unknown total -> 0
                        if self._current_position >= params.end_position_m:
                            endpoint_reached = True
                            break
                    if endpoint_reached or buffer_limit_reached:
                        break

                if not self._stop_flag and not gantry.is_running():
                    raise RuntimeError(
                        "The ROS gantry helper stopped during capture."
                    )
                if self.session is not None:
                    if endpoint_reached:
                        self.session.termination_reason = "endpoint_reached"
                    elif self._stop_flag:
                        self.session.termination_reason = "user_stop"
            finally:
                if gantry is not None:
                    try:
                        gantry.stop_moving()
                    except Exception:
                        pass
                try:
                    pipeline.stop()
                except Exception:
                    pass
                if (
                    gantry is not None
                    and motion_started
                    and not self._stop_flag
                ):
                    home_returned = self._return_home_safely(
                        gantry, HOME_POSITION_M
                    )
                    if self.session is not None:
                        self.session.home_returned = home_returned
                        if endpoint_reached and not home_returned:
                            self.session.termination_reason = (
                                "endpoint_reached_home_failed"
                            )

            from capture.realsense_capture import (
                remove_frame_batch,
                write_frame_batch,
            )

            frame_pairs = frame_buffer.frames
            frame_count = len(frame_pairs)
            on_progress(frame_count, -1)  # acquisition done; saving batch
            write_frame_batch(
                self.out_dir, frame_pairs, cv2_module=self._cv2
            )
            try:
                camera._save_intrinsics(intrinsics)
            except Exception:
                remove_frame_batch(self.out_dir, range(frame_count))
                raise

            return frame_count
        finally:
            if gantry is not None:
                gantry.shutdown()
            self._gantry = None

    # ------------------------------------------------------------------ I/O
    def _capture_one(self, pipeline, align, color_format, rs):
        from capture.realsense_capture import capture_frame_pair

        return capture_frame_pair(
            pipeline,
            align,
            color_format,
            rs,
            cv2_module=self._cv2,
        )

    def _return_home(self, gantry, home_position_m: float) -> bool:
        """Send the go-home command and bound the wait for arrival."""
        if gantry.go_home() is False:
            gantry.stop_moving()
            return False
        deadline = time.monotonic() + self.HOME_TIMEOUT_S
        while gantry.is_running() and not self._stop_flag:
            if abs(self._current_position - home_position_m) <= self.HOME_TOLERANCE_M:
                return True
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        gantry.stop_moving()
        return False

    def _return_home_safely(self, gantry, home_position_m: float) -> bool:
        """Attempt Home without masking an acquisition or persistence error."""
        try:
            return self._return_home(gantry, home_position_m)
        except Exception:
            try:
                gantry.stop_moving()
            except Exception:
                pass
            return False

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

When exactly one D405 and one L515 are connected (and no serial is
requested), the D405 scans out to the endpoint as above, and the L515 then
scans the trip back home. That return pass is buffered the same way and
saved once the gantry is home, as its own dataset in the RETURN_DIR_NAME
subfolder of the capture.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Callable

from capture.base import (
    CaptureBackend,
    CaptureParams,
    MILLIMETRES_PER_METRE,
    RETURN_DIR_NAME,
    ReturnPassSession,
    ensure_free_storage,
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
        ensure_free_storage(self.out_dir)

        # Camera packages stay in the GUI venv. ROS runs under the lab's
        # existing compatible interpreter through RosAgentClient.
        from capture.ros_client import HOME_POSITION_M, RosAgentClient
        from capture.realsense_capture import RealSenseCapture

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
        return_camera = camera._pair_return_camera(rs)
        camera.session = self.session
        camera.out_dir = self.out_dir
        device = camera._select_device(rs)
        pipeline = rs.pipeline()
        profile, color_format = camera._start_pipeline(
            pipeline, device, rs, params
        )
        align = rs.align(rs.stream.color)
        gantry = None
        frame_pairs = []
        endpoint_reached = False
        motion_started = False
        home_returned = None

        try:
            try:
                camera._apply_visual_preset(profile, rs)
                camera._update_session_from_profile(profile, rs)
                intrinsics = camera._read_intrinsics(profile, rs)

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
                            frame_pairs.append(frame_pair)
                            self._record_position(i, self._current_position)
                            i += 1
                            on_progress(i, 0)  # unknown total -> 0
                        if self._current_position >= params.end_position_m:
                            endpoint_reached = True
                            break
                    if endpoint_reached:
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

            from capture.realsense_capture import (
                remove_frame_batch,
                write_frame_batch,
            )

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

            # The forward pass is on disk; the return camera scans the trip
            # back. Its written frames were released by write_frame_batch.
            if (
                return_camera is not None
                and motion_started
                and not self._stop_flag
            ):
                # Persist the forward positions now rather than only after
                # the return pass, so a crash on the way back cannot lose them.
                if self.session is not None:
                    self.session.n_frames = frame_count
                self._write_session()
                home_returned = self._return_with_camera(
                    rs,
                    return_camera,
                    gantry,
                    params,
                    on_progress,
                    HOME_POSITION_M,
                )
                self._record_home(home_returned, endpoint_reached)

            return frame_count
        finally:
            # Returning Home belongs after the buffered image and intrinsics
            # save attempt. Keeping it in this outer cleanup also guarantees
            # that acquisition or persistence failures cannot skip Home.
            if (
                gantry is not None
                and motion_started
                and not self._stop_flag
                and home_returned is None
            ):
                home_returned = self._return_home_safely(
                    gantry, HOME_POSITION_M
                )
                self._record_home(home_returned, endpoint_reached)
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

    def _record_home(self, home_returned: bool, endpoint_reached: bool) -> None:
        if self.session is not None:
            self.session.home_returned = home_returned
            if endpoint_reached and not home_returned:
                self.session.termination_reason = "endpoint_reached_home_failed"

    # ------------------------------------------------------- return pass
    def _return_with_camera(
        self,
        rs,
        camera,
        gantry,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
        home_position_m: float,
    ) -> bool:
        """Scan the trip home with ``camera`` and save it once home.

        The forward pass is already on disk, so a failure here is recorded in
        the return pass's own session.json rather than failing the capture.
        Returns whether the gantry confirmed its arrival home.
        """
        from capture.realsense_capture import (
            remove_frame_batch,
            write_frame_batch,
        )

        out_dir = os.path.join(self.out_dir, RETURN_DIR_NAME)
        session = ReturnPassSession(
            backend=self.name,
            started_at=datetime.now().isoformat(timespec="seconds"),
            width=params.width,
            height=params.height,
            fps=params.fps,
            velocity_mps=params.velocity_mps,
            gantry_axis=params.gantry_axis,
            end_position_m=home_position_m,
        )
        camera.out_dir = out_dir
        camera.session = session
        on_progress(0, 0)  # acquiring again: the forward save has finished

        pipeline = None
        frame_pairs = []
        intrinsics = None
        home_returned = False
        try:
            for path in (
                out_dir,
                os.path.join(out_dir, "rgb"),
                os.path.join(out_dir, "depth"),
            ):
                os.mkdir(path)
            if not gantry.goto_available:
                raise RuntimeError(
                    "The return pass needs go-to from position_controller_ros. "
                    "Source the gantry catkin workspace before launching."
                )
            ensure_free_storage(out_dir)

            device = camera._select_device(rs)
            session.camera = camera._device_label(device, rs)
            pipeline = rs.pipeline()
            profile, color_format = camera._start_pipeline(
                pipeline, device, rs, params
            )
            align = rs.align(rs.stream.color)
            camera._apply_visual_preset(profile, rs)
            camera._update_session_from_profile(profile, rs)
            try:
                session.depth_scale_m = float(
                    profile.get_device().first_depth_sensor().get_depth_scale()
                )
            except Exception:
                pass
            intrinsics = camera._read_intrinsics(profile, rs)
            for _ in range(camera.WARMUP_FRAMES):
                pipeline.wait_for_frames()

            # Travel home at the scan velocity so the return pass is sampled
            # as densely as the forward one. A stop during camera start-up
            # must not be followed by motion.
            if not self._stop_flag and not gantry.goto(
                home_position_m, params.velocity_mps
            ):
                raise RuntimeError("ROS gantry helper is not running")

            i = 0
            last_progress_position = self._current_position
            last_progress_at = time.monotonic()
            while not self._stop_flag:
                position = self._current_position
                if abs(position - home_position_m) <= self.HOME_TOLERANCE_M:
                    home_returned = True
                    break
                if not gantry.is_running():
                    raise RuntimeError(
                        "The ROS gantry helper stopped during the return pass."
                    )
                if (
                    position
                    <= last_progress_position
                    - self.POSITION_PROGRESS_EPSILON_M
                ):
                    last_progress_position = position
                    last_progress_at = time.monotonic()
                elif time.monotonic() - last_progress_at >= self.STALL_TIMEOUT_S:
                    raise RuntimeError(
                        "Gantry position did not move toward home for "
                        f"{self.STALL_TIMEOUT_S:.0f} seconds during the "
                        "return pass."
                    )

                frame_pair = self._capture_one(pipeline, align, color_format, rs)
                if frame_pair is None:
                    continue
                frame_pairs.append(frame_pair)
                camera._record_position(i, self._current_position)
                i += 1
                on_progress(i, 0)  # unknown total -> 0
        except Exception as exc:
            session.error = str(exc) or type(exc).__name__
        finally:
            if pipeline is not None:
                try:
                    pipeline.stop()
                except Exception:
                    pass

        if self._stop_flag:
            # stop() may have raced the go-to above; repeat it after the go-to.
            try:
                gantry.stop_moving()
            except Exception:
                pass
        elif not home_returned:
            # Camera failure or stall: finish the trip with the proven
            # go-home, as the forward pass does after a failure.
            home_returned = self._return_home_safely(gantry, home_position_m)

        if session.error is not None:
            session.termination_reason = "failed"
        elif self._stop_flag:
            session.termination_reason = "user_stop"
        elif session.termination_reason == "completed":
            session.termination_reason = "home_reached"
        session.home_returned = home_returned

        # Back at the starting place: save the return pass.
        frame_count = len(frame_pairs)
        if frame_count:
            on_progress(frame_count, -1)  # acquisition done; saving batch
            try:
                write_frame_batch(out_dir, frame_pairs, cv2_module=self._cv2)
                try:
                    camera._save_intrinsics(intrinsics)
                except Exception:
                    remove_frame_batch(out_dir, range(frame_count))
                    raise
            except Exception as exc:
                frame_count = 0
                session.termination_reason = "failed"
                session.error = "; ".join(
                    message
                    for message in (
                        session.error, str(exc) or type(exc).__name__
                    )
                    if message
                )
        session.n_frames = frame_count

        try:
            camera._write_session()
        except Exception as exc:
            print(
                f"[ros_capture] WARNING: could not write the return pass "
                f"session in {out_dir!r}: {exc}"
            )
        return home_returned

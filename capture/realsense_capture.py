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
from capture.realsense_runtime import import_realsense


def write_frame_pair(
    out_dir: str,
    idx: int,
    color_img,
    depth_img,
    cv2_module=cv2,
) -> None:
    """Write one RGB/depth pair, or leave no files for this frame index."""
    rgb_path = os.path.join(out_dir, "rgb", f"{idx}.png")
    depth_path = os.path.join(out_dir, "depth", f"{idx}.png")
    # Keep temporary images outside rgb/ and depth/ so an interrupted capture
    # cannot make a loader mistake an unfinished write for a real frame.
    rgb_temp = os.path.join(out_dir, f".{idx}.rgb.part.png")
    depth_temp = os.path.join(out_dir, f".{idx}.depth.part.png")

    def remove_files(paths) -> None:
        for path in paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                # Preserve the original write/rename error reported below.
                pass

    try:
        rgb_ok = bool(cv2_module.imwrite(rgb_temp, color_img))
        depth_ok = bool(cv2_module.imwrite(depth_temp, depth_img))
    except Exception as exc:
        remove_files((rgb_temp, depth_temp))
        raise RuntimeError(
            f"Failed to save RGB/depth frame {idx}. No frame was counted. "
            f"Check write permissions and free disk space in {out_dir!r}."
        ) from exc

    if not rgb_ok or not depth_ok:
        remove_files((rgb_temp, depth_temp))
        failed = []
        if not rgb_ok:
            failed.append("RGB")
        if not depth_ok:
            failed.append("depth")
        raise RuntimeError(
            f"Failed to save {' and '.join(failed)} image for frame {idx}. "
            f"No frame was counted and the incomplete pair was removed. "
            f"Check write permissions and free disk space in {out_dir!r}."
        )

    promoted = []
    try:
        os.replace(rgb_temp, rgb_path)
        promoted.append(rgb_path)
        os.replace(depth_temp, depth_path)
        promoted.append(depth_path)
    except OSError as exc:
        remove_files((rgb_temp, depth_temp, *promoted))
        raise RuntimeError(
            f"Failed to finalize RGB/depth frame {idx}. No frame was counted "
            f"and the incomplete pair was removed. Check write permissions "
            f"and free disk space in {out_dir!r}."
        ) from exc


class RealSenseCapture(CaptureBackend):
    name = "realsense"

    def __init__(self, serial_number: str | None = None):
        super().__init__()
        configured = (
            serial_number
            if serial_number is not None
            else os.environ.get("PHENOFUSION_CAMERA_SERIAL")
        )
        self.serial_number = str(configured).strip() if configured else None

    def _run(
        self,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
    ) -> int:
        rs = import_realsense()

        device = self._select_device(rs)
        pipeline = rs.pipeline()
        profile, color_format = self._start_pipeline(pipeline, device, rs, params)

        try:
            self._apply_visual_preset(profile, rs)

            # Save actual stream metadata and intrinsics from the selected profile.
            self._update_session_from_profile(profile, rs)
            self._save_intrinsics(profile, rs)

            # Align depth to color (same as stakeholder)
            align = rs.align(rs.stream.color)

            # Warm-up
            for _ in range(5):
                pipeline.wait_for_frames()

            # Estimate total frames for progress reporting
            actual_fps = self.session.fps if self.session is not None else params.fps
            total_estimate = int(params.duration_s * actual_fps) if params.duration_s > 0 else 0
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
                if color_format == rs.format.rgb8:
                    color_img = cv2.cvtColor(color_img, cv2.COLOR_RGB2BGR)

                write_frame_pair(self.out_dir, i, color_img, depth_img)

                i += 1
                on_progress(i, total_estimate or i)

            return i
        finally:
            try:
                pipeline.stop()
            except Exception:
                pass

    # ---------------------------------------------------------------- helpers
    def _select_device(self, rs):
        """Select one connected RGB-D camera without assuming its serial."""
        ctx = rs.context()
        devices = list(ctx.query_devices())
        if not devices:
            raise RuntimeError(
                "No Intel RealSense camera was found by pyrealsense2/librealsense. "
                "PhenoFusion3D asks the Intel RealSense SDK for RGB-D devices "
                "directly, not ordinary webcam indexes. Open Intel RealSense "
                "Viewer and confirm the camera appears with a depth stream. If "
                "it does not, install/reinstall Intel RealSense SDK 2.0/runtime, "
                "reconnect the camera on a USB 3 port, then restart this app."
            )

        rgbd_devices = [
            device for device in devices
            if self._has_stream(device, rs, rs.stream.color)
            and self._has_stream(device, rs, rs.stream.depth)
        ]
        if not rgbd_devices:
            found = ", ".join(self._device_label(device, rs) for device in devices)
            raise RuntimeError(
                "A camera device was detected, but not as an RGB-D RealSense "
                f"device with both color and depth streams. Found: {found}. "
                "The capture backend needs the RealSense depth interface, not "
                "only the RGB webcam interface."
            )

        if self.serial_number:
            for device in rgbd_devices:
                if self._device_serial(device, rs) == self.serial_number:
                    return device
            available = ", ".join(
                self._device_label(device, rs) for device in rgbd_devices
            ) or "none"
            raise RuntimeError(
                "The requested RealSense camera serial "
                f"{self.serial_number!r} was not found as an RGB-D device. "
                f"Available RGB-D devices: {available}. Check "
                "PHENOFUSION_CAMERA_SERIAL or reconnect the camera."
            )

        if len(rgbd_devices) == 1:
            return rgbd_devices[0]

        choices = "\n".join(
            f"  - {self._device_label(device, rs)}" for device in rgbd_devices
        )
        raise RuntimeError(
            "Multiple RGB-D RealSense cameras are connected. Set "
            "PHENOFUSION_CAMERA_SERIAL to the serial of the camera to use:\n"
            f"{choices}"
        )

    def _start_pipeline(self, pipeline, device, rs, params: CaptureParams):
        serial = self._device_serial(device, rs)

        config = rs.config()
        if serial:
            config.enable_device(serial)
        config.enable_stream(
            rs.stream.color, params.width, params.height, rs.format.bgr8, params.fps
        )
        config.enable_stream(
            rs.stream.depth, params.width, params.height, rs.format.z16, params.fps
        )

        try:
            return pipeline.start(config), rs.format.bgr8
        except RuntimeError as first_error:
            fallback = rs.config()
            if serial:
                fallback.enable_device(serial)
            color_profile = self._choose_video_profile(
                device, rs, rs.stream.color, params, [rs.format.bgr8, rs.format.rgb8]
            )
            depth_profile = self._choose_video_profile(
                device, rs, rs.stream.depth, params, [rs.format.z16]
            )

            if color_profile is None or depth_profile is None:
                raise RuntimeError(
                    "The RealSense camera was detected, but no compatible "
                    "color/depth stream profiles were exposed. "
                    f"Device: {self._device_label(device, rs)}. "
                    f"Original error: {first_error}"
                ) from first_error

            color_vsp = color_profile.as_video_stream_profile()
            depth_vsp = depth_profile.as_video_stream_profile()
            color_format = color_profile.format()

            fallback.enable_stream(
                rs.stream.color,
                color_vsp.width(),
                color_vsp.height(),
                color_format,
                color_profile.fps(),
            )
            fallback.enable_stream(
                rs.stream.depth,
                depth_vsp.width(),
                depth_vsp.height(),
                depth_profile.format(),
                depth_profile.fps(),
            )

            try:
                return pipeline.start(fallback), color_format
            except RuntimeError as fallback_error:
                raise RuntimeError(
                    "The RealSense camera was detected, but capture could not "
                    "start. Close Intel RealSense Viewer, Teams/Zoom, and any "
                    "other app using the camera, then try again. "
                    f"Device: {self._device_label(device, rs)}. "
                    f"Requested: {params.width}x{params.height}@{params.fps}. "
                    f"Original error: {first_error}. "
                    f"Fallback error: {fallback_error}"
                ) from fallback_error

    def _choose_video_profile(self, device, rs, stream, params: CaptureParams, formats):
        candidates = []
        for sensor in device.query_sensors():
            for profile in sensor.get_stream_profiles():
                if profile.stream_type() != stream or profile.format() not in formats:
                    continue
                try:
                    vsp = profile.as_video_stream_profile()
                except RuntimeError:
                    continue
                candidates.append((profile, vsp))

        if not candidates:
            return None

        def score(item):
            profile, vsp = item
            format_rank = formats.index(profile.format())
            resolution_delta = abs(vsp.width() - params.width) + abs(vsp.height() - params.height)
            fps_delta = abs(profile.fps() - params.fps)
            lower_than_requested = int(vsp.width() < params.width or vsp.height() < params.height)
            return (format_rank, resolution_delta, fps_delta, lower_than_requested)

        return min(candidates, key=score)[0]

    def _has_stream(self, device, rs, stream) -> bool:
        return self._choose_video_profile(
            device,
            rs,
            stream,
            CaptureParams(),
            [rs.format.bgr8, rs.format.rgb8] if stream == rs.stream.color else [rs.format.z16],
        ) is not None

    def _update_session_from_profile(self, profile, rs) -> None:
        if self.session is None:
            return
        try:
            vsp = rs.video_stream_profile(profile.get_stream(rs.stream.color))
            intr = vsp.get_intrinsics()
            self.session.width = int(intr.width)
            self.session.height = int(intr.height)
            self.session.fps = int(vsp.fps())
        except Exception:
            pass

    def _device_serial(self, device, rs) -> str:
        try:
            if device.supports(rs.camera_info.serial_number):
                return device.get_info(rs.camera_info.serial_number)
        except Exception:
            pass
        return ""

    def _device_label(self, device, rs) -> str:
        def info(kind, default: str) -> str:
            try:
                if device.supports(kind):
                    return device.get_info(kind)
            except Exception:
                pass
            return default

        name = info(rs.camera_info.name, "Unknown RealSense")
        serial = info(rs.camera_info.serial_number, "no serial")
        return f"{name} ({serial})"

    def _apply_visual_preset(self, profile, rs) -> None:
        """Apply the stakeholder preset appropriate for the detected model."""
        device = profile.get_device()
        name = self._device_name(device, rs).upper()
        preset = 5 if "L515" in name else 4
        try:
            device.first_depth_sensor().set_option(
                rs.option.visual_preset, preset
            )
        except Exception as exc:
            print(
                f"[realsense_capture] WARNING: could not apply preset "
                f"{preset} to {self._device_label(device, rs)}: {exc}"
            )

    def _device_name(self, device, rs) -> str:
        try:
            if device.supports(rs.camera_info.name):
                return device.get_info(rs.camera_info.name)
        except Exception:
            pass
        return "Unknown RealSense"

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

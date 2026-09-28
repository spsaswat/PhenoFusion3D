"""
capture/distance_probe.py
-------------------------
Grab a handful of depth frames for the sole purpose of measuring distance.

This is a read-only probe. It selects the camera and negotiates a stream
profile with the existing ``RealSenseCapture`` helpers, reads the device's own
depth unit, copies a few aligned depth frames, then stops the pipeline. No
output directory, session file, PNG or gantry command is produced, so it is
safe to run while an operator is still positioning the rig.

Device selection, profile negotiation and the visual preset are reused from
the capture backend rather than reimplemented, so the probe cannot drift from
the settings a real capture will use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from capture.base import CaptureParams
from capture.realsense_capture import RealSenseCapture, capture_frame_pair
from capture.realsense_runtime import import_realsense


DEFAULT_PROBE_FRAMES = 10

# Frames the camera may fail to deliver before the probe gives up.
_MAX_ATTEMPTS_PER_FRAME = 5


@dataclass
class DepthProbe:
    """Depth frames and the metadata needed to interpret them."""

    frames: list = field(default_factory=list)
    depth_scale_units_per_m: float = 0.0
    camera_model: str = ''
    width: int = 0
    height: int = 0


def depth_scale_units_per_m(profile, rs) -> float:
    """
    Read raw depth units per metre from the active device.

    librealsense reports metres per unit; distance is meaningless without it,
    so a device that will not answer is an error rather than an assumed
    millimetre default. A D405 typically reports 0.0001 m per unit (10000
    units per metre); the L515 and D435 default to millimetres (1000).
    """
    try:
        metres_per_unit = float(
            profile.get_device().first_depth_sensor().get_depth_scale()
        )
    except Exception as exc:
        raise RuntimeError(
            'The camera did not report its depth scale, so capture distance '
            f'cannot be converted to metres: {exc}'
        ) from exc

    if not math.isfinite(metres_per_unit) or metres_per_unit <= 0.0:
        raise RuntimeError(
            'The camera reported an unusable depth scale '
            f'({metres_per_unit!r} m per unit), so capture distance cannot be '
            'converted to metres.'
        )
    return 1.0 / metres_per_unit


def probe_depth_frames(
    n_frames: int = DEFAULT_PROBE_FRAMES,
    *,
    serial_number: str | None = None,
    params: CaptureParams | None = None,
    should_stop=None,
) -> DepthProbe:
    """
    Open the camera briefly and return depth frames plus their depth scale.

    Args:
        n_frames      : depth frames to keep after the warm-up
        serial_number : specific camera, or None to use the same selection
                        rules as capture (one RGB-D device, or
                        PHENOFUSION_CAMERA_SERIAL when several are attached)
        params        : stream settings, or None for the capture defaults
        should_stop   : optional callable checked between frames. A frame
                        request can block for the driver's own timeout, so
                        cancellation takes effect at the next frame boundary
                        rather than instantly.

    Returns:
        DepthProbe
    """
    if n_frames < 1:
        raise ValueError(f'n_frames must be at least 1 (got {n_frames}).')

    cancelled = should_stop if should_stop is not None else (lambda: False)

    rs = import_realsense()
    backend = RealSenseCapture(serial_number=serial_number)
    settings = params if params is not None else CaptureParams()

    device = backend._select_device(rs)
    camera_model = backend._device_label(device, rs)

    pipeline = rs.pipeline()
    profile, color_format = backend._start_pipeline(pipeline, device, rs, settings)
    try:
        backend._apply_visual_preset(profile, rs)
        depth_scale = depth_scale_units_per_m(profile, rs)

        # Align depth to colour exactly as capture does, so the measured
        # distances describe the frames a capture would actually save.
        align = rs.align(rs.stream.color)

        for _ in range(RealSenseCapture.WARMUP_FRAMES):
            if cancelled():
                raise RuntimeError('The distance probe was cancelled.')
            pipeline.wait_for_frames()

        frames = []
        attempts = 0
        attempt_limit = n_frames * _MAX_ATTEMPTS_PER_FRAME
        while len(frames) < n_frames and attempts < attempt_limit:
            if cancelled():
                raise RuntimeError('The distance probe was cancelled.')
            attempts += 1
            frame_pair = capture_frame_pair(pipeline, align, color_format, rs)
            if frame_pair is None:
                continue
            frames.append(frame_pair[1])
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass

    if not frames:
        raise RuntimeError(
            f'{camera_model} was opened but delivered no aligned depth frames '
            f'in {attempt_limit} attempts. Nothing was captured or saved.'
        )

    frame_height, frame_width = frames[0].shape[:2]
    return DepthProbe(
        frames=frames,
        depth_scale_units_per_m=depth_scale,
        camera_model=camera_model,
        width=int(frame_width),
        height=int(frame_height),
    )

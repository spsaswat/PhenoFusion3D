"""
capture/base.py
---------------
Abstract base class for RGB-D capture backends.

Two concrete backends:
  - ros_capture.py        : Linux + ROS + gantry (lab machine)
  - realsense_capture.py  : Windows / camera-only (dev / sanity test)

Both write to the same on-disk layout so downstream loaders and the
reconstruction pipeline don't care which backend produced the data.
"""

from __future__ import annotations

import abc
import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Optional


GIB = 1024 ** 3
MILLIMETRES_PER_METRE = 1000.0
DEFAULT_END_POSITION_M = 1.65
# A capture refuses to start with less free space than this on its output
# disk: 1 GB, counted in 1024**3-byte units as `df -h` does.
MIN_FREE_STORAGE_BYTES = GIB


@dataclass
class CaptureParams:
    """User-tunable capture parameters."""
    # Output folder root (a timestamped subfolder is created inside)
    out_root: str = "data/captures"

    # Camera streaming
    width: int = 1280
    height: int = 720
    fps: int = 30

    # ROS / gantry only -- ignored by realsense backend
    velocity_mps: float = 0.038        # gantry linear X velocity (m/s)
    end_position_m: float = DEFAULT_END_POSITION_M
    gantry_axis: int = 0               # 0=X, 1=Y in camera frame

    # RealSense-only mode: capture for N seconds (-1 = manual stop)
    duration_s: float = 10.0

    # Naming -- always 0.png, 1.png, ... (matches load_image_pairs default)
    naming: str = "numeric"


@dataclass
class CaptureSession:
    """Metadata persisted alongside captured frames as session.json."""
    backend: str                       # "ros" or "realsense"
    started_at: str                    # ISO timestamp
    width: int
    height: int
    fps: int
    velocity_mps: float
    gantry_axis: int
    end_position_m: float
    n_frames: int = 0
    # frame_index (int) -> gantry position (metres) when available
    frame_positions: dict = field(default_factory=dict)
    termination_reason: str = "completed"
    home_returned: Optional[bool] = None


# Subfolder of a capture holding the L515 recording that follows the D405.
RETURN_DIR_NAME = "l515"


@dataclass
class ReturnPassSession(CaptureSession):
    """session.json of the L515 recording, naming its camera and any failure."""
    camera: str = ""
    error: Optional[str] = None
    # Metres per raw depth unit (the L515 default is 0.25 mm, not 1 mm).
    depth_scale_m: Optional[float] = None


class CaptureBackend(abc.ABC):
    """
    Abstract capture backend.

    Lifecycle:
        backend = SomeBackend()
        backend.start(params, on_progress, on_done, on_error, on_position)
        ...
        backend.stop()                   # request graceful halt
    """

    name: str = "base"

    def __init__(self):
        self._stop_flag = False
        self.session: Optional[CaptureSession] = None
        self.out_dir: Optional[str] = None
        self._position_callback: Optional[Callable[[float], None]] = None

    # ---- subclasses implement these ---------------------------------------
    @abc.abstractmethod
    def _run(
        self,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
    ) -> int:
        """Run the capture loop. Return total frames captured."""

    # ---- public API -------------------------------------------------------

    def start(
        self,
        params: CaptureParams,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_done: Optional[Callable[[str, int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_position: Optional[Callable[[float], None]] = None,
    ) -> Optional[str]:
        """
        Run the capture synchronously (the QThread worker takes care of
        running this off the UI thread). Returns the output directory or None
        on failure.
        """
        self._position_callback = on_position
        if self._stop_flag:
            message = "Capture was cancelled before camera startup completed."
            if on_error:
                on_error(message)
                return None
            raise RuntimeError(message)
        try:
            self.out_dir = self._make_out_dir(params.out_root)
            self.session = CaptureSession(
                backend=self.name,
                started_at=datetime.now().isoformat(timespec="seconds"),
                width=params.width,
                height=params.height,
                fps=params.fps,
                velocity_mps=params.velocity_mps,
                gantry_axis=params.gantry_axis,
                end_position_m=params.end_position_m,
            )

            n = self._run(params, on_progress or (lambda i, t: None))
            self.session.n_frames = n
            self._write_session()

            if on_done:
                on_done(self.out_dir, n)
            return self.out_dir
        except Exception as e:
            if on_error:
                on_error(str(e))
            else:
                raise
            return None

    def stop(self) -> None:
        self._stop_flag = True

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _make_out_dir(root: str) -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        os.makedirs(root, exist_ok=True)
        suffix = 0
        while True:
            name = ts if suffix == 0 else f"{ts}-{suffix}"
            out = os.path.join(root, name)
            try:
                os.mkdir(out)
                break
            except FileExistsError:
                suffix += 1
        os.mkdir(os.path.join(out, "rgb"))
        os.mkdir(os.path.join(out, "depth"))
        return out

    def _write_session(self) -> None:
        if self.out_dir is None or self.session is None:
            return
        path = os.path.join(self.out_dir, "session.json")
        temp_path = os.path.join(self.out_dir, ".session.json.part")
        try:
            with open(temp_path, "w") as f:
                json.dump(asdict(self.session), f, indent=2)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def _record_position(self, frame_idx: int, position_m: float) -> None:
        if self.session is not None:
            self.session.frame_positions[str(frame_idx)] = float(position_m)

    def _report_position(self, position_m: float) -> None:
        """Forward live gantry feedback when the backend provides it."""
        if self._position_callback is not None:
            self._position_callback(float(position_m))


def ensure_free_storage(out_dir: str) -> None:
    """Refuse a capture when its output disk has less than 1 GB free."""
    free = shutil.disk_usage(out_dir).free
    if free < MIN_FREE_STORAGE_BYTES:
        raise RuntimeError(
            f"Only {free / GIB:.2f} GB of storage is free for {out_dir!r}; "
            "a capture needs at least 1 GB. Free up space or choose another "
            "output folder."
        )

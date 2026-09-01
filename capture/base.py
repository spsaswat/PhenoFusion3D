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
import ctypes
import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Optional


GIB = 1024 ** 3
MILLIMETRES_PER_METRE = 1000.0
DEFAULT_MAX_BUFFER_GIB = 6.0
MEMORY_HEADROOM_FRACTION = 0.5
DISK_RESERVE_BYTES = 512 * 1024 ** 2
PNG_WORST_CASE_FACTOR = 1.1


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
    end_position_m: float = 1.64       # stop when current_position >= this
    gantry_axis: int = 0               # 0=X, 1=Y in camera frame

    # RealSense-only mode: capture for N seconds (-1 = manual stop)
    duration_s: float = 10.0

    # In-memory RGB/depth buffering ceiling. The effective limit can be lower
    # when the machine has less free RAM or output disk space.
    max_buffer_gib: float = DEFAULT_MAX_BUFFER_GIB

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


def _available_memory_bytes() -> Optional[int]:
    """Best-effort free-memory query using only the standard library."""
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.available_physical)
        except Exception:
            return None

    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def frame_pair_bytes(width: int, height: int) -> int:
    """Raw BGR8 plus z16 bytes for one aligned RGB/depth pair."""
    return int(width) * int(height) * 5


def capture_buffer_limit_bytes(out_dir: str, max_buffer_gib: float) -> int:
    """Return a conservative RAM/disk-backed raw-frame buffer ceiling."""
    if max_buffer_gib <= 0:
        raise RuntimeError("Capture buffer limit must be greater than zero.")
    configured = max(1, int(float(max_buffer_gib) * GIB))
    limits = [configured]

    available_memory = _available_memory_bytes()
    if available_memory is not None:
        limits.append(max(1, int(available_memory * MEMORY_HEADROOM_FRACTION)))

    disk_free = shutil.disk_usage(out_dir).free
    usable_disk = max(0, disk_free - DISK_RESERVE_BYTES)
    if usable_disk == 0:
        raise RuntimeError(
            "The output disk has less than the required 512 MiB safety reserve."
        )
    limits.append(max(1, int(usable_disk / PNG_WORST_CASE_FACTOR)))
    return min(limits)


def ensure_capture_capacity(
    out_dir: str,
    params: CaptureParams,
    frame_count: int,
    width: int,
    height: int,
) -> int:
    """Reject a requested capture that cannot safely fit in RAM and on disk."""
    limit = capture_buffer_limit_bytes(out_dir, params.max_buffer_gib)
    required = frame_pair_bytes(width, height) * max(0, int(frame_count))
    if required > limit:
        raise RuntimeError(
            "Capture settings require approximately "
            f"{required / GIB:.2f} GiB of raw RGB/depth buffering, but the "
            f"current safe RAM/disk limit is {limit / GIB:.2f} GiB. Reduce "
            "duration, FPS, resolution, end position, or gantry travel time."
        )
    return limit

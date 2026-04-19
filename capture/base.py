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
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Optional


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
    end_position_m: float = 0.78       # stop when current_position >= this
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


class CaptureBackend(abc.ABC):
    """
    Abstract capture backend.

    Lifecycle:
        backend = SomeBackend()
        backend.start(params, on_progress, on_done, on_error)
        ...
        backend.stop()                   # request graceful halt
    """

    name: str = "base"

    def __init__(self):
        self._stop_flag = False
        self.session: Optional[CaptureSession] = None
        self.out_dir: Optional[str] = None

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
    ) -> Optional[str]:
        """
        Run the capture synchronously (the QThread worker takes care of
        running this off the UI thread). Returns the output directory or None
        on failure.
        """
        self._stop_flag = False
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
        out = os.path.join(root, ts)
        os.makedirs(os.path.join(out, "rgb"), exist_ok=True)
        os.makedirs(os.path.join(out, "depth"), exist_ok=True)
        return out

    def _write_session(self) -> None:
        if self.out_dir is None or self.session is None:
            return
        path = os.path.join(self.out_dir, "session.json")
        with open(path, "w") as f:
            json.dump(asdict(self.session), f, indent=2)

    def _record_position(self, frame_idx: int, position_m: float) -> None:
        if self.session is not None:
            self.session.frame_positions[str(frame_idx)] = float(position_m)

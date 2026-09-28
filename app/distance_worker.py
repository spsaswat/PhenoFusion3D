"""
app/distance_worker.py
----------------------
QThread wrapping the capture-distance check.

Two modes:
    'camera'  -- probe the attached camera for a few depth frames
    'dataset' -- measure depth PNGs already saved on disk

Both keep the camera/disk work off the UI thread. Neither writes anything.
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from processing.capture_distance import (
    DistanceThresholds,
    evaluate_depth_directory,
    evaluate_depth_frames,
)


class DistanceWorker(QThread):

    status      = pyqtSignal(str)
    check_ready = pyqtSignal(object)        # DistanceCheck
    error       = pyqtSignal(str)

    def __init__(
        self,
        mode: str = 'camera',
        depth_dir: Optional[str] = None,
        depth_scale: float = 1000.0,
        n_frames: int = 10,
        thresholds: Optional[DistanceThresholds] = None,
        serial_number: Optional[str] = None,
    ):
        super().__init__()
        self.mode          = mode
        self.depth_dir     = depth_dir
        self.depth_scale   = depth_scale
        self.n_frames      = n_frames
        self.thresholds    = thresholds
        self.serial_number = serial_number
        self._stop_flag    = False

    def stop(self):
        """Ask the camera probe to finish at the next frame boundary."""
        self._stop_flag = True

    def run(self):
        try:
            if self.mode == 'camera':
                check = self._check_camera()
            elif self.mode == 'dataset':
                check = self._check_dataset()
            else:
                raise ValueError(
                    f'Unknown distance check mode: {self.mode!r} '
                    "(expected 'camera' or 'dataset')."
                )
            self.check_ready.emit(check)
        except Exception as e:
            self.error.emit(str(e))

    def _check_camera(self):
        # Imported here so a host without the RealSense SDK can still run the
        # dataset mode without the import failing at module load.
        from capture.distance_probe import probe_depth_frames

        self.status.emit('Reading depth frames from the camera...')
        probe = probe_depth_frames(
            self.n_frames,
            serial_number=self.serial_number,
            should_stop=lambda: self._stop_flag,
        )
        self.status.emit(f'Measuring distance from {probe.camera_model}...')
        return evaluate_depth_frames(
            probe.frames,
            probe.depth_scale_units_per_m,
            thresholds=self.thresholds,
            camera_model=probe.camera_model,
        )

    def _check_dataset(self):
        if not self.depth_dir:
            raise ValueError(
                'Select the depth folder of a recording before measuring its '
                'capture distance.'
            )
        self.status.emit(f'Measuring distance from {self.depth_dir}...')
        return evaluate_depth_directory(
            self.depth_dir,
            self.depth_scale,
            max_frames=self.n_frames,
            thresholds=self.thresholds,
        )

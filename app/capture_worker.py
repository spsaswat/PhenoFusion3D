"""
app/capture_worker.py
---------------------
QThread that drives a CaptureBackend off the UI thread.
"""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal

from capture import CaptureParams, get_backend


class CaptureWorker(QThread):

    frame_captured = pyqtSignal(int, int)        # idx, total_estimate (0=unknown)
    finished       = pyqtSignal(str, int)        # out_dir, n_frames
    error          = pyqtSignal(str)
    status         = pyqtSignal(str)

    def __init__(self, backend_pref: str, params: CaptureParams):
        super().__init__()
        self.backend_pref = backend_pref
        self.params       = params
        self._backend     = None

    def run(self):
        try:
            self._backend = get_backend(self.backend_pref)
            errors: list[str] = []
            out_dir = self._backend.start(
                self.params,
                on_progress=lambda i, t: self.frame_captured.emit(i, t),
                on_error=errors.append,
            )

            if out_dir is None and self.backend_pref.lower() == "auto" \
                    and self._backend.name == "ros":
                frame_count = (
                    getattr(self._backend, "frames_captured", None)
                    if getattr(self._backend, "frames_captured", None) is not None
                    else (
                        self._backend.session.n_frames
                        if self._backend.session is not None else 0
                    )
                )
                if frame_count == 0:
                    reason = errors[-1] if errors else "ROS capture did not start"
                    self.status.emit(
                        "ROS + Gantry unavailable; continuing with camera-only "
                        f"capture. {reason}"
                    )
                    self._backend = get_backend("realsense")
                    fallback_errors: list[str] = []
                    out_dir = self._backend.start(
                        self.params,
                        on_progress=lambda i, t: self.frame_captured.emit(i, t),
                        on_error=fallback_errors.append,
                    )
                    errors.extend(fallback_errors)

            if out_dir is None:
                self.error.emit(errors[-1] if errors else "Capture failed")
                return

            frame_count = (
                self._backend.session.n_frames
                if self._backend.session is not None else 0
            )
            self.finished.emit(out_dir, frame_count)
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        if self._backend is not None:
            self._backend.stop()

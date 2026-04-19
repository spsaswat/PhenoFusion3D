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

    def __init__(self, backend_pref: str, params: CaptureParams):
        super().__init__()
        self.backend_pref = backend_pref
        self.params       = params
        self._backend     = None

    def run(self):
        try:
            self._backend = get_backend(self.backend_pref)
            out_dir = self._backend.start(
                self.params,
                on_progress=lambda i, t: self.frame_captured.emit(i, t),
                on_done=lambda d, n: self.finished.emit(d, n),
                on_error=lambda msg: self.error.emit(msg),
            )
            # Note: on_done is called inside backend.start(); nothing else to do
            if out_dir is None:
                # error already emitted via on_error
                return
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        if self._backend is not None:
            self._backend.stop()

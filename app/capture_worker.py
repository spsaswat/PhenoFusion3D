"""
app/capture_worker.py
---------------------
QThread that drives a CaptureBackend off the UI thread.
"""

from __future__ import annotations

import threading

from PyQt5.QtCore import QThread, pyqtSignal

from capture import CaptureParams, get_backend


class CaptureWorker(QThread):

    # idx, total estimate: 0 = unknown capture length, -1 = saving batch
    frame_captured = pyqtSignal(int, int)
    gantry_position_changed = pyqtSignal(float)
    capture_finished = pyqtSignal(str, int)      # out_dir, n_frames
    error          = pyqtSignal(str)

    def __init__(self, backend_pref: str, params: CaptureParams):
        super().__init__()
        self.backend_pref = backend_pref
        self.params       = params
        self._backend     = None
        self._stop_requested = threading.Event()

    def run(self):
        try:
            self._backend = get_backend(self.backend_pref)
            if self._stop_requested.is_set():
                self._backend.stop()
            out_dir = self._backend.start(
                self.params,
                on_progress=lambda i, t: self.frame_captured.emit(i, t),
                on_done=lambda d, n: self.capture_finished.emit(d, n),
                on_error=lambda msg: self.error.emit(msg),
                on_position=lambda position: self.gantry_position_changed.emit(
                    position
                ),
            )
            # Note: on_done is called inside backend.start(); nothing else to do
            if out_dir is None:
                # error already emitted via on_error
                return
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._stop_requested.set()
        if self._backend is not None:
            self._backend.stop()

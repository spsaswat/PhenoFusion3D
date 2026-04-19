"""
app/quality_worker.py
---------------------
QThread wrapping processing.quality.{quick_check, full_report}.
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from processing.quality import QualityParams, quick_check, full_report


class QualityWorker(QThread):

    progress     = pyqtSignal(int, int)
    report_ready = pyqtSignal(object)        # QualityReport
    error        = pyqtSignal(str)

    def __init__(
        self,
        pairs,
        K,
        dist,
        params: QualityParams,
        mode: str = 'quick',
        n_samples: int = 15,
        out_dir: Optional[str] = None,
    ):
        super().__init__()
        self.pairs     = pairs
        self.K         = K
        self.dist      = dist
        self.params    = params
        self.mode      = mode
        self.n_samples = n_samples
        self.out_dir   = out_dir

    def run(self):
        try:
            if self.mode == 'full':
                report = full_report(
                    self.pairs, self.K, self.dist, self.params,
                    out_dir=self.out_dir,
                    on_progress=lambda i, t: self.progress.emit(i, t),
                )
            else:
                report = quick_check(
                    self.pairs, self.K, self.dist, self.params,
                    n_samples=self.n_samples,
                    on_progress=lambda i, t: self.progress.emit(i, t),
                )
            self.report_ready.emit(report)
        except Exception as e:
            self.error.emit(str(e))

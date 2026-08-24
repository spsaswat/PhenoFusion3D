"""
app/selftest_worker.py
----------------------
QThread wrapper around capture.selftest so the camera / gantry checks
never run on the Qt main thread. Both touch hardware SDKs that can block
for seconds at a time while holding the GIL.
"""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal


class SelfTestWorker(QThread):

    done  = pyqtSignal(object)      # SelfTestResult
    error = pyqtSignal(str)

    def __init__(self, subject: str):
        super().__init__()
        self.subject = subject      # "camera" or "gantry"

    def run(self):
        try:
            from capture.selftest import camera_self_test, gantry_self_test
            if self.subject == "camera":
                result = camera_self_test()
            elif self.subject == "gantry":
                result = gantry_self_test()
            else:
                raise ValueError(f"unknown self-test subject: {self.subject!r}")
            self.done.emit(result)
        except Exception as e:
            self.error.emit(str(e))

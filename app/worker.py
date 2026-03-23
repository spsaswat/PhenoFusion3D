from PyQt5.QtCore import QThread, pyqtSignal
from processing.reconstructor import Reconstructor


class ProcessingWorker(QThread):

    frame_done = pyqtSignal(int, int, object, float, float, str)
    finished   = pyqtSignal(object, list, list)
    error      = pyqtSignal(str)

    def __init__(self, pairs, K, dist, depth_scale=1000.0, save_path=None):
        super().__init__()
        self.pairs       = pairs
        self.K           = K
        self.dist        = dist
        self.depth_scale = depth_scale
        self.save_path   = save_path
        self._reconstructor = None

    def run(self):
        try:
            self._reconstructor = Reconstructor(
                pairs=self.pairs,
                K=self.K,
                dist=self.dist,
                depth_scale=self.depth_scale,
                save_path=self.save_path,
                on_frame=self._on_frame
            )
            final_pcd, succeed, fail = self._reconstructor.run()
            self.finished.emit(final_pcd, succeed, fail)
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        if self._reconstructor:
            self._reconstructor.stop()

    def _on_frame(self, idx, total, pcd, fitness, rmse, status):
        self.frame_done.emit(idx, total, pcd, fitness, rmse, status)
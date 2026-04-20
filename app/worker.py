from PyQt5.QtCore import QThread, pyqtSignal
from processing.reconstructor import Reconstructor


class ProcessingWorker(QThread):

    frame_done = pyqtSignal(int, int, object, float, float, str)
    finished   = pyqtSignal(object, list, list)
    error      = pyqtSignal(str)

    def __init__(
        self,
        pairs,
        K,
        dist,
        depth_scale=1000.0,
        depth_trunc=3.2,
        voxel_size=0.005,
        max_iter=50,
        bbox=None,
        gantry_step_m=0.0,
        gantry_axis=0,
        depth_min_mm=0,
        erode=False,
        inpaint=False,
        use_known_poses=False,
        tsdf_voxel_m=0.003,
        min_fitness=0.3,
        max_rmse=0.015,
        save_path=None,
        agent_config=None,
    ):
        super().__init__()
        self.pairs           = pairs
        self.K               = K
        self.dist            = dist
        self.depth_scale     = depth_scale
        self.depth_trunc     = depth_trunc
        self.voxel_size      = voxel_size
        self.max_iter        = max_iter
        self.bbox            = bbox
        self.gantry_step_m   = gantry_step_m
        self.gantry_axis     = gantry_axis
        self.depth_min_mm    = depth_min_mm
        self.erode           = erode
        self.inpaint         = inpaint
        self.use_known_poses = use_known_poses
        self.tsdf_voxel_m    = tsdf_voxel_m
        self.min_fitness     = min_fitness
        self.max_rmse        = max_rmse
        self.save_path       = save_path
        self.agent_config    = agent_config
        self._reconstructor  = None

    def run(self):
        try:
            self._reconstructor = Reconstructor(
                pairs=self.pairs,
                K=self.K,
                dist=self.dist,
                depth_scale=self.depth_scale,
                depth_trunc=self.depth_trunc,
                voxel_size=self.voxel_size,
                max_iter=self.max_iter,
                bbox=self.bbox,
                gantry_step_m=self.gantry_step_m,
                gantry_axis=self.gantry_axis,
                depth_min_mm=self.depth_min_mm,
                erode=self.erode,
                inpaint=self.inpaint,
                use_known_poses=self.use_known_poses,
                tsdf_voxel_m=self.tsdf_voxel_m,
                min_fitness=self.min_fitness,
                max_rmse=self.max_rmse,
                save_path=self.save_path,
                agent_config=self.agent_config,
                on_frame=self._on_frame,
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

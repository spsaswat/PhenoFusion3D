import os
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from file_io.loader   import load_image_pairs, load_intrinsics, get_default_intrinsics
from file_io.exporter import save_ply, save_metrics_csv
from app.worker       import ProcessingWorker
from app.capture_worker import CaptureWorker
from app.quality_worker import QualityWorker
from capture          import CaptureParams
from processing.quality import QualityParams, QualityThresholds
from visualiser.viewer import PointCloudViewer


# Strict reconstruction acceptance thresholds (match QualityThresholds defaults)
DEFAULT_MIN_FITNESS = 0.3
DEFAULT_MAX_RMSE    = 0.015


class Controller(QObject):

    status_changed         = pyqtSignal(str)
    frame_processed        = pyqtSignal(int, int, object, float, float, str)
    reconstruction_complete = pyqtSignal(object, list, list)
    error_occurred         = pyqtSignal(str)

    # Capture pipeline signals
    capture_progress = pyqtSignal(int, int)
    capture_complete = pyqtSignal(str, int)
    capture_error    = pyqtSignal(str)

    # Quality pipeline signals
    quality_progress = pyqtSignal(int, int)
    quality_ready    = pyqtSignal(object)
    quality_error    = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker          = None
        self.capture_worker  = None
        self.quality_worker  = None
        self.viewer          = PointCloudViewer()
        self.final_pcd       = None
        self.all_metrics     = []
        self.n_success       = 0
        self.n_fail          = 0

        # Last known DataPanel paths (refreshed before quality / reconstruction)
        self._last_rgb_dir   = None
        self._last_depth_dir = None
        self._last_intr_path = None

    # ---------------------------------------------------------------- run
    @pyqtSlot(str, str, str, int)
    def on_run_clicked(self, rgb_dir, depth_dir, intrinsics_path, step_size):
        self.n_success   = 0
        self.n_fail      = 0
        self.all_metrics = []
        self.final_pcd   = None

        try:
            pairs = load_image_pairs(rgb_dir, depth_dir, step=step_size)
        except Exception as e:
            self.error_occurred.emit(f'Failed to load images:\n{e}')
            return

        intr = load_intrinsics(intrinsics_path) if intrinsics_path else None
        if intr:
            K, dist, _, _ = intr
        else:
            K, dist = get_default_intrinsics()

        self._last_rgb_dir   = rgb_dir
        self._last_depth_dir = depth_dir
        self._last_intr_path = intrinsics_path

        self.status_changed.emit(f'Starting reconstruction: {len(pairs)} frames...')

        is_icl = 'icl' in rgb_dir.lower()

        depth_scale = 5000.0 if is_icl else 1000.0
        depth_trunc = 4.0    if is_icl else 4.0
        voxel_size  = 0.02   if is_icl else 0.005

        max_iter     = 30    if is_icl else 80
        bbox         = None  if is_icl else None
        erode        = True  if is_icl else False
        inpaint      = True  if is_icl else False
        depth_min_mm = 0     if is_icl else 0

        use_known_poses = False if is_icl else True
        gantry_axis     = 0
        per_frame_step  = 0.0 if is_icl else 0.00127
        gantry_step_m   = per_frame_step * step_size
        tsdf_voxel_m    = 0.003

        self.worker = ProcessingWorker(
            pairs=pairs, K=K, dist=dist,
            depth_scale=depth_scale,
            depth_trunc=depth_trunc,
            voxel_size=voxel_size,
            max_iter=max_iter,
            bbox=bbox,
            gantry_step_m=gantry_step_m,
            gantry_axis=gantry_axis,
            depth_min_mm=depth_min_mm,
            erode=erode,
            inpaint=inpaint,
            use_known_poses=use_known_poses,
            tsdf_voxel_m=tsdf_voxel_m,
            min_fitness=DEFAULT_MIN_FITNESS,
            max_rmse=DEFAULT_MAX_RMSE,
            save_path=os.path.join(os.path.dirname(rgb_dir), 'output')
        )
        self.worker.frame_done.connect(self._on_frame)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self.error_occurred)
        self.worker.start()
        self.viewer.start()

    @pyqtSlot()
    def on_stop_clicked(self):
        if self.worker:
            self.worker.stop()
        self.status_changed.emit('Stopping...')

    @pyqtSlot(int, int, object, float, float, str)
    def _on_frame(self, idx, total, pcd, fitness, rmse, status):
        if status == 'OK':
            self.n_success += 1
        else:
            self.n_fail += 1
        self.all_metrics.append({'frame': idx, 'status': status, 'fitness': fitness, 'rmse': rmse})
        self.viewer.update(pcd)
        self.frame_processed.emit(idx, total, pcd, fitness, rmse, status)
        self.status_changed.emit(f'Frame {idx + 1}/{total} | fitness={fitness:.4f}')

    @pyqtSlot(object, list, list)
    def _on_finished(self, final_pcd, succeed, fail):
        self.final_pcd = final_pcd
        self.status_changed.emit(
            f'Done. {len(succeed)} frames succeeded, {len(fail)} failed. '
            f'Use File menu to export.'
        )
        self.reconstruction_complete.emit(final_pcd, succeed, fail)

    # ---------------------------------------------------------------- capture
    @pyqtSlot(str, str, float, float, int, float)
    def on_capture_clicked(self, backend_pref, out_root, velocity_mps,
                           end_position_m, fps, duration_s):
        params = CaptureParams(
            out_root=out_root or 'data/captures',
            fps=fps,
            velocity_mps=velocity_mps,
            end_position_m=end_position_m,
            duration_s=duration_s,
        )
        self.status_changed.emit(f'Capture starting (backend={backend_pref})...')
        self.capture_worker = CaptureWorker(backend_pref, params)
        self.capture_worker.frame_captured.connect(self.capture_progress)
        self.capture_worker.finished.connect(self._on_capture_finished)
        self.capture_worker.error.connect(self._on_capture_error)
        self.capture_worker.start()

    @pyqtSlot()
    def on_capture_stop(self):
        if self.capture_worker:
            self.capture_worker.stop()
        self.status_changed.emit('Capture stop requested...')

    @pyqtSlot(str, int)
    def _on_capture_finished(self, out_dir, n_frames):
        rgb_dir   = os.path.join(out_dir, 'rgb')
        depth_dir = os.path.join(out_dir, 'depth')
        intr_path = os.path.join(out_dir, 'kdc_intrinsics.txt')
        if not os.path.exists(intr_path):
            intr_path = ''
        self._last_rgb_dir   = rgb_dir
        self._last_depth_dir = depth_dir
        self._last_intr_path = intr_path
        self.status_changed.emit(f'Capture done. {n_frames} frames -> {out_dir}')
        self.capture_complete.emit(out_dir, n_frames)

    @pyqtSlot(str)
    def _on_capture_error(self, msg):
        self.status_changed.emit(f'Capture error: {msg}')
        self.capture_error.emit(msg)

    # ---------------------------------------------------------------- quality
    def _build_quality_params(self, rgb_dir: str) -> QualityParams:
        is_icl = 'icl' in rgb_dir.lower()
        return QualityParams(
            depth_scale=5000.0 if is_icl else 1000.0,
            depth_trunc=4.0,
            voxel_size=0.02 if is_icl else 0.005,
            max_iter=30 if is_icl else 80,
            depth_min_mm=0,
            erode=is_icl,
            inpaint=is_icl,
            thresholds=QualityThresholds(),
        )

    @pyqtSlot(str, str, str, int)
    def on_quality_paths(self, rgb_dir, depth_dir, intrinsics_path, step_size):
        """Capture the most recent DataPanel state for use by Quick/Full check."""
        self._last_rgb_dir   = rgb_dir
        self._last_depth_dir = depth_dir
        self._last_intr_path = intrinsics_path

    def _ensure_paths(self) -> tuple | None:
        if not self._last_rgb_dir or not self._last_depth_dir:
            self.quality_error.emit('Set RGB and depth folders first.')
            return None
        try:
            pairs = load_image_pairs(self._last_rgb_dir, self._last_depth_dir, step=1)
        except Exception as e:
            self.quality_error.emit(f'Failed to load images: {e}')
            return None
        intr = load_intrinsics(self._last_intr_path) if self._last_intr_path else None
        if intr:
            K, dist, _, _ = intr
        else:
            K, dist = get_default_intrinsics()
        return pairs, K, dist

    @pyqtSlot()
    def on_quick_check_clicked(self):
        loaded = self._ensure_paths()
        if loaded is None:
            return
        pairs, K, dist = loaded
        params = self._build_quality_params(self._last_rgb_dir)
        self.status_changed.emit(f'Quick quality check on {len(pairs)} frames...')
        self.quality_worker = QualityWorker(pairs, K, dist, params, mode='quick', n_samples=15)
        self.quality_worker.progress.connect(self.quality_progress)
        self.quality_worker.report_ready.connect(self._on_quality_ready)
        self.quality_worker.error.connect(self._on_quality_error)
        self.quality_worker.start()

    @pyqtSlot()
    def on_full_report_clicked(self):
        loaded = self._ensure_paths()
        if loaded is None:
            return
        pairs, K, dist = loaded
        params = self._build_quality_params(self._last_rgb_dir)
        # Save report next to the dataset
        out_dir = os.path.dirname(self._last_rgb_dir)
        self.status_changed.emit(f'Full quality report on {len(pairs)} frames...')
        self.quality_worker = QualityWorker(
            pairs, K, dist, params, mode='full', out_dir=out_dir,
        )
        self.quality_worker.progress.connect(self.quality_progress)
        self.quality_worker.report_ready.connect(self._on_quality_ready)
        self.quality_worker.error.connect(self._on_quality_error)
        self.quality_worker.start()

    @pyqtSlot(object)
    def _on_quality_ready(self, report):
        self.status_changed.emit(
            f'Quality: {report.verdict} ({report.n_pairs_evaluated} pairs)'
        )
        self.quality_ready.emit(report)

    @pyqtSlot(str)
    def _on_quality_error(self, msg):
        self.status_changed.emit(f'Quality error: {msg}')
        self.quality_error.emit(msg)

    # ---------------------------------------------------------------- export
    def export_ply(self, path):
        if self.final_pcd:
            ok = save_ply(self.final_pcd, path)
            self.status_changed.emit(f'PLY saved: {path}' if ok else 'PLY export failed.')

    def export_csv(self, path):
        ok = save_metrics_csv(self.all_metrics, path)
        self.status_changed.emit(f'CSV saved: {path}' if ok else 'CSV export failed.')

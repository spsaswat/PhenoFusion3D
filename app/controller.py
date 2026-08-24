import os
from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot

from file_io.loader   import load_image_pairs, load_intrinsics, get_default_intrinsics
from app.capture_worker import CaptureWorker
from app.postprocess_worker import PostProcessWorker
from app.o3d_check    import open3d_usable
from capture          import CaptureParams
from capture.gantry   import GantryController

# NOTE: everything that (transitively) imports open3d -- ProcessingWorker,
# QualityWorker, processing.quality, file_io.exporter, visualiser.viewer --
# is imported lazily inside the methods that need it, after an
# open3d_usable() probe. On the lab VM `import open3d` dies with SIGILL
# (no AVX), and a module-level import here killed the whole app at
# startup before the capture/gantry features ever appeared.


# Strict reconstruction acceptance thresholds (match QualityThresholds defaults)
DEFAULT_MIN_FITNESS = 0.3
DEFAULT_MAX_RMSE    = 0.015


class HardwareProbeWorker(QThread):
    """Asks whether the camera and gantry are really there. Off the UI
    thread: the ROS master query is a network round-trip."""

    done = pyqtSignal(bool, str, bool, str)     # cam_ok, cam_msg, gan_ok, gan_msg

    def run(self):
        try:
            from capture.simulation import detect_camera, detect_gantry
            cam_ok, cam_msg = detect_camera()
            gan_ok, gan_msg = detect_gantry()
        except Exception as e:
            cam_ok, cam_msg = False, f'probe failed: {e}'
            gan_ok, gan_msg = False, f'probe failed: {e}'
        self.done.emit(cam_ok, cam_msg, gan_ok, gan_msg)


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
    postprocess_ready = pyqtSignal(str, object)
    postprocess_error = pyqtSignal(str)

    # How often to re-check for real hardware, in ms. A probe costs a few
    # ms (shared librealsense context + one ROS master call), so this is
    # cheap enough to run for the whole session.
    HARDWARE_POLL_MS = 3000

    # Capture lifecycle (panel needs this to disable jog during capture).
    capture_started  = pyqtSignal()
    # Out-of-band capture message, e.g. "SIMULATED camera ..."
    capture_notice   = pyqtSignal(str)
    # camera_ok, camera_detail, gantry_ok, gantry_detail
    hardware_status  = pyqtSignal(bool, str, bool, str)
    selftest_ready   = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker          = None
        self.capture_worker  = None
        self.quality_worker  = None
        self.postprocess_worker = None
        self.viewer          = None   # created lazily (imports open3d)
        self.final_pcd       = None
        self.all_metrics     = []
        self.n_success       = 0
        self.n_fail          = 0

        # Last known DataPanel paths (refreshed before quality / reconstruction)
        self._last_rgb_dir   = None
        self._last_depth_dir = None
        self._last_intr_path = None

        # Gantry controller -- ROS init is deferred to first call so this
        # is cheap on Windows / non-ROS hosts.
        self.gantry = GantryController()

        # Continuous hardware auto-detection. Real camera / real ROS
        # gantry always take priority over the simulated stand-ins, so we
        # keep looking for them instead of deciding once at startup: on
        # this rig the camera is often passed through (or the gantry
        # driver started) after the app is already open.
        self._hw_worker = None
        self._hw_state = None          # (camera_ok, gantry_ok) or None
        self._hw_timer = QTimer(self)
        self._hw_timer.setInterval(self.HARDWARE_POLL_MS)
        self._hw_timer.timeout.connect(self.refresh_hardware_status)
        self._hw_timer.start()

    # ---------------------------------------------------------------- run
    @pyqtSlot(str, str, str, int)
    def on_run_clicked(self, rgb_dir, depth_dir, intrinsics_path, step_size):
        ok, why = open3d_usable()
        if not ok:
            self.error_occurred.emit(f'Reconstruction unavailable:\n{why}')
            return
        from app.worker import ProcessingWorker
        from visualiser.viewer import PointCloudViewer
        if self.viewer is None:
            self.viewer = PointCloudViewer()

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
        depth_trunc = 4.0
        voxel_size  = 0.02 if is_icl else 0.01

        max_iter     = 30 if is_icl else 80
        bbox         = None
        erode        = False
        inpaint      = False
        depth_min_mm = 0

        # Stakeholder pipeline only: RGBD -> clean_pcd -> frame-to-frame ICP.
        use_known_poses = False
        gantry_axis     = 0
        gantry_step_m   = 0.0
        tsdf_voxel_m    = 0.005   # matches D405 noise floor (~5 mm RMSE) at 2.8 m

        self.worker = ProcessingWorker(
            pairs=pairs, K=K, dist=None,
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
        self.capture_started.emit()
        self.capture_worker = CaptureWorker(backend_pref, params)
        self.capture_worker.frame_captured.connect(self.capture_progress)
        self.capture_worker.finished.connect(self._on_capture_finished)
        self.capture_worker.error.connect(self._on_capture_error)
        self.capture_worker.notice.connect(self._on_capture_notice)
        self.capture_worker.start()

    @pyqtSlot(str)
    def _on_capture_notice(self, msg: str):
        self.status_changed.emit(msg)
        self.capture_notice.emit(msg)

    # ------------------------------------------------- hardware / selftest
    @pyqtSlot()
    def refresh_hardware_status(self):
        """Probe what is actually attached. Runs on a worker thread: the
        ROS master query is a network round-trip and must not block the
        UI."""
        # Never stack probes; never probe mid-capture (the camera and the
        # ROS master are busy, and the answer can't change usefully).
        if self._hw_worker is not None and self._hw_worker.isRunning():
            return
        if self.capture_worker is not None and self.capture_worker.isRunning():
            return
        worker = HardwareProbeWorker()
        worker.done.connect(self._on_hardware_probed)
        # Keep a reference or the QThread is garbage-collected mid-run.
        self._hw_worker = worker
        worker.start()

    @pyqtSlot(bool, str, bool, str)
    def _on_hardware_probed(self, cam_ok, cam_msg, gan_ok, gan_msg):
        """Real hardware takes priority over the simulated stand-ins, so
        announce the moment a real device appears or disappears."""
        previous = self._hw_state
        self._hw_state = (cam_ok, gan_ok)
        self.hardware_status.emit(cam_ok, cam_msg, gan_ok, gan_msg)

        if previous is None:
            # First probe of the session.
            for name, ok, detail in (("Camera", cam_ok, cam_msg),
                                     ("Gantry", gan_ok, gan_msg)):
                log_line = (f'{name} detected: {detail}' if ok
                            else f'{name} not detected ({detail}) '
                                 f'-- Quick Scan will simulate it')
                self.status_changed.emit(log_line)
            return

        for name, was, now, detail in (
            ("Camera", previous[0], cam_ok, cam_msg),
            ("Gantry", previous[1], gan_ok, gan_msg),
        ):
            if now and not was:
                self.status_changed.emit(
                    f'Real {name.lower()} connected ({detail}) -- it will be '
                    f'used instead of the simulated one.')
            elif was and not now:
                self.status_changed.emit(
                    f'Real {name.lower()} disconnected ({detail}).')

    @pyqtSlot(str)
    def on_selftest_requested(self, subject: str):
        from app.selftest_worker import SelfTestWorker
        self.status_changed.emit(f'Testing {subject}...')
        self.selftest_worker = SelfTestWorker(subject)
        self.selftest_worker.done.connect(self._on_selftest_done)
        self.selftest_worker.error.connect(
            lambda m: self.capture_error.emit(f'{subject} test failed: {m}'))
        self.selftest_worker.start()

    @pyqtSlot(object)
    def _on_selftest_done(self, result):
        self.status_changed.emit(result.headline)
        self.selftest_ready.emit(result)
        # A test changes what we know about the hardware -- refresh.
        self.refresh_hardware_status()

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
    def _build_quality_params(self, rgb_dir: str):
        from processing.quality import QualityParams, QualityThresholds
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
        ok, why = open3d_usable()
        if not ok:
            self.quality_error.emit(f'Quality check unavailable: {why}')
            return
        from app.quality_worker import QualityWorker
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
        ok, why = open3d_usable()
        if not ok:
            self.quality_error.emit(f'Quality check unavailable: {why}')
            return
        from app.quality_worker import QualityWorker
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

    # ---------------------------------------------------------- postprocess
    def _postprocess_available(self) -> bool:
        # The post-processing scripts run in subprocesses but import
        # open3d there -- probe once and give a clear error instead of a
        # cryptic subprocess crash.
        ok, why = open3d_usable()
        if not ok:
            self.postprocess_error.emit(f'Post-processing unavailable: {why}')
        return ok

    @pyqtSlot(str, str)
    def on_clean_ply_requested(self, input_ply: str, output_dir: str):
        if not self._postprocess_available():
            return
        self.status_changed.emit('Cleaning point cloud...')
        self.postprocess_worker = PostProcessWorker('clean', input_ply, output_dir)
        self.postprocess_worker.done.connect(self._on_postprocess_done)
        self.postprocess_worker.error.connect(self._on_postprocess_error)
        self.postprocess_worker.start()

    @pyqtSlot(str, str, int)
    def on_segment_requested(self, input_ply: str, output_dir: str, expected_plants: int):
        if not self._postprocess_available():
            return
        self.status_changed.emit(f'Segmenting {expected_plants} plant(s)...')
        self.postprocess_worker = PostProcessWorker('segment', input_ply, output_dir, expected_plants)
        self.postprocess_worker.done.connect(self._on_postprocess_done)
        self.postprocess_worker.error.connect(self._on_postprocess_error)
        self.postprocess_worker.start()

    @pyqtSlot(str, str)
    def on_traits_requested(self, input_ply: str, output_dir: str):
        if not self._postprocess_available():
            return
        self.status_changed.emit('Extracting plant traits...')
        self.postprocess_worker = PostProcessWorker('traits', input_ply, output_dir)
        self.postprocess_worker.done.connect(self._on_postprocess_done)
        self.postprocess_worker.error.connect(self._on_postprocess_error)
        self.postprocess_worker.start()

    @pyqtSlot(str, str, int)
    def on_pipeline_requested(self, input_ply: str, dataset_dir: str, expected_plants: int):
        if not self._postprocess_available():
            return
        self.status_changed.emit('Running cleanup, segmentation, and per-plant trait extraction...')
        self.postprocess_worker = PostProcessWorker('pipeline', input_ply, dataset_dir, expected_plants)
        self.postprocess_worker.done.connect(self._on_postprocess_done)
        self.postprocess_worker.error.connect(self._on_postprocess_error)
        self.postprocess_worker.start()

    @pyqtSlot(str, object)
    def _on_postprocess_done(self, mode: str, result):
        self.status_changed.emit(f'Post-processing complete: {mode}')
        self.postprocess_ready.emit(mode, result)
        self.postprocess_worker = None

    @pyqtSlot(str)
    def _on_postprocess_error(self, msg: str):
        self.status_changed.emit(f'Post-processing error: {msg}')
        self.postprocess_error.emit(msg)
        self.postprocess_worker = None

    # ---------------------------------------------------------------- gantry
    @pyqtSlot(float)
    def on_gantry_jog(self, velocity_mps: float):
        if velocity_mps == 0.0:
            self.gantry.stop()
        else:
            self.gantry.start_jog(velocity_mps)

    @pyqtSlot()
    def on_gantry_stop(self):
        self.gantry.stop()

    @pyqtSlot(float)
    def on_gantry_goto(self, position_m: float):
        self.gantry.go_to(position_m)

    @pyqtSlot()
    def on_gantry_home(self):
        self.gantry.go_home()

    def shutdown(self):
        """Called from MainWindow.closeEvent. Final safety stop +
        unregister subscribers."""
        try:
            self._hw_timer.stop()
        except Exception:
            pass
        try:
            self.gantry.shutdown()
        except Exception:
            pass

    # ---------------------------------------------------------------- export
    def export_ply(self, path):
        usable, why = open3d_usable()
        if not usable:
            self.status_changed.emit(f'PLY export unavailable: {why}')
            return
        from file_io.exporter import save_ply
        if self.final_pcd:
            ok = save_ply(self.final_pcd, path)
            self.status_changed.emit(f'PLY saved: {path}' if ok else 'PLY export failed.')

    def export_csv(self, path):
        from file_io.exporter import save_metrics_csv
        ok = save_metrics_csv(self.all_metrics, path)
        self.status_changed.emit(f'CSV saved: {path}' if ok else 'CSV export failed.')

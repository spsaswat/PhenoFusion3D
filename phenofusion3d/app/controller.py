"""
Controller - Orchestrates processing, passes data between UI and processing.
"""
import os
from PyQt5.QtCore import QObject

from phenofusion3d.io import save_ply, save_metrics_csv

from .processing_worker import ProcessingWorker


class Controller(QObject):
    """Wires data panel, controls, metrics, log, and worker."""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.worker = None
        self.current_pcd = None
        self.metrics_list = []

    def on_run_requested(self, rgb_dir, depth_dir, intrinsics_path, step_size):
        if not rgb_dir or not os.path.isdir(rgb_dir):
            self.main_window.log_panel.append("Error: Select a valid RGB image folder.")
            return

        # Disable run, enable stop
        self.main_window.data_panel.set_run_enabled(False)
        self.main_window.controls_panel.set_stop_enabled(True)
        self.main_window.metrics_panel.reset()
        self.main_window.log_panel.clear()
        self.main_window.statusBar().showMessage("Processing...")
        self.main_window.log_panel.append("Starting reconstruction...")

        self.worker = ProcessingWorker(
            rgb_dir=rgb_dir,
            depth_dir=depth_dir or rgb_dir,
            intrinsics_path=intrinsics_path or "",
            step_size=step_size,
        )
        self.worker.frame_done.connect(self._on_frame_done)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.progress.connect(self._on_progress)
        try:
            self.main_window.controls_panel.stop_requested.disconnect()
        except TypeError:
            pass
        self.main_window.controls_panel.stop_requested.connect(self.worker.stop)
        self.worker.start()

    def _on_frame_done(self, pcd, frame_idx, fitness, rmse, success):
        self.current_pcd = pcd
        total = getattr(self.worker, "_total_frames", 0) or 1
        self.main_window.metrics_panel.update_metrics(frame_idx, total, fitness, rmse)
        if success:
            self.main_window.log_panel.log_success(frame_idx, fitness, rmse)
        else:
            self.main_window.log_panel.log_fail(frame_idx)
        self.main_window.update_viewer(pcd)

    def _on_finished(self, pcd, metrics_list):
        self.current_pcd = pcd
        self.metrics_list = metrics_list
        self.main_window.data_panel.set_run_enabled(True)
        self.main_window.controls_panel.set_stop_enabled(False)
        self.main_window.statusBar().showMessage("Reconstruction complete.")
        self.main_window.log_panel.append("Done.")
        self.main_window.update_viewer(pcd)
        # Emergency save to project root
        try:
            save_ply(pcd, "emergency_save.ply")
        except Exception:
            pass

    def _on_error(self, msg):
        self.main_window.data_panel.set_run_enabled(True)
        self.main_window.controls_panel.set_stop_enabled(False)
        self.main_window.statusBar().showMessage("Error")
        self.main_window.log_panel.append(f"Error: {msg}")

    def _on_progress(self, current, total):
        if self.worker:
            self.worker._total_frames = total
        self.main_window.statusBar().showMessage(f"Processing frame {current}/{total}")

    def export_ply(self, path):
        if self.current_pcd is not None:
            return save_ply(self.current_pcd, path)
        return False

    def export_metrics_csv(self, path):
        if self.metrics_list:
            return save_metrics_csv(self.metrics_list, path)
        return False

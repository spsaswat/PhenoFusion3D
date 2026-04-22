"""
Processing worker - runs reconstruction in background thread. Never block Qt main thread.
"""
import sys
import os

# Ensure phenofusion3d package is on path when run from project root
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import cv2
import copy
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

# Import from package (run from project root: python main.py)
try:
    from phenofusion3d.processing import rgbd2pcd, clean_pcd, color_icp
    from phenofusion3d.io import load_image_pairs, load_intrinsics, get_default_intrinsics
except ImportError:
    from processing import rgbd2pcd, clean_pcd, color_icp
    from io import load_image_pairs, load_intrinsics, get_default_intrinsics


class ProcessingWorker(QThread):
    """Runs merge_one_cam logic in background. Emits per-frame and final results."""

    frame_done = pyqtSignal(object, int, float, float, bool)  # pcd, frame_idx, fitness, rmse, success
    finished = pyqtSignal(object, list)  # final pcd, metrics_list
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # current, total

    def __init__(self, rgb_dir, depth_dir, intrinsics_path, step_size, depth_scale=1000.0):
        super().__init__()
        self.rgb_dir = rgb_dir
        self.depth_dir = depth_dir or rgb_dir
        self.intrinsics_path = intrinsics_path
        self.step_size = step_size
        self.depth_scale = depth_scale
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            pairs = load_image_pairs(self.rgb_dir, self.depth_dir, self.step_size)
            if not pairs:
                self.error.emit("No image pairs found. Check folder paths and naming (rgb_*.png, depth_*.png).")
                return

            if self.intrinsics_path and os.path.exists(self.intrinsics_path):
                K, dist = load_intrinsics(self.intrinsics_path)
            else:
                K, dist = get_default_intrinsics()

            reference_pcd = None
            last_transform = np.eye(4)
            target = None
            metrics_list = []
            total = len(pairs)

            for i in range(total):
                if self._stopped:
                    break

                self.progress.emit(i + 1, total)

                rgb_path, depth_path = pairs[i]
                color = cv2.imread(rgb_path)
                if color is None:
                    continue
                color = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
                depth = cv2.imread(depth_path, -1)
                if depth is None:
                    continue

                source = rgbd2pcd(color, depth, K, dist=dist, depth_scale=self.depth_scale)
                source = clean_pcd(source)

                if source.is_empty():
                    continue

                if i == 0:
                    target = source
                    reference_pcd = copy.deepcopy(source)
                    self.frame_done.emit(reference_pcd, 0, 0.0, 0.0, True)
                    metrics_list.append({"frame_idx": 0, "fitness": 0, "inlier_rmse": 0, "success": True})
                    continue

                _, transformation, fitness, inlier_rmse = color_icp(source, target)

                # Allow first few frames even with low fitness (stakeholder logic)
                if fitness > 0 or i < 3:
                    last_transform = np.dot(last_transform, transformation)
                    transformed = copy.deepcopy(source).transform(last_transform)
                    reference_pcd += transformed
                    target = source
                    self.frame_done.emit(reference_pcd, i, fitness, inlier_rmse, True)
                    metrics_list.append({
                        "frame_idx": i,
                        "fitness": fitness,
                        "inlier_rmse": inlier_rmse,
                        "success": True,
                    })
                else:
                    self.frame_done.emit(reference_pcd, i, fitness, inlier_rmse, False)
                    metrics_list.append({
                        "frame_idx": i,
                        "fitness": fitness,
                        "inlier_rmse": inlier_rmse,
                        "success": False,
                    })

            if reference_pcd is not None:
                self.finished.emit(reference_pcd, metrics_list)
            else:
                self.error.emit("No valid frames processed.")

        except Exception as e:
            self.error.emit(str(e))

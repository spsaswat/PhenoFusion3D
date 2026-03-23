import os
import copy
import numpy as np
import cv2
import open3d as o3d

from processing.rgbd import rgbd2pcd
from processing.icp import color_icp
from processing.utils import clean_pcd


class Reconstructor:
    """
    Sequential RGB-D point cloud reconstruction.

    Iterates over image pairs, converts each to a point cloud, registers
    it against the previous frame using ICP, and accumulates a merged
    reference point cloud.

    Designed to run inside a QThread worker - all UI interaction happens
    via the on_frame and on_complete callbacks.
    """

    def __init__(
        self,
        pairs,
        K,
        dist=None,
        step_size=1,
        depth_scale=1000.0,
        depth_trunc=3.0,
        voxel_size=0.005,
        save_path=None,
        on_frame=None,
        on_complete=None
    ):
        """
        Args:
            pairs        : list of (rgb_path, depth_path) tuples (already stepped by loader)
            K            : 3x3 intrinsic matrix (np.ndarray)
            dist         : distortion coefficients list, or None
            step_size    : kept for metadata only - loader handles stepping
            depth_scale  : mm->metres divisor (1000 for RealSense, 1.0 for ICL-NUIM)
            depth_trunc  : discard depth beyond this many metres
            voxel_size   : voxel size for downsampling and ICP radius
            save_path    : directory to write intermediate PLY files, or None
            on_frame     : callback(frame_idx, total, merged_pcd, fitness, rmse, status)
            on_complete  : callback(final_pcd, succeed_list, fail_list)
        """
        self.pairs = pairs
        self.K = K
        self.dist = dist
        self.step_size = step_size
        self.depth_scale = depth_scale
        self.depth_trunc = depth_trunc
        self.voxel_size = voxel_size
        self.save_path = save_path
        self.on_frame = on_frame
        self.on_complete = on_complete

        self._stop_flag = False
        self.reference_pcd = None
        self.succeed_list = []
        self.fail_list = []

        if save_path and not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

    def stop(self):
        """Signal the run loop to halt cleanly after the current frame."""
        self._stop_flag = True
        print('[reconstructor] Stop requested.')

    def run(self):
        """
        Main reconstruction loop.
        Call this from QThread.run() or directly from a test script.
        """
        self._stop_flag = False
        self.succeed_list = []
        self.fail_list = []

        total = len(self.pairs)
        last_transform = np.eye(4)
        target = None
        self.reference_pcd = o3d.geometry.PointCloud()

        print(f'[reconstructor] Starting reconstruction: {total} frames')

        for i, (rgb_path, depth_path) in enumerate(self.pairs):

            if self._stop_flag:
                print(f'[reconstructor] Stopped at frame {i}.')
                self._emergency_save()
                break

            # --- Load images ---
            color = cv2.imread(rgb_path)
            if color is None:
                print(f'[reconstructor] WARNING: Could not read {rgb_path}, skipping.')
                self.fail_list.append({'frame': i, 'reason': 'imread failed'})
                continue
            color = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)

            depth = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)
            if depth is None:
                print(f'[reconstructor] WARNING: Could not read {depth_path}, skipping.')
                self.fail_list.append({'frame': i, 'reason': 'imread failed'})
                continue

            # --- Convert to point cloud ---
            try:
                source = rgbd2pcd(
                    color, depth, self.K,
                    dist=self.dist,
                    depth_scale=self.depth_scale,
                    depth_trunc=self.depth_trunc
                )
                source = clean_pcd(source, voxel_size=self.voxel_size)
            except Exception as e:
                print(f'[reconstructor] Frame {i} rgbd2pcd failed: {e}')
                self.fail_list.append({'frame': i, 'reason': str(e)})
                continue

            if source.is_empty():
                print(f'[reconstructor] Frame {i} produced empty cloud, skipping.')
                self.fail_list.append({'frame': i, 'reason': 'empty cloud'})
                continue

            # --- First frame: set as reference and target ---
            if i == 0:
                target = source
                self.reference_pcd = copy.deepcopy(source)
                self.succeed_list.append({'frame': i, 'fitness': 1.0, 'rmse': 0.0})
                self._fire_on_frame(i, total, self.reference_pcd, 1.0, 0.0, 'OK')
                self._save_intermediate()
                continue

            # --- ICP registration against previous frame ---
            try:
                _, transformation, fitness, rmse = color_icp(
                    source, target, voxel_size=self.voxel_size
                )
            except Exception as e:
                print(f'[reconstructor] Frame {i} ICP failed: {e}')
                self.fail_list.append({'frame': i, 'reason': f'ICP error: {e}'})
                self._fire_on_frame(i, total, self.reference_pcd, 0.0, 0.0, 'FAILED')
                continue

            if fitness > 0 or i < 3:
                # Accumulate into reference
                last_transform = np.dot(last_transform, transformation)
                frame_pcd = copy.deepcopy(source)
                frame_pcd.transform(last_transform)
                self.reference_pcd += frame_pcd
                target = source

                self.succeed_list.append({'frame': i, 'fitness': fitness, 'rmse': rmse})
                self._fire_on_frame(i, total, self.reference_pcd, fitness, rmse, 'OK')
                self._save_intermediate()

                print(f'[reconstructor] Frame {i:4d}/{total} | fitness={fitness:.4f} | rmse={rmse:.4f}')
            else:
                self.fail_list.append({'frame': i, 'reason': f'fitness=0'})
                self._fire_on_frame(i, total, self.reference_pcd, 0.0, 0.0, 'FAILED')
                print(f'[reconstructor] Frame {i:4d}/{total} | ICP failed (fitness=0)')

        # --- Done ---
        print(f'[reconstructor] Complete. Success={len(self.succeed_list)} Fail={len(self.fail_list)}')
        if self.on_complete:
            self.on_complete(self.reference_pcd, self.succeed_list, self.fail_list)

        return self.reference_pcd, self.succeed_list, self.fail_list

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fire_on_frame(self, frame_idx, total, pcd, fitness, rmse, status):
        if self.on_frame:
            self.on_frame(frame_idx, total, pcd, fitness, rmse, status)

    def _save_intermediate(self):
        if self.save_path and self.reference_pcd and not self.reference_pcd.is_empty():
            out = os.path.join(self.save_path, 'merge_pcd_live.ply')
            o3d.io.write_point_cloud(out, self.reference_pcd)

    def _emergency_save(self):
        if self.reference_pcd and not self.reference_pcd.is_empty():
            out = os.path.join(self.save_path or '.', 'emergency_save.ply')
            o3d.io.write_point_cloud(out, self.reference_pcd)
            print(f'[reconstructor] Emergency save written to {out}')
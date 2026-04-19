import os
import copy
import numpy as np
import cv2
import open3d as o3d

from processing.rgbd import rgbd2pcd
from processing.icp import color_icp
from processing.utils import clean_pcd, clean_pcd_for_registration


class Reconstructor:
    """
    Sequential RGB-D point cloud reconstruction.

    Two operating modes selected by `use_known_poses`:

    ICP mode (use_known_poses=False, default):
        Registers each frame against the previous with colour-assisted ICP,
        accumulating a merged point cloud. Works for any camera motion.

    Known-pose / TSDF mode (use_known_poses=True):
        Skips ICP entirely. Computes camera poses from gantry kinematics
        (constant-velocity linear translation) and integrates all frames
        into an Open3D ScalableTSDFVolume. Produces clean, hole-filled
        surfaces and is much more robust when ICP is degenerate (e.g. flat
        scenes viewed from directly above).

    In both modes the class is designed to run inside a QThread worker --
    all UI interaction happens via the on_frame and on_complete callbacks.
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
        max_iter=50,
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
        on_frame=None,
        on_complete=None,
        bbox=None,
    ):
        """
        Args:
            pairs           : list of (rgb_path, depth_path) tuples (already stepped)
            K               : 3x3 intrinsic matrix (np.ndarray)
            dist            : distortion coefficients list, or None
            step_size       : kept for metadata; loader handles stepping
            depth_scale     : mm->metres divisor (1000 for RealSense, 1.0 for ICL-NUIM)
            depth_trunc     : discard depth beyond this many metres
            voxel_size      : voxel size for ICP radius and final-output downsampling
            max_iter        : max ICP iterations per frame pair (ICP mode only)
            gantry_step_m   : camera translation per PAIR in metres (pre-multiplied by
                              sampling step). Used as ICP init seed (ICP mode) or as
                              kinematic pose step (known-pose mode).
            gantry_axis     : camera-space axis the gantry moves along: 0=X, 1=Y
                              (determined by calibrate_gantry.py)
            depth_min_mm    : near clip for raw depth (mm); 0 disables
            erode           : shrink valid depth mask (flying pixels) -- ICP mode
            inpaint         : fill interior holes in depth -- ICP mode
            use_known_poses : if True, use TSDF + kinematic poses instead of ICP
            tsdf_voxel_m    : TSDF voxel size in metres (known-pose mode only)
            save_path       : directory to write intermediate PLY files, or None
            on_frame        : callback(frame_idx, total, merged_pcd, fitness, rmse, status)
            on_complete     : callback(final_pcd, succeed_list, fail_list)
            bbox            : optional [x1, y1, x2, y2] crop passed to rgbd2pcd
        """
        self.pairs           = pairs
        self.K               = K
        self.dist            = dist
        self.step_size       = step_size
        self.depth_scale     = depth_scale
        self.depth_trunc     = depth_trunc
        self.voxel_size      = voxel_size
        self.max_iter        = max_iter
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
        self.on_frame        = on_frame
        self.on_complete     = on_complete
        self.bbox            = bbox

        self._stop_flag    = False
        self.reference_pcd = None
        self.succeed_list  = []
        self.fail_list     = []

        if save_path and not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

    def stop(self):
        """Signal the run loop to halt cleanly after the current frame."""
        self._stop_flag = True
        print('[reconstructor] Stop requested.')

    def run(self):
        """
        Main entry point. Dispatches to the appropriate mode.
        Call this from QThread.run() or directly from a test script.
        """
        self._stop_flag   = False
        self.succeed_list = []
        self.fail_list    = []
        self.reference_pcd = o3d.geometry.PointCloud()

        if self.use_known_poses:
            return self._run_known_pose_tsdf()
        else:
            return self._run_icp()

    # ------------------------------------------------------------------
    # Mode A: Known-pose TSDF integration
    # ------------------------------------------------------------------

    def _run_known_pose_tsdf(self):
        """
        Integrate all frames into an Open3D ScalableTSDFVolume using
        camera poses derived from gantry kinematics.

        gantry_step_m is the 3D translation per consecutive PAIR (already
        multiplied by the sampling step by the caller).
        """
        total = len(self.pairs)
        print(f'[reconstructor] Known-pose TSDF: {total} frames, '
              f'step={self.gantry_step_m*1000:.2f}mm, '
              f'axis={self.gantry_axis}, '
              f'voxel={self.tsdf_voxel_m*1000:.1f}mm')

        sdf_trunc = self.tsdf_voxel_m * 8   # standard: 8x voxel_length

        volume = o3d.pipelines.integration.ScalableTSDFVolume(
            voxel_length=self.tsdf_voxel_m,
            sdf_trunc=sdf_trunc,
            color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
        )

        # Build PinholeCameraIntrinsic from first image shape + K matrix
        K_mat = np.array(self.K, dtype=np.float64)
        first_bgr = cv2.imread(self.pairs[0][0])
        if first_bgr is None:
            raise RuntimeError(f'Cannot read first frame: {self.pairs[0][0]}')
        img_h, img_w = first_bgr.shape[:2]

        # Adjust intrinsics for bbox crop if used
        cx = float(K_mat[0, 2])
        cy = float(K_mat[1, 2])
        if self.bbox is not None:
            x1, y1, x2, y2 = self.bbox
            cx     -= x1
            cy     -= y1
            img_w   = x2 - x1
            img_h   = y2 - y1

        intrinsic = o3d.camera.PinholeCameraIntrinsic(
            width=img_w, height=img_h,
            fx=float(K_mat[0, 0]),
            fy=float(abs(K_mat[1, 1])),
            cx=cx, cy=cy,
        )

        # Pre-compute undistortion maps (if needed)
        map1, map2 = None, None
        if self.dist is not None and any(d != 0.0 for d in self.dist):
            dist_arr = np.array(self.dist, dtype=np.float64)
            raw_h, raw_w = first_bgr.shape[:2]
            map1, map2 = cv2.initUndistortRectifyMap(
                K_mat, dist_arr, None, K_mat, (raw_w, raw_h), cv2.CV_32FC1
            )

        depth_max_mm = int(self.depth_trunc * self.depth_scale)

        for i, (rgb_path, depth_path) in enumerate(self.pairs):
            if self._stop_flag:
                print(f'[reconstructor] Stopped at frame {i}.')
                self._emergency_save()
                break

            # Load
            color_bgr = cv2.imread(rgb_path)
            depth_raw = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)
            if color_bgr is None or depth_raw is None:
                print(f'[reconstructor] WARNING: Cannot read frame {i}, skipping.')
                self.fail_list.append({'frame': i, 'reason': 'imread failed'})
                continue

            color_rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)

            # Undistort (depth: nearest-neighbour to avoid value corruption)
            if map1 is not None:
                color_rgb = cv2.undistort(
                    color_rgb, K_mat, np.array(self.dist, dtype=np.float64)
                )
                depth_raw = cv2.remap(depth_raw, map1, map2, cv2.INTER_NEAREST)

            # Optional bbox crop
            if self.bbox is not None:
                x1, y1, x2, y2 = self.bbox
                color_rgb = color_rgb[y1:y2, x1:x2]
                depth_raw = depth_raw[y1:y2, x1:x2]

            # Depth range masking
            depth_masked = depth_raw.astype(np.uint16).copy()
            depth_masked[depth_masked > depth_max_mm] = 0
            if self.depth_min_mm > 0:
                depth_masked[(depth_masked > 0) & (depth_masked < self.depth_min_mm)] = 0

            # Build RGBD image (Open3D needs C-contiguous arrays)
            o3d_color = o3d.geometry.Image(np.ascontiguousarray(color_rgb))
            o3d_depth = o3d.geometry.Image(np.ascontiguousarray(depth_masked))
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                o3d_color, o3d_depth,
                depth_scale=self.depth_scale,
                depth_trunc=self.depth_trunc,
                convert_rgb_to_intensity=False,
            )

            # Kinematic camera pose: camera-to-world for frame i
            T_c2w = np.eye(4)
            T_c2w[self.gantry_axis, 3] = i * self.gantry_step_m

            # TSDF integrate() expects world-to-camera (inverse of camera pose)
            extrinsic = np.linalg.inv(T_c2w)

            volume.integrate(rgbd, intrinsic, extrinsic)

            self.succeed_list.append({'frame': i, 'fitness': 1.0, 'rmse': 0.0})
            # Pass empty cloud during integration (full cloud only at the end)
            self._fire_on_frame(i, total, self.reference_pcd, 1.0, 0.0, 'OK')

            if i % 10 == 0 or i == total - 1:
                print(f'[reconstructor] TSDF {i + 1:4d}/{total}')

        print('[reconstructor] Extracting point cloud from TSDF volume...')
        self.reference_pcd = volume.extract_point_cloud()
        pts = len(self.reference_pcd.points)
        print(f'[reconstructor] TSDF complete. '
              f'Points: {pts:,}  '
              f'success={len(self.succeed_list)}  fail={len(self.fail_list)}')

        self._save_intermediate()
        if self.on_complete:
            self.on_complete(self.reference_pcd, self.succeed_list, self.fail_list)

        return self.reference_pcd, self.succeed_list, self.fail_list

    # ------------------------------------------------------------------
    # Mode B: ICP-based registration (fixed)
    # ------------------------------------------------------------------

    def _run_icp(self):
        """
        Sequential ICP registration (original approach, fixed):
        - Uses clean_pcd_for_registration (no voxel downsample) before ICP
        - Voxel downsampling applied only to the final merged cloud
        - gantry_step_m seeds the ICP initial transform (per-pair, pre-multiplied)
        """
        total          = len(self.pairs)
        last_transform = np.eye(4)
        target         = None

        print(f'[reconstructor] ICP mode: {total} frames')

        for i, (rgb_path, depth_path) in enumerate(self.pairs):

            if self._stop_flag:
                print(f'[reconstructor] Stopped at frame {i}.')
                self._emergency_save()
                break

            # Load images
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

            # Convert to point cloud
            try:
                source = rgbd2pcd(
                    color, depth, self.K,
                    dist=self.dist,
                    bbox=self.bbox,
                    depth_scale=self.depth_scale,
                    depth_trunc=self.depth_trunc,
                    depth_min_mm=self.depth_min_mm,
                    erode=self.erode,
                    inpaint=self.inpaint,
                )
                # Outlier removal WITHOUT voxel downsampling before ICP.
                # Voxel downsampling before ICP kills sub-voxel displacement
                # signal (gantry moves ~1-7mm but voxels are 8mm).
                source = clean_pcd_for_registration(source)
            except Exception as e:
                print(f'[reconstructor] Frame {i} rgbd2pcd failed: {e}')
                self.fail_list.append({'frame': i, 'reason': str(e)})
                continue

            if source.is_empty():
                print(f'[reconstructor] Frame {i} produced empty cloud, skipping.')
                self.fail_list.append({'frame': i, 'reason': 'empty cloud'})
                continue

            # First frame: set as reference and target
            if i == 0:
                target = source
                self.reference_pcd = copy.deepcopy(source)
                self.succeed_list.append({'frame': i, 'fitness': 1.0, 'rmse': 0.0})
                self._fire_on_frame(i, total, self.reference_pcd, 1.0, 0.0, 'OK')
                self._save_intermediate()
                continue

            # ICP registration against previous frame
            try:
                init_tf = np.eye(4)
                if self.gantry_step_m != 0.0:
                    init_tf[self.gantry_axis, 3] = self.gantry_step_m
                _, transformation, fitness, rmse = color_icp(
                    source, target,
                    max_iter=self.max_iter,
                    voxel_size=self.voxel_size,
                    init=init_tf,
                )
            except Exception as e:
                print(f'[reconstructor] Frame {i} ICP failed: {e}')
                self.fail_list.append({'frame': i, 'reason': f'ICP error: {e}'})
                self._fire_on_frame(i, total, self.reference_pcd, 0.0, 0.0, 'FAILED')
                continue

            # Strict acceptance: require BOTH a meaningful overlap AND a tight fit.
            # Rejected frames don't update last_transform so the chain stays clean.
            accept = (fitness >= self.min_fitness) and (rmse <= self.max_rmse)
            if accept:
                last_transform = np.dot(last_transform, transformation)
                frame_pcd = copy.deepcopy(source)
                frame_pcd.transform(last_transform)
                self.reference_pcd += frame_pcd
                target = source

                self.succeed_list.append({'frame': i, 'fitness': fitness, 'rmse': rmse})
                self._fire_on_frame(i, total, self.reference_pcd, fitness, rmse, 'OK')
                self._save_intermediate()

                print(f'[reconstructor] Frame {i:4d}/{total} | '
                      f'fitness={fitness:.4f} | rmse={rmse:.4f}')
            else:
                if fitness < self.min_fitness:
                    reason = f'low fitness {fitness:.3f} < {self.min_fitness:.3f}'
                else:
                    reason = f'high rmse {rmse:.4f} > {self.max_rmse:.4f}'
                self.fail_list.append({'frame': i, 'reason': reason,
                                       'fitness': fitness, 'rmse': rmse})
                self._fire_on_frame(i, total, self.reference_pcd, fitness, rmse, 'REJECTED')
                print(f'[reconstructor] Frame {i:4d}/{total} | REJECTED ({reason})')

        print(f'[reconstructor] ICP complete. '
              f'Success={len(self.succeed_list)} Fail={len(self.fail_list)}')
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

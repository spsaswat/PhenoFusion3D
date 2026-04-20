"""
test_with_whole_seq.py
----------------------
Full-sequence reconstruction test.

Two modes -- change USE_KNOWN_POSES to switch:

  USE_KNOWN_POSES = True  (default, recommended for gantry data)
      Skips ICP. Uses TSDF volume integration with kinematic camera poses.
      Robust for flat/featureless scenes viewed from above.

  USE_KNOWN_POSES = False
      Uses colour-assisted ICP registration between consecutive frames.
      Requires sufficient scene texture and geometry variation.

Run calibrate_gantry.py first to determine GANTRY_AXIS and GANTRY_STEP_M
for your specific dataset.
"""

import sys
sys.path.insert(0, ".")

import os
import open3d as o3d

from file_io.loader import load_image_pairs, load_intrinsics
from processing.reconstructor import Reconstructor

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SEQ_ROOT       = "data/main/test_plant_rs13_1"
rgb_dir        = os.path.join(SEQ_ROOT, "rgb")
depth_dir      = os.path.join(SEQ_ROOT, "depth")
intrinsics_path = os.path.join(SEQ_ROOT, "kdc_intrinsics.txt")

# ---------------------------------------------------------------------------
# Sampling
# step=1  → every frame  (~211 pairs after plant-only crop)
# step=5  → every 5th    (~42 pairs, faster for testing)
# step=10 → every 10th   (~21 pairs, quick sanity check)
# ---------------------------------------------------------------------------
STEP = 1

# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------
USE_KNOWN_POSES = True   # True = TSDF + kinematics; False = ICP

# ---------------------------------------------------------------------------
# Gantry parameters  (run calibrate_gantry.py to refine these)
#   GANTRY_AXIS      : 0 = camera X (horizontal), 1 = camera Y (vertical)
#   GANTRY_STEP_M    : per-ORIGINAL-frame displacement in metres
#                      (~1.27 mm/frame at 38 mm/s, 30 fps)
# ---------------------------------------------------------------------------
GANTRY_AXIS   = 0
GANTRY_STEP_M = 0.00127   # metres per original frame

# ---------------------------------------------------------------------------
# Depth / reconstruction parameters
# ---------------------------------------------------------------------------
DEPTH_SCALE  = 1000.0
DEPTH_TRUNC  = 3.5        # metres -- scene at ~2.82 m, trim background noise
VOXEL_SIZE   = 0.005      # ICP radius and output downsample (ICP mode)
MAX_ITER     = 80         # ICP iterations per frame pair (ICP mode)
TSDF_VOXEL_M = 0.005      # 5 mm TSDF voxels: matches D405 noise floor at 2.8 m
BBOX         = None       # No crop -- TSDF benefits from full frame
DEPTH_MIN_MM = 0          # No near-clip -- keep all valid depth
ERODE        = False
INPAINT      = False

save_path = os.path.join(SEQ_ROOT, "output")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
pairs = load_image_pairs(rgb_dir, depth_dir, step=STEP)
if not pairs:
    raise SystemExit(
        f"No RGB/depth pairs under {rgb_dir!r} / {depth_dir!r}. "
        f"Check paths and that PNG counts match."
    )

intr = load_intrinsics(intrinsics_path)
if intr is None:
    raise SystemExit(f"Missing or invalid intrinsics: {intrinsics_path!r}")
K, dist, _, _ = intr

# ---------------------------------------------------------------------------
# Per-pair gantry step (CRITICAL: multiply per-frame step by sampling step)
# The Reconstructor receives pre-stepped pairs, so gantry_step_m must be
# the displacement between CONSECUTIVE PAIRS, not per original frame.
# ---------------------------------------------------------------------------
gantry_step_per_pair = GANTRY_STEP_M * STEP
print(f"Gantry step per pair: {gantry_step_per_pair*1000:.2f} mm  "
      f"(={GANTRY_STEP_M*1000:.3f} mm/frame × step={STEP})")

# ---------------------------------------------------------------------------
# Run reconstruction
# ---------------------------------------------------------------------------
mode_str = "TSDF+known-pose" if USE_KNOWN_POSES else "ICP"
print(f"\nMode: {mode_str}  |  pairs: {len(pairs)}  |  step: {STEP}")

final_pcd, succeed, fail = Reconstructor(
    pairs=pairs,
    K=K,
    dist=dist,
    depth_scale=DEPTH_SCALE,
    depth_trunc=DEPTH_TRUNC,
    voxel_size=VOXEL_SIZE,
    max_iter=MAX_ITER,
    gantry_step_m=gantry_step_per_pair,
    gantry_axis=GANTRY_AXIS,
    depth_min_mm=DEPTH_MIN_MM,
    erode=ERODE,
    inpaint=INPAINT,
    use_known_poses=USE_KNOWN_POSES,
    tsdf_voxel_m=TSDF_VOXEL_M,
    bbox=BBOX,
    save_path=save_path,
).run()

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
print(f"\npairs used: {len(pairs)} | success: {len(succeed)}, fail: {len(fail)}")
print(f"points: {len(final_pcd.points):,}")

if final_pcd.is_empty():
    raise SystemExit(
        "Merged point cloud is empty!\n"
        "  - Check depth data: run test_with_one_img.py (MODE 1) first\n"
        "  - Check gantry_axis with calibrate_gantry.py\n"
        "  - Try USE_KNOWN_POSES=False to compare ICP mode"
    )

os.makedirs(save_path, exist_ok=True)
out_ply = os.path.join(save_path, "merge_manual.ply")
o3d.io.write_point_cloud(out_ply, final_pcd)
print(f"Wrote: {out_ply}")

o3d.visualization.draw_geometries([final_pcd], window_name=f"merged ({mode_str})")

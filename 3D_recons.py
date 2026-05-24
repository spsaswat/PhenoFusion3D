"""
Simple RGB-D point cloud reconstruction entry point.

This keeps the stakeholder script's `merge_one_cam(...)` idea, but makes it
runnable from this repository on either:
  - data/main/<dataset>/rgb/*.png + data/main/<dataset>/depth/*.png
  - data/main/<dataset>/rgb_*.png + data/main/<dataset>/depth_*.png
  - data/main/<dataset>/camera_<id>/...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import open3d as o3d

from file_io.loader import get_default_intrinsics, load_image_pairs, load_intrinsics
from processing.reconstructor import Reconstructor
from processing.registration_agent import AgentConfig
from processing.utils import clean_pcd


def _resolve_record_path(record_path: str | Path, cam_id: str | int | None) -> Path:
    """Return camera_<id> when present, otherwise the given dataset path."""
    path = Path(record_path).resolve()
    if cam_id not in (None, ""):
        camera_path = path / f"camera_{cam_id}"
        if camera_path.exists():
            return camera_path
    return path


def _resolve_rgb_depth_dirs(record_path: Path) -> tuple[Path, Path]:
    """Support both folder and flat stakeholder file layouts."""
    rgb_dir = record_path / "rgb"
    depth_dir = record_path / "depth"
    if rgb_dir.is_dir() and depth_dir.is_dir():
        return rgb_dir, depth_dir
    return record_path, record_path


def _load_intrinsics_for_dataset(record_path: Path, first_rgb_path: str):
    """Load kdc_intrinsics.txt, or fall back to image-size based defaults."""
    intrinsics = load_intrinsics(str(record_path / "kdc_intrinsics.txt"))
    if intrinsics:
        K, dist, _, _ = intrinsics
        return K, dist

    first_img = cv2.imread(first_rgb_path)
    if first_img is None:
        raise RuntimeError(f"Could not read first RGB frame: {first_rgb_path}")

    height, width = first_img.shape[:2]
    return get_default_intrinsics(width=width, height=height)


def merge_one_cam(
    record_path: str | Path,
    cam_id: str | int | None = "",
    step_size: int = 2,
    *,
    output_dir: str | Path | None = None,
    max_frames: int | None = None,
    depth_min_mm: int = 500,
    depth_trunc: float = 4.0,
    voxel_size: float = 0.01,
    max_iter: int = 80,
    min_fitness: float = 0.0,
    max_rmse: float = 0.05,
    gantry_step_m: float = 0.0,
    gantry_axis: int = 0,
    use_tsdf: bool = False,
    tsdf_voxel_m: float = 0.005,
) -> Path:
    """Run a simple single-camera reconstruction and return the output PLY path."""
    record_path = _resolve_record_path(record_path, cam_id)
    if not record_path.exists():
        raise FileNotFoundError(f"Dataset folder does not exist: {record_path}")

    rgb_dir, depth_dir = _resolve_rgb_depth_dirs(record_path)
    pairs = load_image_pairs(str(rgb_dir), str(depth_dir), step=max(1, int(step_size)))
    if max_frames is not None and max_frames > 0:
        pairs = pairs[:max_frames]

    if not pairs:
        raise RuntimeError(f"No RGB-D pairs found in {record_path}")

    K, dist = _load_intrinsics_for_dataset(record_path, pairs[0][0])

    save_path = Path(output_dir).resolve() if output_dir else record_path / "merge"
    save_path.mkdir(parents=True, exist_ok=True)
    ply_path = save_path / f"merge_pcd_cam{cam_id or 0}.ply"
    summary_path = save_path / "reconstruction_summary.json"

    print(f"[3D_recons] Dataset: {record_path}")
    print(f"[3D_recons] RGB dir:  {rgb_dir}")
    print(f"[3D_recons] Depth dir:{depth_dir}")
    print(f"[3D_recons] Frames:   {len(pairs)} (step={step_size})")
    print(f"[3D_recons] Output:   {ply_path}")

    def on_frame(idx, total, _pcd, fitness, rmse, status):
        print(
            f"[3D_recons] Frame {idx + 1:4d}/{total} | "
            f"{status:9s} | fitness={fitness:.4f} | rmse={rmse:.4f}"
        )

    if use_tsdf:
        print("[3D_recons] --tsdf is deprecated for now; using stakeholder ICP.")

    agent_config = AgentConfig(
        floor_min_fitness=0.0,
        floor_max_rmse=999.0,
        enable_feature_init=False,
    )

    reconstructor = Reconstructor(
        pairs=pairs,
        K=K,
        # Stakeholder path loaded distortion but did not apply it in rgbd2pcd.
        dist=None,
        depth_scale=1000.0,
        depth_trunc=float(depth_trunc),
        voxel_size=float(voxel_size),
        max_iter=int(max_iter),
        gantry_step_m=0.0,
        gantry_axis=0,
        depth_min_mm=int(depth_min_mm),
        erode=False,
        inpaint=False,
        use_known_poses=False,
        tsdf_voxel_m=float(tsdf_voxel_m),
        min_fitness=float(min_fitness),
        max_rmse=float(max_rmse),
        save_path=str(save_path),
        agent_config=agent_config,
        on_frame=on_frame,
    )

    final_pcd, succeed, fail = reconstructor.run()
    if final_pcd is None or final_pcd.is_empty():
        raise RuntimeError("Reconstruction produced an empty point cloud.")

    o3d.io.write_point_cloud(str(ply_path), final_pcd)

    summary = {
        "dataset": str(record_path),
        "rgb_dir": str(rgb_dir),
        "depth_dir": str(depth_dir),
        "output_ply": str(ply_path),
        "frames_used": len(pairs),
        "succeeded": len(succeed),
        "failed": len(fail),
        "points": len(final_pcd.points),
        "step_size": step_size,
        "depth_min_mm": depth_min_mm,
        "depth_trunc_m": depth_trunc,
        "voxel_size_m": voxel_size,
        "use_tsdf": False,
        "pipeline": "stakeholder_icp",
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"[3D_recons] Done. Points: {len(final_pcd.points):,}")
    print(f"[3D_recons] Summary: {summary_path}")
    return ply_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run simple point cloud reconstruction on one RGB-D dataset."
    )
    parser.add_argument("dataset", help="Dataset folder, e.g. data/main/test_plant_...")
    parser.add_argument("--camera-id", default="", help="Optional camera_<id> subfolder.")
    parser.add_argument("--step", type=int, default=2, help="Use every Nth frame.")
    parser.add_argument("--max-frames", type=int, default=30, help="Limit frames for a quick run; 0 = all frames.")
    parser.add_argument("--output", default=None, help="Output folder. Default: <dataset>/merge")
    parser.add_argument("--depth-min-mm", type=int, default=500, help="Ignore depth below this many mm.")
    parser.add_argument("--depth-trunc", type=float, default=4.0, help="Ignore depth beyond this many metres.")
    parser.add_argument("--voxel-size", type=float, default=0.01, help="ICP/final downsample voxel size in metres.")
    parser.add_argument("--max-iter", type=int, default=80, help="ICP iterations per frame.")
    parser.add_argument("--min-fitness", type=float, default=0.0, help="ICP acceptance floor.")
    parser.add_argument("--max-rmse", type=float, default=0.05, help="ICP acceptance ceiling in metres.")
    parser.add_argument("--gantry-step-m", type=float, default=0.0, help="Known motion per sampled frame, if available.")
    parser.add_argument("--gantry-axis", type=int, default=0, choices=(0, 1, 2), help="Axis for gantry-step-m.")
    parser.add_argument("--tsdf", action="store_true", help="Use known-pose TSDF instead of ICP.")
    parser.add_argument("--tsdf-voxel-m", type=float, default=0.005, help="TSDF voxel size in metres.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    max_frames = None if args.max_frames == 0 else args.max_frames
    merge_one_cam(
        args.dataset,
        args.camera_id,
        args.step,
        output_dir=args.output,
        max_frames=max_frames,
        depth_min_mm=args.depth_min_mm,
        depth_trunc=args.depth_trunc,
        voxel_size=args.voxel_size,
        max_iter=args.max_iter,
        min_fitness=args.min_fitness,
        max_rmse=args.max_rmse,
        gantry_step_m=args.gantry_step_m,
        gantry_axis=args.gantry_axis,
        use_tsdf=args.tsdf,
        tsdf_voxel_m=args.tsdf_voxel_m,
    )

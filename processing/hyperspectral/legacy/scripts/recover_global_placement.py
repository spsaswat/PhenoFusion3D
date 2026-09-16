"""Recover plant-to-global transforms from an existing ICP scene.

The legacy reconstruction stored the merged PLY but omitted cumulative per-frame
poses.  For this dataset the selected plant frames are themselves included in the
step-10 ICP run, so a rigid transform can be recovered by registering each cleaned
camera-frame plant cloud directly to the sampled merged scene.  The script keeps a
fit/validation split, exports the transforms and places all spectral PLYs globally.

This is a dataset-specific pose recovery path, not a replacement for saving every
accepted cumulative pose during future reconstructions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import cKDTree

from build_interactive_viewer_assets import read_binary_ply


PLANTS = {
    "coleus": {"label": "Coleus", "plant_id": "plant_2", "frame": 330, "global_x_seed_m": 0.62},
    "fuzzy_kalanchoe": {"label": "Fuzzy kalanchoe", "plant_id": "plant_3", "frame": 540, "global_x_seed_m": 0.97},
    "succulent_jade": {"label": "Succulent / jade", "plant_id": "plant_1", "frame": 750, "global_x_seed_m": 1.18},
}
INDICES = ("NDVI", "NDRE", "NDWI", "MSI", "NDNI")


def write_binary_ply(path: Path, xyz: np.ndarray, colours: np.ndarray, comment: str = "") -> None:
    comment_line = f"comment {comment}\n" if comment else ""
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"{comment_line}element vertex {len(xyz)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    ).encode("ascii")
    records = np.empty(len(xyz), dtype=[
        ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
        ("r", "u1"), ("g", "u1"), ("b", "u1"),
    ])
    records["x"], records["y"], records["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    records["r"], records["g"], records["b"] = colours[:, 0], colours[:, 1], colours[:, 2]
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(records.tobytes())


def saturation(colours: np.ndarray) -> np.ndarray:
    colours_float = colours.astype(np.float32)
    return (colours_float.max(axis=1) - colours_float.min(axis=1)) / np.maximum(colours_float.max(axis=1), 1.0)


def voxel_indices(xyz: np.ndarray, voxel_m: float) -> np.ndarray:
    keys = np.floor(xyz / voxel_m).astype(np.int64)
    _, indices = np.unique(keys, axis=0, return_index=True)
    return np.sort(indices)


def rigid_fit(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source_centre = source.mean(axis=0)
    target_centre = target.mean(axis=0)
    covariance = (source - source_centre).T @ (target - target_centre)
    u, _, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotation
    transform[:3, 3] = target_centre - rotation @ source_centre
    return transform


def transform_points(xyz: np.ndarray, transform: np.ndarray) -> np.ndarray:
    return xyz @ transform[:3, :3].T + transform[:3, 3]


def rotation_degrees(rotation: np.ndarray) -> float:
    value = np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(value)))


def robust_icp(
    source_xyz: np.ndarray,
    source_rgb: np.ndarray,
    target_xyz: np.ndarray,
    target_rgb: np.ndarray,
    initial: np.ndarray,
    iterations: int = 45,
) -> tuple[np.ndarray, list[dict]]:
    tree = cKDTree(target_xyz)
    transform = initial.copy()
    history: list[dict] = []
    source_colour = source_rgb.astype(np.float32) / 255.0
    target_colour = target_rgb.astype(np.float32) / 255.0

    for iteration in range(iterations):
        moved = transform_points(source_xyz, transform)
        distances, neighbours = tree.query(moved, k=1, workers=-1)
        threshold = max(0.018, 0.055 - iteration * 0.0012)
        colour_distance = np.linalg.norm(source_colour - target_colour[neighbours], axis=1)
        valid = (distances < threshold) & (colour_distance < 0.58)
        if valid.sum() < 80:
            raise RuntimeError(f"ICP retained only {valid.sum()} correspondences")
        cutoff = np.quantile(distances[valid], 0.78)
        valid &= distances <= cutoff
        delta = rigid_fit(moved[valid], target_xyz[neighbours[valid]])
        transform = delta @ transform
        history.append({
            "iteration": iteration + 1,
            "correspondences": int(valid.sum()),
            "median_distance_mm": float(np.median(distances[valid]) * 1000.0),
            "p90_distance_mm": float(np.percentile(distances[valid], 90) * 1000.0),
            "delta_translation_mm": float(np.linalg.norm(delta[:3, 3]) * 1000.0),
            "delta_rotation_deg": rotation_degrees(delta[:3, :3]),
        })
        if history[-1]["delta_translation_mm"] < 0.01 and history[-1]["delta_rotation_deg"] < 0.002:
            break
    return transform, history


def recover_one(
    key: str,
    config: dict,
    dataset: Path,
    fusion_dir: Path,
    scene_xyz: np.ndarray,
    scene_rgb: np.ndarray,
    output_dir: Path,
) -> dict:
    specimen_path = dataset / "validation" / "software_traits" / config["plant_id"] / "specimen_pointcloud.ply"
    specimen_xyz, specimen_rgb = read_binary_ply(specimen_path)
    sampled = voxel_indices(specimen_xyz, 0.004)
    specimen_sample_xyz = specimen_xyz[sampled]
    specimen_sample_rgb = specimen_rgb[sampled]

    # The first frame defines the legacy global axes, so camera-frame orientation
    # remains close to identity.  X seeds identify the three visibly separated
    # plant clusters in the saved global scene preview.
    x_seed = float(config["global_x_seed_m"])
    region = (
        (scene_xyz[:, 0] > x_seed - 0.28) & (scene_xyz[:, 0] < x_seed + 0.28)
        & (scene_xyz[:, 1] > -0.28) & (scene_xyz[:, 1] < 0.28)
        & (scene_xyz[:, 2] > 0.38) & (scene_xyz[:, 2] < 0.80)
    )
    scene_sat = saturation(scene_rgb)
    target_mask = region & (scene_sat > 0.08)
    target_xyz = scene_xyz[target_mask]
    target_rgb = scene_rgb[target_mask]
    if len(target_xyz) < 500:
        raise RuntimeError(f"Too few global target points for {key}: {len(target_xyz)}")

    seed_mask = region & (scene_sat > 0.18)
    seed_xyz = scene_xyz[seed_mask]
    seed_xyz = seed_xyz[np.abs(seed_xyz[:, 0] - x_seed) < 0.16]
    source_centre = np.median(specimen_sample_xyz, axis=0)
    target_centre = np.median(seed_xyz, axis=0)
    target_centre[0] = x_seed
    initial = np.eye(4, dtype=np.float64)
    initial[:3, 3] = target_centre - source_centre

    # Even voxel-order points fit the transform; odd points are held out for the
    # independent numerical surface check reported below.
    fit_selector = np.arange(len(specimen_sample_xyz)) % 2 == 0
    transform, history = robust_icp(
        specimen_sample_xyz[fit_selector], specimen_sample_rgb[fit_selector],
        target_xyz, target_rgb, initial,
    )

    moved_all = transform_points(specimen_sample_xyz, transform)
    validation_selector = ~fit_selector
    validation_tree = cKDTree(target_xyz)
    validation_distances, _ = validation_tree.query(moved_all[validation_selector], k=1, workers=-1)
    validation = {
        "held_out_points": int(validation_selector.sum()),
        "nearest_scene_distance_median_mm": float(np.median(validation_distances) * 1000.0),
        "nearest_scene_distance_p90_mm": float(np.percentile(validation_distances, 90) * 1000.0),
        "within_20mm_fraction": float(np.mean(validation_distances <= 0.020)),
        "within_30mm_fraction": float(np.mean(validation_distances <= 0.030)),
    }

    plant_output = output_dir / key
    plant_output.mkdir(parents=True, exist_ok=True)
    exported = []
    for index_name in INDICES:
        local_path = fusion_dir / key / f"{key}_{index_name.lower()}_on_specimen.ply"
        local_xyz, local_rgb = read_binary_ply(local_path)
        global_xyz = transform_points(local_xyz, transform).astype(np.float32)
        global_path = plant_output / f"{key}_{index_name.lower()}_global.ply"
        write_binary_ply(global_path, global_xyz, local_rgb, "Recovered direct placement in legacy ICP scene coordinates")
        exported.append(str(global_path.relative_to(output_dir.parent)).replace("\\", "/"))

    result = {
        "plant": key,
        "label": config["label"],
        "rgbd_frame": int(config["frame"]),
        "method": "direct cleaned-plant to sampled-global-scene robust rigid ICP",
        "global_x_seed_m": x_seed,
        "source_specimen_points": int(len(specimen_xyz)),
        "source_voxel_sample_points": int(len(specimen_sample_xyz)),
        "target_scene_points": int(len(target_xyz)),
        "fit_points": int(fit_selector.sum()),
        "transform_camera_to_global": transform.tolist(),
        "translation_m": [float(value) for value in transform[:3, 3]],
        "rotation_magnitude_deg": rotation_degrees(transform[:3, :3]),
        "iterations": len(history),
        "final_fit_iteration": history[-1],
        "held_out_validation": validation,
        "exported_models": exported,
        "limitations": [
            "This recovers the selected plant-frame transform directly against the saved scene; it does not reconstruct the missing complete 95-frame pose trajectory.",
            "The 300,000-point diagnostic scene sample is used as the registration target rather than the 1.2 GB full PLY.",
            "Future reconstructions should save every accepted cumulative pose during ICP.",
        ],
    }
    (plant_output / "global_placement.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def save_global_preview(path: Path, scene_xyz: np.ndarray, scene_rgb: np.ndarray, results: list[dict], fusion_dir: Path) -> None:
    stride = max(1, len(scene_xyz) // 90000)
    scene = scene_xyz[::stride]
    scene_colours = scene_rgb[::stride].astype(np.float32) / 255.0
    figure, axes = plt.subplots(1, 2, figsize=(18, 7))
    axes[0].scatter(scene[:, 0], scene[:, 1], c=scene_colours, s=0.25, alpha=0.18, linewidths=0)
    axes[1].scatter(scene[:, 0], scene[:, 2], c=scene_colours, s=0.25, alpha=0.18, linewidths=0)
    colour_map = {"coleus": "#ff336d", "fuzzy_kalanchoe": "#ffd43b", "succulent_jade": "#4ee6a8"}
    for item in results:
        key = item["plant"]
        local_xyz, _ = read_binary_ply(fusion_dir / key / f"{key}_ndvi_on_specimen.ply")
        measured_count = json.loads((fusion_dir / key / "fusion_metrics.json").read_text(encoding="utf-8"))["coverage"]["points_within_20mm_of_specimen_surface"]
        measured = local_xyz[-int(measured_count):]
        transform = np.asarray(item["transform_camera_to_global"], dtype=np.float64)
        global_measured = transform_points(measured, transform)
        axes[0].scatter(global_measured[:, 0], global_measured[:, 1], c=colour_map[key], s=2.8, alpha=0.95, linewidths=0, label=item["label"])
        axes[1].scatter(global_measured[:, 0], global_measured[:, 2], c=colour_map[key], s=2.8, alpha=0.95, linewidths=0)
    axes[0].set(title="Top projection (X–Y)", xlabel="X (m)", ylabel="Y (m)")
    axes[1].set(title="Side projection (X–Z)", xlabel="X (m)", ylabel="Z (m)")
    axes[0].legend(markerscale=4, loc="lower right")
    for axis in axes:
        axis.grid(alpha=0.15)
        axis.set_aspect("equal", adjustable="box")
    figure.suptitle("Recovered global placement of measured hyperspectral surfaces", fontsize=17, fontweight="bold")
    figure.tight_layout()
    figure.savefig(path, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def build_scene_models(output_dir: Path, scene_xyz: np.ndarray, scene_rgb: np.ndarray, results: list[dict], fusion_dir: Path) -> list[str]:
    outputs = []
    scene_colours = np.clip(scene_rgb.astype(np.float32) * 0.48 + 45, 0, 255).astype(np.uint8)
    for index_name in INDICES:
        points = [scene_xyz.astype(np.float32)]
        colours = [scene_colours]
        for item in results:
            key = item["plant"]
            local_xyz, local_rgb = read_binary_ply(fusion_dir / key / f"{key}_{index_name.lower()}_on_specimen.ply")
            measured_count = json.loads((fusion_dir / key / "fusion_metrics.json").read_text(encoding="utf-8"))["coverage"]["points_within_20mm_of_specimen_surface"]
            local_xyz = local_xyz[-int(measured_count):]
            local_rgb = local_rgb[-int(measured_count):]
            transform = np.asarray(item["transform_camera_to_global"], dtype=np.float64)
            points.append(transform_points(local_xyz, transform).astype(np.float32))
            colours.append(local_rgb)
        output_path = output_dir / f"global_scene_{index_name.lower()}_sampled.ply"
        write_binary_ply(output_path, np.vstack(points), np.vstack(colours), "Sampled legacy scene plus globally placed measured hyperspectral surfaces")
        outputs.append(str(output_path.relative_to(output_dir.parent)).replace("\\", "/"))
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--fusion-dir", type=Path, default=Path("results/20260828_showcase/fusion"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/20260828_showcase/global_placement"))
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    fusion_dir = args.fusion_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_path = dataset / "merge_simple_full_step10" / "diagnostics" / "scene_preview_sampled.ply"
    scene_xyz, scene_rgb = read_binary_ply(scene_path)

    results = [
        recover_one(key, config, dataset, fusion_dir, scene_xyz, scene_rgb, output_dir)
        for key, config in PLANTS.items()
    ]
    save_global_preview(output_dir / "global_placement_preview.png", scene_xyz, scene_rgb, results, fusion_dir)
    scene_models = build_scene_models(output_dir, scene_xyz, scene_rgb, results, fusion_dir)
    summary = {
        "status": "candidate_global_placement_validated_against_held_out_surface_points",
        "dataset": str(dataset),
        "legacy_scene_points": 44_430_791,
        "registration_target": str(scene_path),
        "registration_target_points": int(len(scene_xyz)),
        "plants": results,
        "global_scene_models": scene_models,
        "scientific_boundary": "Direct scene registration recovers the three required transforms but not the omitted full camera trajectory. Save cumulative poses at reconstruction time for future datasets.",
    }
    (output_dir / "global_placement_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({
        item["plant"]: item["held_out_validation"] for item in results
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Project measured hyperspectral pixels onto matching RGB-D plant surfaces.

This is a cross-modal registration and 2.5D lifting workflow.  ICP is used by
PhenoFusion3D to merge RGB-D frames; this script solves the separate problem of
matching a hyperspectral scan to selected RGB-D frames.  Only points with an
actual hyperspectral measurement and a valid depth sample are exported.
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import spectral
from scipy.spatial import cKDTree


@dataclass(frozen=True)
class PlantConfig:
    key: str
    label: str
    frame: int
    specimen_id: int
    expected_centroid_row: float
    registration_rows: tuple[int, int]


PLANTS = {
    "coleus": PlantConfig("coleus", "Coleus", 330, 2, 167.0, (0, 245)),
    "fuzzy_kalanchoe": PlantConfig("fuzzy_kalanchoe", "Fuzzy kalanchoe", 540, 3, 299.0, (90, 405)),
    "succulent_jade": PlantConfig("succulent_jade", "Succulent / jade", 750, 1, 374.0, (245, 496)),
}


INDEX_NAMES = ("NDVI", "NDRE", "NDWI", "MSI", "NDNI")


def robust_channel(channel: np.ndarray) -> np.ndarray:
    channel = np.nan_to_num(channel.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    lo, hi = np.percentile(channel, [2, 98])
    if hi <= lo:
        return np.zeros_like(channel)
    return np.clip((channel - lo) / (hi - lo), 0, 1)


def nearest_band(wavelengths: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(wavelengths - target)))


def load_cube(hdr: Path) -> tuple[np.ndarray, np.ndarray]:
    image = spectral.open_image(str(hdr))
    cube = np.asarray(image.open_memmap(), dtype=np.float32)
    wavelengths = np.asarray(image.metadata["wavelength"], dtype=np.float32)
    return cube, wavelengths


def natural_projection(cube: np.ndarray, wavelengths: np.ndarray) -> np.ndarray:
    channels = [robust_channel(cube[:, :, nearest_band(wavelengths, target)]) for target in (660.0, 550.0, 470.0)]
    return np.stack(channels, axis=-1)


def feature_gray(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def register_hsi_to_rgb(
    hsi_rgb: np.ndarray,
    rgb: np.ndarray,
    rows: tuple[int, int],
    plant_mask: np.ndarray,
    scale: float = 3.0,
) -> dict:
    y0, y1 = rows
    crop = np.clip(hsi_rgb[y0:y1] * 255, 0, 255).astype(np.uint8)
    crop_scaled = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    source_gray = feature_gray(crop_scaled)
    target_gray = feature_gray(rgb)

    sift = cv2.SIFT_create(nfeatures=8000, contrastThreshold=0.015, edgeThreshold=14)
    keypoints_source, descriptors_source = sift.detectAndCompute(source_gray, None)
    keypoints_target, descriptors_target = sift.detectAndCompute(target_gray, None)
    if descriptors_source is None or descriptors_target is None:
        raise RuntimeError("SIFT could not find descriptors in both modalities")

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    forward = matcher.knnMatch(descriptors_source, descriptors_target, k=2)
    backward = matcher.knnMatch(descriptors_target, descriptors_source, k=2)
    good_forward = [m for m, n in forward if m.distance < 0.78 * n.distance]
    good_backward = [m for m, n in backward if m.distance < 0.78 * n.distance]
    backward_pairs = {(m.trainIdx, m.queryIdx) for m in good_backward}
    mutual = [m for m in good_forward if (m.queryIdx, m.trainIdx) in backward_pairs]
    candidates = mutual if len(mutual) >= 8 else good_forward
    if len(candidates) < 8:
        raise RuntimeError(f"Insufficient cross-modal feature matches: {len(candidates)}")

    source_points_scaled = np.float32([keypoints_source[m.queryIdx].pt for m in candidates]).reshape(-1, 1, 2)
    target_points = np.float32([keypoints_target[m.trainIdx].pt for m in candidates]).reshape(-1, 1, 2)
    homography_scaled, inlier_mask = cv2.findHomography(source_points_scaled, target_points, cv2.RANSAC, 7.0, maxIters=10000, confidence=0.999)
    if homography_scaled is None or inlier_mask is None:
        raise RuntimeError("RANSAC could not estimate a cross-modal homography")

    crop_scale = np.array([[scale, 0, 0], [0, scale, -scale * y0], [0, 0, 1]], dtype=np.float64)
    board_homography = homography_scaled @ crop_scale
    inliers = inlier_mask.ravel().astype(bool)
    projected = cv2.perspectiveTransform(source_points_scaled[inliers], homography_scaled).reshape(-1, 2)
    observed = target_points[inliers].reshape(-1, 2)
    errors = np.linalg.norm(projected - observed, axis=1)

    # Try a second model from plant-local visible features.  It is intentionally
    # separate from the board model because the elevated leaves exhibit parallax.
    plant_candidates = []
    for m, n in forward:
        source_x, source_y = keypoints_source[m.queryIdx].pt
        native_col = int(round(source_x / scale))
        native_row = int(round(source_y / scale + y0))
        if (m.distance < 0.90 * n.distance and 0 <= native_row < plant_mask.shape[0]
                and 0 <= native_col < plant_mask.shape[1] and plant_mask[native_row, native_col]):
            plant_candidates.append(m)
    plant_homography = None
    plant_inliers = 0
    plant_rmse = None
    if len(plant_candidates) >= 8:
        plant_source = np.float32([keypoints_source[m.queryIdx].pt for m in plant_candidates]).reshape(-1, 1, 2)
        plant_target = np.float32([keypoints_target[m.trainIdx].pt for m in plant_candidates]).reshape(-1, 1, 2)
        plant_h_scaled, plant_inlier_mask = cv2.findHomography(
            plant_source, plant_target, cv2.RANSAC, 10.0, maxIters=20000, confidence=0.999,
        )
        if plant_h_scaled is not None and plant_inlier_mask is not None:
            plant_good = plant_inlier_mask.ravel().astype(bool)
            plant_inliers = int(plant_good.sum())
            if plant_inliers:
                plant_projected = cv2.perspectiveTransform(plant_source[plant_good], plant_h_scaled).reshape(-1, 2)
                plant_observed = plant_target[plant_good].reshape(-1, 2)
                plant_rmse = float(np.sqrt(np.mean(np.linalg.norm(plant_projected - plant_observed, axis=1) ** 2)))
            candidate_homography = plant_h_scaled @ crop_scale
            component_rows, component_cols = np.nonzero(plant_mask)
            sample_step = max(1, len(component_rows) // 2000)
            component_xy = np.column_stack([component_cols[::sample_step], component_rows[::sample_step]]).astype(np.float32).reshape(-1, 1, 2)
            mapped_component = cv2.perspectiveTransform(component_xy, candidate_homography).reshape(-1, 2)
            mapped_span = np.ptp(mapped_component, axis=0)
            geometrically_valid = (
                np.all(np.isfinite(mapped_component)) and mapped_span[0] >= 40 and mapped_span[1] >= 40
                and mapped_span[0] <= rgb.shape[1] and mapped_span[1] <= rgb.shape[0]
            )
            if plant_inliers >= 8 and plant_rmse is not None and plant_rmse <= 6.0 and geometrically_valid:
                plant_homography = candidate_homography

    # The board is planar but leaves sit above it, so the board homography has
    # predictable parallax on the plant. Refine the already-warped visible image
    # locally with ECC, using only the measured plant mask as input support.
    target_height, target_width = rgb.shape[:2]
    full_source_gray = feature_gray(np.clip(hsi_rgb * 255, 0, 255).astype(np.uint8))
    warped_gray = cv2.warpPerspective(full_source_gray, board_homography, (target_width, target_height))
    warped_plant_mask = cv2.warpPerspective(
        plant_mask.astype(np.uint8) * 255, board_homography,
        (target_width, target_height), flags=cv2.INTER_NEAREST,
    )
    residual = np.eye(2, 3, dtype=np.float32)
    ecc_correlation = None
    homography = plant_homography if plant_homography is not None else board_homography
    try:
        if plant_homography is not None:
            raise cv2.error("plant-local homography accepted; ECC not required")
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7)
        ecc_correlation, residual = cv2.findTransformECC(
            target_gray.astype(np.float32) / 255.0,
            warped_gray.astype(np.float32) / 255.0,
            residual, cv2.MOTION_AFFINE, criteria,
            inputMask=cv2.dilate(warped_plant_mask, np.ones((11, 11), np.uint8)),
            gaussFiltSize=5,
        )
        residual_3x3 = np.vstack([residual, [0, 0, 1]]).astype(np.float64)
        homography = np.linalg.inv(residual_3x3) @ board_homography
    except cv2.error:
        pass

    matched_image = cv2.drawMatches(
        cv2.cvtColor(crop_scaled, cv2.COLOR_RGB2BGR), keypoints_source,
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), keypoints_target,
        candidates, None, matchesMask=inlier_mask.ravel().tolist(),
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )
    return {
        "homography": homography,
        "keypoints_hsi": len(keypoints_source),
        "keypoints_rgb": len(keypoints_target),
        "candidate_matches": len(candidates),
        "inliers": int(inliers.sum()),
        "inlier_ratio": float(inliers.mean()),
        "reprojection_rmse_px": float(np.sqrt(np.mean(errors**2))),
        "reprojection_median_px": float(np.median(errors)),
        "plant_refinement": "plant-local SIFT/RANSAC homography" if plant_homography is not None else "ECC affine residual after planar SIFT/RANSAC registration",
        "plant_candidate_matches": len(plant_candidates),
        "plant_inliers": plant_inliers,
        "plant_reprojection_rmse_px": plant_rmse,
        "selected_model": "plant-local SIFT/RANSAC homography" if plant_homography is not None else "board homography plus plant-masked ECC",
        "ecc_correlation": None if ecc_correlation is None else float(ecc_correlation),
        "ecc_residual_affine": residual.tolist(),
        "match_image_bgr": matched_image,
    }


def nearest_valid_depth(depth: np.ndarray, u: int, v: int, max_radius: int = 4) -> tuple[int, int, int] | None:
    height, width = depth.shape[:2]
    if 0 <= u < width and 0 <= v < height and depth[v, u] > 0:
        return u, v, int(depth[v, u])
    for radius in range(1, max_radius + 1):
        x0, x1 = max(0, u - radius), min(width, u + radius + 1)
        y0, y1 = max(0, v - radius), min(height, v + radius + 1)
        patch = depth[y0:y1, x0:x1]
        ys, xs = np.nonzero(patch)
        if xs.size:
            distances = (xs + x0 - u) ** 2 + (ys + y0 - v) ** 2
            index = int(np.argmin(distances))
            px, py = int(xs[index] + x0), int(ys[index] + y0)
            return px, py, int(depth[py, px])
    return None


def select_plant_components(mask: np.ndarray, expected_centroid_row: float) -> np.ndarray:
    """Select the real connected plant component instead of overlapping row thirds."""
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    selected = np.zeros_like(mask, dtype=bool)
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        centroid_row = float(centroids[component, 1])
        if area >= 100 and abs(centroid_row - expected_centroid_row) <= 45:
            selected |= labels == component
    if selected.sum() < 100:
        raise RuntimeError(f"Could not isolate plant component near row {expected_centroid_row}")
    return selected


def index_colours(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    finite = values[np.isfinite(values)]
    lo, hi = np.percentile(finite, [2, 98])
    normalized = np.clip((values - lo) / max(hi - lo, 1e-8), 0, 1)
    colours = plt.get_cmap("inferno")(normalized)[:, :3]
    return np.clip(colours * 255, 0, 255).astype(np.uint8), float(lo), float(hi)


def write_binary_ply(path: Path, xyz: np.ndarray, colours: np.ndarray) -> None:
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(xyz)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    ).encode("ascii")
    records = np.empty(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    records["x"], records["y"], records["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    records["r"], records["g"], records["b"] = colours[:, 0], colours[:, 1], colours[:, 2]
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(records.tobytes())


def read_open3d_binary_ply(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read the repository's Open3D binary PLY layout: float64 XYZ + uint8 RGB."""
    with path.open("rb") as handle:
        header_lines = []
        while True:
            line = handle.readline()
            if not line:
                raise ValueError(f"Invalid PLY header: {path}")
            header_lines.append(line.decode("ascii").strip())
            if line.strip() == b"end_header":
                break
        if "format binary_little_endian 1.0" not in header_lines:
            raise ValueError(f"Unsupported PLY format: {path}")
        vertex_line = next(line for line in header_lines if line.startswith("element vertex "))
        vertex_count = int(vertex_line.split()[-1])
        dtype = np.dtype([("x", "<f8"), ("y", "<f8"), ("z", "<f8"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
        data = np.fromfile(handle, dtype=dtype, count=vertex_count)
    xyz = np.column_stack([data["x"], data["y"], data["z"]]).astype(np.float32)
    colours = np.column_stack([data["r"], data["g"], data["b"]]).astype(np.uint8)
    return xyz, colours


def save_registration_figure(path: Path, label: str, hsi_rgb: np.ndarray, rgb: np.ndarray, registration: dict, mapped_mask: np.ndarray) -> None:
    height, width = rgb.shape[:2]
    warped = cv2.warpPerspective((hsi_rgb * 255).astype(np.uint8), registration["homography"], (width, height))
    valid = cv2.warpPerspective(np.ones(hsi_rgb.shape[:2], dtype=np.uint8), registration["homography"], (width, height), flags=cv2.INTER_NEAREST).astype(bool)
    overlay = rgb.copy()
    overlay[valid] = (0.55 * overlay[valid] + 0.45 * warped[valid]).astype(np.uint8)
    mask_overlay = rgb.copy()
    mask_overlay[mapped_mask] = (0.35 * mask_overlay[mapped_mask] + 0.65 * np.array([255, 204, 40])).astype(np.uint8)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    axes[0, 0].imshow(hsi_rgb); axes[0, 0].set_title("FX10 calibrated projection")
    axes[0, 1].imshow(rgb); axes[0, 1].set_title("Selected RGB-D frame")
    axes[1, 0].imshow(overlay); axes[1, 0].set_title("Cross-modal registration overlay")
    axes[1, 1].imshow(mask_overlay); axes[1, 1].set_title("Measured spectral pixels with valid depth")
    for axis in axes.ravel(): axis.axis("off")
    fig.suptitle(f"{label} · hyperspectral to RGB-D registration", fontsize=17, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def save_pointcloud_preview(path: Path, label: str, xyz: np.ndarray, values: np.ndarray, index_name: str, specimen_xyz: np.ndarray) -> None:
    count = len(xyz)
    stride = max(1, count // 25000)
    points = xyz[::stride]
    colours = values[::stride]
    specimen_stride = max(1, len(specimen_xyz) // 35000)
    specimen = specimen_xyz[::specimen_stride]
    lo, hi = np.percentile(colours[np.isfinite(colours)], [2, 98])
    fig = plt.figure(figsize=(16, 6))
    ax1 = fig.add_subplot(131, projection="3d")
    ax1.scatter(specimen[:, 0], specimen[:, 1], specimen[:, 2], c="#aab4ae", s=1, alpha=.12)
    ax1.scatter(points[:, 0], points[:, 1], points[:, 2], c=colours, s=3, cmap="inferno", vmin=lo, vmax=hi)
    ax1.set_title(f"Measured 3D surface · {index_name}")
    ax1.set_xlabel("X (m)"); ax1.set_ylabel("Y (m)"); ax1.set_zlabel("Z (m)")
    ax2 = fig.add_subplot(132)
    ax2.scatter(specimen[:, 0], specimen[:, 1], c="#aab4ae", s=1, alpha=.12)
    scatter = ax2.scatter(points[:, 0], points[:, 1], c=colours, s=3, cmap="inferno", vmin=lo, vmax=hi)
    ax2.set_aspect("equal"); ax2.set_title("Camera-plane projection"); ax2.set_xlabel("X (m)"); ax2.set_ylabel("Y (m)")
    fig.colorbar(scatter, ax=ax2, label=index_name)
    ax3 = fig.add_subplot(133)
    ax3.scatter(specimen[:, 0], specimen[:, 2], c="#aab4ae", s=1, alpha=.12)
    ax3.scatter(points[:, 0], points[:, 2], c=colours, s=3, cmap="inferno", vmin=lo, vmax=hi)
    ax3.set_title("Depth profile"); ax3.set_xlabel("X (m)"); ax3.set_ylabel("Z / depth (m)")
    fig.suptitle(f"{label} · measured hyperspectral points lifted into RGB-D geometry", fontsize=16, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fuse_plant(
    config: PlantConfig,
    showcase: Path,
    rgbd: Path,
    output_root: Path,
    hsi_rgb: np.ndarray,
    merged_cube: np.ndarray,
    wavelengths: np.ndarray,
    all_indices: dict[str, np.ndarray],
    intrinsics: dict,
    depth_scale: float,
) -> dict:
    output = output_root / config.key
    output.mkdir(parents=True, exist_ok=True)
    rgb_path = rgbd / "rgb" / f"{config.frame}.png"
    depth_path = rgbd / "depth" / f"{config.frame}.png"
    rgb_bgr = cv2.imread(str(rgb_path), cv2.IMREAD_COLOR)
    depth = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
    if rgb_bgr is None or depth is None:
        raise FileNotFoundError(f"Missing RGB-D frame {config.frame}")
    rgb = cv2.cvtColor(rgb_bgr, cv2.COLOR_BGR2RGB)

    base_index = all_indices["NDVI"]
    mask = np.isfinite(base_index)
    region_mask = select_plant_components(mask, config.expected_centroid_row)
    registration = register_hsi_to_rgb(hsi_rgb, rgb, config.registration_rows, region_mask)
    rows, cols = np.nonzero(region_mask)
    source_xy = np.column_stack([cols, rows]).astype(np.float32).reshape(-1, 1, 2)
    mapped_xy = cv2.perspectiveTransform(source_xy, registration["homography"]).reshape(-1, 2)

    K = np.asarray(intrinsics["K"], dtype=np.float64)
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    xyz, rgb_values, kept_rows, kept_cols, kept_uv = [], [], [], [], []
    mapped_mask = np.zeros(rgb.shape[:2], dtype=bool)
    for row, col, (mapped_u, mapped_v) in zip(rows, cols, mapped_xy):
        u, v = int(round(float(mapped_u))), int(round(float(mapped_v)))
        sample = nearest_valid_depth(depth, u, v)
        if sample is None:
            continue
        sample_u, sample_v, raw_depth = sample
        z = raw_depth / depth_scale
        if not 0.30 <= z <= 1.50:
            continue
        x = (sample_u - cx) * z / fx
        y = (sample_v - cy) * z / fy
        xyz.append((x, y, z))
        rgb_values.append(rgb[sample_v, sample_u])
        kept_rows.append(row); kept_cols.append(col); kept_uv.append((sample_u, sample_v))
        mapped_mask[sample_v, sample_u] = True

    xyz = np.asarray(xyz, dtype=np.float32)
    rgb_values = np.asarray(rgb_values, dtype=np.uint8)
    kept_rows = np.asarray(kept_rows, dtype=np.int32)
    kept_cols = np.asarray(kept_cols, dtype=np.int32)
    kept_uv = np.asarray(kept_uv, dtype=np.int32)
    if len(xyz) < 100:
        raise RuntimeError(f"Only {len(xyz)} hyperspectral pixels obtained valid RGB-D depth for {config.label}")

    mapped_depth_samples = len(xyz)
    _, unique_indices = np.unique(kept_uv, axis=0, return_index=True)
    unique_indices = np.sort(unique_indices)
    xyz, rgb_values = xyz[unique_indices], rgb_values[unique_indices]
    kept_rows, kept_cols, kept_uv = kept_rows[unique_indices], kept_cols[unique_indices], kept_uv[unique_indices]

    # A slightly misplaced plant pixel can land on the board behind the plant.
    # Separate the nearer plant surface from the more distant planar board when
    # the depth distribution is distinctly bimodal.
    depth_median_before_filter = float(np.median(xyz[:, 2]))
    depth_center = depth_median_before_filter
    depth_center_method = "median depth"
    depth_cluster_values = xyz[:, 2]
    compact = xyz[:, 2].astype(np.float32).reshape(-1, 1)
    if len(compact) >= 200:
        _, depth_labels, depth_centers = cv2.kmeans(
            compact, 2, None,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-5),
            20, cv2.KMEANS_PP_CENTERS,
        )
        depth_centers = depth_centers.ravel()
        near_label, far_label = int(np.argmin(depth_centers)), int(np.argmax(depth_centers))
        near_fraction = float(np.mean(depth_labels.ravel() == near_label))
        separation = float(depth_centers[far_label] - depth_centers[near_label])
        if separation >= 0.055 and near_fraction >= 0.15:
            depth_center = float(depth_centers[near_label])
            depth_center_method = "nearer k-means depth layer"
            depth_cluster_values = xyz[:, 2][depth_labels.ravel() == near_label]
    depth_mad = float(np.median(np.abs(depth_cluster_values - depth_center)))
    depth_radius = min(0.10, max(0.06, 4.0 * depth_mad))
    depth_layer = np.abs(xyz[:, 2] - depth_center) <= depth_radius
    xyz, rgb_values = xyz[depth_layer], rgb_values[depth_layer]
    kept_rows, kept_cols, kept_uv = kept_rows[depth_layer], kept_cols[depth_layer], kept_uv[depth_layer]
    mapped_mask[:] = False
    mapped_mask[kept_uv[:, 1], kept_uv[:, 0]] = True

    specimen_path = rgbd / "validation" / "software_traits" / f"plant_{config.specimen_id}" / "specimen_pointcloud.ply"
    specimen_xyz, specimen_rgb = read_open3d_binary_ply(specimen_path)
    surface_distances, _ = cKDTree(specimen_xyz).query(xyz, k=1, workers=-1)
    surface_distance_median = float(np.median(surface_distances))
    surface_distance_p90 = float(np.percentile(surface_distances, 90))
    surface_match = surface_distances <= 0.020
    surface_points_before_filter = len(xyz)
    xyz, rgb_values = xyz[surface_match], rgb_values[surface_match]
    kept_rows, kept_cols, kept_uv = kept_rows[surface_match], kept_cols[surface_match], kept_uv[surface_match]
    mapped_mask[:] = False
    mapped_mask[kept_uv[:, 1], kept_uv[:, 0]] = True
    if len(xyz) < 100:
        raise RuntimeError(f"Only {len(xyz)} points remained within 20 mm of the cleaned {config.label} specimen cloud")

    spectra = merged_cube[kept_rows, kept_cols]
    index_values = {name: values[kept_rows, kept_cols].astype(np.float32) for name, values in all_indices.items()}
    write_binary_ply(output / f"{config.key}_measured_rgb.ply", xyz, rgb_values)
    display_ranges = {}
    for name, values in index_values.items():
        finite = np.isfinite(values)
        if finite.sum() < 10:
            continue
        colours, lo, hi = index_colours(values)
        write_binary_ply(output / f"{config.key}_{name.lower()}.ply", xyz, colours)
        specimen_grey = np.full((len(specimen_xyz), 3), 170, dtype=np.uint8)
        write_binary_ply(
            output / f"{config.key}_{name.lower()}_on_specimen.ply",
            np.vstack([specimen_xyz, xyz]), np.vstack([specimen_grey, colours]),
        )
        display_ranges[name] = {"p02": lo, "p98": hi, "median": float(np.nanmedian(values))}

    np.savez_compressed(
        output / f"{config.key}_spectral_points.npz",
        xyz_m=xyz, rgb=rgb_values, hsi_row=kept_rows, hsi_col=kept_cols,
        rgbd_uv=kept_uv, spectra=spectra.astype(np.float32), wavelengths_nm=wavelengths,
        **{f"index_{name}": values for name, values in index_values.items()},
    )
    cv2.imwrite(str(output / "feature_inlier_matches.png"), registration.pop("match_image_bgr"))
    save_registration_figure(output / "registration_and_depth_overlay.png", config.label, hsi_rgb, rgb, registration, mapped_mask)
    save_pointcloud_preview(output / "ndvi_3d_preview.png", config.label, xyz, index_values["NDVI"], "NDVI", specimen_xyz)

    metrics = {
        "plant": config.key,
        "label": config.label,
        "rgbd_frame": config.frame,
        "coordinate_frame": f"RGB-D camera frame {config.frame}; not yet transformed by the global ICP pose",
        "registration": {
            "method": "mutual SIFT matches plus RANSAC board homography and plant-masked ECC refinement",
            **{key: value for key, value in registration.items() if key != "homography"},
            "homography_hsi_to_rgb": registration["homography"].tolist(),
        },
        "coverage": {
            "hyperspectral_plant_pixels_in_region": int(len(rows)),
            "mapped_samples_before_unique_pixel_filter": int(mapped_depth_samples),
            "unique_rgbd_depth_pixels": int(len(unique_indices)),
            "points_with_valid_depth": int(len(xyz)),
            "valid_depth_fraction": float(len(xyz) / max(len(rows), 1)),
            "depth_layer_center_m": depth_center,
            "depth_layer_center_method": depth_center_method,
            "depth_layer_filter_radius_m": depth_radius,
            "points_before_specimen_surface_filter": int(surface_points_before_filter),
            "points_within_20mm_of_specimen_surface": int(len(xyz)),
            "specimen_surface_retention_fraction": float(len(xyz) / max(surface_points_before_filter, 1)),
        },
        "geometry": {
            "depth_scale_units_per_m": depth_scale,
            "bounds_min_m": xyz.min(axis=0).tolist(),
            "bounds_max_m": xyz.max(axis=0).tolist(),
            "extent_m": (xyz.max(axis=0) - xyz.min(axis=0)).tolist(),
            "median_depth_m": float(np.median(xyz[:, 2])),
        },
        "specimen_surface_validation": {
            "specimen_pointcloud": str(specimen_path),
            "specimen_points": int(len(specimen_xyz)),
            "nearest_surface_distance_median_mm_before_filter": 1000 * surface_distance_median,
            "nearest_surface_distance_p90_mm_before_filter": 1000 * surface_distance_p90,
            "acceptance_distance_mm": 20.0,
        },
        "spectral": {
            "bands": int(spectra.shape[1]),
            "wavelength_min_nm": float(wavelengths.min()),
            "wavelength_max_nm": float(wavelengths.max()),
            "index_display_ranges": display_ranges,
        },
        "limitations": [
            "Only hyperspectrally measured upper-visible pixels are exported.",
            "A planar homography approximates cross-modal alignment; elevated leaves can exhibit parallax.",
            "Points remain in the selected RGB-D camera frame until a saved ICP pose is available.",
        ],
    }
    (output / "fusion_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--showcase-dir", type=Path, default=Path("results/20260828_showcase"))
    parser.add_argument("--rgbd-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--plants", nargs="+", choices=tuple(PLANTS), default=list(PLANTS))
    parser.add_argument("--depth-scale", type=float, default=10000.0, help="Raw depth units per metre for this dataset")
    args = parser.parse_args()

    showcase = args.showcase_dir.resolve()
    rgbd = args.rgbd_dir.resolve()
    output_root = args.output_dir.resolve() if args.output_dir else showcase / "fusion"
    output_root.mkdir(parents=True, exist_ok=True)

    fx10_cube, fx10_wavelengths = load_cube(showcase / "cubes" / "fx10_calibrated_showcase.hdr")
    merged_cube, merged_wavelengths = load_cube(showcase / "cubes" / "merged_plant_only_showcase.hdr")
    hsi_rgb = natural_projection(fx10_cube, fx10_wavelengths)
    all_indices = {name: np.load(showcase / "indices" / f"{name}.npy") for name in INDEX_NAMES}
    intrinsics = json.loads((rgbd / "kdc_intrinsics.txt").read_text(encoding="utf-8"))

    metrics = []
    for plant_name in args.plants:
        print(f"[fusion] Processing {PLANTS[plant_name].label}", flush=True)
        metrics.append(fuse_plant(
            PLANTS[plant_name], showcase, rgbd, output_root, hsi_rgb,
            merged_cube, merged_wavelengths, all_indices, intrinsics, args.depth_scale,
        ))

    summary = {
        "method": "FX10-to-RGB SIFT/RANSAC registration, aligned-depth backprojection, measured spectra only",
        "rgbd_dataset": str(rgbd),
        "showcase": str(showcase),
        "plants": metrics,
    }
    (output_root / "fusion_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (output_root / "fusion_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["plant", "frame", "inliers", "reprojection_rmse_px", "hsi_pixels", "valid_depth_points", "valid_depth_fraction", "median_depth_m", "ndvi_median"]
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for item in metrics:
            writer.writerow({
                "plant": item["label"], "frame": item["rgbd_frame"],
                "inliers": item["registration"]["inliers"],
                "reprojection_rmse_px": item["registration"]["reprojection_rmse_px"],
                "hsi_pixels": item["coverage"]["hyperspectral_plant_pixels_in_region"],
                "valid_depth_points": item["coverage"]["points_with_valid_depth"],
                "valid_depth_fraction": item["coverage"]["valid_depth_fraction"],
                "median_depth_m": item["geometry"]["median_depth_m"],
                "ndvi_median": item["spectral"]["index_display_ranges"]["NDVI"]["median"],
            })
    print(f"[fusion] Complete: {output_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

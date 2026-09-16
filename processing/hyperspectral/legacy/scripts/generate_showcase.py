#!/usr/bin/env python3
"""Generate a reusable, headless hyperspectral showcase from a paired FX10/FX17 scan.

The interactive application is useful for exploration, but it does not save every
plot and its full-resolution calibration is memory hungry.  This script keeps all
224 spectral bands while spatially sampling the scene for a presentation-ready
bundle.  The source ENVI files are opened read-only and never modified.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import spectral
from scipy.optimize import minimize


CAMERAS = {
    "fx10": {
        "white": (77, 110, 165, 900),
        "dark": (2091, 2100, 165, 900),
        "scene": (110, 2091, 165, 900),
        "rgb": (660.0, 550.0, 470.0),
        "label": "FX10 · VNIR · 398–1004 nm",
    },
    "fx17": {
        "white": (28, 30, 75, 545),
        "dark": (2085, 2087, 100, 540),
        "scene": (30, 2085, 75, 545),
        "rgb": (1600.0, 1300.0, 1050.0),
        "label": "FX17 · SWIR · 936–1720 nm",
    },
}

INDEX_FORMULAS = {
    "NDVI": "(R800 − R680) / (R800 + R680)",
    "NPCI": "(R680 − R430) / (R680 + R430)",
    "PSRI": "(R678 − R500) / R750",
    "PRI": "(R531 − R570) / (R531 + R570)",
    "SR": "R800 / R680",
    "SIPI": "(R800 − R445) / (R800 + R680)",
    "RENDVI": "(R750 − R705) / (R750 + R705)",
    "NPQI": "(R415 − R430) / (R415 + R430)",
    "NDRE": "(R790 − R720) / (R790 + R720)",
    "CCCI": "NDRE / NDVI",
    "CRI2": "1/R510 − 1/R700",
    "NDWI": "(R860 − R1240) / (R860 + R1240)",
    "MSI": "R1600 / R820",
    "NDNI": "log(1/R1510) − log(1/R1680), normalized",
}


def log(message: str) -> None:
    print(message, flush=True)


def nearest_band(wavelengths: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(wavelengths - target)))


def robust_channel(channel: np.ndarray) -> np.ndarray:
    channel = np.nan_to_num(channel.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    lo, hi = np.percentile(channel, [2, 98])
    if hi <= lo:
        return np.zeros_like(channel)
    return np.clip((channel - lo) / (hi - lo), 0, 1)


def cube_rgb(cube: np.ndarray, wavelengths: np.ndarray, targets: tuple[float, float, float]) -> np.ndarray:
    channels = [robust_channel(cube[:, :, nearest_band(wavelengths, t)]) for t in targets]
    return np.stack(channels, axis=-1)


def read_roi(memmap: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    y0, y1, x0, x1 = roi
    return np.asarray(memmap[y0:y1, x0:x1, :], dtype=np.float32)


def save_envi(path: Path, cube: np.ndarray, metadata: dict, description: str) -> None:
    meta = dict(metadata)
    meta["description"] = description
    meta["samples"] = int(cube.shape[1])
    meta["lines"] = int(cube.shape[0])
    meta["bands"] = int(cube.shape[2])
    meta["data type"] = 4
    meta["interleave"] = "bil"
    spectral.envi.save_image(
        str(path), cube.astype(np.float32, copy=False), dtype=np.float32,
        interleave="bil", metadata=meta, force=True,
    )


def load_and_calibrate(hdr_path: Path, camera: str, stride: int) -> dict:
    cfg = CAMERAS[camera]
    image = spectral.open_image(str(hdr_path))
    wavelengths = np.asarray(image.metadata["wavelength"], dtype=np.float64)
    # The downloaded acquisition contains both ``.raw`` and ``.bil`` siblings.
    # Spectral Python prefers ``.raw`` when the header does not name a data file,
    # even though the ENVI dimensions describe the larger ``.bil`` file.  Map the
    # verified BIL explicitly: disk order is (lines, bands, samples), while the
    # processing code uses (lines, samples, bands).
    bil_path = hdr_path.with_suffix(".bil")
    if not bil_path.exists():
        raise FileNotFoundError(f"Missing ENVI BIL data file: {bil_path}")
    lines, samples, bands = (int(v) for v in image.shape)
    bil = np.memmap(bil_path, dtype="<u2", mode="r", shape=(lines, bands, samples))
    memmap = np.transpose(bil, (0, 2, 1))

    white = read_roi(memmap, cfg["white"])
    dark = read_roi(memmap, cfg["dark"])
    white_spectrum = np.median(white, axis=(0, 1))
    dark_spectrum = np.median(dark, axis=(0, 1))
    denominator = white_spectrum - dark_spectrum
    safe = np.abs(denominator) >= 32.0
    denominator = np.where(safe, denominator, np.nan)

    y0, y1, x0, x1 = cfg["scene"]
    raw = np.asarray(memmap[y0:y1:stride, x0:x1:stride, :], dtype=np.float32)
    calibrated = (raw - dark_spectrum[None, None, :]) / denominator[None, None, :]
    calibrated = np.clip(np.nan_to_num(calibrated, nan=0.0, posinf=1.0, neginf=0.0), 0, 1)

    return {
        "camera": camera,
        "raw": raw,
        "cube": calibrated.astype(np.float32),
        "wavelengths": wavelengths,
        "metadata": image.metadata.copy(),
        "white_spectrum": white_spectrum,
        "dark_spectrum": dark_spectrum,
        "valid_calibration_bands": int(np.count_nonzero(safe)),
        "source_shape": tuple(int(v) for v in image.shape),
        "scene_box": cfg["scene"],
    }


def threshold_consensus(index_map: np.ndarray) -> tuple[float, dict]:
    from sklearn.mixture import GaussianMixture
    from skimage.filters import threshold_otsu
    from scipy.ndimage import gaussian_filter

    values = index_map[np.isfinite(index_map)]
    if values.size < 20:
        raise ValueError("Not enough finite pixels to determine a plant threshold")
    otsu = float(threshold_otsu(values))
    percentile = float(np.percentile(values, 93))
    sample = values[:: max(1, values.size // 100_000)].reshape(-1, 1)
    gmm = GaussianMixture(n_components=2, random_state=0).fit(sample)
    means = gmm.means_.ravel()
    grid = np.linspace(float(values.min()), float(values.max()), 1000)
    probs = gmm.predict_proba(grid.reshape(-1, 1))
    low_component, high_component = np.argsort(means)
    between = (grid >= means[low_component]) & (grid <= means[high_component])
    candidates = np.flatnonzero(between)
    if candidates.size:
        crossing = candidates[np.argmin(np.abs(probs[candidates, low_component] - probs[candidates, high_component]))]
        gmm_threshold = float(grid[crossing])
    else:
        gmm_threshold = otsu
    smooth = gaussian_filter(index_map, sigma=2)
    spatial = float(threshold_otsu(smooth[np.isfinite(smooth)]))
    methods = {"otsu": otsu, "percentile_93": percentile, "gmm": gmm_threshold, "spatial_otsu": spatial}
    return float(np.median(list(methods.values()))), methods


def plant_mask(cube: np.ndarray, wavelengths: np.ndarray, camera: str) -> tuple[np.ndarray, np.ndarray, float, dict]:
    from skimage.morphology import disk, opening, remove_small_holes, remove_small_objects

    eps = 1e-8
    if camera == "fx10":
        red = cube[:, :, (wavelengths >= 665) & (wavelengths <= 680)].mean(axis=2)
        nir = cube[:, :, (wavelengths >= 750) & (wavelengths <= 800)].mean(axis=2)
        index_map = (nir - red) / (nir + red + eps)
    else:
        r1 = cube[:, :, (wavelengths >= 1080) & (wavelengths <= 1150)].mean(axis=2)
        r2 = cube[:, :, (wavelengths >= 1400) & (wavelengths <= 1470)].mean(axis=2)
        index_map = (r1 - r2) / (r1 + r2 + eps)
    threshold, methods = threshold_consensus(index_map)
    mask = index_map > threshold
    mask = opening(mask, disk(1))
    mask = remove_small_objects(mask, max_size=23)
    mask = remove_small_holes(mask, max_size=15)
    return index_map, mask, threshold, methods


def mean_spectrum(cube: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    if mask is None:
        return np.nanmean(cube, axis=(0, 1))
    pixels = cube[mask]
    return np.nanmean(pixels, axis=0) if pixels.size else np.nanmean(cube, axis=(0, 1))


def spectral_cross_calibration(fx10: dict, fx17: dict, mask10: np.ndarray, mask17: np.ndarray) -> dict:
    wl10, wl17 = fx10["wavelengths"], fx17["wavelengths"]
    spec10 = mean_spectrum(fx10["cube"], mask10)
    spec17 = mean_spectrum(fx17["cube"], mask17)
    start = max(936.0, float(wl10.min()), float(wl17.min()))
    stop = min(1000.0, float(wl10.max()), float(wl17.max()))
    grid = np.linspace(start, stop, 300)
    overlap10 = np.interp(grid, wl10, spec10)
    overlap17 = np.interp(grid, wl17, spec17)
    design = np.vstack([overlap17, np.ones_like(overlap17)]).T
    gain, offset = np.linalg.lstsq(design, overlap10, rcond=None)[0]
    corrected_cube = np.clip(gain * fx17["cube"] + offset, 0, 1).astype(np.float32)
    corrected_spec = np.clip(gain * spec17 + offset, 0, 1)
    rmse_before = float(np.sqrt(np.mean((overlap17 - overlap10) ** 2)))
    rmse_after = float(np.sqrt(np.mean((gain * overlap17 + offset - overlap10) ** 2)))
    return {
        "gain": float(gain), "offset": float(offset), "cube": corrected_cube,
        "fx10_spectrum": spec10, "fx17_spectrum": spec17,
        "corrected_spectrum": corrected_spec, "grid": grid,
        "overlap10": overlap10, "overlap17": overlap17,
        "rmse_before": rmse_before, "rmse_after": rmse_after,
    }


def normalize_image(image: np.ndarray) -> np.ndarray:
    image = image.astype(np.float32)
    image -= np.nanmin(image)
    return image / (np.nanmax(image) + 1e-8)


def mutual_information(reference: np.ndarray, moving: np.ndarray) -> float:
    histogram, _, _ = np.histogram2d(reference.ravel(), moving.ravel(), bins=64)
    pxy = histogram / max(float(histogram.sum()), 1.0)
    px = pxy.sum(axis=1)
    py = pxy.sum(axis=0)
    product = px[:, None] * py[None, :]
    valid = pxy > 0
    return float(np.sum(pxy[valid] * np.log(pxy[valid] / (product[valid] + 1e-12))))


def register_fx17(fx10: dict, corrected17: np.ndarray) -> dict:
    wl10, wl17 = fx10["wavelengths"], np.asarray(fx10.get("fx17_wavelengths"), dtype=float)
    image10 = normalize_image(fx10["cube"][:, :, (wl10 >= 936) & (wl10 <= 1000)].mean(axis=2))
    image17_native = normalize_image(corrected17[:, :, (wl17 >= 936) & (wl17 <= 1000)].mean(axis=2))
    height, width = image10.shape
    image17 = cv2.resize(image17_native, (width, height), interpolation=cv2.INTER_AREA)
    img10 = (image10 * 255).astype(np.uint8)
    img17 = (image17 * 255).astype(np.uint8)

    sift = cv2.SIFT_create()
    kp10, des10 = sift.detectAndCompute(img10, None)
    kp17, des17 = sift.detectAndCompute(img17, None)
    good = []
    inliers = None
    method = "SIFT + RANSAC + mutual information"
    matrix = None
    pts10 = pts17 = None
    if des10 is not None and des17 is not None:
        pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(des10, des17, k=2)
        good = [m for m, n in pairs if m.distance < 0.75 * n.distance]
        if len(good) >= 3:
            pts10 = np.float32([kp10[m.queryIdx].pt for m in good])
            pts17 = np.float32([kp17[m.trainIdx].pt for m in good])
            matrix, inliers = cv2.estimateAffine2D(pts17, pts10, method=cv2.RANSAC, ransacReprojThreshold=5)

    if matrix is None:
        method = "ECC affine fallback + mutual information"
        matrix = np.eye(2, 3, dtype=np.float32)
        try:
            _, matrix = cv2.findTransformECC(
                img10.astype(np.float32) / 255.0, img17.astype(np.float32) / 255.0,
                matrix, cv2.MOTION_AFFINE,
                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7),
            )
        except cv2.error:
            method = "identity fallback"

    initial_mi = mutual_information(image10, cv2.warpAffine(image17, matrix, (width, height)))

    def warp_params(params: np.ndarray) -> np.ndarray:
        candidate = np.asarray([[params[0], params[1], params[4]], [params[2], params[3], params[5]]], dtype=np.float32)
        return cv2.warpAffine(image17, candidate, (width, height))

    initial = np.asarray([matrix[0, 0], matrix[0, 1], matrix[1, 0], matrix[1, 1], matrix[0, 2], matrix[1, 2]])
    result = minimize(lambda p: -mutual_information(image10, warp_params(p)), initial, method="Powell", options={"maxiter": 100})
    p = result.x
    matrix = np.asarray([[p[0], p[1], p[4]], [p[2], p[3], p[5]]], dtype=np.float32)
    warped_projection = cv2.warpAffine(image17, matrix, (width, height))

    resized = np.empty((height, width, corrected17.shape[2]), dtype=np.float32)
    registered = np.empty_like(resized)
    for band in range(corrected17.shape[2]):
        resized[:, :, band] = cv2.resize(corrected17[:, :, band], (width, height), interpolation=cv2.INTER_AREA)
        registered[:, :, band] = cv2.warpAffine(resized[:, :, band], matrix, (width, height))

    reprojection = []
    if inliers is not None and pts10 is not None and pts17 is not None:
        keep = inliers.ravel().astype(bool)
        homogeneous = np.column_stack([pts17[keep], np.ones(np.count_nonzero(keep))])
        reprojection = np.linalg.norm((matrix @ homogeneous.T).T - pts10[keep], axis=1).tolist()

    return {
        "cube": registered, "matrix": matrix, "inliers": int(np.sum(inliers)) if inliers is not None else 0,
        "good_matches": len(good), "keypoints_fx10": len(kp10), "keypoints_fx17": len(kp17),
        "method": method, "mi_initial": initial_mi, "mi_final": mutual_information(image10, warped_projection),
        "mean_reprojection_error": float(np.mean(reprojection)) if reprojection else None,
        "projection10": image10, "projection17": image17, "warped_projection": warped_projection,
    }


def merge_cubes(fx10: dict, registered17: np.ndarray, wl17: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    wl10 = fx10["wavelengths"]
    keep10 = wl10 <= 1000.0
    keep17 = wl17 > 1000.0
    merged = np.concatenate([fx10["cube"][:, :, keep10], registered17[:, :, keep17]], axis=2).astype(np.float32)
    wavelengths = np.concatenate([wl10[keep10], wl17[keep17]])
    return merged, wavelengths


def calculate_index(cube: np.ndarray, wavelengths: np.ndarray, name: str) -> np.ndarray:
    eps = 1e-8

    def r(wavelength: float) -> np.ndarray:
        return cube[:, :, nearest_band(wavelengths, wavelength)]

    def ratio(numerator: np.ndarray, denominator: np.ndarray, minimum: float = 0.02) -> np.ndarray:
        output = np.full(numerator.shape, np.nan, dtype=np.float32)
        valid = np.isfinite(numerator) & np.isfinite(denominator) & (np.abs(denominator) >= minimum)
        np.divide(numerator, denominator + eps, out=output, where=valid)
        return output

    if name == "NDVI": return ratio(r(800) - r(680), r(800) + r(680))
    if name == "NPCI": return ratio(r(680) - r(430), r(680) + r(430))
    if name == "PSRI": return ratio(r(678) - r(500), r(750))
    if name == "PRI": return ratio(r(531) - r(570), r(531) + r(570))
    if name == "SR": return ratio(r(800), r(680))
    if name == "SIPI": return ratio(r(800) - r(445), r(800) + r(680))
    if name == "RENDVI": return ratio(r(750) - r(705), r(750) + r(705))
    if name == "NPQI": return ratio(r(415) - r(430), r(415) + r(430))
    if name == "NDRE": return ratio(r(790) - r(720), r(790) + r(720))
    if name == "CCCI":
        ndre = calculate_index(cube, wavelengths, "NDRE")
        ndvi = ratio(r(800) - r(670), r(800) + r(670))
        return ratio(ndre, ndvi, minimum=0.05)
    if name == "CRI2":
        a, b = r(510), r(700)
        output = np.full(a.shape, np.nan, dtype=np.float32)
        valid = (a >= 0.02) & (b >= 0.02)
        output[valid] = 1 / a[valid] - 1 / b[valid]
        return output
    if name == "NDWI": return ratio(r(860) - r(1240), r(860) + r(1240))
    if name == "MSI": return ratio(r(1600), r(820))
    if name == "NDNI":
        reflectance1510, reflectance1680 = r(1510), r(1680)
        output = np.full(reflectance1510.shape, np.nan, dtype=np.float32)
        valid = (reflectance1510 >= 0.02) & (reflectance1680 >= 0.02)
        a = np.zeros_like(reflectance1510); b = np.zeros_like(reflectance1680)
        a[valid], b[valid] = np.log(1 / reflectance1510[valid]), np.log(1 / reflectance1680[valid])
        denominator = a + b
        valid &= np.abs(denominator) >= 0.02
        output[valid] = (a[valid] - b[valid]) / denominator[valid]
        return output
    raise ValueError(name)


def save_figure(path: Path, figure: plt.Figure) -> None:
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


INDEX_DETAILS = {
    "NDVI": ("Normalized Difference Vegetation Index", "Greenness and vegetation contrast", "Higher values usually mean a stronger vegetation response. The median is not a health percentage."),
    "SR": ("Simple Ratio", "Near-infrared divided by red reflectance", "A median of 4.69 means NIR reflectance was about 4.69 times red reflectance in the analysed plant pixels."),
    "NDRE": ("Normalized Difference Red Edge", "Red-edge and chlorophyll-sensitive contrast", "Useful for relative within-scene comparison; it is not a chlorophyll concentration."),
    "RENDVI": ("Red Edge NDVI", "Spatial variation around the red edge", "Use the map to locate relative differences, not to diagnose stress by itself."),
    "CCCI": ("Canopy Chlorophyll Content Index", "Relative canopy chlorophyll proxy", "Crop-specific calibration and reference measurements are required before treating this as chlorophyll content."),
    "NPCI": ("Normalized Pigment Chlorophyll Index", "Relative pigment balance", "Negative is not automatically bad. Species, illumination, calibration and pigment balance all affect the sign."),
    "PSRI": ("Plant Senescence Reflectance Index", "Possible senescence-related pigment change", "Higher values can be associated with senescence, but interpretation needs a healthy baseline and ground truth."),
    "PRI": ("Photochemical Reflectance Index", "Short-term photosynthetic and xanthophyll-cycle proxy", "This index is especially sensitive to illumination, view angle and measurement time."),
    "SIPI": ("Structure-Insensitive Pigment Index", "Carotenoid-to-chlorophyll-related variation", "Treat it as a relative pigment proxy, not a direct biochemical measurement."),
    "NPQI": ("Normalized Phaeophytinization Index", "Possible chlorophyll degradation", "Small differences need comparison with labelled healthy and stressed samples."),
    "CRI2": ("Carotenoid Reflectance Index 2", "Carotenoid-sensitive reflectance contrast", "Its scale differs from normalized indices, so the number cannot be compared directly with NDVI or NDRE."),
    "NDWI": ("Normalized Difference Water Index", "Water-related spectral contrast", "Higher often indicates a stronger water-related signal, but this is not water percentage."),
    "MSI": ("Moisture Stress Index", "Moisture-stress-sensitive ratio", "Higher often means more moisture stress; 0.62 does not mean 62 percent stress."),
    "NDNI": ("Normalized Difference Nitrogen Index", "Nitrogen-related SWIR absorption proxy", "This is not nitrogen concentration. Laboratory nitrogen measurements are needed for calibration."),
}


INDEX_GROUPS = [
    ("Greenness and vegetation", "greenness", ("NDVI", "SR")),
    ("Red edge and chlorophyll proxies", "chlorophyll", ("NDRE", "RENDVI", "CCCI")),
    ("Pigment, senescence and photochemistry", "pigment", ("NPCI", "PSRI", "PRI", "SIPI", "NPQI", "CRI2")),
    ("Water and nitrogen proxies", "water", ("NDWI", "MSI", "NDNI")),
]


def build_report_html(
    metrics: dict,
    summaries: list[dict],
    segment_rows: list[dict],
    fusion_summary: dict | None = None,
    rgbd_reconstruction: dict | None = None,
    rgbd_traits: list[dict] | None = None,
    rgbd_validation: dict | None = None,
    global_placement: dict | None = None,
) -> str:
    summary_by_name = {row["index"]: row for row in summaries}
    background = metrics["background_removal"]
    cross = metrics["cross_calibration"]
    registration = metrics["registration"]
    merged = metrics["merged_cube"]

    group_sections = []
    for group_title, group_class, names in INDEX_GROUPS:
        cards = []
        for name in names:
            row = summary_by_name[name]
            full_name, purpose, interpretation = INDEX_DETAILS[name]
            cards.append(f"""
            <article class="index-card {group_class}">
              <div class="index-copy">
                <p class="eyebrow">{html.escape(full_name)}</p>
                <h4>{name} <span class="value">median {float(row['median']):.3f}</span></h4>
                <p><strong>What it shows:</strong> {html.escape(purpose)}.</p>
                <p><strong>How to read this result:</strong> {html.escape(interpretation)}</p>
                <p class="formula"><strong>Formula:</strong> {html.escape(str(row['formula']))}</p>
                <p class="range">Plant-pixel spread (10th–90th percentile): {float(row['p10']):.3f} to {float(row['p90']):.3f} · valid pixels: {int(float(row['pixels'])):,}</p>
              </div>
              <a class="figure-link" href="indices/{name}.png" title="Open the full-resolution {name} figure">
                <img src="indices/{name}.png" alt="{name} result with plant image, colour heatmap and plant overlay" loading="lazy">
              </a>
            </article>""")
        group_sections.append(f'<section class="index-group"><h3>{group_title}</h3>{"".join(cards)}</section>')

    segments = {row["segment"]: row for row in segment_rows}
    rgbd_results_html = ""
    if rgbd_reconstruction and rgbd_traits and rgbd_validation:
        trait_by_key = {item["specimen_label"]: item for item in rgbd_traits}
        trait_cards = []
        for key, label in (("coleus", "Coleus"), ("fuzzy_kalanchoe", "Fuzzy kalanchoe"), ("succulent_jade", "Succulent / jade")):
            item = trait_by_key[key]
            height_mm = float(item["plant_height_m"]) * 1000.0
            major_mm = float(item["canopy_major_span_m"]) * 1000.0
            minor_mm = float(item["canopy_minor_span_m"]) * 1000.0
            area_cm2 = float(item["projected_canopy_area_m2"]) * 10000.0
            trait_cards.append(f"""
            <article class="trait-card"><div class="trait-copy"><p class="eyebrow">RGB-D frame {int(item['frame_index'])}</p><h3>{html.escape(label)}</h3>
            <dl class="trait-list"><div><dt>Plant height</dt><dd>{height_mm:.1f} mm</dd></div><div><dt>Canopy span</dt><dd>{major_mm:.1f} × {minor_mm:.1f} mm</dd></div><div><dt>Projected canopy area</dt><dd>{area_cm2:.1f} cm²</dd></div><div><dt>Cleaned 3D points</dt><dd>{int(item['point_count']):,}</dd></div><div><dt>Visible segments</dt><dd>{int(item['visible_leaf_segment_count'])}</dd></div></dl>
            <p class="range">Height is the configured soil/support depth minus the top one-percent plant depth. Canopy area is the 2D footprint of the cleaned point cloud. “Visible segments” are image segments—not a guaranteed biological leaf count.</p>
            <div class="downloads"><a href="rgbd_icp/plants/{key}/specimen_pointcloud.ply">Cleaned RGB-D PLY</a><a href="rgbd_icp/plants/{key}/traits.json">Trait JSON</a></div></div>
            <div class="trait-images"><a href="rgbd_icp/plants/{key}/plant_overlay.png"><img src="rgbd_icp/plants/{key}/plant_overlay.png" alt="{html.escape(label)} RGB-D plant measurement overlay" loading="lazy"></a><a href="rgbd_icp/plants/{key}/leaf_segments.png"><img src="rgbd_icp/plants/{key}/leaf_segments.png" alt="{html.escape(label)} visible leaf segmentation" loading="lazy"></a></div></article>""")
        rgbd_results_html = f"""
<section id="rgbd-results"><h2>The RGB-D / ICP results this fusion builds upon</h2><p class="eyebrow">Pure geometry and trait calculation · same plant run</p>
<div class="panel"><h3>Yes—these are the independent RGB-D results</h3><p>This stage used RGB colour plus depth only. It reconstructed the scene with sequential ICP, isolated each plant and calculated geometric traits. It did <strong>not</strong> use hyperspectral values. The later fusion stage attaches the 427-band spectra to this measured geometry.</p></div>
<div class="metrics"><div class="metric"><span>Captured pairs</span><b>945</b><small>945 RGB frames and their 945 aligned depth frames.</small></div><div class="metric"><span>ICP frames used</span><b>{int(rgbd_reconstruction['frames_used'])}</b><small>Every tenth frame; {int(rgbd_reconstruction['succeeded'])} succeeded and {int(rgbd_reconstruction['failed'])} failed.</small></div><div class="metric"><span>Full merged scene</span><b>{int(rgbd_reconstruction['points']):,}</b><small>Points in the legacy ICP reconstruction.</small></div><div class="metric"><span>Voxel setting</span><b>{float(rgbd_reconstruction['voxel_size_m'])*1000:.0f} mm</b><small>ICP/reconstruction spatial sampling parameter.</small></div></div>
<article class="core"><div class="core-copy"><h3>What the 44-million-point image shows</h3><p>The left panel is a top projection and the right panel is a side projection of a uniformly sampled preview of the full reconstruction. The board, pots, plants, gantry surroundings and accumulated reconstruction noise are visible. The coloured plant structures around the middle-lower part of the scene are the geometry later used for fusion.</p><p><strong>Important:</strong> 44 million points describes density, not accuracy. Registration validation and manual trait comparisons are the useful accuracy evidence.</p><div class="downloads"><a href="rgbd_icp/scene_preview_sampled.ply">Sampled scene PLY (300,000 points)</a><a href="rgbd_icp/reconstruction_summary.json">Reconstruction summary</a><a href="../../../PhenoFusion3D/data/main/test_plant_20260828120800_best_lighting/merge_simple_full_step10/merge_pcd_cam0.ply">Full local 44M-point PLY (about 1.2 GB)</a></div></div><a href="rgbd_icp/scene_top_side_preview.png"><img src="rgbd_icp/scene_top_side_preview.png" alt="Top and side projections of the legacy 44-million-point ICP reconstruction" loading="lazy"></a></article>
<h3 class="subheading">Per-plant geometry and automatically calculated traits</h3>
{''.join(trait_cards)}
<div class="metrics"><div class="metric"><span>Plant-height MAPE</span><b>{float(rgbd_validation['height_mape_percent']):.2f}%</b><small>Mean absolute percentage error across the three plants.</small></div><div class="metric"><span>Matched leaf-length MAPE</span><b>{float(rgbd_validation['matched_leaf_length_mape_percent']):.2f}%</b><small>Guided, manually matched leaf landmarks.</small></div><div class="metric"><span>Matched leaf-width MAPE</span><b>{float(rgbd_validation['matched_leaf_width_mape_percent']):.2f}%</b><small>Guided, manually matched leaf landmarks.</small></div><div class="metric"><span>Validation status</span><b>3 plants</b><small>All heights and nine annotated leaves reviewed.</small></div></div>
<div class="claims"><div class="panel"><h3>How to interpret the validation</h3><p>MAPE means the average absolute error expressed as a percentage of the manual measurement. Lower is better. The three reported aggregate values show close agreement for plant height and the specifically matched leaf dimensions in this validation set.</p><p>The underlying report keeps every plant and leaf comparison visible, so the aggregate number is not hiding which items differed.</p></div><div class="panel"><h3>What remains limited</h3><p>The leaf result is a <strong>guided comparison</strong>: a human identified corresponding leaves/landmarks. Automatic cross-view leaf identity is still future work. The canopy-area and segment outputs are useful geometric descriptions, but they are not biological ground truth.</p></div></div>
<div class="downloads"><a href="rgbd_icp/validation/validation_report.html">Open full RGB-D validation report</a><a href="rgbd_icp/validation/plant_height_comparison.csv">Plant-height comparisons</a><a href="rgbd_icp/validation/matched_leaf_comparison.csv">Matched leaf comparisons</a><a href="rgbd_icp/software_traits.csv">All software traits (CSV)</a></div></section>"""

    fusion_results_html = ""
    if fusion_summary and fusion_summary.get("plants"):
        global_ready = bool(global_placement and global_placement.get("plants"))
        coordinate_status = "Global ICP scene" if global_ready else "Per-plant 3D"
        coordinate_note = "Recovered scene transforms validated on held-out surface points." if global_ready else "Selected camera frames; global ICP placement is still pending."
        scene_status_panel = (
            "<div class=\"panel\"><h3>Global-scene milestone complete</h3><p>The three selected camera-frame surfaces have now been transformed into the common legacy ICP scene coordinate system using direct cleaned-surface registration. The dedicated global-placement section records the transforms, held-out distance validation and inspectable global PLY files.</p><p>The complete historical 95-frame trajectory remains unavailable; only the three transforms required for this fusion were recovered.</p></div>"
            if global_ready else
            "<div class=\"panel\"><h3>Remaining global-scene milestone</h3><p>The current outputs are genuine 3D spectral surfaces in frames 330, 540 and 750, and they coincide with the cleaned per-plant point clouds produced from those same frames. The existing 44-million-point ICP scene does not include its per-frame cumulative pose matrices, so these three surfaces have not yet been transformed into that one noisy global scene coordinate system. The reconstructor must save or reproduce those poses before claiming global ICP placement.</p><p>This does not invalidate the per-plant fusion; it precisely limits the coordinate claim.</p></div>"
        )
        fusion_cards = []
        total_points = 0
        for item in fusion_summary["plants"]:
            key = item["plant"]
            label = item["label"]
            registration_result = item["registration"]
            coverage = item["coverage"]
            surface = item["specimen_surface_validation"]
            spectral_result = item["spectral"]
            total_points += int(coverage["points_within_20mm_of_specimen_surface"])
            if registration_result["selected_model"].startswith("plant-local"):
                registration_text = f"{int(registration_result['plant_inliers'])} plant-local inliers · {float(registration_result['plant_reprojection_rmse_px']):.2f} px RMSE"
                confidence_note = "The plant-local model was selected because it passed feature-count, error and geometric-spread checks."
            else:
                registration_text = f"{int(registration_result['inliers'])} board inliers · ECC plant refinement"
                confidence_note = "Lower-confidence registration: the plant-local homography was rejected as geometrically unstable, so the planar board model plus plant-masked ECC was retained."
            fusion_cards.append(f"""
            <article class="core"><div class="core-copy"><p class="eyebrow">RGB-D frame {int(item['rgbd_frame'])}</p><h3>{html.escape(label)}</h3>
            <p><strong>Registration:</strong> {registration_text}. {confidence_note}</p>
            <p><strong>Measured fused output:</strong> {int(coverage['points_within_20mm_of_specimen_surface']):,} XYZ points, each carrying {int(spectral_result['bands'])} reflectance bands. This retains {100*float(coverage['valid_depth_fraction']):.1f}% of the isolated hyperspectral component after unique-depth, foreground-layer and specimen-surface checks.</p>
            <p><strong>3D surface check:</strong> {100*float(coverage['specimen_surface_retention_fraction']):.1f}% of the depth-layer points lay within 20 mm of the cleaned plant cloud. Pre-filter nearest-surface distance: median {float(surface['nearest_surface_distance_median_mm_before_filter']):.2f} mm, 90th percentile {float(surface['nearest_surface_distance_p90_mm_before_filter']):.2f} mm.</p>
            <p><strong>Exploratory NDVI median on retained points:</strong> {float(spectral_result['index_display_ranges']['NDVI']['median']):.3f}.</p>
            <div class="downloads"><a href="fusion/{key}/{key}_ndvi_on_specimen.ply">NDVI + grey specimen PLY</a><a href="fusion/{key}/{key}_spectral_points.npz">427-band point data</a><a href="fusion/{key}/fusion_metrics.json">Metrics</a></div></div>
            <div class="fusion-figures"><a href="fusion/{key}/registration_and_depth_overlay.png"><img src="fusion/{key}/registration_and_depth_overlay.png" alt="{html.escape(label)} hyperspectral to RGB-D registration and measured depth overlay" loading="lazy"></a><a href="fusion/{key}/ndvi_3d_preview.png"><img src="fusion/{key}/ndvi_3d_preview.png" alt="{html.escape(label)} NDVI measured surface over the grey cleaned specimen point cloud" loading="lazy"></a></div></article>""")
        fusion_results_html = f"""
<section id="fusion-results"><h2>Fusion milestones: measured results</h2><p class="eyebrow">Pipeline run recorded 31 August 2026</p>
<div class="metrics"><div class="metric"><span>Plants fused</span><b>{len(fusion_summary['plants'])}</b><small>Coleus, fuzzy kalanchoe and succulent/jade.</small></div><div class="metric"><span>Measured spectral XYZ points</span><b>{total_points:,}</b><small>After depth and cleaned-surface validation.</small></div><div class="metric"><span>Spectrum per retained point</span><b>427 bands</b><small>Approximately 398–1720 nm.</small></div><div class="metric"><span>Current coordinate status</span><b>{coordinate_status}</b><small>{coordinate_note}</small></div></div>
<div class="panel"><h3>What was corrected during implementation</h3><p>The first extension used equal top/middle/bottom row thirds. Visual validation showed that those ranges overlap the plant silhouettes, mixing Coleus pixels into the fuzzy plant and fuzzy pixels into the jade plant. The production run now selects the actual connected plant components from the NDVI mask. Degenerate local homographies are rejected by inlier, reprojection-error and mapped-area checks; mapped pixels are deduplicated, separated from the background depth layer and finally required to lie within 20 mm of the corresponding cleaned 3D plant cloud.</p></div>
{''.join(fusion_cards)}
<div class="claims"><div class="panel"><h3>Milestones now complete</h3><ul><li>Hyperspectral-to-RGB-D registration for all three plants.</li><li>Depth backprojection into metric XYZ coordinates using the saved colour intrinsics and 10,000-unit-per-metre scale.</li><li>Complete 427-band spectral attachment for every retained point.</li><li>NDVI, NDRE, NDWI, MSI and NDNI PLY exports.</li><li>Combined models with measured spectral points coloured and unmeasured specimen geometry grey.</li><li>Numerical registration, depth-coverage and cleaned-surface validation files.</li></ul></div>{scene_status_panel}</div>
<div class="downloads"><a href="fusion/fusion_summary.csv">Fusion summary (CSV)</a><a href="fusion/fusion_summary.json">Complete fusion provenance (JSON)</a></div></section>"""

    viewer_html = ""
    if fusion_summary and fusion_summary.get("plants"):
        viewer_html = """
<section id="interactive-3d"><h2>Inspect every measured 3D spectral point</h2><p>The viewer now supports up to <strong>40× zoom</strong>. Drag to rotate, hold <strong>Shift while dragging</strong> to pan, use the mouse wheel or +/− buttons to zoom, and double-click a point to select and focus it. Switch between five index colourings without losing the underlying spectrum.</p>
<div class="viewer-shell panel"><div class="viewer-toolbar" aria-label="3D viewer controls"><div class="viewer-plants" role="group" aria-label="Choose a model"><button type="button" class="active" data-viewer-plant="coleus" aria-pressed="true">Coleus</button><button type="button" data-viewer-plant="fuzzy_kalanchoe" aria-pressed="false">Fuzzy kalanchoe</button><button type="button" data-viewer-plant="succulent_jade" aria-pressed="false">Succulent / jade</button><button type="button" data-viewer-plant="global_scene" aria-pressed="false">Global ICP scene</button></div><label>Colour by <select id="viewer-index"><option>NDVI</option><option>NDRE</option><option>NDWI</option><option>MSI</option><option>NDNI</option></select></label><label>Point size <input id="viewer-point-size" type="range" min="1" max="6" step="0.25" value="2"></label><button type="button" id="viewer-zoom-out" aria-label="Zoom out">−</button><button type="button" id="viewer-zoom-in" aria-label="Zoom in">+</button><button type="button" id="viewer-focus" title="Centre the selected point and zoom closely">Focus selected</button><label class="check"><input id="viewer-auto-rotate" type="checkbox" checked> Auto-rotate</label><button type="button" id="viewer-reset">Reset view</button></div>
<canvas id="fusion-viewer-canvas" tabindex="0" aria-label="Interactive 3D point-cloud viewer. Drag or use arrow keys to rotate; shift-drag to pan; wheel or plus and minus keys to zoom; click a point to inspect it."></canvas>
<div class="viewer-footer"><div><span class="legend-grey"></span> RGB-D geometry without a spectral measurement <span class="legend-gradient"></span> measured spectral point, low → high within the selected index</div><p id="viewer-status" aria-live="polite">Loading model…</p><a id="viewer-download" href="fusion/coleus/coleus_ndvi_on_specimen.ply">Download full model PLY</a></div></div>
<div class="spectral-inspector panel"><div class="inspector-copy"><p class="eyebrow">Per-point spectral inspector</p><h3 id="inspector-title">Select a measured spectral point</h3><p id="inspector-message">Click a coloured point in the model. Grey points are RGB-D geometry without a directly measured hyperspectral spectrum.</p><div id="inspector-details" hidden><p data-field="coordinate"></p><p data-field="hsi"></p><p data-field="rgbd"></p><div id="inspector-indices" class="inspector-indices"></div></div></div><div class="spectrum-wrap"><canvas id="viewer-spectrum-canvas" aria-label="Reflectance spectrum of the selected measured point"></canvas><p id="spectrum-readout">No spectrum selected.</p></div></div>
<div class="claims viewer-meaning"><div class="panel"><h3>What “complete fusion” means here</h3><p><strong>Yes, the prototype fusion is complete for all retained measured points:</strong> 10,485 XYZ points each carry the full 427-band calibrated spectrum, five displayed indices, their source hyperspectral pixel and their corresponding RGB-D pixel. Those points are also placed in the common ICP scene.</p></div><div class="panel"><h3>What it does not mean</h3><p>It is not complete surface coverage of every leaf. The hyperspectral cameras mainly observed upper-visible surfaces, so sides, undersides and occluded areas remain grey and have no invented spectrum. Registration is measured and validated, but still an approximation affected by parallax and the five-minute capture gap.</p></div></div>
<p class="callout"><strong>Display and precision note:</strong> all measured spectral points are selectable. Grey scene/specimen geometry is deterministically sampled for responsiveness. Spectra in the local viewer are stored at 16-bit display precision; the downloadable NPZ files retain the original float32 arrays.</p></section>"""

    global_placement_html = ""
    if global_placement and global_placement.get("plants"):
        placement_cards = []
        for item in global_placement["plants"]:
            validation = item["held_out_validation"]
            placement_cards.append(f"""
            <div class="metric"><span>{html.escape(item['label'])} · frame {int(item['rgbd_frame'])}</span><b>{float(validation['nearest_scene_distance_median_mm']):.2f} mm</b><small>Held-out median nearest-scene distance; p90 {float(validation['nearest_scene_distance_p90_mm']):.2f} mm · {100*float(validation['within_20mm_fraction']):.1f}% within 20 mm.</small></div>""")
        global_placement_html = f"""
<section id="global-placement"><h2>Global placement inside the legacy ICP scene</h2><p class="eyebrow">Missing-pose workaround completed · 31 August 2026</p>
<div class="panel"><h3>What we did instead of rerunning the 1.2 GB reconstruction</h3><p>The legacy run omitted its cumulative pose files, but frames 330, 540 and 750 were included in the every-tenth-frame ICP sequence. Each cleaned plant cloud therefore has a matching surface already embedded in the merged scene. I recovered a rigid camera-to-global transform by registering each cleaned plant cloud directly to the saved 300,000-point scene sample, then applied that transform to every fused spectral model.</p><p>This solves the placement needed for these three plants. It does <strong>not</strong> recreate the missing complete trajectory of all 95 cameras.</p></div>
<div class="metrics">{''.join(placement_cards)}</div>
<article class="core"><div class="core-copy"><h3>Independent check on points not used to fit the transform</h3><p>Alternate voxel-sampled source points were held out of the pose fit. Their nearest distance to the global scene was then measured. Across the plants, median distances were 3.55–4.95 mm and 97.2–99.8% of held-out points landed within 20 mm of the scene surface.</p><p>The pink, yellow and mint points in the figure are the measured hyperspectral surfaces after transformation. Their locations coincide with the three corresponding plants in both top and side projections.</p><div class="downloads"><a href="global_placement/global_placement_summary.json">Transforms and validation (JSON)</a><a href="global_placement/global_scene_ndvi_sampled.ply">Global NDVI scene PLY</a><a href="global_placement/global_scene_ndre_sampled.ply">Global NDRE scene PLY</a><a href="global_placement/global_scene_ndwi_sampled.ply">Global NDWI scene PLY</a></div></div><a href="global_placement/global_placement_preview.png"><img src="global_placement/global_placement_preview.png" alt="Top and side projections showing three hyperspectral plant surfaces placed in the legacy global ICP scene" loading="lazy"></a></article>
<div class="claims"><div class="panel"><h3>Claim now supported</h3><p>The 10,485 measured hyperspectral XYZ points have been transformed from their selected RGB-D camera frames into one common coordinate system aligned to the existing ICP scene. The interactive viewer and global PLY exports expose that placement.</p></div><div class="panel"><h3>Engineering fix for future runs</h3><p>Modify the reconstructor so it writes the cumulative 4×4 matrix after every accepted frame, together with frame index, fitness and RMSE. Then global placement is a direct matrix application, and this recovery step is unnecessary.</p></div></div>
<blockquote class="script">“The RGB-D pipeline first reconstructed a 44.4-million-point scene and measured plant geometry. Separately, the paired hyperspectral cameras produced a registered 427-band cube. We attached those spectra to valid RGB-D depth points, producing 10,485 measured 3D spectral points across three plants. Because the legacy ICP run did not save camera poses, we recovered each required transform by directly registering its cleaned plant cloud to the existing global scene. Held-out surface checks gave median errors below five millimetres, with at least 97.2 percent of points within twenty millimetres. The result is one inspectable global scene with NDVI, NDRE, water, moisture-stress and nitrogen-related spectral colourings—while unmeasured geometry remains explicitly grey.”</blockquote></section>"""
    style = """
    :root { --ink:#10221b; --muted:#52655c; --paper:#f4f0e7; --card:#fffdf8; --green:#0d4734; --mint:#b9ecd8; --cyan:#76d9d2; --gold:#f3c969; --rust:#c76343; --line:#d8ded7; --shadow:0 14px 45px rgba(18,45,34,.10); scroll-behavior:smooth; }
    * { box-sizing:border-box; }
    body { margin:0; color:var(--ink); background:var(--paper); font:16px/1.62 system-ui,-apple-system,"Segoe UI",sans-serif; }
    a { color:#126247; } img { display:block; width:100%; height:auto; }
    .hero { color:white; background:radial-gradient(circle at 85% 18%,rgba(118,217,210,.3),transparent 28%),linear-gradient(135deg,#082d25,#0d523b 62%,#17644a); padding:72px max(5vw,24px) 62px; }
    .hero-inner,.wrap { width:min(1180px,100%); margin:auto; }
    .kicker,.eyebrow { margin:0 0 8px; text-transform:uppercase; letter-spacing:.13em; font-weight:800; font-size:.76rem; }
    .hero h1 { max-width:850px; margin:0; font-size:clamp(2.4rem,6vw,5.4rem); line-height:1; letter-spacing:-.045em; }
    .hero .lead { max-width:820px; font-size:clamp(1.05rem,2vw,1.35rem); color:#dff8ed; }
    .badge { display:inline-block; margin-top:12px; padding:8px 12px; border:1px solid #86cdb5; border-radius:999px; color:#e4fff6; background:#ffffff12; font-size:.88rem; }
    nav { position:sticky; top:0; z-index:10; overflow:auto; white-space:nowrap; padding:10px max(5vw,24px); background:#fffdf8ee; backdrop-filter:blur(12px); border-bottom:1px solid var(--line); }
    nav div { width:min(1180px,100%); margin:auto; } nav a { display:inline-block; padding:7px 12px; text-decoration:none; font-weight:700; }
    main { padding:32px max(5vw,24px) 80px; } section[id] { scroll-margin-top:72px; }
    h2 { margin:72px 0 14px; font-size:clamp(1.8rem,4vw,3.15rem); line-height:1.1; letter-spacing:-.035em; }
    h3 { font-size:1.45rem; line-height:1.2; } h4 { margin:0 0 8px; font-size:1.35rem; }
    .intro { display:grid; grid-template-columns:1.4fr .8fr; gap:20px; margin-top:10px; }
    .panel,.metric,.core,.index-card,.trait-card,.script { background:var(--card); border:1px solid #e1e4de; border-radius:20px; box-shadow:var(--shadow); }
    .panel { padding:24px; } .panel h3 { margin-top:0; }
    .glossary { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
    .term { padding:14px; border-radius:14px; background:#edf4ef; } .term strong { display:block; color:var(--green); }
    .metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:24px 0; }
    .metric { padding:20px; border-top:5px solid var(--cyan); }
    .metric b { display:block; font-size:1.65rem; line-height:1.15; color:var(--green); } .metric small { display:block; margin-top:8px; color:var(--muted); }
    .pipeline { display:grid; grid-template-columns:repeat(7,1fr); gap:10px; align-items:stretch; margin:24px 0; }
    .step { position:relative; min-height:135px; padding:16px 12px; border-radius:16px; color:white; background:var(--green); }
    .step:nth-child(even) { background:#185c53; } .step strong { display:block; margin-bottom:8px; }
    .step:not(:last-child)::after { content:"→"; position:absolute; right:-14px; top:48px; z-index:2; color:var(--gold); font-size:1.6rem; font-weight:900; }
    .core { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr); overflow:hidden; margin:22px 0; }
    .core-copy { padding:28px; } .core-copy h3 { margin-top:0; }
    .core img { height:100%; object-fit:contain; background:white; }
    .callout { padding:14px 16px; border-left:5px solid var(--gold); border-radius:0 12px 12px 0; background:#fff5d9; }
    .index-guide { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:18px 0 32px; }
    .index-guide div { padding:18px; border-radius:16px; background:#e9f3ed; }
    .index-group { margin-top:44px; } .index-group>h3 { padding-bottom:10px; border-bottom:3px solid var(--mint); }
    .index-card { display:grid; grid-template-columns:minmax(300px,.72fr) minmax(0,1.28fr); overflow:hidden; margin:16px 0; border-left:7px solid var(--cyan); }
    .index-card.chlorophyll { border-left-color:#74bd78; } .index-card.pigment { border-left-color:var(--gold); } .index-card.water { border-left-color:#6c9cdf; }
    .index-copy { padding:24px; } .value { display:inline-block; margin-left:8px; padding:4px 8px; border-radius:999px; background:#dff2e7; font-size:.85rem; vertical-align:middle; }
    .formula,.range { color:var(--muted); font-size:.9rem; } .figure-link { align-self:stretch; background:white; } .figure-link img { height:100%; object-fit:contain; }
    .claims { display:grid; grid-template-columns:1fr 1fr; gap:18px; } .claims .panel:first-child { border-top:6px solid #4eaa70; } .claims .panel:last-child { border-top:6px solid var(--rust); }
    .script { padding:30px; font-size:1.12rem; border-left:8px solid var(--gold); }
    .downloads { display:flex; flex-wrap:wrap; gap:10px; } .downloads a { padding:10px 13px; border-radius:10px; background:white; border:1px solid var(--line); text-decoration:none; font-weight:700; }
    .fusion-figures { display:grid; align-content:start; gap:10px; padding:12px; background:#eef3ef; } .fusion-figures img { border-radius:12px; }
    .subheading { margin-top:38px; }
    .trait-card { display:grid; grid-template-columns:minmax(300px,.82fr) minmax(0,1.18fr); overflow:hidden; margin:18px 0; }
    .trait-copy { padding:26px; } .trait-copy h3 { margin-top:0; }
    .trait-list { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:18px 0; }
    .trait-list div { padding:12px; border-radius:12px; background:#edf4ef; } .trait-list dt { color:var(--muted); font-size:.8rem; font-weight:800; text-transform:uppercase; letter-spacing:.05em; } .trait-list dd { margin:2px 0 0; color:var(--green); font-size:1.13rem; font-weight:850; }
    .trait-images { display:grid; grid-template-columns:1fr 1fr; gap:3px; padding:3px; background:#dfe9e2; } .trait-images img { width:100%; height:100%; min-height:280px; object-fit:contain; background:#111; }
    .viewer-shell { padding:14px; overflow:hidden; background:#0a2a22; color:#eefcf5; }
    .viewer-toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:4px 2px 14px; }
    .viewer-toolbar label { display:flex; align-items:center; gap:7px; font-weight:700; }
    .viewer-toolbar button,.viewer-toolbar select { min-height:38px; padding:8px 11px; border:1px solid #78aa98; border-radius:9px; color:#eefcf5; background:#133c32; font:inherit; font-weight:750; cursor:pointer; }
    .viewer-toolbar button:hover,.viewer-toolbar button:focus-visible,.viewer-toolbar button.active { color:#09261f; background:var(--mint); outline:none; }
    #viewer-zoom-in,#viewer-zoom-out { min-width:42px; font-size:1.25rem; line-height:1; }
    .viewer-plants { display:flex; flex-wrap:wrap; gap:6px; margin-right:auto; }
    #fusion-viewer-canvas { display:block; width:100%; height:min(66vh,610px); min-height:390px; border:1px solid #477868; border-radius:14px; background:#071d18; cursor:grab; touch-action:none; }
    #fusion-viewer-canvas:active { cursor:grabbing; } #fusion-viewer-canvas:focus-visible { outline:3px solid var(--gold); outline-offset:3px; }
    .viewer-footer { display:grid; grid-template-columns:1fr auto; gap:6px 18px; align-items:center; padding:13px 4px 2px; color:#d5e9e1; font-size:.9rem; }
    .viewer-footer p { grid-column:1 / -1; margin:0; } .viewer-footer a { color:#b9ecd8; font-weight:800; }
    .legend-grey,.legend-gradient { display:inline-block; width:30px; height:10px; margin:0 5px 0 12px; border-radius:999px; vertical-align:middle; }
    .legend-grey { background:#aaa; } .legend-gradient { width:70px; background:linear-gradient(90deg,#08041f,#7a1a6c,#ef5a2f,#fcffa4); }
    .spectral-inspector { display:grid; grid-template-columns:minmax(280px,.72fr) minmax(0,1.28fr); gap:18px; margin-top:18px; padding:24px; }
    .inspector-copy h3 { margin:0 0 8px; } .inspector-copy>p { margin-top:5px; }
    #inspector-details { margin-top:16px; padding-top:12px; border-top:1px solid var(--line); } #inspector-details p { margin:5px 0; font-size:.92rem; }
    .inspector-indices { display:grid; grid-template-columns:repeat(5,1fr); gap:7px; margin-top:14px; }
    .inspector-indices div { padding:10px 7px; border-radius:10px; text-align:center; background:#edf4ef; } .inspector-indices span { display:block; color:var(--muted); font-size:.74rem; font-weight:800; } .inspector-indices b { display:block; color:var(--green); font-size:1rem; }
    .spectrum-wrap { min-width:0; } #viewer-spectrum-canvas { display:block; width:100%; height:310px; border:1px solid var(--line); border-radius:12px; background:#fbfdf9; touch-action:none; }
    #spectrum-readout { min-height:1.5em; margin:7px 2px 0; color:var(--muted); font-size:.88rem; }
    .viewer-meaning { margin-top:18px; }
    footer { padding:28px max(5vw,24px); color:#d9eee5; background:#082d25; } footer p { width:min(1180px,100%); margin:auto; }
    @media (max-width:900px) { .intro,.core,.index-card,.trait-card,.claims,.spectral-inspector { grid-template-columns:1fr; } .metrics { grid-template-columns:repeat(2,1fr); } .pipeline { grid-template-columns:1fr 1fr; } .step:not(:last-child)::after { display:none; } .trait-images img { min-height:220px; } }
    @media (max-width:560px) { .metrics,.glossary,.index-guide,.pipeline,.trait-list,.trait-images,.viewer-footer { grid-template-columns:1fr; } .hero { padding-top:48px; } main { padding-inline:18px; } #fusion-viewer-canvas { min-height:350px; } .inspector-indices { grid-template-columns:repeat(2,1fr); } #viewer-spectrum-canvas { height:260px; } }
    @media print { nav,.viewer-toolbar { display:none; } body { background:white; font-size:11pt; } .hero { padding:28px; } main { padding:10px 24px; } .panel,.metric,.core,.index-card,.trait-card,.script { box-shadow:none; break-inside:avoid; } h2 { margin-top:32px; } a { color:inherit; text-decoration:none; } #fusion-viewer-canvas { height:420px; } }
    """
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paired Plant Hyperspectral Showcase · 28 August 2026</title><style>{style}</style></head>
<body>
<header class="hero"><div class="hero-inner"><p class="kicker">FX10 VNIR + FX17 SWIR + RGB-D ICP · 28 August 2026</p><h1>From invisible plant spectra to an inspectable 3D scene</h1><p class="lead">A guided, presentation-ready walkthrough of hyperspectral calibration, RGB-D reconstruction and traits, cross-modal fusion, interactive 3D models and recovered placement in the legacy ICP scene.</p><span class="badge">Measured prototype · exploratory indices, not a biological diagnosis</span></div></header>
<nav aria-label="Report sections"><div><a href="#overview">Overview</a><a href="#pipeline">Hyperspectral pipeline</a><a href="#core-results">Spectral results</a><a href="#indices">Indices</a><a href="#rgbd-results">RGB-D / ICP</a><a href="#fusion-results">Fusion</a><a href="#interactive-3d">3D viewer</a><a href="#global-placement">Global placement</a><a href="#claims">Boundaries</a></div></nav>
<main class="wrap">
<section id="overview"><h2>Start here: what am I looking at?</h2><div class="intro"><div class="panel"><h3>One scene, hundreds of invisible colours</h3><p>An ordinary RGB camera records red, green and blue. A hyperspectral camera records a narrow reflectance measurement at hundreds of wavelengths for every image location. FX10 covers visible and near-infrared light; FX17 extends into short-wave infrared. Together they describe pigment, leaf structure and water-related spectral behaviour that normal colour photography cannot show.</p><p><strong>This dataset contains three separate potted plants in one scan.</strong> The page compares their spatial patterns, but it does not contain labels such as healthy, diseased, watered or dry.</p></div><div class="panel"><h3>Four words to know</h3><div class="glossary"><div class="term"><strong>Pixel</strong>One image location.</div><div class="term"><strong>Band</strong>An image at one wavelength.</div><div class="term"><strong>Spectrum</strong>All wavelength values for one pixel.</div><div class="term"><strong>Cube</strong>Rows × columns × bands.</div></div></div></div>
<div class="metrics"><div class="metric"><span>Merged wavelength range</span><b>{float(merged['wavelength_min_nm']):.0f}–{float(merged['wavelength_max_nm']):.0f} nm</b><small>Visible through SWIR after fusion.</small></div><div class="metric"><span>FX10 pixels retained as plant</span><b>{100*float(background['fx10_plant_fraction']):.1f}%</b><small>The rest was treated as background—not discarded spectral bands.</small></div><div class="metric"><span>Overlap disagreement</span><b>{float(cross['overlap_rmse_before']):.4f} → {float(cross['overlap_rmse_after']):.4f}</b><small>Lower is better; cross-camera spectral agreement improved.</small></div><div class="metric"><span>Registration quality</span><b>{int(registration['inliers'])} inliers · {float(registration['mean_reprojection_error']):.2f}px</b><small>Many consistent matches and sub-pixel average alignment error.</small></div></div>
<div class="callout"><strong>Important processing detail:</strong> all 224 spectral bands from each camera were retained, while every fourth spatial row and column was sampled to make this presentation bundle practical. The merged plant cube contains {int(merged['shape'][2])} wavelength bands.</div></section>

<section id="pipeline"><h2>How the raw scan became these results</h2><p>The sequence matters: an index is only meaningful after the sensor values are calibrated, plant pixels are isolated, and the two cameras are brought onto comparable spectral and spatial coordinates.</p><div class="pipeline" aria-label="Hyperspectral processing pipeline"><div class="step"><strong>1 · Raw scans</strong>FX10 and FX17 record sensor intensity.</div><div class="step"><strong>2 · Calibrate</strong>White and dark panels convert intensity to reflectance.</div><div class="step"><strong>3 · Mask</strong>NDVI and NWACI separate plants from the scene.</div><div class="step"><strong>4 · Cross-calibrate</strong>Shared wavelengths correct FX17 scale and offset.</div><div class="step"><strong>5 · Register</strong>SIFT and RANSAC align the two camera views.</div><div class="step"><strong>6 · Merge</strong>Aligned spectra form one 398–1720 nm cube.</div><div class="step"><strong>7 · Analyse</strong>Fourteen indices map relative plant properties.</div></div></section>

<section id="core-results"><h2>Core results, explained</h2>
<article class="core"><div class="core-copy"><p class="eyebrow">Figure 1</p><h3>Raw intensity versus calibrated reflectance</h3><p><strong>Raw</strong> panels show sensor brightness, which depends on lighting and camera response. <strong>Calibrated</strong> panels estimate the fraction of incoming light reflected at each wavelength by subtracting the dark reference and scaling to the white reference.</p><p>FX10 can be displayed in roughly natural colour because it includes visible wavelengths. FX17 is shown in false colour because 1050–1600 nm is invisible to human eyes; the colours reveal contrast, not the plant's real appearance.</p></div><a href="figures/01_raw_and_calibrated_previews.png"><img src="figures/01_raw_and_calibrated_previews.png" alt="FX10 and FX17 raw and calibrated image comparisons"></a></article>
<article class="core"><div class="core-copy"><p class="eyebrow">Figure 2</p><h3>Plant isolation and background removal</h3><p>The software calculated NDVI for FX10 and NWACI for FX17, automatically selected thresholds, then cleaned small holes and isolated noise. White mask pixels mean “use this plant pixel”; black means “exclude this background pixel”.</p><p>FX10 retained <strong>{100*float(background['fx10_plant_fraction']):.1f}%</strong> of its scene at threshold <strong>{float(background['fx10_threshold']):.3f}</strong>. FX17 retained <strong>{100*float(background['fx17_plant_fraction']):.1f}%</strong> at threshold <strong>{float(background['fx17_threshold']):.3f}</strong>. Different percentages are expected because camera framing and wavelengths differ.</p></div><a href="figures/02_background_removal.png"><img src="figures/02_background_removal.png" alt="Original projections, vegetation index maps, masks and masked plant outputs"></a></article>
<article class="core"><div class="core-copy"><p class="eyebrow">Figure 3</p><h3>The mean spectral fingerprint</h3><p>The horizontal axis is wavelength in nanometres. The vertical axis is mean reflectance of the retained plant pixels. The visible pigment region, the sharp red-edge rise near 700 nm, the NIR plateau and strong SWIR water-absorption features are all plant-like spectral structure.</p><p>FX10 and FX17 overlap around 936–1004 nm. A linear gain of <strong>{float(cross['gain']):.3f}</strong> and offset of <strong>{float(cross['offset']):.3f}</strong> reduced overlap RMSE from <strong>{float(cross['overlap_rmse_before']):.4f}</strong> to <strong>{float(cross['overlap_rmse_after']):.4f}</strong>. This means their average curves agree better; it does not prove every individual pixel is perfectly calibrated.</p></div><a href="figures/03_mean_spectra.png"><img src="figures/03_mean_spectra.png" alt="Mean FX10 and FX17 spectra before and after overlap correction"></a></article>
<article class="core"><div class="core-copy"><p class="eyebrow">Figure 4</p><h3>Spatial registration: making the cameras look at the same place</h3><p><strong>SIFT keypoints</strong> are distinctive visual landmarks. <strong>Matches</strong> pair similar landmarks between cameras. <strong>RANSAC inliers</strong> are the pairs that agree on one geometric transformation after outliers are rejected.</p><p>The workflow found {int(registration['keypoints_fx10'])} FX10 and {int(registration['keypoints_fx17'])} FX17 keypoints, {int(registration['good_matches'])} good matches and <strong>{int(registration['inliers'])} inliers</strong>. The average reprojection error was <strong>{float(registration['mean_reprojection_error']):.2f} pixels</strong>. Mutual information rose from {float(registration['mi_initial']):.3f} to {float(registration['mi_final']):.3f}; the small increase is supporting evidence, while the match count, error and overlay provide the clearer alignment evidence.</p><p>The yellow overlay should closely follow the plant shapes. Registration is essential before attaching spectra from the two sensors to the same leaf location.</p></div><a href="figures/04_registration.png"><img src="figures/04_registration.png" alt="FX10 and FX17 projections before alignment and their registered overlay"></a></article>
<article class="core"><div class="core-copy"><p class="eyebrow">Figure 5</p><h3>Three vertical scan regions—not three canopy heights</h3><p>The image was split into top, middle and bottom thirds for a safe demonstration of regional statistics. In this scene those thirds mostly correspond to <strong>three different plants</strong>, so “upper”, “middle” and “lower” describe image position, not top, middle and lower leaves on one plant.</p><p>Mean NDVI was <strong>{float(segments['upper']['mean_NDVI']):.3f}</strong>, <strong>{float(segments['middle']['mean_NDVI']):.3f}</strong> and <strong>{float(segments['lower']['mean_NDVI']):.3f}</strong>. The middle scan region was lower, but without treatment or health labels we cannot say why.</p></div><a href="figures/05_canopy_segments.png"><img src="figures/05_canopy_segments.png" alt="Three vertical regions of the scanned scene used for regional statistics"></a></article>
</section>

<section id="indices"><h2>Fourteen spectral indices: how to read every card</h2><p>Each figure contains three panels: the plant view for orientation, a numerical heatmap, and the same heatmap over the plant. In the inferno colour scale, dark purple is lower and yellow is higher <em>within that index</em>. Blank or black background is masked or invalid. A brighter colour is not universally “healthier”—the biological direction depends on the index.</p><div class="index-guide"><div><strong>Median</strong><br>The middle plant-pixel value; half are below and half above.</div><div><strong>10th–90th percentile</strong><br>The central spread, less distorted by extreme pixels.</div><div><strong>Formula</strong><br><em>R</em> means reflectance at the named wavelength in nanometres.</div></div>{''.join(group_sections)}</section>

<section id="claims"><h2>What the hyperspectral stage does—and does not—establish</h2><div class="claims"><div class="panel"><h3>Evidence supported by this stage</h3><ul><li>Both cameras produced usable, plant-like spectra across their stated ranges.</li><li>The background masks isolate the three plant regions cleanly enough for exploratory analysis.</li><li>FX10 and FX17 average spectra agree substantially better after overlap correction.</li><li>The two camera views were aligned with 190 consistent feature matches and about 0.63-pixel average error.</li><li>A registered 427-band plant cube spanning approximately 398–1720 nm was produced.</li><li>The fourteen maps reveal spatial variation that can guide later sampling and modelling.</li></ul></div><div class="panel"><h3>Scientific boundaries that still apply</h3><ul><li>The indices cannot diagnose disease, drought, nutrient deficiency or plant health without labelled ground truth.</li><li>Index values are not percentages or laboratory concentrations.</li><li>The three scan regions cannot be ranked biologically without labels and controlled treatments.</li><li>The hyperspectral-only stage did not contain 3D geometry; the later RGB-D fusion sections add measured depth and global placement.</li><li>Cross-camera and cross-modal registration are validated approximations, not proof of perfect correspondence everywhere.</li><li>Biological conclusions require reference targets, repeat scans and laboratory or treatment measurements.</li></ul></div></div></section>

<section id="present"><h2>A 60-second hyperspectral-stage script</h2><blockquote class="script">“We captured the same three plants with two hyperspectral cameras. FX10 measures visible and near-infrared wavelengths, while FX17 extends the range into short-wave infrared. We first used white and dark references to convert raw sensor intensity into reflectance, then removed the background so the analysis focused on plant pixels. Because the cameras differ in both spectral response and viewpoint, we corrected their overlapping wavelengths and spatially registered the images. The overlap error fell from 0.0055 to 0.0019, and registration retained 190 consistent feature matches with about 0.63-pixel average error. This produced a 427-band cube spanning roughly 398 to 1720 nanometres. We then calculated fourteen exploratory vegetation, pigment, water and nitrogen-related indices. These maps reveal relative spatial patterns, but they are not diagnoses. The later sections show how the spectra were attached to measured RGB-D geometry and placed in the common ICP scene.”</blockquote></section>

<section id="downloads"><h2>Open the evidence and reusable outputs</h2><p>The figures are presentation views; the linked files below contain the exact values and processed ENVI products.</p><div class="downloads"><a href="quality_metrics.json">Quality metrics (JSON)</a><a href="tables/index_summary.csv">Index summary (CSV)</a><a href="tables/mean_spectra.csv">Mean spectra (CSV)</a><a href="tables/segment_summary.csv">Region summary (CSV)</a><a href="cubes/merged_plant_only_showcase.hdr">Plant-only merged cube header</a><a href="cubes/merged_fx10_fx17_showcase.hdr">Merged cube header</a></div></section>

{rgbd_results_html}

<section id="fusion-roadmap"><h2>Fusion roadmap and current status</h2><p class="eyebrow">Feasibility finding and completed prototype · recorded 31 August 2026</p><div class="panel"><h3>Verdict: feasible—and now demonstrated with the captured data</h3><p>The matching RGB-D run contains <strong>945 RGB frames and 945 depth frames</strong>, calibrated colour and depth intrinsics, an existing ICP reconstruction from 95 sampled frames, a <strong>44,430,791-point</strong> merged cloud, and cleaned point clouds for all three plants. The hyperspectral and RGB-D images visibly contain the same three plants, board grid and black-and-white fiducial markers.</p><p>The RGB-D folder identifies the run as 12:08:00. Both hyperspectral headers record 02:13:42 UTC, equivalent to approximately 12:13:42 Sydney time: about five minutes and forty-two seconds later. Because the subjects are stationary plants and the scene layout matches, sequential—not simultaneous—capture is acceptable for a prototype, although small leaf movement remains a registration error source.</p></div>
<div class="claims"><div class="panel"><h3>Inputs already available</h3><ul><li>Calibrated FX10 and FX17 data and a merged 427-band cube.</li><li>RGB images, aligned depth images and camera intrinsics.</li><li>ICP-based scene reconstruction and individual plant point clouds.</li><li>Strong cross-modal anchors: the board, grid and fiducial markers.</li><li>Reference frames: Coleus 330, fuzzy kalanchoe 540 and succulent/jade 750.</li></ul></div><div class="panel"><h3>Implemented in this prototype</h3><ul><li>FX10-to-RGB-D registration for all three selected frames.</li><li>Depth backprojection from matched pixels into metric XYZ.</li><li>Full 427-band attachment plus five index-coloured 3D exports.</li><li>Depth coverage, reprojection and specimen-surface validation.</li><li>Direct recovery of the three transforms needed for global ICP placement.</li></ul></div></div>
<div class="panel" style="margin-top:18px"><h3>What ICP does—and what it does not do</h3><p>ICP aligns successive RGB-D point clouds to one another. It creates the 3D geometry but cannot directly align a two-dimensional hyperspectral cube to that geometry. Cross-modal fusion therefore needs a separate image-registration step. After an FX10 pixel is matched to an RGB-D pixel, its depth gives camera-space XYZ; the saved ICP pose then places that spectral point in the common reconstruction coordinate system.</p></div>
<div class="panel" style="margin-top:18px"><h3>Implementation sequence—five milestones completed</h3><ol><li><strong>Coleus proof of concept:</strong> registered the upper hyperspectral component to RGB-D frame 330 and exported a depth-derived NDVI surface.</li><li><strong>Complete spectral attachment:</strong> associated the full 427-band spectrum and five indices with each valid 3D point.</li><li><strong>Other plants:</strong> repeated the validated workflow for fuzzy kalanchoe frame 540 and succulent/jade frame 750.</li><li><strong>Global scene placement:</strong> recovered the three required transforms directly against the legacy scene and exported global models.</li><li><strong>Presentation outputs:</strong> added registration overlays, numerical validation, downloadable PLYs and a local interactive viewer.</li></ol><p class="callout"><strong>Coverage limitation:</strong> the hyperspectral cameras primarily measured the upper visible surfaces. Occluded sides and leaf undersides remain grey/unmeasured. Any value propagated to those points would be an inference, not a measurement.</p></div></section>
{fusion_results_html}
{viewer_html}
{global_placement_html}
<script src="fusion/viewer_models.js"></script><script src="fusion/viewer.js"></script>
</main><footer><p><strong>Reproducible local report.</strong> Generated from the 28 August 2026 paired FX10/FX17 and RGB-D acquisitions. Source data were opened read-only. Methods include reflectance calibration, plant masking, cross-camera and cross-modal registration, depth backprojection, spectral attachment, RGB-D trait calculation and direct recovery of the three required legacy-scene transforms.</p></footer>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/20260828"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/20260828_showcase"))
    parser.add_argument("--stride", type=int, default=4, help="Spatial sampling interval; all spectral bands are retained")
    parser.add_argument("--report-only", action="store_true", help="Rebuild index.html from existing metrics and CSV tables without reprocessing cubes")
    args = parser.parse_args()
    data_dir, output_dir = args.data_dir.resolve(), args.output_dir.resolve()
    figures = output_dir / "figures"
    indices_dir = output_dir / "indices"
    tables = output_dir / "tables"
    cubes = output_dir / "cubes"
    for folder in (figures, indices_dir, tables, cubes):
        folder.mkdir(parents=True, exist_ok=True)

    if args.report_only:
        metrics_path = output_dir / "quality_metrics.json"
        index_table = tables / "index_summary.csv"
        segment_table = tables / "segment_summary.csv"
        for required in (metrics_path, index_table, segment_table):
            if not required.exists():
                raise FileNotFoundError(f"Report-only input is missing: {required}")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        with index_table.open(newline="", encoding="utf-8") as handle:
            summaries = list(csv.DictReader(handle))
        with segment_table.open(newline="", encoding="utf-8") as handle:
            segment_rows = list(csv.DictReader(handle))
        fusion_path = output_dir / "fusion" / "fusion_summary.json"
        fusion_summary = json.loads(fusion_path.read_text(encoding="utf-8")) if fusion_path.exists() else None
        rgbd_dir = output_dir / "rgbd_icp"
        reconstruction_path = rgbd_dir / "reconstruction_summary.json"
        traits_path = rgbd_dir / "software_traits.json"
        validation_path = rgbd_dir / "validation" / "validation_results.json"
        global_path = output_dir / "global_placement" / "global_placement_summary.json"
        rgbd_reconstruction = json.loads(reconstruction_path.read_text(encoding="utf-8")) if reconstruction_path.exists() else None
        rgbd_traits = json.loads(traits_path.read_text(encoding="utf-8")) if traits_path.exists() else None
        rgbd_validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else None
        global_placement = json.loads(global_path.read_text(encoding="utf-8")) if global_path.exists() else None
        (output_dir / "index.html").write_text(
            build_report_html(metrics, summaries, segment_rows, fusion_summary, rgbd_reconstruction, rgbd_traits, rgbd_validation, global_placement),
            encoding="utf-8",
        )
        log(f"Presentation report refreshed: {output_dir / 'index.html'}")
        return 0

    fx10_hdr = data_dir / "001-specim-fx10.hdr"
    fx17_hdr = data_dir / "001-specim-fx17.hdr"
    if not fx10_hdr.exists() or not fx17_hdr.exists():
        raise FileNotFoundError("Expected 001-specim-fx10.hdr and 001-specim-fx17.hdr")

    log("[1/8] Loading and calibrating spatially sampled cubes")
    fx10 = load_and_calibrate(fx10_hdr, "fx10", args.stride)
    fx17 = load_and_calibrate(fx17_hdr, "fx17", args.stride)
    save_envi(cubes / "fx10_calibrated_showcase.hdr", fx10["cube"], fx10["metadata"], "FX10 ROI-mean calibrated showcase cube")
    save_envi(cubes / "fx17_calibrated_showcase.hdr", fx17["cube"], fx17["metadata"], "FX17 ROI-mean calibrated showcase cube")

    log("[2/8] Creating raw and calibrated previews")
    fig, axes = plt.subplots(2, 2, figsize=(12, 15))
    for col, item in enumerate((fx10, fx17)):
        camera = item["camera"]
        axes[0, col].imshow(cube_rgb(item["raw"], item["wavelengths"], CAMERAS[camera]["rgb"]))
        axes[0, col].set_title(f"{CAMERAS[camera]['label']}\nRaw scene")
        axes[1, col].imshow(cube_rgb(item["cube"], item["wavelengths"], CAMERAS[camera]["rgb"]))
        axes[1, col].set_title(f"{CAMERAS[camera]['label']}\nReflectance calibrated")
        axes[0, col].axis("off"); axes[1, col].axis("off")
    fig.suptitle("Paired hyperspectral acquisition · 28 August 2026", fontsize=18, fontweight="bold")
    fig.tight_layout()
    save_figure(figures / "01_raw_and_calibrated_previews.png", fig)

    log("[3/8] Detecting plant pixels")
    index10, mask10, threshold10, methods10 = plant_mask(fx10["cube"], fx10["wavelengths"], "fx10")
    index17, mask17, threshold17, methods17 = plant_mask(fx17["cube"], fx17["wavelengths"], "fx17")
    plant10, plant17 = fx10["cube"] * mask10[:, :, None], fx17["cube"] * mask17[:, :, None]
    save_envi(cubes / "fx10_plant_only_showcase.hdr", plant10, fx10["metadata"], "FX10 calibrated cube with NDVI background removal")
    save_envi(cubes / "fx17_plant_only_showcase.hdr", plant17, fx17["metadata"], "FX17 calibrated cube with NWACI background removal")
    fig, axes = plt.subplots(2, 3, figsize=(15, 12))
    for row, (item, idx, mask, title, threshold) in enumerate(((fx10, index10, mask10, "FX10 NDVI", threshold10), (fx17, index17, mask17, "FX17 NWACI", threshold17))):
        rgb = cube_rgb(item["cube"], item["wavelengths"], CAMERAS[item["camera"]]["rgb"])
        axes[row, 0].imshow(rgb); axes[row, 0].set_title(f"{item['camera'].upper()} calibrated")
        im = axes[row, 1].imshow(idx, cmap="RdYlGn"); axes[row, 1].set_title(f"{title} · threshold {threshold:.3f}")
        fig.colorbar(im, ax=axes[row, 1], fraction=0.046)
        axes[row, 2].imshow(rgb * mask[:, :, None]); axes[row, 2].set_title(f"Plant mask · {100 * mask.mean():.1f}% retained")
        for ax in axes[row]: ax.axis("off")
    fig.tight_layout(); save_figure(figures / "02_background_removal.png", fig)

    log("[4/8] Cross-calibrating FX17 to FX10")
    cross = spectral_cross_calibration(fx10, fx17, mask10, mask17)
    corrected17 = cross["cube"]
    save_envi(cubes / "fx17_corrected_showcase.hdr", corrected17, fx17["metadata"], "FX17 linearly cross-calibrated to FX10 in the spectral overlap")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(fx10["wavelengths"], cross["fx10_spectrum"], label="FX10 plant mean", lw=2)
    ax.plot(fx17["wavelengths"], cross["fx17_spectrum"], label="FX17 original plant mean", alpha=.65)
    ax.plot(fx17["wavelengths"], cross["corrected_spectrum"], label="FX17 corrected", lw=2)
    ax.axvspan(936, 1000, color="#7c3aed", alpha=.1, label="Fitting overlap")
    ax.set(xlabel="Wavelength (nm)", ylabel="Reflectance", title="Plant reflectance spectra and FX10/FX17 cross-calibration")
    ax.grid(alpha=.2); ax.legend(); fig.tight_layout(); save_figure(figures / "03_mean_spectra.png", fig)

    log("[5/8] Spatially registering FX17 to FX10")
    fx10["fx17_wavelengths"] = fx17["wavelengths"]
    registration = register_fx17(fx10, corrected17)
    save_envi(cubes / "fx17_registered_showcase.hdr", registration["cube"], fx17["metadata"], "FX17 corrected and spatially registered to FX10")
    overlay = np.zeros((*registration["projection10"].shape, 3), dtype=np.float32)
    overlay[:, :, 1] = registration["projection10"]
    overlay[:, :, 0] = normalize_image(registration["warped_projection"])
    fig, axes = plt.subplots(1, 4, figsize=(18, 6))
    for ax, image, title in zip(axes, (registration["projection10"], registration["projection17"], registration["warped_projection"], overlay), ("FX10 overlap", "FX17 resized", "FX17 registered", "Red/green overlay")):
        ax.imshow(image, cmap="gray" if image.ndim == 2 else None); ax.set_title(title); ax.axis("off")
    fig.suptitle(f"Registration · {registration['method']} · MI {registration['mi_initial']:.3f} → {registration['mi_final']:.3f}")
    fig.tight_layout(); save_figure(figures / "04_registration.png", fig)

    log("[6/8] Building the merged 398–1720 nm cube")
    merged, merged_wavelengths = merge_cubes(fx10, registration["cube"], fx17["wavelengths"])
    merged_metadata = fx10["metadata"].copy(); merged_metadata["wavelength"] = merged_wavelengths.tolist()
    # FX10-only FWHM metadata no longer matches the merged band count.
    merged_metadata.pop("fwhm", None)
    save_envi(cubes / "merged_fx10_fx17_showcase.hdr", merged, merged_metadata, "Merged FX10 plus registered/corrected FX17 showcase cube")
    merged_plant = merged * mask10[:, :, None]
    save_envi(cubes / "merged_plant_only_showcase.hdr", merged_plant, merged_metadata, "Merged showcase cube with FX10 NDVI plant mask")
    merged_rgb = cube_rgb(merged, merged_wavelengths, (680, 550, 450))

    log("[7/8] Calculating and saving all vegetation indices")
    summaries = []
    index_images = []
    for name, formula in INDEX_FORMULAS.items():
        values = calculate_index(merged, merged_wavelengths, name).astype(np.float32)
        values[~mask10] = np.nan
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            continue
        np.save(indices_dir / f"{name}.npy", values)
        lo, hi = np.percentile(finite, [2, 98])
        display = np.clip((values - lo) / (hi - lo + 1e-8), 0, 1)
        heat = plt.cm.inferno(np.nan_to_num(display))[:, :, :3]
        overlay_index = np.clip(.5 * merged_rgb + .5 * heat, 0, 1)
        overlay_index[~mask10] = merged_rgb[~mask10] * .2
        fig, axes = plt.subplots(1, 3, figsize=(15, 6))
        axes[0].imshow(merged_rgb * mask10[:, :, None]); axes[0].set_title("Plant")
        im = axes[1].imshow(values, cmap="inferno", vmin=lo, vmax=hi); axes[1].set_title(f"{name} heatmap")
        fig.colorbar(im, ax=axes[1], fraction=.046)
        axes[2].imshow(overlay_index); axes[2].set_title(f"{name} overlay")
        for ax in axes: ax.axis("off")
        fig.suptitle(f"{name} · {formula}", fontweight="bold")
        fig.tight_layout(); save_figure(indices_dir / f"{name}.png", fig)
        summaries.append({
            "index": name, "formula": formula, "pixels": int(finite.size),
            "mean": float(np.mean(finite)), "median": float(np.median(finite)),
            "std": float(np.std(finite)), "p10": float(np.percentile(finite, 10)),
            "p90": float(np.percentile(finite, 90)), "display_p02": float(lo), "display_p98": float(hi),
        })
        index_images.append((name, f"indices/{name}.png"))

    with (tables / "index_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0].keys()))
        writer.writeheader(); writer.writerows(summaries)

    with (tables / "mean_spectra.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(["camera", "wavelength_nm", "mean_reflectance"])
        for wl, value in zip(fx10["wavelengths"], cross["fx10_spectrum"]): writer.writerow(["FX10", wl, value])
        for wl, value in zip(fx17["wavelengths"], cross["fx17_spectrum"]): writer.writerow(["FX17_original", wl, value])
        for wl, value in zip(fx17["wavelengths"], cross["corrected_spectrum"]): writer.writerow(["FX17_corrected", wl, value])

    # Three vertical canopy segments, matching the app's safe n_cols=1 workflow.
    row_edges = np.linspace(0, merged.shape[0], 4, dtype=int)
    segment_rows = []
    fig, axes = plt.subplots(1, 3, figsize=(15, 8))
    for i, label in enumerate(("upper", "middle", "lower")):
        r0, r1 = int(row_edges[i]), int(row_edges[i + 1])
        segment_mask = mask10[r0:r1]
        axes[i].imshow(merged_rgb[r0:r1] * segment_mask[:, :, None]); axes[i].set_title(f"{label.title()} canopy\nrows {r0}–{r1}"); axes[i].axis("off")
        segment_rows.append({"segment": label, "row_start": r0, "row_end": r1, "plant_fraction": float(segment_mask.mean()), "mean_NDVI": float(np.nanmean(calculate_index(merged[r0:r1], merged_wavelengths, "NDVI")[segment_mask]))})
    fig.suptitle("Presentation segmentation · three vertical canopy regions", fontweight="bold")
    fig.tight_layout(); save_figure(figures / "05_canopy_segments.png", fig)
    with (tables / "segment_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(segment_rows[0].keys())); writer.writeheader(); writer.writerows(segment_rows)

    log("[8/8] Writing provenance, quality metrics, and HTML gallery")
    metrics = {
        "source": {"data_directory": str(data_dir), "fx10_shape": fx10["source_shape"], "fx17_shape": fx17["source_shape"], "spatial_stride": args.stride},
        "calibration": {"method": "median white/dark ROI spectra, reflectance clipped to 0–1", "fx10_valid_bands": fx10["valid_calibration_bands"], "fx17_valid_bands": fx17["valid_calibration_bands"]},
        "background_removal": {"fx10_index": "NDVI", "fx10_threshold": threshold10, "fx10_threshold_methods": methods10, "fx10_plant_fraction": float(mask10.mean()), "fx17_index": "NWACI", "fx17_threshold": threshold17, "fx17_threshold_methods": methods17, "fx17_plant_fraction": float(mask17.mean())},
        "cross_calibration": {"gain": cross["gain"], "offset": cross["offset"], "overlap_rmse_before": cross["rmse_before"], "overlap_rmse_after": cross["rmse_after"]},
        "registration": {k: v for k, v in registration.items() if k not in {"cube", "matrix", "projection10", "projection17", "warped_projection"}},
        "registration_matrix": registration["matrix"].tolist(),
        "merged_cube": {"shape": merged.shape, "wavelength_min_nm": float(merged_wavelengths.min()), "wavelength_max_nm": float(merged_wavelengths.max())},
        "scientific_caveat": "Showcase outputs retain every spectral band but use spatial stride sampling. Index values are exploratory proxies and require biological ground-truth validation.",
    }
    (output_dir / "quality_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    fusion_path = output_dir / "fusion" / "fusion_summary.json"
    fusion_summary = json.loads(fusion_path.read_text(encoding="utf-8")) if fusion_path.exists() else None
    rgbd_dir = output_dir / "rgbd_icp"
    reconstruction_path = rgbd_dir / "reconstruction_summary.json"
    traits_path = rgbd_dir / "software_traits.json"
    validation_path = rgbd_dir / "validation" / "validation_results.json"
    global_path = output_dir / "global_placement" / "global_placement_summary.json"
    rgbd_reconstruction = json.loads(reconstruction_path.read_text(encoding="utf-8")) if reconstruction_path.exists() else None
    rgbd_traits = json.loads(traits_path.read_text(encoding="utf-8")) if traits_path.exists() else None
    rgbd_validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else None
    global_placement = json.loads(global_path.read_text(encoding="utf-8")) if global_path.exists() else None
    page = build_report_html(metrics, summaries, segment_rows, fusion_summary, rgbd_reconstruction, rgbd_traits, rgbd_validation, global_placement)
    (output_dir / "index.html").write_text(page, encoding="utf-8")
    log(f"Showcase complete: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

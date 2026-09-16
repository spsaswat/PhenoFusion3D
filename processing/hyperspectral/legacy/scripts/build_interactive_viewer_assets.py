"""Build compact, file://-safe data for the showcase point-cloud viewer.

The presentation page is opened directly from disk, where browser fetch rules can
block local binary PLY reads.  This script therefore packs a deterministic sample
of each validated fusion model into one JavaScript data file.  Geometry is stored
once per plant; index colours are attached as separate byte arrays.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import numpy as np


INDICES = ("NDVI", "NDRE", "NDWI", "MSI", "NDNI")


def read_binary_ply(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("rb") as handle:
        header: list[str] = []
        while True:
            line = handle.readline()
            if not line:
                raise ValueError(f"Invalid PLY header: {path}")
            decoded = line.decode("ascii").strip()
            header.append(decoded)
            if decoded == "end_header":
                break

        if "format binary_little_endian 1.0" not in header:
            raise ValueError(f"Only binary little-endian PLY is supported: {path}")
        vertex_count = int(next(line for line in header if line.startswith("element vertex ")).split()[-1])
        xyz_type = "<f4" if "property float x" in header else "<f8"
        dtype = np.dtype([
            ("x", xyz_type), ("y", xyz_type), ("z", xyz_type),
            ("r", "u1"), ("g", "u1"), ("b", "u1"),
        ])
        records = np.fromfile(handle, dtype=dtype, count=vertex_count)

    xyz = np.column_stack((records["x"], records["y"], records["z"])).astype("<f4")
    rgb = np.column_stack((records["r"], records["g"], records["b"])).astype("u1")
    return xyz, rgb


def encoded(array: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(array).tobytes()).decode("ascii")


def deterministic_sample(specimen_count: int, measured_count: int, specimen_limit: int) -> np.ndarray:
    if specimen_count <= specimen_limit:
        specimen = np.arange(specimen_count, dtype=np.int64)
    else:
        specimen = np.linspace(0, specimen_count - 1, specimen_limit, dtype=np.int64)
    measured = np.arange(specimen_count, specimen_count + measured_count, dtype=np.int64)
    return np.concatenate((specimen, measured))


def build_model(fusion_dir: Path, key: str, label: str, measured_count: int, specimen_limit: int) -> dict:
    base_path = fusion_dir / key / f"{key}_ndvi_on_specimen.ply"
    xyz, ndvi_colours = read_binary_ply(base_path)
    specimen_count = len(xyz) - measured_count
    if specimen_count < 0:
        raise ValueError(f"Measured count exceeds vertices for {key}")
    selection = deterministic_sample(specimen_count, measured_count, specimen_limit)
    selected_xyz = xyz[selection]
    centre = selected_xyz.mean(axis=0)
    centred = selected_xyz - centre
    radius = float(np.linalg.norm(centred, axis=1).max())
    if radius <= 0:
        raise ValueError(f"Degenerate geometry for {key}")
    centred /= radius

    colours: dict[str, str] = {"NDVI": encoded(ndvi_colours[selection])}
    for index_name in INDICES[1:]:
        index_path = fusion_dir / key / f"{key}_{index_name.lower()}_on_specimen.ply"
        index_xyz, index_colours = read_binary_ply(index_path)
        if len(index_xyz) != len(xyz) or not np.allclose(index_xyz[selection], xyz[selection], atol=1e-6):
            raise ValueError(f"Geometry mismatch in {index_path}")
        colours[index_name] = encoded(index_colours[selection])

    return {
        "label": label,
        "sourceVertices": int(len(xyz)),
        "displayVertices": int(len(selection)),
        "displaySpecimenVertices": int(min(specimen_count, specimen_limit)),
        "measuredVertices": int(measured_count),
        "centreMetres": [round(float(value), 6) for value in centre],
        "normalisationRadiusMetres": round(radius, 6),
        "positions": encoded(centred.astype("<f4")),
        "colours": colours,
        "measuredSegments": [{"plant": key, "start": 0, "count": int(measured_count)}],
    }


def build_global_scene_model(global_dir: Path, counts: dict[str, int], scene_limit: int) -> dict:
    measured_count = sum(counts.values())
    base_path = global_dir / "global_scene_ndvi_sampled.ply"
    xyz, ndvi_colours = read_binary_ply(base_path)
    scene_count = len(xyz) - measured_count
    selection = deterministic_sample(scene_count, measured_count, scene_limit)
    selected_xyz = xyz[selection]
    centre = selected_xyz.mean(axis=0)
    centred = selected_xyz - centre
    radius = float(np.linalg.norm(centred, axis=1).max())
    centred /= radius
    colours: dict[str, str] = {"NDVI": encoded(ndvi_colours[selection])}
    for index_name in INDICES[1:]:
        index_path = global_dir / f"global_scene_{index_name.lower()}_sampled.ply"
        index_xyz, index_colours = read_binary_ply(index_path)
        if len(index_xyz) != len(xyz) or not np.allclose(index_xyz[selection], xyz[selection], atol=1e-6):
            raise ValueError(f"Geometry mismatch in {index_path}")
        colours[index_name] = encoded(index_colours[selection])
    start = 0
    segments = []
    for key in ("coleus", "fuzzy_kalanchoe", "succulent_jade"):
        segments.append({"plant": key, "start": start, "count": int(counts[key])})
        start += int(counts[key])
    return {
        "label": "Global ICP scene",
        "sourceVertices": int(len(xyz)),
        "displayVertices": int(len(selection)),
        "displaySpecimenVertices": int(min(scene_count, scene_limit)),
        "measuredVertices": int(measured_count),
        "centreMetres": [round(float(value), 6) for value in centre],
        "normalisationRadiusMetres": round(radius, 6),
        "positions": encoded(centred.astype("<f4")),
        "colours": colours,
        "measuredSegments": segments,
    }


def build_spectral_point_data(fusion_dir: Path, key: str) -> tuple[dict, np.ndarray]:
    npz_path = fusion_dir / key / f"{key}_spectral_points.npz"
    with np.load(npz_path) as arrays:
        spectra = np.clip(arrays["spectra"], 0.0, 1.0)
        spectra_u16 = np.rint(spectra * 65535.0).astype("<u2")
        hsi_pixels = np.column_stack((arrays["hsi_row"], arrays["hsi_col"])).astype("<u2")
        rgbd_pixels = arrays["rgbd_uv"].astype("<u2")
        index_values = np.column_stack([arrays[f"index_{name}"] for name in INDICES]).astype("<f4")
        wavelengths = arrays["wavelengths_nm"].astype("<f4")
    return {
        "count": int(len(spectra_u16)),
        "bands": int(spectra_u16.shape[1]),
        "spectraU16": encoded(spectra_u16),
        "hsiPixelsU16": encoded(hsi_pixels),
        "rgbdPixelsU16": encoded(rgbd_pixels),
        "indicesF32": encoded(index_values),
        "quantisationScale": 65535,
    }, wavelengths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fusion-dir", type=Path, default=Path("results/20260828_showcase/fusion"))
    parser.add_argument("--output", type=Path, default=Path("results/20260828_showcase/fusion/viewer_models.js"))
    parser.add_argument("--specimen-limit", type=int, default=12000)
    args = parser.parse_args()

    fusion_dir = args.fusion_dir.resolve()
    summary = json.loads((fusion_dir / "fusion_summary.json").read_text(encoding="utf-8"))
    labels = {item["plant"]: item["label"] for item in summary["plants"]}
    counts = {
        item["plant"]: int(item["coverage"]["points_within_20mm_of_specimen_surface"])
        for item in summary["plants"]
    }
    order = ("coleus", "fuzzy_kalanchoe", "succulent_jade")
    models = {
        key: build_model(fusion_dir, key, labels[key], counts[key], args.specimen_limit)
        for key in order
    }
    spectral_points = {}
    wavelengths = None
    for key in order:
        spectral_points[key], current_wavelengths = build_spectral_point_data(fusion_dir, key)
        if wavelengths is None:
            wavelengths = current_wavelengths
        elif not np.allclose(wavelengths, current_wavelengths):
            raise ValueError(f"Wavelength mismatch in {key}")
    global_dir = fusion_dir.parent / "global_placement"
    if (global_dir / "global_scene_ndvi_sampled.ply").exists():
        models["global_scene"] = build_global_scene_model(global_dir, counts, 30000)
    payload = {
        "indices": list(INDICES),
        "wavelengthsF32": encoded(wavelengths),
        "spectralPoints": spectral_points,
        "models": models,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    text = "window.FUSION_VIEWER_MODELS=" + json.dumps(payload, separators=(",", ":")) + ";\n"
    args.output.write_text(text, encoding="utf-8")
    print(f"Wrote {args.output} ({args.output.stat().st_size:,} bytes)")
    for key, model in payload["models"].items():
        print(f"  {key}: {model['displayVertices']:,} displayed / {model['sourceVertices']:,} source vertices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

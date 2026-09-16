#!/usr/bin/env python3
"""Validate fusion arrays, global placement, viewer assets and report links."""

from __future__ import annotations

import json
import re
import base64
from pathlib import Path

import numpy as np
from validate_report_links import check_report_links


def ply_vertex_count(path: Path) -> int:
    with path.open("rb") as handle:
        header = b""
        while b"end_header\n" not in header:
            line = handle.readline()
            if not line:
                raise AssertionError(f"Invalid PLY header: {path}")
            header += line
    assert b"format binary_little_endian 1.0" in header
    return int(re.search(rb"element vertex (\d+)", header).group(1))


def main() -> int:
    showcase = Path("results/20260828_showcase").resolve()
    fusion = showcase / "fusion"
    summary = json.loads((fusion / "fusion_summary.json").read_text(encoding="utf-8"))

    for plant in summary["plants"]:
        key = plant["plant"]
        expected = int(plant["coverage"]["points_within_20mm_of_specimen_surface"])
        with np.load(fusion / key / f"{key}_spectral_points.npz") as arrays:
            assert arrays["xyz_m"].shape == (expected, 3)
            assert arrays["spectra"].shape == (expected, 427)
            assert arrays["wavelengths_nm"].shape == (427,)
            assert np.isfinite(arrays["xyz_m"]).all()
            finite_percent = 100 * float(np.isfinite(arrays["spectra"]).mean())

        combined_ply = fusion / key / f"{key}_ndvi_on_specimen.ply"
        vertices = ply_vertex_count(combined_ply)
        specimen = int(plant["specimen_surface_validation"]["specimen_points"])
        assert vertices == specimen + expected
        print(f"{plant['label']}: {expected:,} points x 427 bands; {finite_percent:.2f}% finite; combined PLY {vertices:,} vertices")

    global_dir = showcase / "global_placement"
    global_summary = json.loads((global_dir / "global_placement_summary.json").read_text(encoding="utf-8"))
    assert len(global_summary["plants"]) == 3
    measured_total = sum(int(plant["coverage"]["points_within_20mm_of_specimen_surface"]) for plant in summary["plants"])
    for plant in global_summary["plants"]:
        transform = np.asarray(plant["transform_camera_to_global"], dtype=float)
        assert transform.shape == (4, 4)
        assert np.allclose(transform[3], [0, 0, 0, 1])
        assert np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3), atol=1e-5)
        assert np.isclose(np.linalg.det(transform[:3, :3]), 1.0, atol=1e-5)
        validation = plant["held_out_validation"]
        assert float(validation["nearest_scene_distance_median_mm"]) < 10.0
        assert float(validation["nearest_scene_distance_p90_mm"]) < 20.0
        assert float(validation["within_20mm_fraction"]) > 0.95
        for index_name in ("ndvi", "ndre", "ndwi", "msi", "ndni"):
            assert (global_dir / plant["plant"] / f"{plant['plant']}_{index_name}_global.ply").exists()
        print(
            f"{plant['label']} global: median {float(validation['nearest_scene_distance_median_mm']):.2f} mm; "
            f"p90 {float(validation['nearest_scene_distance_p90_mm']):.2f} mm; "
            f"{100*float(validation['within_20mm_fraction']):.1f}% within 20 mm"
        )
    for index_name in ("ndvi", "ndre", "ndwi", "msi", "ndni"):
        vertices = ply_vertex_count(global_dir / f"global_scene_{index_name}_sampled.ply")
        assert vertices == 300_000 + measured_total

    viewer_models = fusion / "viewer_models.js"
    viewer_code = fusion / "viewer.js"
    assert viewer_models.exists() and viewer_models.stat().st_size > 1_000_000
    assert viewer_code.exists() and "global_scene" in viewer_code.read_text(encoding="utf-8")
    viewer_source = viewer_models.read_text(encoding="utf-8")
    prefix = "window.FUSION_VIEWER_MODELS="
    assert viewer_source.startswith(prefix) and viewer_source.rstrip().endswith(";")
    viewer_payload = json.loads(viewer_source[len(prefix):].strip()[:-1])
    assert len(base64.b64decode(viewer_payload["wavelengthsF32"])) == 427 * 4
    assert viewer_payload["indices"] == ["NDVI", "NDRE", "NDWI", "MSI", "NDNI"]
    for plant in summary["plants"]:
        key = plant["plant"]
        expected = int(plant["coverage"]["points_within_20mm_of_specimen_surface"])
        point_data = viewer_payload["spectralPoints"][key]
        assert point_data["count"] == expected
        assert point_data["bands"] == 427
        assert len(base64.b64decode(point_data["spectraU16"])) == expected * 427 * 2
        assert len(base64.b64decode(point_data["hsiPixelsU16"])) == expected * 2 * 2
        assert len(base64.b64decode(point_data["rgbdPixelsU16"])) == expected * 2 * 2
        assert len(base64.b64decode(point_data["indicesF32"])) == expected * 5 * 4
        model = viewer_payload["models"][key]
        assert model["measuredSegments"] == [{"plant": key, "start": 0, "count": expected}]
    assert sum(segment["count"] for segment in viewer_payload["models"]["global_scene"]["measuredSegments"]) == measured_total

    page = showcase / "index.html"
    source = page.read_text(encoding="utf-8")
    report_count, reference_count = check_report_links(showcase)
    assert "What was corrected during implementation" in source
    assert 'id="rgbd-results"' in source
    assert 'id="interactive-3d"' in source
    assert 'id="global-placement"' in source
    assert 'id="viewer-spectrum-canvas"' in source
    assert 'id="inspector-indices"' in source
    assert "up to <strong>40× zoom</strong>" in source
    assert "10,485 XYZ points each carry the full 427-band calibrated spectrum" in source
    assert "Missing-pose workaround completed" in source
    assert "global ICP placement is still pending" not in source
    print(f"Reports: {report_count} HTML pages; {reference_count} local references; none missing")
    print("SHOWCASE_VALIDATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import tempfile
import unittest
from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from processing.canopy import CanopyReconstructionConfig, reconstruct_canopy
from processing.reconstructor import ReconstructionConfig, reconstruct_sequence


class ReconstructionE2ETest(unittest.TestCase):
    # The two `test_reconstructs_*` cases below depend on a multi-GB
    # `test_plant_rs13_1/` dataset that is intentionally not committed to
    # git. Tag them as `slow` so the default `pytest` invocation skips
    # them on a fresh checkout / lab machine (see pyproject.toml ->
    # `addopts = "-m 'not slow'"`). Run them explicitly with `pytest -m
    # slow` once the dataset is dropped into the repo root.
    @pytest.mark.slow
    def test_reconstructs_subset_of_bundled_dataset(self):
        repo_root = Path(__file__).resolve().parents[1]
        dataset = repo_root / "test_plant_rs13_1"
        if not dataset.exists():
            self.skipTest("Bundled dataset 'test_plant_rs13_1/' not present.")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "reconstruction_local"
            result = reconstruct_sequence(
                dataset,
                config=ReconstructionConfig(
                    step_size=120,
                    max_frames=3,
                    output_dir=str(output_dir),
                    min_fitness=0.0,
                ),
            )

            self.assertTrue(Path(result.merged_point_cloud_path).exists())
            self.assertTrue(Path(result.summary_path).exists())
            self.assertGreater(result.frames_registered, 0)
            self.assertGreater(result.final_point_count, 0)

    @pytest.mark.slow
    def test_reconstructs_mask_guided_canopy(self):
        repo_root = Path(__file__).resolve().parents[1]
        dataset = repo_root / "test_plant_rs13_1"
        if not dataset.exists():
            self.skipTest("Bundled dataset 'test_plant_rs13_1/' not present.")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "canopy_local"
            result = reconstruct_canopy(
                dataset,
                config=CanopyReconstructionConfig(
                    max_frames=3,
                    min_mask_area=200000,
                    coverage_threshold=1,
                    output_dir=str(output_dir),
                ),
            )

            self.assertTrue(Path(result.point_cloud_path).exists())
            self.assertTrue(Path(result.mesh_path).exists())
            self.assertTrue(Path(result.viewer_path).exists())
            self.assertTrue(Path(result.summary_path).exists())
            self.assertGreater(result.frames_used, 0)
            self.assertGreater(result.final_point_count, 0)

    def test_auto_mask_canopy_without_precomputed_masks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "auto_canopy"
            dataset.mkdir()
            intrinsics = {
                "K": [[90.0, 0, 60.0], [0, 90.0, 40.0], [0, 0, 1]],
                "dist": [0, 0, 0, 0, 0],
                "width": 120,
                "height": 80,
            }
            (dataset / "kdc_intrinsics.txt").write_text(json.dumps(intrinsics), encoding="utf-8")

            for token, dy in [(100, -8), (200, 0), (300, 8)]:
                rgb = np.full((80, 120, 3), 80, dtype=np.uint8)
                depth = np.zeros((80, 120), dtype=np.uint16)
                cv2.ellipse(rgb, (60, 40 + dy), (28, 18), 0, 0, 360, (35, 135, 35), -1)
                cv2.ellipse(depth, (60, 40 + dy), (28, 18), 0, 0, 360, 1200, -1)
                cv2.imwrite(str(dataset / f"rgb_{token}.png"), rgb)
                cv2.imwrite(str(dataset / f"depth_{token}.png"), depth)

            output_dir = Path(temp_dir) / "canopy_auto"
            result = reconstruct_canopy(
                dataset,
                config=CanopyReconstructionConfig(
                    max_frames=3,
                    min_mask_area=200,
                    min_component_area=50,
                    min_valid_depth_points=20,
                    coverage_threshold=1,
                    output_dir=str(output_dir),
                    canvas_padding=8,
                ),
            )

            self.assertTrue(Path(result.point_cloud_path).exists())
            self.assertTrue(Path(result.viewer_path).exists())
            self.assertTrue((output_dir / "auto_masks").exists())
            self.assertGreater(result.frames_used, 0)
            self.assertGreater(result.final_point_count, 0)


if __name__ == "__main__":
    unittest.main()

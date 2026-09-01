import os
import sys
import json
import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from file_io.loader import (
    get_default_intrinsics,
    load_image_pairs,
    load_intrinsics,
    load_session_positions,
)


def test_default_intrinsics_shape():
    K, dist = get_default_intrinsics(640, 480)
    assert K.shape == (3, 3), 'K must be 3x3'
    assert len(dist) == 5, 'dist must have 5 elements'


def test_default_intrinsics_values():
    K, dist = get_default_intrinsics(640, 480, fov_deg=60)
    assert K[0, 2] == 320.0, 'cx should be width/2'
    assert K[1, 2] == 240.0, 'cy should be height/2'
    assert K[2, 2] == 1.0
    assert all(d == 0.0 for d in dist)


def test_load_intrinsics_missing_file():
    result = load_intrinsics('nonexistent_path.txt')
    assert result is None, 'Should return None for missing file'


def test_load_intrinsics_valid(tmp_path):
    import json
    data = {
        'K': [[481.2, 0, 319.5], [0, 480.0, 239.5], [0, 0, 1]],
        'dist': [0, 0, 0, 0, 0],
        'width': 640,
        'height': 480
    }
    f = tmp_path / 'kdc_intrinsics.txt'
    f.write_text(json.dumps(data))
    result = load_intrinsics(str(f))
    assert result is not None
    K, dist, w, h = result
    assert K.shape == (3, 3)
    assert w == 640
    assert h == 480
    assert K[0, 0] == pytest.approx(481.2)


def test_image_pairs_require_matching_frame_identifiers(tmp_path):
    rgb_dir = tmp_path / "rgb"
    depth_dir = tmp_path / "depth"
    rgb_dir.mkdir()
    depth_dir.mkdir()
    for name in ("0.png", "2.png"):
        (rgb_dir / name).touch()
    for name in ("0.png", "1.png"):
        (depth_dir / name).touch()

    with pytest.raises(ValueError, match="frame identifiers.*index 1"):
        load_image_pairs(str(rgb_dir), str(depth_dir))


def test_prefixed_rgb_and_depth_identifiers_are_paired(tmp_path):
    for name in ("rgb_000000.png", "rgb_000002.png"):
        (tmp_path / name).touch()
    for name in ("depth_000000.png", "depth_000002.png"):
        (tmp_path / name).touch()

    pairs = load_image_pairs(str(tmp_path), str(tmp_path))

    assert [os.path.basename(rgb) for rgb, _depth in pairs] == [
        "rgb_000000.png",
        "rgb_000002.png",
    ]
    assert [os.path.basename(depth) for _rgb, depth in pairs] == [
        "depth_000000.png",
        "depth_000002.png",
    ]


def test_session_positions_follow_sampled_pair_identifiers(tmp_path):
    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "gantry_axis": 1,
                "frame_positions": {
                    "0": 0.100,
                    "2": 0.106,
                    "4": 0.112,
                },
            }
        )
    )
    pairs = [
        (str(tmp_path / f"rgb_{index:06d}.png"), str(tmp_path / "unused"))
        for index in (0, 2, 4)
    ]

    positions, axis, step_m = load_session_positions(session_path, pairs)

    assert positions == [0.100, 0.106, 0.112]
    assert axis == 1
    assert step_m == pytest.approx(0.006)

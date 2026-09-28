import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from processing.capture_distance import (  # noqa: E402
    D405_MAX_RANGE_M,
    D405_MIN_RANGE_M,
    VERDICT_ADJUST,
    VERDICT_GOOD,
    VERDICT_NO_DATA,
    VERDICT_OUT_OF_RANGE,
    DistanceThresholds,
    evaluate_depth_directory,
    evaluate_depth_frames,
)


D405_UNITS_PER_M = 10000.0


def depth_frame(near_m, far_m, h=120, w=160, seed=0):
    """Depth frame whose surfaces span [near_m, far_m], in D405 raw units."""
    rng = np.random.RandomState(seed)
    metres = rng.uniform(near_m, far_m, (h, w))
    return (metres * D405_UNITS_PER_M).astype(np.uint16)


def test_plant_inside_the_range_is_good():
    check = evaluate_depth_frames([depth_frame(0.30, 0.45)], D405_UNITS_PER_M)
    assert check.verdict == VERDICT_GOOD
    assert check.suggested_camera_move_m == pytest.approx(0.0)
    assert check.subject_in_range_fraction == pytest.approx(1.0)


def test_camera_too_high_says_lower_it():
    check = evaluate_depth_frames([depth_frame(0.65, 0.80)], D405_UNITS_PER_M)
    assert check.verdict == VERDICT_OUT_OF_RANGE
    # Negative means lower the camera; the far edge must land inside the range.
    assert check.suggested_camera_move_m < 0.0
    assert check.subject_farthest_m + check.suggested_camera_move_m <= (
        D405_MAX_RANGE_M
    )
    assert 'Lower the camera' in check.advice


def test_camera_too_low_says_raise_it():
    check = evaluate_depth_frames([depth_frame(0.03, 0.06)], D405_UNITS_PER_M)
    assert check.verdict == VERDICT_OUT_OF_RANGE
    assert check.suggested_camera_move_m > 0.0
    assert check.subject_nearest_m + check.suggested_camera_move_m >= (
        D405_MIN_RANGE_M
    )
    assert 'Raise the camera' in check.advice


def test_plant_against_the_far_boundary_needs_a_small_move():
    check = evaluate_depth_frames([depth_frame(0.20, 0.52)], D405_UNITS_PER_M)
    assert check.verdict == VERDICT_ADJUST
    assert -0.10 < check.suggested_camera_move_m < 0.0


def test_empty_depth_reports_no_data_rather_than_a_distance():
    check = evaluate_depth_frames(
        [np.zeros((120, 160), dtype=np.uint16)], D405_UNITS_PER_M
    )
    assert check.verdict == VERDICT_NO_DATA
    assert check.nearest_m is None
    assert check.valid_fraction == pytest.approx(0.0)


def test_no_frames_reports_no_data():
    check = evaluate_depth_frames([], D405_UNITS_PER_M)
    assert check.verdict == VERDICT_NO_DATA
    assert check.frames_evaluated == 0


def test_background_behind_the_plant_does_not_decide_the_verdict():
    """Floor far behind the canopy must not read as a badly placed camera."""
    frame = depth_frame(0.20, 0.40)
    frame[:, :80] = int(1.2 * D405_UNITS_PER_M)
    check = evaluate_depth_frames([frame], D405_UNITS_PER_M)

    assert check.verdict == VERDICT_GOOD
    # The whole-frame numbers still report the out-of-range background.
    assert check.too_far_fraction == pytest.approx(0.5, abs=0.02)
    assert check.subject_pixel_fraction == pytest.approx(0.5, abs=0.02)
    assert any('behind the layer measured above' in note for note in check.notes)


def test_a_subject_filling_the_whole_range_is_not_called_unfittable():
    """The comfort margins must not contradict a GOOD verdict."""
    check = evaluate_depth_frames(
        [depth_frame(D405_MIN_RANGE_M, D405_MAX_RANGE_M)], D405_UNITS_PER_M
    )
    assert check.subject_in_range_fraction == pytest.approx(1.0)
    assert check.verdict == VERDICT_GOOD
    assert check.subject_fits_in_range
    assert not any(
        'deeper than the usable interval' in note for note in check.notes
    )


def test_subject_deeper_than_the_usable_range_is_flagged_as_unfittable():
    wide = DistanceThresholds(subject_band_m=0.80)
    check = evaluate_depth_frames(
        [depth_frame(0.20, 0.90)], D405_UNITS_PER_M, thresholds=wide
    )
    assert not check.subject_fits_in_range
    assert any('deeper than the usable interval' in note for note in check.notes)


def test_readings_against_the_sensor_floor_warn_about_lost_surfaces():
    """Surfaces nearer than the floor are dropped, not measured."""
    check = evaluate_depth_frames(
        [depth_frame(D405_MIN_RANGE_M, 0.25)], D405_UNITS_PER_M
    )
    assert any('floor' in note for note in check.notes)
    assert check.suggested_camera_move_m > 0.0


def test_a_well_placed_plant_carries_no_warnings():
    check = evaluate_depth_frames([depth_frame(0.30, 0.45)], D405_UNITS_PER_M)
    assert check.verdict == VERDICT_GOOD
    assert check.notes == []


def test_material_behind_a_reachable_layer_is_noted_even_when_adjusting():
    """A tall plant and a distant floor look alike; say so either way."""
    check = evaluate_depth_frames([depth_frame(0.20, 0.90)], D405_UNITS_PER_M)
    assert check.too_far_fraction > 0.2
    assert any('behind the layer measured above' in note for note in check.notes)


def test_a_camera_far_too_high_is_not_told_about_background():
    """Everything is out of range, so nothing sits 'behind' the layer."""
    check = evaluate_depth_frames([depth_frame(0.65, 0.80)], D405_UNITS_PER_M)
    assert check.too_far_fraction == pytest.approx(1.0)
    assert not any(
        'behind the layer measured above' in note for note in check.notes
    )


def test_depth_scale_changes_the_measured_distance():
    """A millimetre frame read as D405 units would look ten times closer."""
    millimetre_frame = (np.full((60, 80), 300, dtype=np.uint16))
    correct = evaluate_depth_frames([millimetre_frame], 1000.0)
    wrong = evaluate_depth_frames([millimetre_frame], 10000.0)
    assert correct.nearest_m == pytest.approx(0.30, abs=1e-6)
    assert wrong.nearest_m == pytest.approx(0.03, abs=1e-6)
    assert correct.verdict == VERDICT_GOOD
    assert wrong.verdict == VERDICT_OUT_OF_RANGE


@pytest.mark.parametrize('bad_scale', [0.0, -1000.0, float('nan')])
def test_invalid_depth_scale_is_rejected(bad_scale):
    with pytest.raises(ValueError):
        evaluate_depth_frames([depth_frame(0.30, 0.40)], bad_scale)


def test_non_d405_camera_is_noted_as_advisory():
    check = evaluate_depth_frames(
        [depth_frame(0.30, 0.40)],
        D405_UNITS_PER_M,
        camera_model='Intel RealSense L515 (f0231234)',
    )
    assert any('advisory' in note for note in check.notes)


def test_thresholds_are_configurable():
    """A narrower usable band moves the same scene out of range."""
    frame = depth_frame(0.30, 0.45)
    narrow = DistanceThresholds(min_range_m=0.05, max_range_m=0.20)
    check = evaluate_depth_frames(
        [frame], D405_UNITS_PER_M, thresholds=narrow
    )
    assert check.verdict == VERDICT_OUT_OF_RANGE
    assert check.suggested_camera_move_m < 0.0


def test_multiple_frames_are_pooled():
    frames = [depth_frame(0.30, 0.40, seed=i) for i in range(4)]
    check = evaluate_depth_frames(frames, D405_UNITS_PER_M)
    assert check.frames_evaluated == 4
    assert check.verdict == VERDICT_GOOD


def test_evaluate_depth_directory_reads_saved_frames(tmp_path):
    cv2 = pytest.importorskip('cv2')
    depth_dir = tmp_path / 'depth'
    depth_dir.mkdir()
    for index in range(6):
        cv2.imwrite(
            str(depth_dir / f'{index}.png'), depth_frame(0.25, 0.40, seed=index)
        )

    check = evaluate_depth_directory(
        str(depth_dir), D405_UNITS_PER_M, max_frames=3
    )
    assert check.verdict == VERDICT_GOOD
    assert check.frames_evaluated == 3
    assert any('saved depth frames' in note for note in check.notes)


def test_evaluate_depth_directory_honours_the_requested_frame_count(tmp_path):
    """A stride of ceil(n / max_frames) silently returned far fewer frames."""
    cv2 = pytest.importorskip('cv2')
    depth_dir = tmp_path / 'depth'
    depth_dir.mkdir()
    for index in range(12):
        cv2.imwrite(
            str(depth_dir / f'{index}.png'), depth_frame(0.25, 0.40, seed=index)
        )

    check = evaluate_depth_directory(
        str(depth_dir), D405_UNITS_PER_M, max_frames=10
    )
    assert check.frames_evaluated == 10

    # Fewer frames on disk than requested is not an error.
    check = evaluate_depth_directory(
        str(depth_dir), D405_UNITS_PER_M, max_frames=50
    )
    assert check.frames_evaluated == 12


def test_evaluate_depth_directory_rejects_an_empty_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        evaluate_depth_directory(str(tmp_path), D405_UNITS_PER_M)

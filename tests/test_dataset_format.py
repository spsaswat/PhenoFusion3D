"""The dataset preset decides the depth scale, so a misread path rescales
every reconstruction by five. These cases pin the matching rule."""

import pytest

from app.controller import (
    ICL_FORMAT,
    REALSENSE_FORMAT,
    detect_dataset_format,
)


@pytest.mark.parametrize(
    "rgb_dir",
    [
        "/srv/icl/rgb",
        "/srv/ICL/rgb",
        "/srv/ICL-NUIM/living_room_traj0/rgb",
        "/srv/icl_nuim/office/rgb",
        "icl-nuim/rgb",
    ],
)
def test_icl_sequences_use_the_icl_preset(rgb_dir):
    assert detect_dataset_format(rgb_dir) == ICL_FORMAT


@pytest.mark.parametrize(
    "rgb_dir",
    [
        # Ordinary names that a substring test over the whole path would
        # have misread as ICL-NUIM, scaling depth by five.
        "/data/particles/rgb",
        "/home/vicl/data/rgb",
        "/data/helicL/rgb",
        "/data/my_icls/rgb",
        "/data/follicle_study/rgb",
        # The lab's own captures.
        "/data/main/test_plant_20260828120800/rgb",
        "data/captures/session_01/rgb",
        "",
    ],
)
def test_other_paths_use_the_realsense_preset(rgb_dir):
    assert detect_dataset_format(rgb_dir) == REALSENSE_FORMAT


def test_reconstruction_and_quality_agree_on_the_preset():
    """Both pipelines must read the same format from the same path."""
    from app.controller import Controller

    icl = "/srv/ICL-NUIM/living_room_traj0/rgb"
    lab = "/data/particles/rgb"

    controller = Controller.__new__(Controller)  # no Qt/ROS setup needed
    assert controller._build_quality_params(icl).depth_scale == 5000.0
    assert controller._build_quality_params(lab).depth_scale == 1000.0

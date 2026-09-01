import os
import sys
import numpy as np
import pytest
import open3d as o3d

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from processing.icp import color_icp, point_to_plane_icp
from processing.reconstructor import Reconstructor
from processing.registration_agent import AgentConfig


def make_sphere_pcd(n=500, noise=0.001):
    """Synthetic coloured point cloud on a sphere surface."""
    phi = np.random.uniform(0, np.pi, n)
    theta = np.random.uniform(0, 2 * np.pi, n)
    x = np.sin(phi) * np.cos(theta) + np.random.randn(n) * noise
    y = np.sin(phi) * np.sin(theta) + np.random.randn(n) * noise
    z = np.cos(phi) + np.random.randn(n) * noise
    pts = np.stack([x, y, z], axis=1)
    colors = np.random.uniform(0, 1, (n, 3))
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    pcd.colors = o3d.utility.Vector3dVector(colors)
    return pcd


def make_offset_pair(offset=0.01):
    """Source and target are the same cloud with a small translation."""
    source = make_sphere_pcd(n=500)
    target = o3d.geometry.PointCloud(source)
    # Apply a tiny known translation
    T = np.eye(4)
    T[0, 3] = offset
    target.transform(T)
    return source, target


def test_color_icp_returns_tuple():
    source, target = make_offset_pair()
    result, transform, fitness, rmse = color_icp(source, target)
    assert transform.shape == (4, 4)
    assert isinstance(fitness, float)
    assert isinstance(rmse, float)


def test_color_icp_fitness_positive():
    source, target = make_offset_pair(offset=0.005)
    _, _, fitness, _ = color_icp(source, target, voxel_size=0.01)
    assert fitness >= 0.0, 'Fitness must be non-negative'


def test_point_to_plane_icp_runs():
    source, target = make_offset_pair()
    result, transform, fitness, rmse = point_to_plane_icp(source, target)
    assert transform.shape == (4, 4)


def test_color_icp_empty_input():
    empty = o3d.geometry.PointCloud()
    source = make_sphere_pcd()
    _, transform, fitness, rmse = color_icp(empty, source)
    assert fitness == 0.0
    assert np.allclose(transform, np.eye(4))


def test_reconstructor_seeds_full_gap_after_rejected_frame(monkeypatch):
    def cloud():
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector([[0.0, 0.0, 1.0]])
        pcd.colors = o3d.utility.Vector3dVector([[0.5, 0.5, 0.5]])
        return pcd

    monkeypatch.setattr(
        "processing.reconstructor.cv2.imread",
        lambda *_args, **_kwargs: np.zeros((2, 2, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        "processing.reconstructor.cv2.cvtColor",
        lambda image, _code: image,
    )
    monkeypatch.setattr(
        "processing.reconstructor.rgbd2pcd",
        lambda *_args, **_kwargs: cloud(),
    )
    monkeypatch.setattr(
        "processing.reconstructor.clean_pcd_for_registration",
        lambda pcd: pcd,
    )

    seeds = []

    def fake_color_icp(_source, _target, **kwargs):
        init = np.asarray(kwargs["init"]).copy()
        seeds.append(float(init[0, 3]))
        if len(seeds) == 1:
            return None, init, 0.0, 0.0
        return None, init, 0.8, 0.002

    monkeypatch.setattr("processing.reconstructor.color_icp", fake_color_icp)
    reconstructor = Reconstructor(
        pairs=[("rgb0", "depth0"), ("rgb1", "depth1"), ("rgb2", "depth2")],
        K=np.eye(3),
        gantry_step_m=0.01,
        gantry_axis=0,
        agent_config=AgentConfig(
            floor_min_fitness=1e-9,
            floor_max_rmse=1.0,
            max_retries=0,
        ),
    )

    _cloud, succeeded, failed = reconstructor.run()

    assert seeds == pytest.approx([0.01, 0.02])
    assert [entry["frame"] for entry in succeeded] == [0, 2]
    assert [entry["frame"] for entry in failed] == [1]


def test_reconstructor_extrapolates_last_accepted_motion_for_legacy_data(
    monkeypatch,
):
    def cloud():
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector([[0.0, 0.0, 1.0]])
        pcd.colors = o3d.utility.Vector3dVector([[0.5, 0.5, 0.5]])
        return pcd

    monkeypatch.setattr(
        "processing.reconstructor.cv2.imread",
        lambda *_args, **_kwargs: np.zeros((2, 2, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        "processing.reconstructor.cv2.cvtColor",
        lambda image, _code: image,
    )
    monkeypatch.setattr(
        "processing.reconstructor.rgbd2pcd",
        lambda *_args, **_kwargs: cloud(),
    )
    monkeypatch.setattr(
        "processing.reconstructor.clean_pcd_for_registration",
        lambda pcd: pcd,
    )

    seeds = []

    def fake_color_icp(_source, _target, **kwargs):
        init = np.asarray(kwargs["init"]).copy()
        seeds.append(float(init[0, 3]))
        transformation = init.copy()
        if len(seeds) == 1:
            transformation[0, 3] = 0.01
            return None, transformation, 0.8, 0.002
        if len(seeds) == 2:
            return None, transformation, 0.0, 0.0
        return None, transformation, 0.8, 0.002

    monkeypatch.setattr("processing.reconstructor.color_icp", fake_color_icp)
    reconstructor = Reconstructor(
        pairs=[
            ("rgb0", "depth0"),
            ("rgb1", "depth1"),
            ("rgb2", "depth2"),
            ("rgb3", "depth3"),
        ],
        K=np.eye(3),
        agent_config=AgentConfig(
            floor_min_fitness=1e-9,
            floor_max_rmse=1.0,
            max_retries=0,
        ),
    )

    _cloud, succeeded, failed = reconstructor.run()

    assert seeds == pytest.approx([0.0, 0.01, 0.02])
    assert [entry["frame"] for entry in succeeded] == [0, 1, 3]
    assert [entry["frame"] for entry in failed] == [2]

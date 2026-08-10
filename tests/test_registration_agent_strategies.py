"""
tests/test_registration_agent_strategies.py
-------------------------------------------
Integration tests for the recovery strategies in
``processing.registration_agent.apply_strategy``.

Unlike ``test_registration_agent.py`` (which exercises the pure-numpy
judging core), these tests construct a real Open3D synthetic point cloud
pair and confirm each strategy returns a valid, non-empty (source,
target, init_tf, kwargs, use_p2p) tuple suitable for feeding back into
``color_icp`` / ``point_to_plane_icp``.

Skipped automatically when Open3D is not importable so the unit suite
stays green on slim CI environments.
"""

import sys
import os
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

o3d = pytest.importorskip('open3d')

from processing.registration_agent import (
    AgentConfig,
    RegistrationAgent,
    apply_strategy,
)


# --------------------------------------------------------------- fixtures

def _make_cloud(n_points: int = 1000,
                seed: int = 0,
                offset: tuple = (0.0, 0.0, 0.0)):
    """Build a synthetic coloured point cloud roughly 0.5 m across at z~1 m.

    A textured (random RGB) plane-ish cloud is enough to exercise every
    strategy: depth clipping, voxel downsampling, statistical outlier
    removal, init re-seed, point-to-plane and FPFH/RANSAC.
    """
    rng = np.random.default_rng(seed)
    xs = rng.uniform(-0.25, 0.25, n_points)
    ys = rng.uniform(-0.25, 0.25, n_points)
    # z noise around 1.0 m so the depth-clip strategy has a meaningful
    # median + MAD to work against.
    zs = 1.0 + rng.normal(0.0, 0.02, n_points)
    pts = np.stack([xs + offset[0],
                    ys + offset[1],
                    zs + offset[2]], axis=1)
    cols = rng.uniform(0.0, 1.0, (n_points, 3))

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    pcd.colors = o3d.utility.Vector3dVector(cols)
    return pcd


@pytest.fixture
def synthetic_pair():
    """A small (~1k) source/target pair used by every strategy except
    feature_init (which is given a denser cloud below)."""
    src = _make_cloud(n_points=1000, seed=1)
    tgt = _make_cloud(n_points=1000, seed=2, offset=(0.001, 0.0, 0.0))
    return src, tgt


# ---------------------------------------------------------- parametrized

# Every strategy except feature_init -- that one needs a denser cloud
# AND a wall-clock budget, so it lives in its own test below.
_FAST_STRATEGIES = (
    'tighter_crop',
    'voxel_downsample',
    'denoise',
    'reseed_init',
    'point_to_plane',
)


@pytest.mark.parametrize('strategy', _FAST_STRATEGIES)
def test_strategy_returns_valid_tuple(synthetic_pair, strategy):
    """Each fast strategy must return a 5-tuple whose clouds are non-empty
    and whose init transform is a 4x4 float matrix."""
    src, tgt = synthetic_pair
    voxel_size = 0.005

    out = apply_strategy(
        strategy, src, tgt,
        init_tf=np.eye(4),
        voxel_size=voxel_size,
        expected_step_m=0.001,
        gantry_axis=0,
        max_iter=20,
    )

    assert isinstance(out, tuple) and len(out) == 5, (
        f'{strategy!r} returned {type(out).__name__} of length '
        f'{len(out) if hasattr(out, "__len__") else "?"}'
    )
    src2, tgt2, init2, kwargs, use_p2p = out

    # Clouds must still be Open3D PointCloud instances and non-empty.
    assert isinstance(src2, o3d.geometry.PointCloud), (
        f'{strategy!r} returned source of type {type(src2).__name__}')
    assert isinstance(tgt2, o3d.geometry.PointCloud), (
        f'{strategy!r} returned target of type {type(tgt2).__name__}')
    assert not src2.is_empty(), f'{strategy!r} produced empty source'
    assert not tgt2.is_empty(), f'{strategy!r} produced empty target'

    # init transform must be a finite 4x4 matrix.
    init2 = np.asarray(init2)
    assert init2.shape == (4, 4), (
        f'{strategy!r} returned init shape {init2.shape}, expected (4, 4)')
    assert np.isfinite(init2).all(), (
        f'{strategy!r} returned non-finite init transform')

    # icp kwargs must contain a positive voxel_size and max_iter.
    assert 'voxel_size' in kwargs and kwargs['voxel_size'] > 0
    assert 'max_iter' in kwargs and kwargs['max_iter'] > 0

    # only point_to_plane should set use_p2p.
    assert use_p2p is (strategy == 'point_to_plane')


def test_reseed_init_uses_expected_step():
    """The reseed_init strategy should encode the gantry step on the
    requested axis -- this is the whole point of the strategy."""
    src = _make_cloud(n_points=200, seed=3)
    tgt = _make_cloud(n_points=200, seed=4)

    _, _, init_tf, _, _ = apply_strategy(
        'reseed_init', src, tgt,
        init_tf=np.array([[1, 0, 0, 99],     # poisoned init -- should be wiped
                          [0, 1, 0, 99],
                          [0, 0, 1, 99],
                          [0, 0, 0,  1]], dtype=float),
        voxel_size=0.005,
        expected_step_m=0.0042,
        gantry_axis=1,
        max_iter=10,
    )
    # Identity rotation, expected_step on axis 1, zero on others.
    np.testing.assert_allclose(init_tf[:3, :3], np.eye(3), atol=1e-9)
    assert abs(init_tf[1, 3] - 0.0042) < 1e-9
    assert abs(init_tf[0, 3]) < 1e-9 and abs(init_tf[2, 3]) < 1e-9


def test_unknown_strategy_raises():
    src = _make_cloud(n_points=50, seed=5)
    tgt = _make_cloud(n_points=50, seed=6)
    with pytest.raises(ValueError):
        apply_strategy(
            'does_not_exist', src, tgt,
            init_tf=np.eye(4), voxel_size=0.005,
            expected_step_m=0.0, gantry_axis=0, max_iter=10,
        )


# ----------------------------------------------------------- feature_init

# Feature-based init is heavy (FPFH + RANSAC) and gated behind
# ``AgentConfig.enable_feature_init``. We deliberately decouple it from
# Sub-issue 2 so the rest of the recovery loop doesn't pay for it.
#
# Budget: warn (not fail) if a 10k-point cloud takes longer than 5 seconds
# end-to-end. CI hardware varies, so a hard fail would be flaky.

def test_feature_init_runs_in_reasonable_time(recwarn):
    src = _make_cloud(n_points=10_000, seed=7)
    tgt = _make_cloud(n_points=10_000, seed=8, offset=(0.005, 0.0, 0.0))

    t0 = time.perf_counter()
    src2, tgt2, init2, kwargs, use_p2p = apply_strategy(
        'feature_init', src, tgt,
        init_tf=np.eye(4),
        voxel_size=0.005,
        expected_step_m=0.005,
        gantry_axis=0,
        max_iter=20,
    )
    elapsed = time.perf_counter() - t0

    assert isinstance(src2, o3d.geometry.PointCloud) and not src2.is_empty()
    assert isinstance(tgt2, o3d.geometry.PointCloud) and not tgt2.is_empty()
    init2 = np.asarray(init2)
    assert init2.shape == (4, 4)
    assert np.isfinite(init2).all()
    # feature_init returns a normal color-ICP-shaped tuple (not p2p).
    assert use_p2p is False

    if elapsed > 5.0:
        import warnings
        warnings.warn(
            f'feature_init took {elapsed:.2f}s on a 10k-point cloud '
            f'(soft budget 5.0s). Consider lowering the RANSAC iteration '
            f'cap or down-sampling before FPFH.',
            stacklevel=1,
        )


def test_feature_init_gated_by_config():
    """Sanity check: enable_feature_init flips the agent's recovery list."""
    # Default config: feature_init must NOT appear in the recovery sequence.
    agent = RegistrationAgent(AgentConfig())
    seen = {agent.next_recovery(i) for i in range(20)} - {None}
    assert 'feature_init' not in seen

    # Opt-in: feature_init must appear (and it's the heaviest, so it's last).
    agent_on = RegistrationAgent(AgentConfig(enable_feature_init=True,
                                             max_retries=10))
    seen_on = [agent_on.next_recovery(i) for i in range(10)]
    seen_on = [s for s in seen_on if s is not None]
    assert 'feature_init' in seen_on
    assert seen_on[-1] == 'feature_init', (
        'feature_init should be the last (heaviest) recovery option')

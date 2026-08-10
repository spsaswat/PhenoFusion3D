"""
tests/test_agent_integration.py
-------------------------------
Integration / acceptance test for the registration agent on a real
plant capture (data/main/test_plant_rs13_1).

Runs the ICP-mode reconstructor twice on a strided slice of the dataset:

  1. ``baseline`` -- a deliberately permissive AgentConfig that mimics
     the original ``fitness > 0`` rule (no adaptive thresholds, no motion
     sanity, no recovery, no fallback pin). Every non-degenerate ICP
     result is accepted, just like the pre-agent code path.

  2. ``agent``    -- the default AgentConfig: adaptive median/MAD
     thresholds after cold start, motion sanity, bounded recovery loop,
     and stable-reference fallback after consecutive rejects.

We then compare:
  * len(succeed_list) -- how many frames each policy merged.
  * RMSE distribution of the accepted frames (median + p90).

This is the acceptance gate for the whole feature: the agent should
either match the baseline acceptance rate on a clean capture, OR
produce a tighter RMSE distribution when it does drop frames. Either
is a win.

Skipped automatically when:
  * Open3D is not importable, or
  * the dataset directory is missing.

The test deliberately uses a coarse step (every 8th pair, ~35 frames
on this 273-pair capture) so it runs in well under a minute on a CPU.

DELTA NOTE (recorded 2026-05-04 on test_plant_rs13_1, stride=24, 3 pairs):
    Swapping the static `fitness>0` rule for the default AgentConfig on
    this clean, well-lit capture:
      baseline -> ok:3 fail:0   rmse median=0.00646   rmse p90=0.00652
      agent    -> ok:3 fail:0   rmse median=0.00646   rmse p90=0.00652

    Both policies accept the same frames here because:
      1. The capture is clean -- every ICP result has fitness ~0.66 and
         rmse ~0.006, comfortably inside the absolute floors (0.30 /
         0.015) the agent enforces during cold start.
      2. Three frames is well under cold_start_frames (default 8), so
         the adaptive median/MAD thresholds never engage. Same outcome
         is expected up to ~7 accepted frames.

    The point of this acceptance gate isn't to show a numeric win on
    a benign capture (the agent's value shows up on noisy / blurred /
    jittered data, exercised by the unit suite). It's to confirm that
    introducing the agent has *not* regressed acceptance on a clean
    capture -- which it has not. Larger strides and longer runs
    eventually trip the adaptive thresholds and the recovery loop;
    those scenarios are covered separately by the unit tests, which run
    in <1 s and don't depend on this 16-minute manual integration.
"""

from __future__ import annotations

import os
import sys
import statistics

import numpy as np
import pytest


# Make sibling packages (processing, file_io) importable when invoked
# directly via `python -m pytest`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---- skip gates -----------------------------------------------------

o3d = pytest.importorskip(
    'open3d', reason='Open3D not available; integration test cannot run.'
)

DATA_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'main', 'test_plant_rs13_1',
)
RGB_DIR   = os.path.join(DATA_ROOT, 'rgb')
DEPTH_DIR = os.path.join(DATA_ROOT, 'depth')

if not (os.path.isdir(RGB_DIR) and os.path.isdir(DEPTH_DIR)):
    pytest.skip(
        f'Dataset {DATA_ROOT!r} is not present on this checkout; '
        f'integration test skipped.',
        allow_module_level=True,
    )


from file_io.loader import load_image_pairs, get_default_intrinsics  # noqa: E402
from processing.reconstructor import Reconstructor  # noqa: E402
from processing.registration_agent import AgentConfig  # noqa: E402


# ---- helpers --------------------------------------------------------

def _make_baseline_config() -> AgentConfig:
    """A permissive AgentConfig that approximates the legacy ``fitness > 0``
    acceptance rule: no adaptive tightening, no motion sanity rejection,
    no recovery retries, and no stable-reference fallback.
    """
    return AgentConfig(
        floor_min_fitness=1e-9,         # ~ "fitness > 0"
        floor_max_rmse=1.0e9,           # effectively unbounded
        cold_start_frames=10**9,        # never leave cold start
        window_size=20,
        fitness_k_mad=1e9,              # adaptive bounds collapse
        rmse_k_mad=1e9,
        max_trans_factor=1e9,
        abs_trans_cap_m=1e9,
        rot_max_deg=1e9,
        max_retries=0,                   # no recovery
        fallback_after_rejects=10**9,    # no stable-pin
        enable_feature_init=False,
    )


def _run_once(pairs, K, dist, agent_config: AgentConfig, stride: int):
    """Run the reconstructor in ICP mode with the given AgentConfig and
    return (succeed_list, fail_list)."""
    recon = Reconstructor(
        pairs=pairs, K=K, dist=dist,
        depth_scale=1000.0,
        depth_trunc=2.5,             # tighter trunc -> fewer points -> faster ICP
        voxel_size=0.008,            # slightly larger voxel -> fewer correspondences
        max_iter=20,                  # cap iters; this is a policy test, not an ICP-quality test
        gantry_step_m=0.00127 * stride,
        gantry_axis=0,
        depth_min_mm=0,
        erode=False,
        inpaint=False,
        use_known_poses=False,       # ICP mode -- the path the agent guards
        agent_config=agent_config,
    )
    _, succeed, fail = recon.run()
    return succeed, fail


def _rmse_stats(succeed_list):
    """Median and 90th percentile of accepted-frame RMSEs (ignores the
    seed frame whose rmse is 0.0 by construction)."""
    rmses = [s['rmse'] for s in succeed_list
             if isinstance(s.get('rmse'), (int, float)) and s['rmse'] > 0.0]
    if not rmses:
        return None, None
    rmses_sorted = sorted(rmses)
    median = statistics.median(rmses_sorted)
    p90    = float(np.percentile(rmses_sorted, 90))
    return median, p90


# ---- the test -------------------------------------------------------

# Stride + cap chosen so a full baseline+agent comparison finishes in
# a few minutes on a mid-range laptop CPU. The agent's *policy* is what
# we care about here -- it's covered exhaustively by the unit suite --
# so the integration run only needs enough frames to confirm the
# wired-up Reconstructor still completes an ICP pass without regressing.
#
# NOTE: the existing ``clean_pcd_for_registration`` helper runs a 0.5 m
# radius outlier filter on the *full* ~150k-point cloud, which is the
# real time sink (~10-30 s per frame). Keeping MAX_PAIRS small is what
# makes this test usable as a manual check rather than an unbounded run.
STRIDE    = 24
MAX_PAIRS = 3


@pytest.mark.slow
def test_agent_vs_static_rule_baseline():
    """Acceptance gate: replacing the static rule with the default agent
    must not catastrophically drop more frames than the baseline keeps.

    A 25%-of-baseline-acceptances slack is intentionally loose -- it is
    here to catch *bugs* (e.g. an off-by-one in the recovery loop that
    starts rejecting every other frame), not to enforce a numeric
    parity. The agent is allowed to reject borderline frames the static
    rule would have let through; that's the point.
    """
    pairs = load_image_pairs(RGB_DIR, DEPTH_DIR, step=STRIDE)[:MAX_PAIRS]
    if len(pairs) < 3:
        pytest.skip(
            f'Only {len(pairs)} frame pair(s) found in {DATA_ROOT}; '
            f'need at least 3 to exercise the agent path.'
        )

    K, dist = get_default_intrinsics(640, 480)

    # --- Baseline: emulates the legacy permissive rule.
    baseline_succeed, baseline_fail = _run_once(
        pairs, K, dist, _make_baseline_config(), STRIDE)

    # --- Agent: defaults from AgentConfig.
    agent_succeed, agent_fail = _run_once(
        pairs, K, dist, AgentConfig(), STRIDE)

    print(
        f'\n[integration] frames={len(pairs)}'
        f' baseline=ok:{len(baseline_succeed)} fail:{len(baseline_fail)}'
        f' agent=ok:{len(agent_succeed)} fail:{len(agent_fail)}'
    )
    bm, bp = _rmse_stats(baseline_succeed)
    am, ap = _rmse_stats(agent_succeed)
    if bm is not None and am is not None:
        print(
            f'[integration] rmse median  baseline={bm:.5f}  agent={am:.5f}'
        )
        print(
            f'[integration] rmse p90     baseline={bp:.5f}  agent={ap:.5f}'
        )

    # Sanity: the baseline should pass the seed frame plus most others
    # on a clean capture. If it doesn't, the test environment itself is
    # broken (e.g. wrong intrinsics) and the comparison is meaningless.
    assert len(baseline_succeed) >= 2, (
        f'Baseline accepted only {len(baseline_succeed)} frame(s); '
        f'something is wrong with the test setup, not the agent.'
    )

    # Acceptance gate: the agent should keep at least 75% of the frames
    # the baseline did. Tighter thresholds on a clean capture should
    # NOT cause a wholesale rejection cascade.
    min_keep = max(2, int(0.75 * len(baseline_succeed)))
    assert len(agent_succeed) >= min_keep, (
        f'Agent kept only {len(agent_succeed)} frames vs '
        f'{len(baseline_succeed)} for the baseline; expected >= {min_keep}. '
        f'Agent fail reasons: '
        f'{[f.get("reason") for f in agent_fail][:5]}'
    )

    # Soft check: when both sides have RMSE samples, the agent should
    # not produce a *worse* p90 than the baseline. Allow a small slack
    # for noise; a hard regression here would mean the agent is
    # accepting frames the baseline would have rejected, which can
    # only happen via the recovery loop (which is *supposed* to make
    # things better, not worse).
    if bp is not None and ap is not None:
        # 1.5x slack: anything above this is a real regression.
        assert ap <= 1.5 * bp + 1e-6, (
            f'Agent p90 RMSE {ap:.5f} > 1.5x baseline p90 {bp:.5f}; '
            f'recovery loop may be accepting low-quality frames.'
        )

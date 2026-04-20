"""
processing/registration_agent.py
--------------------------------
Lightweight, deterministic policy module that wraps the per-frame ICP
acceptance decision in `Reconstructor._run_icp`.

Replaces the static `(fitness >= floor) and (rmse <= floor)` rule with
context-aware judgement: adaptive median/MAD thresholds over a rolling
window of recent good frames, motion-sanity checks against the expected
gantry step, and a bounded recovery loop that re-tries ICP under
progressively more aggressive pre-processing before falling back.

No ML, no LLM, no extra dependencies -- pure NumPy + (optional) Open3D
for the recovery helpers. The judging core is import-light so it can be
unit tested without Open3D installed.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np


# ---------------------------------------------------------------- config

@dataclass
class AgentConfig:
    """Tunables for the registration agent. All fields have sensible defaults."""

    # Absolute floors -- always enforced, regardless of adaptive state.
    # These mirror the static rule the agent replaces.
    floor_min_fitness: float = 0.3
    floor_max_rmse:    float = 0.015

    # Cold start: number of accepted frames during which ONLY absolute floors
    # apply (no adaptive median/MAD). Keeps short sequences (e.g. 13-frame
    # plant captures) from getting spurious retries on frame 2 from a noisy
    # half-filled window.
    cold_start_frames: int = 8

    # Rolling window of recent accepted frames used for adaptive thresholds.
    window_size: int = 20

    # Adaptive thresholds:  threshold = max(floor, median - k * MAD)
    # Larger k = more permissive (lets through more borderline frames).
    fitness_k_mad: float = 3.0
    rmse_k_mad:    float = 3.0

    # Motion sanity (per-frame ICP transform):
    # - translation: reject if |t| exceeds max_trans_factor * expected_step,
    #   or, when expected_step is zero, exceeds abs_trans_cap_m.
    max_trans_factor: float = 3.0
    abs_trans_cap_m:  float = 0.05      # 5 cm absolute cap
    # - rotation: reject if axis-angle magnitude exceeds rot_max_deg.
    rot_max_deg: float = 10.0

    # Recovery:
    max_retries: int = 5
    # Ordered strategy names. 'feature_init' is heavy; off by default.
    strategies: tuple = (
        'tighter_crop',
        'voxel_downsample',
        'denoise',
        'reseed_init',
        'point_to_plane',
        'feature_init',
    )
    enable_feature_init: bool = False

    # Stable-reference fallback: after this many CONSECUTIVE rejects, the
    # agent recommends pinning `target` to the last known good cloud and
    # NOT advancing `last_transform` until a frame is accepted again.
    fallback_after_rejects: int = 3


# ---------------------------------------------------------------- decision

@dataclass
class FrameDecision:
    action: str                     # 'accept' | 'retry' | 'reject'
    reason: str = ''
    next_strategy: Optional[str] = None
    # Diagnostic snapshot of the thresholds that were active.
    fitness_threshold: float = 0.0
    rmse_threshold:    float = 0.0


# ---------------------------------------------------------------- helpers

def rotation_magnitude_deg(T: np.ndarray) -> float:
    """Magnitude (axis-angle) of the rotation part of a 4x4 transform, in degrees.

    Duplicated from processing/quality.py to keep this module import-light
    (quality.py pulls in cv2 and Open3D at module level).
    """
    if T is None:
        return 0.0
    R = np.asarray(T[:3, :3], dtype=float)
    cos_t = (np.trace(R) - 1.0) / 2.0
    cos_t = max(-1.0, min(1.0, float(cos_t)))
    return math.degrees(math.acos(cos_t))


def translation_magnitude_m(T: np.ndarray) -> float:
    if T is None:
        return 0.0
    t = np.asarray(T[:3, 3], dtype=float)
    return float(np.linalg.norm(t))


def _median_mad(values) -> Tuple[float, float]:
    """Return (median, MAD) of a sequence; (0, 0) on empty input."""
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    return med, mad


# ---------------------------------------------------------------- agent

class RegistrationAgent:
    """
    Stateful per-frame decision module. One instance per Reconstructor run.

    Usage:
        agent = RegistrationAgent(AgentConfig(...))
        decision = agent.judge(fitness, rmse, T, expected_step_m, gantry_axis)
        # ... handle accept / retry (with agent.next_recovery) / reject ...
        agent.record_accept(fitness, rmse, T) / agent.record_reject()
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config if config is not None else AgentConfig()
        self._fit_window:  deque = deque(maxlen=self.config.window_size)
        self._rmse_window: deque = deque(maxlen=self.config.window_size)
        self._trans_window: deque = deque(maxlen=self.config.window_size)
        self._n_accepted = 0
        self._consecutive_rejects = 0

    # --------------------------------------------------------- thresholds

    def _is_cold_start(self) -> bool:
        return self._n_accepted < self.config.cold_start_frames

    def current_thresholds(self) -> Tuple[float, float]:
        """Return (min_fitness, max_rmse) currently in effect."""
        cfg = self.config
        if self._is_cold_start() or len(self._fit_window) < 3:
            return cfg.floor_min_fitness, cfg.floor_max_rmse

        fit_med, fit_mad = _median_mad(self._fit_window)
        rmse_med, rmse_mad = _median_mad(self._rmse_window)

        # Lower bound on fitness, upper bound on rmse.
        adaptive_min_fit = fit_med - cfg.fitness_k_mad * fit_mad
        adaptive_max_rmse = rmse_med + cfg.rmse_k_mad * rmse_mad

        # The floor is an absolute floor on fitness (must be >= floor) and an
        # absolute ceiling on rmse (must be <= floor). The adaptive value
        # only ever TIGHTENS those, never loosens.
        min_fit = max(cfg.floor_min_fitness, adaptive_min_fit)
        max_rmse = min(cfg.floor_max_rmse, adaptive_max_rmse)
        return float(min_fit), float(max_rmse)

    # ------------------------------------------------------------- judge

    def judge(
        self,
        fitness: float,
        rmse:    float,
        transformation: np.ndarray,
        expected_step_m: float = 0.0,
        gantry_axis: int = 0,
        attempt: int = 0,
    ) -> FrameDecision:
        """
        Judge a single ICP result. `attempt` is 0 for the first ICP call on
        this frame, and increments for each recovery attempt -- once it
        reaches `config.max_retries`, the agent stops recommending retries
        and returns 'reject' instead.
        """
        cfg = self.config
        min_fit, max_rmse = self.current_thresholds()

        # Motion sanity is hard-rejected (no adaptive softening): a huge
        # jump is almost certainly a bad alignment, not a noisy estimate.
        t_mag = translation_magnitude_m(transformation)
        rot_deg = rotation_magnitude_deg(transformation)

        if expected_step_m > 0.0:
            trans_cap = max(cfg.max_trans_factor * expected_step_m,
                            cfg.abs_trans_cap_m)
        else:
            trans_cap = cfg.abs_trans_cap_m

        motion_bad = (t_mag > trans_cap) or (rot_deg > cfg.rot_max_deg)
        metrics_bad = (fitness < min_fit) or (rmse > max_rmse)

        if not motion_bad and not metrics_bad:
            return FrameDecision(
                action='accept',
                reason=f'fitness={fitness:.3f} rmse={rmse:.4f} '
                       f't={t_mag*1000:.1f}mm rot={rot_deg:.2f}deg',
                fitness_threshold=min_fit,
                rmse_threshold=max_rmse,
            )

        # Build a diagnostic reason string.
        reasons = []
        if fitness < min_fit:
            reasons.append(f'low fitness {fitness:.3f} < {min_fit:.3f}')
        if rmse > max_rmse:
            reasons.append(f'high rmse {rmse:.4f} > {max_rmse:.4f}')
        if t_mag > trans_cap:
            reasons.append(f'translation {t_mag*1000:.1f}mm > '
                           f'{trans_cap*1000:.1f}mm cap')
        if rot_deg > cfg.rot_max_deg:
            reasons.append(f'rotation {rot_deg:.2f}deg > '
                           f'{cfg.rot_max_deg:.2f}deg cap')
        reason = '; '.join(reasons) if reasons else 'rejected'

        # Decide retry vs reject.
        next_strategy = self.next_recovery(attempt)
        if attempt < cfg.max_retries and next_strategy is not None:
            return FrameDecision(
                action='retry',
                reason=reason,
                next_strategy=next_strategy,
                fitness_threshold=min_fit,
                rmse_threshold=max_rmse,
            )

        return FrameDecision(
            action='reject',
            reason=reason,
            fitness_threshold=min_fit,
            rmse_threshold=max_rmse,
        )

    # ---------------------------------------------------------- recovery

    def next_recovery(self, attempt_idx: int) -> Optional[str]:
        """Return the strategy name to try at this attempt index, or None."""
        cfg = self.config
        # Filter strategies according to enable flags.
        enabled = [s for s in cfg.strategies
                   if s != 'feature_init' or cfg.enable_feature_init]
        if attempt_idx < 0 or attempt_idx >= len(enabled):
            return None
        if attempt_idx >= cfg.max_retries:
            return None
        return enabled[attempt_idx]

    # --------------------------------------------------------- bookkeeping

    def record_accept(self, fitness: float, rmse: float,
                      transformation: Optional[np.ndarray] = None) -> None:
        self._fit_window.append(float(fitness))
        self._rmse_window.append(float(rmse))
        if transformation is not None:
            self._trans_window.append(translation_magnitude_m(transformation))
        self._n_accepted += 1
        self._consecutive_rejects = 0

    def record_reject(self) -> None:
        self._consecutive_rejects += 1

    def should_fallback_reference(self) -> bool:
        """
        True when the chain has degraded enough that the next accepted frame
        should register against the LAST known stable target rather than the
        most recent (likely also bad) cloud.
        """
        return self._consecutive_rejects >= self.config.fallback_after_rejects

    # ------------------------------------------------------------- state

    @property
    def n_accepted(self) -> int:
        return self._n_accepted

    @property
    def consecutive_rejects(self) -> int:
        return self._consecutive_rejects


# ---------------------------------------------------------------- recovery
# Strategy helpers. Each takes the current (source, target, init_tf,
# voxel_size) and returns a re-prepared (source, target, init_tf, kwargs)
# tuple suitable for feeding back into `color_icp(...)` (or, for the
# point-to-plane strategy, `point_to_plane_icp(...)`).
#
# Open3D is imported lazily so the judging core can be tested without it.


def _depth_clip(pcd, percentile_hi: float = 90.0, mad_mult: float = 2.0):
    """Drop points beyond median_depth + mad_mult * MAD along the camera Z axis."""
    if pcd is None or pcd.is_empty():
        return pcd
    pts = np.asarray(pcd.points)
    if pts.size == 0:
        return pcd
    z = pts[:, 2]
    med = float(np.median(z))
    mad = float(np.median(np.abs(z - med)))
    if mad <= 0:
        cap = float(np.percentile(z, percentile_hi))
    else:
        cap = med + mad_mult * mad
    keep = z <= cap
    if not keep.any():
        return pcd
    return pcd.select_by_index(np.where(keep)[0])


def apply_strategy(
    strategy: str,
    source,
    target,
    init_tf: np.ndarray,
    voxel_size: float,
    expected_step_m: float = 0.0,
    gantry_axis: int = 0,
    max_iter: int = 50,
):
    """
    Re-prepare (source, target, init_tf) according to the chosen strategy
    and return everything needed to re-run ICP.

    Returns (source2, target2, init_tf2, icp_kwargs, use_p2p).

    `use_p2p` is True for the 'point_to_plane' strategy (caller should use
    point_to_plane_icp instead of color_icp). For 'feature_init', the
    returned init_tf2 already encodes the FPFH/RANSAC global registration
    result and the caller should run color_icp normally.
    """
    import copy
    import open3d as o3d  # lazy import

    src = source
    tgt = target
    init = np.asarray(init_tf, dtype=float).copy()
    kwargs = {'max_iter': max_iter, 'voxel_size': voxel_size}
    use_p2p = False

    if strategy == 'tighter_crop':
        src = _depth_clip(copy.deepcopy(source))
        tgt = _depth_clip(copy.deepcopy(target))

    elif strategy == 'voxel_downsample':
        ds = max(2 * voxel_size, 1e-4)
        src = source.voxel_down_sample(ds)
        tgt = target.voxel_down_sample(ds)

    elif strategy == 'denoise':
        src_c = copy.deepcopy(source)
        tgt_c = copy.deepcopy(target)
        src_c, _ = src_c.remove_statistical_outlier(nb_neighbors=30, std_ratio=1.5)
        tgt_c, _ = tgt_c.remove_statistical_outlier(nb_neighbors=30, std_ratio=1.5)
        src, tgt = src_c, tgt_c

    elif strategy == 'reseed_init':
        init = np.eye(4)
        if expected_step_m != 0.0:
            init[gantry_axis, 3] = expected_step_m

    elif strategy == 'point_to_plane':
        kwargs['voxel_size'] = voxel_size * 2  # looser correspondence radius
        use_p2p = True

    elif strategy == 'feature_init':
        # Heavy global registration. Off by default (gated by AgentConfig).
        ds = max(2 * voxel_size, 1e-4)
        src_ds = source.voxel_down_sample(ds)
        tgt_ds = target.voxel_down_sample(ds)
        radius_normal = ds * 2
        radius_feature = ds * 5
        for cloud in (src_ds, tgt_ds):
            cloud.estimate_normals(
                o3d.geometry.KDTreeSearchParamHybrid(
                    radius=radius_normal, max_nn=30))
        src_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            src_ds,
            o3d.geometry.KDTreeSearchParamHybrid(
                radius=radius_feature, max_nn=100))
        tgt_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            tgt_ds,
            o3d.geometry.KDTreeSearchParamHybrid(
                radius=radius_feature, max_nn=100))
        distance_threshold = ds * 1.5
        result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
            src_ds, tgt_ds, src_fpfh, tgt_fpfh, True,
            distance_threshold,
            o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
            3,
            [
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(
                    distance_threshold),
            ],
            o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999),
        )
        init = np.asarray(result.transformation, dtype=float).copy()

    else:
        raise ValueError(f'Unknown recovery strategy: {strategy!r}')

    return src, tgt, init, kwargs, use_p2p

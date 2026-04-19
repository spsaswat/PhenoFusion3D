"""
processing/quality.py
---------------------
Data-quality metrics for captured RGB-D sequences.

Two entry points:
    quick_check(pairs, K, dist, params, n_samples=15) -> QualityReport
    full_report(pairs, K, dist, params)               -> QualityReport

Both compute, per evaluated pair:
    - depth_validity   : fraction of depth pixels in (0, depth_trunc]
    - median_depth_m   : median valid depth (metres)
    - n_points         : point count after rgbd2pcd
    - icp_fitness      : Open3D coloured-ICP fitness vs the next frame
    - icp_rmse         : inlier RMSE (metres)
    - rotation_deg     : magnitude of the rotation in the ICP transform

A PASS / WARN / FAIL verdict is computed against the strict thresholds
documented at the bottom of this file. The defaults match the planning
doc.
"""

from __future__ import annotations

import csv
import math
import os
import random
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import cv2
import numpy as np

from processing.rgbd import rgbd2pcd
from processing.icp import color_icp


# ---------------------------------------------------------------- thresholds

@dataclass
class QualityThresholds:
    fitness_pass: float = 0.5
    fitness_warn: float = 0.3
    rmse_pass:    float = 0.005
    rmse_warn:    float = 0.015
    validity_pass: float = 0.30
    validity_warn: float = 0.10
    rotation_pass_deg: float = 1.0
    rotation_warn_deg: float = 5.0


# ---------------------------------------------------------------- params

@dataclass
class QualityParams:
    depth_scale: float = 1000.0
    depth_trunc: float = 4.0
    voxel_size:  float = 0.005
    max_iter:    int   = 50
    bbox: Optional[list] = None
    depth_min_mm: int = 0
    erode:   bool = False
    inpaint: bool = False
    thresholds: QualityThresholds = field(default_factory=QualityThresholds)


# ---------------------------------------------------------------- report

@dataclass
class PairMetrics:
    pair_index:     int
    depth_validity: float
    median_depth_m: float
    n_points:       int
    icp_fitness:    float
    icp_rmse:       float
    rotation_deg:   float
    error: str = ''


@dataclass
class QualityReport:
    n_pairs_evaluated: int
    pair_metrics: list = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    verdict: str = 'UNKNOWN'           # PASS / WARN / FAIL
    failing_metrics: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'n_pairs_evaluated': self.n_pairs_evaluated,
            'aggregate': self.aggregate,
            'verdict': self.verdict,
            'failing_metrics': self.failing_metrics,
            'pair_metrics': [asdict(m) for m in self.pair_metrics],
        }

    def write_csv(self, path: str) -> None:
        if not self.pair_metrics:
            return
        keys = list(asdict(self.pair_metrics[0]).keys())
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for m in self.pair_metrics:
                w.writerow(asdict(m))

    def write_summary(self, path: str) -> None:
        with open(path, 'w') as f:
            f.write('PhenoFusion3D quality report\n')
            f.write('============================\n\n')
            f.write(f'Verdict: {self.verdict}\n')
            if self.failing_metrics:
                f.write(f'Failing metrics: {", ".join(self.failing_metrics)}\n')
            f.write(f'Pairs evaluated: {self.n_pairs_evaluated}\n\n')
            f.write('Aggregate (mean / median / p25 / p75):\n')
            for k, stats in self.aggregate.items():
                f.write(
                    f'  {k:>18} : '
                    f'mean={stats["mean"]:.4f}  '
                    f'median={stats["median"]:.4f}  '
                    f'p25={stats["p25"]:.4f}  '
                    f'p75={stats["p75"]:.4f}\n'
                )


# ---------------------------------------------------------------- internals

def _rotation_magnitude_deg(T: np.ndarray) -> float:
    """Magnitude (axis-angle) of the rotation part of a 4x4 transform, in degrees."""
    R = T[:3, :3]
    cos_t = (np.trace(R) - 1.0) / 2.0
    cos_t = max(-1.0, min(1.0, cos_t))
    return math.degrees(math.acos(cos_t))


def _depth_validity(depth: np.ndarray, depth_trunc_mm: float) -> tuple[float, float]:
    """Return (valid_fraction, median_valid_depth_mm)."""
    if depth is None or depth.size == 0:
        return 0.0, 0.0
    valid = (depth > 0) & (depth <= depth_trunc_mm)
    frac = float(valid.sum()) / float(depth.size)
    if valid.any():
        med = float(np.median(depth[valid]))
    else:
        med = 0.0
    return frac, med


def _evaluate_pair(
    rgb_a, depth_a, rgb_b, depth_b, K, dist, params: QualityParams,
) -> PairMetrics | None:
    color_a = cv2.imread(rgb_a)
    depth_a_im = cv2.imread(depth_a, cv2.IMREAD_UNCHANGED)
    color_b = cv2.imread(rgb_b)
    depth_b_im = cv2.imread(depth_b, cv2.IMREAD_UNCHANGED)
    if color_a is None or depth_a_im is None or color_b is None or depth_b_im is None:
        return None

    color_a = cv2.cvtColor(color_a, cv2.COLOR_BGR2RGB)
    color_b = cv2.cvtColor(color_b, cv2.COLOR_BGR2RGB)

    try:
        pcd_a = rgbd2pcd(
            color_a, depth_a_im, K, dist=dist, bbox=params.bbox,
            depth_scale=params.depth_scale, depth_trunc=params.depth_trunc,
            depth_min_mm=params.depth_min_mm, erode=params.erode, inpaint=params.inpaint,
        )
        pcd_b = rgbd2pcd(
            color_b, depth_b_im, K, dist=dist, bbox=params.bbox,
            depth_scale=params.depth_scale, depth_trunc=params.depth_trunc,
            depth_min_mm=params.depth_min_mm, erode=params.erode, inpaint=params.inpaint,
        )
    except Exception as e:
        return PairMetrics(0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, error=str(e))

    depth_trunc_mm = params.depth_trunc * params.depth_scale
    valid_frac, med_mm = _depth_validity(depth_a_im, depth_trunc_mm)
    n_pts = len(pcd_a.points) if pcd_a is not None else 0

    if pcd_a is None or pcd_b is None or pcd_a.is_empty() or pcd_b.is_empty():
        return PairMetrics(0, valid_frac, med_mm / 1000.0, n_pts, 0.0, 0.0, 0.0,
                           error='empty cloud')

    try:
        _, T, fitness, rmse = color_icp(
            pcd_a, pcd_b, max_iter=params.max_iter, voxel_size=params.voxel_size,
        )
        rot_deg = _rotation_magnitude_deg(T)
    except Exception as e:
        return PairMetrics(0, valid_frac, med_mm / 1000.0, n_pts, 0.0, 0.0, 0.0,
                           error=f'icp: {e}')

    return PairMetrics(
        pair_index=0,
        depth_validity=valid_frac,
        median_depth_m=med_mm / 1000.0,
        n_points=n_pts,
        icp_fitness=float(fitness),
        icp_rmse=float(rmse),
        rotation_deg=float(rot_deg),
    )


def _aggregate(metrics: list[PairMetrics]) -> dict:
    out = {}
    keys = ('depth_validity', 'median_depth_m', 'n_points',
            'icp_fitness', 'icp_rmse', 'rotation_deg')
    if not metrics:
        return out
    for k in keys:
        vals = np.array([getattr(m, k) for m in metrics if not m.error], dtype=float)
        if vals.size == 0:
            out[k] = {'mean': 0.0, 'median': 0.0, 'p25': 0.0, 'p75': 0.0}
            continue
        out[k] = {
            'mean':   float(np.mean(vals)),
            'median': float(np.median(vals)),
            'p25':    float(np.percentile(vals, 25)),
            'p75':    float(np.percentile(vals, 75)),
        }
    return out


def _verdict(agg: dict, t: QualityThresholds) -> tuple[str, list[str]]:
    if not agg:
        return 'FAIL', ['no metrics']
    fit_mean = agg.get('icp_fitness', {}).get('mean', 0.0)
    rmse_mean = agg.get('icp_rmse', {}).get('mean', 1.0)
    val_mean = agg.get('depth_validity', {}).get('mean', 0.0)
    rot_mean = agg.get('rotation_deg', {}).get('mean', 0.0)

    failing = []
    state = 'PASS'

    def downgrade(s):
        nonlocal state
        order = {'PASS': 0, 'WARN': 1, 'FAIL': 2}
        if order[s] > order[state]:
            state = s

    if fit_mean < t.fitness_warn:
        downgrade('FAIL'); failing.append(f'fitness mean {fit_mean:.3f}')
    elif fit_mean < t.fitness_pass:
        downgrade('WARN'); failing.append(f'fitness mean {fit_mean:.3f}')

    if rmse_mean > t.rmse_warn:
        downgrade('FAIL'); failing.append(f'rmse mean {rmse_mean:.4f} m')
    elif rmse_mean > t.rmse_pass:
        downgrade('WARN'); failing.append(f'rmse mean {rmse_mean:.4f} m')

    if val_mean < t.validity_warn:
        downgrade('FAIL'); failing.append(f'depth validity {val_mean*100:.1f}%')
    elif val_mean < t.validity_pass:
        downgrade('WARN'); failing.append(f'depth validity {val_mean*100:.1f}%')

    if rot_mean > t.rotation_warn_deg:
        downgrade('FAIL'); failing.append(f'rotation mean {rot_mean:.2f} deg')
    elif rot_mean > t.rotation_pass_deg:
        downgrade('WARN'); failing.append(f'rotation mean {rot_mean:.2f} deg')

    return state, failing


# ---------------------------------------------------------------- public API

def quick_check(
    pairs: list,
    K,
    dist,
    params: QualityParams,
    n_samples: int = 15,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> QualityReport:
    """
    Sample n_samples random consecutive (i, i+1) pairs and evaluate them.
    Returns a QualityReport in seconds-to-tens-of-seconds.
    """
    if len(pairs) < 2:
        return QualityReport(n_pairs_evaluated=0, verdict='FAIL',
                             failing_metrics=['need >= 2 frames'])

    n_avail = len(pairs) - 1
    n = min(n_samples, n_avail)
    indices = sorted(random.sample(range(n_avail), n))

    metrics: list[PairMetrics] = []
    for k, i in enumerate(indices):
        a_rgb, a_d = pairs[i]
        b_rgb, b_d = pairs[i + 1]
        m = _evaluate_pair(a_rgb, a_d, b_rgb, b_d, K, dist, params)
        if m is not None:
            m.pair_index = i
            metrics.append(m)
        if on_progress:
            on_progress(k + 1, n)

    agg = _aggregate(metrics)
    verdict, failing = _verdict(agg, params.thresholds)
    return QualityReport(
        n_pairs_evaluated=len(metrics),
        pair_metrics=metrics,
        aggregate=agg,
        verdict=verdict,
        failing_metrics=failing,
    )


def full_report(
    pairs: list,
    K,
    dist,
    params: QualityParams,
    out_dir: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> QualityReport:
    """
    Evaluate every consecutive pair. Writes quality_report.csv +
    quality_report.txt to `out_dir` if provided.
    """
    if len(pairs) < 2:
        return QualityReport(n_pairs_evaluated=0, verdict='FAIL',
                             failing_metrics=['need >= 2 frames'])

    n = len(pairs) - 1
    metrics: list[PairMetrics] = []
    for i in range(n):
        a_rgb, a_d = pairs[i]
        b_rgb, b_d = pairs[i + 1]
        m = _evaluate_pair(a_rgb, a_d, b_rgb, b_d, K, dist, params)
        if m is not None:
            m.pair_index = i
            metrics.append(m)
        if on_progress:
            on_progress(i + 1, n)

    agg = _aggregate(metrics)
    verdict, failing = _verdict(agg, params.thresholds)
    report = QualityReport(
        n_pairs_evaluated=len(metrics),
        pair_metrics=metrics,
        aggregate=agg,
        verdict=verdict,
        failing_metrics=failing,
    )

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        report.write_csv(os.path.join(out_dir, 'quality_report.csv'))
        report.write_summary(os.path.join(out_dir, 'quality_report.txt'))

    return report

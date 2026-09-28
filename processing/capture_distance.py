"""
processing/capture_distance.py
------------------------------
Capture-distance ("camera height") check for the RealSense D405.

The D405 is a short-range stereo module: its usable, high-confidence depth
band is roughly **7 cm to 50 cm**. Below 7 cm the sensor cannot triangulate
and returns nothing; beyond 50 cm stereo error grows with the square of the
distance, so the surface is reported but is no longer trustworthy. On the
overhead gantry rig that translates directly into a mounting requirement: the
camera has to sit low enough that most of the plant falls inside the band.

This module answers one question from depth data alone -- *is the current
standoff good enough, and if not, which way should the camera move?* It opens
no camera, writes no file and touches no capture, quality or reconstruction
state. Live frames come from ``capture/distance_probe.py``; the Capture
Distance panel presents the result.

Two sources of depth are supported:

    evaluate_depth_frames(frames, depth_scale)        -> DistanceCheck
    evaluate_depth_directory(depth_dir, depth_scale)  -> DistanceCheck

Both need the raw depth unit as *units per metre* (``depth_scale``), because
that is the only way to convert a z16 image into a distance. A D405 commonly
reports 0.0001 m per unit, i.e. ``depth_scale=10000``; the L515/D435 default
is millimetres, i.e. ``depth_scale=1000``. The live probe reads this value
from the device instead of guessing.

Command line, no camera required:

    python -m processing.capture_distance DEPTH_DIR --depth-scale 10000
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import sys
from dataclasses import asdict, dataclass, field

import numpy as np


# ---------------------------------------------------------------- range facts

# Intel's published high-confidence depth interval for the D405.
D405_MIN_RANGE_M = 0.07
D405_MAX_RANGE_M = 0.50

CENTIMETRES_PER_METRE = 100.0

# Verdicts, ordered worst to best for the panel's colour mapping.
VERDICT_NO_DATA = 'NO_DATA'
VERDICT_OUT_OF_RANGE = 'OUT_OF_RANGE'
VERDICT_ADJUST = 'ADJUST'
VERDICT_GOOD = 'GOOD'


# ---------------------------------------------------------------- thresholds

@dataclass
class DistanceThresholds:
    """Bands and robustness settings for the capture-distance check."""

    # Usable depth interval of the sensor.
    min_range_m: float = D405_MIN_RANGE_M
    max_range_m: float = D405_MAX_RANGE_M

    # Share of the subject that must sit inside the interval.
    good_in_range_fraction: float = 0.90
    warn_in_range_fraction: float = 0.60

    # Percentiles used instead of min/max so a handful of flying pixels at a
    # depth discontinuity cannot decide the verdict.
    near_percentile: float = 2.0
    far_percentile: float = 98.0

    # The subject is the nearest surface layer. Looking down at a plant, that
    # is the canopy; the bench and floor sit behind it. Pixels deeper than
    # (nearest + subject band) are treated as background and excluded from the
    # verdict, though they are still reported. The default band is one usable
    # interval wide, because a surface further behind the nearest one than that
    # cannot be brought into range by any camera height anyway.
    subject_band_m: float | None = None

    # Below this share of usable depth pixels the reading is not a distance
    # measurement, it is an empty frame.
    min_valid_fraction: float = 0.05

    # Keep the recommended standoff off the exact interval boundary.
    margin_m: float = 0.02

    # Ignore a recommended move smaller than this; it is within mounting slop.
    move_tolerance_m: float = 0.01

    def subject_band(self) -> float:
        if self.subject_band_m is not None:
            return float(self.subject_band_m)
        return float(self.max_range_m - self.min_range_m)

    def target_min_m(self) -> float:
        return self.min_range_m + self.margin_m

    def target_max_m(self) -> float:
        return self.max_range_m - self.margin_m


# ---------------------------------------------------------------- result

@dataclass
class DistanceCheck:
    """Outcome of one capture-distance measurement."""

    verdict: str = VERDICT_NO_DATA
    advice: str = ''

    frames_evaluated: int = 0
    pixels_sampled: int = 0
    valid_fraction: float = 0.0

    # Whole frame, over usable depth pixels only.
    nearest_m: float | None = None
    median_m: float | None = None
    farthest_m: float | None = None
    in_range_fraction: float = 0.0
    too_near_fraction: float = 0.0
    too_far_fraction: float = 0.0

    # Nearest surface layer -- the plant, for an overhead rig.
    subject_pixel_fraction: float = 0.0
    subject_nearest_m: float | None = None
    subject_farthest_m: float | None = None
    subject_in_range_fraction: float = 0.0

    # Positive = raise the camera, negative = lower it.
    suggested_camera_move_m: float = 0.0
    subject_fits_in_range: bool = True

    depth_scale_units_per_m: float = 0.0
    camera_model: str = ''
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """One-line operator summary, verdict included."""
        return f'{self.verdict}: {self.advice}'


# ---------------------------------------------------------------- depth input

def _validate_depth_scale(depth_scale: float) -> float:
    scale = float(depth_scale)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError(
            'depth_scale must be a positive number of raw depth units per '
            f'metre (got {depth_scale!r}). A D405 reporting 0.0001 m per unit '
            'means depth_scale=10000; millimetre depth means 1000.'
        )
    return scale


def _sampled_depths_m(
    frame,
    depth_scale: float,
    max_samples_per_frame: int,
) -> tuple[int, np.ndarray]:
    """Return (pixels sampled, usable depths in metres) for one depth frame."""
    array = np.asarray(frame)
    if array.ndim == 3 and array.shape[2] == 1:
        array = array[:, :, 0]
    if array.ndim != 2:
        raise ValueError(
            'Depth frames must be single-channel 2D images; got shape '
            f'{array.shape}.'
        )

    flat = array.reshape(-1)
    stride = max(1, int(math.ceil(flat.size / max(1, max_samples_per_frame))))
    sample = flat[::stride]

    metres = sample.astype(np.float64) / depth_scale
    usable = metres[np.isfinite(metres) & (metres > 0.0)]
    return int(sample.size), usable


# ---------------------------------------------------------------- evaluation

def evaluate_depth_frames(
    frames,
    depth_scale: float,
    *,
    thresholds: DistanceThresholds | None = None,
    camera_model: str = '',
    max_samples_per_frame: int = 200_000,
) -> DistanceCheck:
    """
    Judge capture distance from one or more aligned depth frames.

    Args:
        frames        : iterable of 2D depth images (raw integer units)
        depth_scale   : raw depth units per metre (e.g. 10000 for a D405
                        reporting 0.0001 m per unit)
        thresholds    : DistanceThresholds, or None for the D405 defaults
        camera_model  : label recorded in the result, for the report only
        max_samples_per_frame: pixels sampled per frame; frames are strided,
                        not cropped, so the whole field of view is represented

    Returns:
        DistanceCheck -- verdict, measured distances and the recommended
        camera move (positive = raise, negative = lower).
    """
    limits = thresholds or DistanceThresholds()
    scale = _validate_depth_scale(depth_scale)

    frame_list = list(frames)
    sampled_total = 0
    usable_parts = []
    for frame in frame_list:
        sampled, usable = _sampled_depths_m(frame, scale, max_samples_per_frame)
        sampled_total += sampled
        if usable.size:
            usable_parts.append(usable)

    check = DistanceCheck(
        frames_evaluated=len(frame_list),
        pixels_sampled=sampled_total,
        depth_scale_units_per_m=scale,
        camera_model=camera_model,
    )
    if camera_model and 'D405' not in camera_model.upper():
        check.notes.append(
            f'The 7-50 cm interval is the D405 specification; {camera_model} '
            'has a different usable range, so read this result as advisory.'
        )

    if not frame_list:
        check.advice = 'No depth frames were supplied, so distance is unknown.'
        return check

    usable = (
        np.concatenate(usable_parts) if usable_parts else np.empty(0, np.float64)
    )
    check.valid_fraction = (
        float(usable.size) / sampled_total if sampled_total else 0.0
    )

    if check.valid_fraction < limits.min_valid_fraction:
        check.advice = (
            f'Only {check.valid_fraction * 100:.1f}% of depth pixels carry a '
            'reading, which is too few to measure distance. Nothing is inside '
            f'{limits.min_range_m * CENTIMETRES_PER_METRE:.0f}-'
            f'{limits.max_range_m * CENTIMETRES_PER_METRE:.0f} cm of the '
            'camera, or the scene is too dark, glossy or featureless for the '
            'stereo depth module. Raise the camera if it is almost touching '
            'the plant, lower it if the plant is far below, then measure '
            'again.'
        )
        return check

    # Whole-frame picture, background included.
    check.nearest_m = float(np.percentile(usable, limits.near_percentile))
    check.median_m = float(np.median(usable))
    check.farthest_m = float(np.percentile(usable, limits.far_percentile))
    check.in_range_fraction = float(
        np.count_nonzero(
            (usable >= limits.min_range_m) & (usable <= limits.max_range_m)
        )
    ) / usable.size
    check.too_near_fraction = float(
        np.count_nonzero(usable < limits.min_range_m)
    ) / usable.size
    check.too_far_fraction = float(
        np.count_nonzero(usable > limits.max_range_m)
    ) / usable.size

    # The subject: the nearest surface layer, i.e. the plant seen from above.
    subject = usable[usable <= check.nearest_m + limits.subject_band()]
    if subject.size == 0:
        subject = usable
    check.subject_pixel_fraction = float(subject.size) / usable.size
    check.subject_nearest_m = float(
        np.percentile(subject, limits.near_percentile)
    )
    check.subject_farthest_m = float(
        np.percentile(subject, limits.far_percentile)
    )
    check.subject_in_range_fraction = float(
        np.count_nonzero(
            (subject >= limits.min_range_m) & (subject <= limits.max_range_m)
        )
    ) / subject.size

    move, fits = _suggested_move_m(
        check.subject_nearest_m, check.subject_farthest_m, limits
    )
    check.suggested_camera_move_m = move
    check.subject_fits_in_range = fits

    check.verdict = _verdict(check, limits)
    check.advice = _advice(check, limits)
    if not fits:
        check.notes.append(
            'The plant is deeper than the usable interval, so no camera height '
            'puts all of it in the high-confidence band. The recommended move '
            'centres it; expect the nearest and farthest surfaces to stay '
            'noisy. A shorter pass or a second view covers them better.'
        )
    if check.subject_nearest_m <= limits.min_range_m + limits.margin_m:
        check.notes.append(
            'The nearest readings sit at the sensor\'s '
            f'{limits.min_range_m * CENTIMETRES_PER_METRE:.0f} cm floor. '
            'Anything closer is dropped by the camera rather than measured, so '
            'the top of the plant may be missing from the depth data. Raise '
            'the camera and measure again.'
        )
    # Fires whenever a lot of the frame sits behind a measured layer that is
    # itself within reach -- not only when the verdict is already GOOD, since
    # the same geometry is what truncates a tall plant.
    if check.too_far_fraction > 0.2 and (
        check.subject_nearest_m <= limits.max_range_m
    ):
        check.notes.append(
            f'{check.too_far_fraction * 100:.0f}% of the whole frame is beyond '
            f'{limits.max_range_m * CENTIMETRES_PER_METRE:.0f} cm, behind the '
            'layer measured above. On an overhead rig that is normally the '
            'bench or floor and can be ignored; if the plant itself reaches '
            'that far back, no single camera height covers all of it.'
        )
    return check


def _suggested_move_m(
    near_m: float,
    far_m: float,
    limits: DistanceThresholds,
) -> tuple[float, bool]:
    """
    Camera move that brings [near_m, far_m] inside the usable interval.

    Raising the camera adds the same offset to every measured depth, so the
    problem is a 1D interval fit. Returns (metres, whether a perfect fit
    exists); positive metres mean raise the camera, negative mean lower it.
    """
    # Whether a fit exists at all is a property of the usable interval, not of
    # the comfort margins: a subject that exactly fills 7-50 cm does fit, even
    # though no move satisfies both margins.
    fits = (limits.min_range_m - near_m) <= (limits.max_range_m - far_m)

    lowest_allowed = limits.target_min_m() - near_m   # move must be >= this
    highest_allowed = limits.target_max_m() - far_m   # move must be <= this

    if lowest_allowed > highest_allowed:
        # No move satisfies both margins, so centre the subject instead.
        interval_centre = (limits.target_min_m() + limits.target_max_m()) / 2.0
        subject_centre = (near_m + far_m) / 2.0
        return float(interval_centre - subject_centre), fits

    if lowest_allowed <= 0.0 <= highest_allowed:
        return 0.0, fits
    if lowest_allowed > 0.0:
        return float(lowest_allowed), fits
    return float(highest_allowed), fits


def _verdict(check: DistanceCheck, limits: DistanceThresholds) -> str:
    share = check.subject_in_range_fraction
    within_tolerance = (
        abs(check.suggested_camera_move_m) <= limits.move_tolerance_m
    )
    if share >= limits.good_in_range_fraction and within_tolerance:
        return VERDICT_GOOD
    # Enough of the plant is in range, but it sits against a boundary rather
    # than inside it, so a small move still buys confidence.
    if share >= limits.warn_in_range_fraction:
        return VERDICT_ADJUST
    return VERDICT_OUT_OF_RANGE


def _move_sentence(check: DistanceCheck, limits: DistanceThresholds) -> str:
    move_cm = check.suggested_camera_move_m * CENTIMETRES_PER_METRE
    if abs(check.suggested_camera_move_m) <= limits.move_tolerance_m:
        return 'No change of camera height is needed.'
    direction = 'Raise' if move_cm > 0 else 'Lower'
    return f'{direction} the camera by about {abs(move_cm):.1f} cm.'


def _advice(check: DistanceCheck, limits: DistanceThresholds) -> str:
    low_cm = limits.min_range_m * CENTIMETRES_PER_METRE
    high_cm = limits.max_range_m * CENTIMETRES_PER_METRE
    near_cm = (check.subject_nearest_m or 0.0) * CENTIMETRES_PER_METRE
    far_cm = (check.subject_farthest_m or 0.0) * CENTIMETRES_PER_METRE
    share_pct = check.subject_in_range_fraction * 100.0

    measured = (
        f'The plant reads {near_cm:.1f}-{far_cm:.1f} cm from the camera and '
        f'{share_pct:.0f}% of it is inside the {low_cm:.0f}-{high_cm:.0f} cm '
        'high-confidence range.'
    )
    return f'{measured} {_move_sentence(check, limits)}'


# ---------------------------------------------------------------- dataset path

def evaluate_depth_directory(
    depth_dir: str,
    depth_scale: float,
    *,
    max_frames: int = 10,
    thresholds: DistanceThresholds | None = None,
    camera_model: str = '',
) -> DistanceCheck:
    """
    Judge capture distance from depth PNGs already on disk.

    Frames are taken at an even stride across the whole sequence rather than
    from its start, so a gantry pass is represented end to end. Reads only
    depth images; RGB, intrinsics and session metadata are untouched.
    """
    if max_frames < 1:
        raise ValueError(f'max_frames must be at least 1 (got {max_frames}).')

    # Same two layouts the loader accepts: prefixed stakeholder names first,
    # then plain numbered PNGs.
    candidates = glob.glob(os.path.join(depth_dir, 'depth_*.png')) or glob.glob(
        os.path.join(depth_dir, '*.png')
    )
    if not candidates:
        raise FileNotFoundError(
            f'No depth PNG files found in: {depth_dir}'
        )

    # Decoding dependencies are needed only once there is something to read,
    # which keeps the frame-level entry point usable without them.
    import cv2
    from natsort import natsorted

    candidates = natsorted(candidates)
    # Even spread across the whole sequence, always min(available, max_frames)
    # frames. A stride of ceil(n / max_frames) silently returns far fewer
    # whenever n sits just above max_frames.
    if len(candidates) <= max_frames:
        selected = candidates
    else:
        step = len(candidates) / max_frames
        selected = [candidates[int(index * step)] for index in range(max_frames)]

    frames = []
    unreadable = []
    for path in selected:
        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if image is None:
            unreadable.append(os.path.basename(path))
            continue
        frames.append(image)

    if not frames:
        raise RuntimeError(
            f'None of the {len(selected)} selected depth images in '
            f'{depth_dir} could be read as an image.'
        )

    check = evaluate_depth_frames(
        frames,
        depth_scale,
        thresholds=thresholds,
        camera_model=camera_model,
    )
    check.notes.append(
        f'Measured from {len(frames)} of {len(candidates)} saved depth frames '
        f'in {depth_dir}, sampled evenly across the sequence.'
    )
    if unreadable:
        check.notes.append(
            'Skipped unreadable depth images: ' + ', '.join(unreadable)
        )
    return check


# ---------------------------------------------------------------- command line

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Report whether a saved depth sequence sits inside the RealSense '
            'D405 high-confidence range (7-50 cm).'
        )
    )
    parser.add_argument('depth_dir', help='Directory of depth PNG frames.')
    parser.add_argument(
        '--depth-scale',
        type=float,
        required=True,
        help=(
            'Raw depth units per metre for this recording. A D405 reporting '
            '0.0001 m per unit is 10000; millimetre depth is 1000.'
        ),
    )
    parser.add_argument(
        '--frames',
        type=int,
        default=10,
        help='Number of depth frames to sample (default: 10).',
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        check = evaluate_depth_directory(
            args.depth_dir, args.depth_scale, max_frames=args.frames
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f'[capture_distance] ERROR: {exc}', file=sys.stderr)
        return 2
    print(f'[capture_distance] {check.summary()}')
    if check.nearest_m is not None:
        print(
            f'[capture_distance] whole frame: '
            f'nearest={check.nearest_m * CENTIMETRES_PER_METRE:.1f} cm '
            f'median={check.median_m * CENTIMETRES_PER_METRE:.1f} cm '
            f'farthest={check.farthest_m * CENTIMETRES_PER_METRE:.1f} cm'
        )
        print(
            f'[capture_distance] in range={check.in_range_fraction * 100:.1f}% '
            f'too near={check.too_near_fraction * 100:.1f}% '
            f'too far={check.too_far_fraction * 100:.1f}%'
        )
    for note in check.notes:
        print(f'[capture_distance] note: {note}')
    return 0 if check.verdict == VERDICT_GOOD else 1


if __name__ == '__main__':
    raise SystemExit(main())

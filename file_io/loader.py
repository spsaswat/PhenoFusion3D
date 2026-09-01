import os
import json
import math
import statistics
import numpy as np
from natsort import natsorted
import glob


_FRAME_PREFIXES = ("rgb_", "color_", "colour_", "depth_")


def frame_identifier(path):
    """Return a comparable frame identifier for an RGB or depth filename."""
    stem = os.path.splitext(os.path.basename(path))[0].casefold()
    for prefix in _FRAME_PREFIXES:
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    if stem.isdigit():
        return str(int(stem))
    return stem


def load_image_pairs(rgb_dir, depth_dir, step=1):
    """
    Load sorted RGB + depth image path pairs from two directories.
    Handles both naming conventions:
      - Stakeholder format: rgb_XXXXXX.png / depth_XXXXXX.png
      - ICL-NUIM format:    0.png, 1.png, 2.png ...
    Returns a list of (rgb_path, depth_path) tuples sampled at 'step' interval.
    """
    # Try prefixed format first (stakeholder convention)
    rgb_files   = natsorted(glob.glob(os.path.join(rgb_dir,   'rgb_*.png')))
    depth_files = natsorted(glob.glob(os.path.join(depth_dir, 'depth_*.png')))

    # Fall back to plain numbered PNGs (ICL-NUIM convention)
    if not rgb_files:
        rgb_files = natsorted(glob.glob(os.path.join(rgb_dir, '*.png')))
    if not depth_files:
        depth_files = natsorted(glob.glob(os.path.join(depth_dir, '*.png')))

    if not rgb_files:
        raise FileNotFoundError(f'No PNG files found in RGB directory: {rgb_dir}')
    if not depth_files:
        raise FileNotFoundError(f'No PNG files found in depth directory: {depth_dir}')
    if len(rgb_files) != len(depth_files):
        raise ValueError(
            f'RGB and depth image counts do not match: '
            f'{len(rgb_files)} RGB vs {len(depth_files)} depth'
        )

    rgb_ids = [frame_identifier(path) for path in rgb_files]
    depth_ids = [frame_identifier(path) for path in depth_files]
    if rgb_ids != depth_ids:
        mismatch = next(
            (
                (index, rgb_id, depth_id)
                for index, (rgb_id, depth_id) in enumerate(
                    zip(rgb_ids, depth_ids)
                )
                if rgb_id != depth_id
            ),
            None,
        )
        index, rgb_id, depth_id = mismatch
        raise ValueError(
            "RGB and depth frame identifiers do not match at sorted index "
            f"{index}: RGB frame {rgb_id!r} vs depth frame {depth_id!r}. "
            "A missing or misnamed image would corrupt every later pair."
        )

    pairs = list(zip(rgb_files, depth_files))
    sampled = pairs[::step]
    print(f'[loader] Found {len(pairs)} pairs, using {len(sampled)} at step={step}')
    return sampled


def load_session_positions(session_path, pairs):
    """Load capture positions aligned to ``pairs`` from session metadata.

    Returns ``(positions_m, gantry_axis, median_step_m)``. Positions may
    contain ``None`` for individual legacy frames missing from the metadata.
    ``positions_m`` itself is ``None`` when the session is unavailable or has
    no positions matching this sequence.
    """
    if not session_path or not os.path.isfile(session_path):
        return None, None, None
    try:
        with open(session_path, "r") as session_file:
            session = json.load(session_file)
        raw_positions = session.get("frame_positions", {})
        if not isinstance(raw_positions, dict):
            raise ValueError("frame_positions is not an object")

        positions_m = []
        for rgb_path, _depth_path in pairs:
            value = raw_positions.get(frame_identifier(rgb_path))
            if value is None:
                positions_m.append(None)
                continue
            position_m = float(value)
            if not math.isfinite(position_m):
                raise ValueError(
                    f"non-finite position for frame {frame_identifier(rgb_path)}"
                )
            positions_m.append(position_m)

        if not any(position is not None for position in positions_m):
            return None, None, None

        nonzero_steps = [
            current - previous
            for previous, current in zip(positions_m, positions_m[1:])
            if previous is not None
            and current is not None
            and abs(current - previous) > 1e-9
        ]
        median_step_m = (
            float(statistics.median(nonzero_steps))
            if nonzero_steps
            else None
        )
        axis_value = session.get("gantry_axis")
        gantry_axis = int(axis_value) if axis_value is not None else None
        if gantry_axis not in (None, 0, 1, 2):
            gantry_axis = None
        return positions_m, gantry_axis, median_step_m
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[loader] WARNING: Could not load session positions: {exc}")
        return None, None, None


def load_intrinsics(json_path):
    """
    Parse a kdc_intrinsics.txt JSON file in the stakeholder format.
    Returns: (K np.ndarray 3x3, dist list, width int, height int)
    Returns None if file is missing or malformed.
    """
    if not json_path or not os.path.exists(json_path):
        print(f'[loader] WARNING: Intrinsics file not found: {json_path}. Using defaults.')
        return None
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        K      = np.array(data['K'], dtype=np.float64)
        dist   = data.get('dist', [0, 0, 0, 0, 0])
        width  = int(data.get('width',  640))
        height = int(data.get('height', 480))
        print(f'[loader] Loaded intrinsics: {width}x{height}, fx={K[0,0]:.2f}, fy={K[1,1]:.2f}')
        return K, dist, width, height
    except Exception as e:
        print(f'[loader] WARNING: Failed to parse intrinsics: {e}. Using defaults.')
        return None


def get_default_intrinsics(width=640, height=480, fov_deg=60.0):
    """
    Build a pinhole intrinsics matrix when no file is available.
    Returns: (K np.ndarray 3x3, dist list of 5 zeros)
    """
    fx = width / (2.0 * math.tan(math.radians(fov_deg / 2.0)))
    fy = fx
    cx = width / 2.0
    cy = height / 2.0
    K = np.array([
        [fx,  0, cx],
        [ 0, fy, cy],
        [ 0,  0,  1]
    ], dtype=np.float64)
    dist = [0.0, 0.0, 0.0, 0.0, 0.0]
    print(f'[loader] Using default intrinsics: {width}x{height}, fx=fy={fx:.2f}')
    return K, dist

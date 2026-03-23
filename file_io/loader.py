import os
import json
import math
import numpy as np
from natsort import natsorted
import glob


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

    pairs = list(zip(rgb_files, depth_files))
    sampled = pairs[::step]
    print(f'[loader] Found {len(pairs)} pairs, using {len(sampled)} at step={step}')
    return sampled


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
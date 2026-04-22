"""
Image and intrinsics loading. Handles both combined and separate RGB/depth folders.
"""
import json
import os
import re
import numpy as np
from natsort import natsorted


def load_image_pairs(rgb_dir, depth_dir, step=1):
    """
    Load paired RGB and depth image paths. Supports:
    - Same folder: rgb_*.png and depth_*.png (stakeholder format)
    - Separate folders: rgb_dir and depth_dir with matching ids (e.g. rgb_123.png, depth_123.png)

    Returns:
        natsorted list of (rgb_path, depth_path) tuples.
    """
    depth_dir_use = depth_dir.strip() if depth_dir and depth_dir.strip() else rgb_dir

    if rgb_dir == depth_dir_use:
        # Combined folder: rgb_*.png, depth_*.png
        rgb_files = natsorted(
            [f for f in os.listdir(rgb_dir) if f.startswith("rgb_") and f.endswith(".png")]
        )
        depth_files = natsorted(
            [f for f in os.listdir(rgb_dir) if f.startswith("depth_") and f.endswith(".png")]
        )
        # Match by id: rgb_12345.png <-> depth_12345.png
        def _id(f, prefix):
            stem = f.replace(prefix, "").replace(".png", "")
            m = re.search(r"(\d+)", stem)
            return m.group(1) if m else stem
        rgb_by_id = {_id(f, "rgb_"): f for f in rgb_files}
        depth_by_id = {_id(f, "depth_"): f for f in depth_files}
    else:
        # Separate folders - match by numeric id
        rgb_files = [f for f in os.listdir(rgb_dir) if f.endswith(".png")]
        depth_files = [f for f in os.listdir(depth_dir_use) if f.endswith(".png")]

        def _id(f):
            m = re.search(r"(\d+)", f)
            return m.group(1) if m else f

        rgb_by_id = {_id(f): f for f in rgb_files}
        depth_by_id = {_id(f): f for f in depth_files}

    common_ids = set(rgb_by_id.keys()) & set(depth_by_id.keys())
    common = natsorted(common_ids)
    pairs = []
    for i in range(0, len(common), step):
        k = common[i]
        rgb_path = os.path.join(rgb_dir, rgb_by_id[k])
        depth_path = os.path.join(depth_dir_use, depth_by_id[k])
        if os.path.exists(rgb_path) and os.path.exists(depth_path):
            pairs.append((rgb_path, depth_path))
    return pairs


def load_intrinsics(json_path):
    """
    Parse kdc_intrinsics.txt (colour stream) or kd_intrinsics.txt format.
    Returns (K, dist) where K is 3x3 np.ndarray, dist is list.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(json_path)
    with open(json_path, "r") as f:
        d = json.load(f)
    K = np.array(d["K"], dtype=float)
    dist = d.get("dist", [0, 0, 0, 0, 0])
    return K, dist


def get_default_intrinsics(width=640, height=480, fov_deg=60):
    """Reasonable default intrinsics for datasets without intrinsics file."""
    import math

    f = (width / 2) / math.tan(math.radians(fov_deg / 2))
    K = np.array([
        [f, 0, width / 2],
        [0, f, height / 2],
        [0, 0, 1],
    ])
    return K, [0, 0, 0, 0, 0]

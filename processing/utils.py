import numpy as np
import open3d as o3d


def clean_pcd(pcd, nb_neighbors=10, std_ratio=0.4, voxel_size=0.005):
    """
    Stakeholder-compatible point cloud cleanup.

    The original notebook cleans without voxel downsampling:
        remove_statistical_outlier(nb_neighbors=10, std_ratio=0.4)
        remove_radius_outlier(nb_points=20, radius=3)

    Our Open3D point clouds are in metres and have wider neighbour spacing
    than the stakeholder's mm-scale helper output. A strict 0.003 m radius
    deletes entire valid frames, so 0.03 m preserves surfaces while removing
    isolated flying pixels.
    `voxel_size` is accepted for backwards compatibility but intentionally
    unused in stakeholder mode.
    Returns cleaned PointCloud. Handles empty input gracefully.
    """
    if pcd is None or pcd.is_empty():
        print('[utils] WARNING: clean_pcd received empty point cloud, skipping.')
        return pcd

    pcd, _ = pcd.remove_statistical_outlier(
        nb_neighbors=nb_neighbors,
        std_ratio=std_ratio
    )
    pcd, _ = pcd.remove_radius_outlier(nb_points=20, radius=0.03)
    return pcd


def clean_pcd_for_registration(pcd):
    """
    Outlier removal WITHOUT voxel downsampling -- for use before ICP.

    Alias of stakeholder cleanup used before each ICP step.
    """
    return clean_pcd(pcd)


def estimate_normals(pcd, radius=0.01, max_nn=30):
    """
    Estimate and orient normals on a point cloud.
    Required for point-to-plane ICP fallback.
    """
    if pcd is None or pcd.is_empty():
        return pcd
    pcd.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(
            radius=radius, max_nn=max_nn
        )
    )
    pcd.orient_normals_consistent_tangent_plane(k=10)
    return pcd


def check_gpu():
    """
    Returns True if CUDA + CuPy are available.
    Used to switch between numpy and cupy in the pipeline.
    """
    try:
        import torch
        if torch.cuda.is_available():
            import cupy
            print('[utils] GPU detected: using CuPy')
            return True
    except ImportError:
        pass
    print('[utils] No GPU/CuPy available: using NumPy')
    return False


def numpy_or_cupy():
    """
    Returns cupy if GPU available, numpy otherwise.
    Drop-in replacement for array operations.
    """
    if check_gpu():
        import cupy as cp
        return cp
    return np
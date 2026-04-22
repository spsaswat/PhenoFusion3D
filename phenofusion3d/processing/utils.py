"""
Shared processing utilities. No UI imports.
"""
import open3d as o3d


def clean_pcd(pcd, nb_neighbors=20, std_ratio=2.0, voxel_size=0.005):
    """
    Clean point cloud: downsample, remove statistical outliers.

    Args:
        pcd: o3d.geometry.PointCloud
        nb_neighbors: for statistical outlier removal
        std_ratio: for statistical outlier removal
        voxel_size: voxel size for downsampling

    Returns:
        Cleaned o3d.geometry.PointCloud
    """
    pcd = pcd.voxel_down_sample(voxel_size=voxel_size)
    pcd, _ = pcd.remove_statistical_outlier(
        nb_neighbors=nb_neighbors,
        std_ratio=std_ratio,
    )
    return pcd

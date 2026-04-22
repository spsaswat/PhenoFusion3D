"""
Coloured ICP registration. No UI imports.
"""
import numpy as np
import open3d as o3d


def color_icp(source, target, max_iter=50, voxel_size=0.005):
    """
    Coloured ICP registration.

    Args:
        source: o3d.geometry.PointCloud
        target: o3d.geometry.PointCloud
        max_iter: max ICP iterations
        voxel_size: feature radius = voxel_size * 2

    Returns:
        (result, transformation, fitness, inlier_rmse)
    """
    radius = voxel_size * 2
    criteria = o3d.pipelines.registration.ICPConvergenceCriteria(
        max_iteration=max_iter
    )
    try:
        result = o3d.pipelines.registration.registration_colored_icp(
            source,
            target,
            radius,
            np.eye(4),
            criteria=criteria,
        )
        return (
            result,
            result.transformation,
            result.fitness,
            result.inlier_rmse,
        )
    except Exception:
        # Fallback to point-to-plane if coloured ICP fails
        result = o3d.pipelines.registration.registration_icp(
            source,
            target,
            radius,
            np.eye(4),
            o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            criteria,
        )
        return (
            result,
            result.transformation,
            result.fitness,
            result.inlier_rmse,
        )

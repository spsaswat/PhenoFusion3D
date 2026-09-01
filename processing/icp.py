import open3d as o3d
import numpy as np


def _ensure_normals(pcd, radius, max_nn=30):
    """Estimate normals if the point cloud doesn't have them yet."""
    if not pcd.has_normals():
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(
                radius=radius, max_nn=max_nn
            )
        )


def color_icp(source, target, max_iter=50, voxel_size=0.005, init=None):
    """
    Colour-assisted ICP registration between two point clouds.
    Pre-estimates normals if missing (required by Open3D coloured ICP).
    Falls back to point_to_plane_icp if colour ICP fails.

    Args:
        init: 4x4 initial transform from source to target. Default identity.

    Returns: (result, transformation, fitness, inlier_rmse)
    """
    if source.is_empty() or target.is_empty():
        print('[icp] WARNING: Empty point cloud passed to color_icp, skipping.')
        return None, np.eye(4), 0.0, 0.0

    radius = voxel_size * 2
    init_tf = init if init is not None else np.eye(4)

    # Normals are required by coloured ICP - estimate them upfront
    _ensure_normals(source, radius)
    _ensure_normals(target, radius)

    try:
        result = o3d.pipelines.registration.registration_colored_icp(
            source, target,
            radius,
            init_tf,
            criteria=o3d.pipelines.registration.ICPConvergenceCriteria(
                max_iteration=max_iter
            )
        )
        fitness = result.fitness
        inlier_rmse = result.inlier_rmse

        if fitness == 0.0:
            print('[icp] colour_icp fitness=0, falling back to point-to-plane ICP')
            return point_to_plane_icp(source, target, max_iter, voxel_size, init_tf)

        return result, result.transformation, fitness, inlier_rmse

    except Exception as e:
        detail = str(e)
        if 'No correspondences found' in detail:
            detail = 'no correspondences at the current motion seed/radius'
        else:
            detail = ' '.join(detail.split())[:300]
        print(
            f'[icp] colour_icp failed ({detail}); '
            'trying point-to-plane ICP'
        )
        return point_to_plane_icp(source, target, max_iter, voxel_size, init_tf)


def point_to_plane_icp(source, target, max_iter=50, voxel_size=0.005, init=None):
    """
    Point-to-plane ICP fallback. Estimates normals if not present.

    Args:
        init: 4x4 initial transform. Default identity.

    Returns: (result, transformation, fitness, inlier_rmse)
    """
    if source.is_empty() or target.is_empty():
        return None, np.eye(4), 0.0, 0.0

    radius = voxel_size * 2
    init_tf = init if init is not None else np.eye(4)
    _ensure_normals(source, radius)
    _ensure_normals(target, radius)

    result = o3d.pipelines.registration.registration_icp(
        source, target,
        max_correspondence_distance=radius,
        init=init_tf,
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPlane(),
        criteria=o3d.pipelines.registration.ICPConvergenceCriteria(
            max_iteration=max_iter
        )
    )

    return result, result.transformation, result.fitness, result.inlier_rmse

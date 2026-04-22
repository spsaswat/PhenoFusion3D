"""
RGB-D to PointCloud conversion. No UI imports. Standalone, testable.
"""
import numpy as np
import cv2
import open3d as o3d


def rgbd2pcd(color_img, depth_img, K, dist=None, bbox=None, depth_scale=1000.0):
    """
    Create point cloud from RGB and depth images.

    Args:
        color_img: np.ndarray (H, W, 3) RGB
        depth_img: np.ndarray (H, W) uint16 depth in mm
        K: 3x3 intrinsic matrix (np.ndarray or list)
        dist: distortion coefficients (optional). If provided, undistort before conversion.
        bbox: [x1, y1, x2, y2] crop region or None
        depth_scale: converts raw depth pixel values to metres. 1000 for RealSense mm.

    Returns:
        o3d.geometry.PointCloud with colour
    """
    K = np.array(K, dtype=np.float64)
    h, w = color_img.shape[:2]

    # Undistort if dist provided
    if dist is not None and np.any(np.array(dist) != 0):
        color_img = cv2.undistort(color_img, K, np.array(dist))
        depth_img = cv2.undistort(depth_img, K, np.array(dist))

    # Apply bbox crop if provided
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        color_img = color_img[y1:y2, x1:x2]
        depth_img = depth_img[y1:y2, x1:x2]

    # Ensure depth is correct type (uint16)
    if depth_img.dtype != np.uint16:
        depth_img = np.asarray(depth_img, dtype=np.uint16)

    # Convert to Open3D format
    color_o3d = o3d.geometry.Image(np.ascontiguousarray(color_img))
    depth_o3d = o3d.geometry.Image(np.ascontiguousarray(depth_img))

    rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
        color_o3d,
        depth_o3d,
        depth_scale=depth_scale,
        depth_trunc=3.0,
        convert_rgb_to_intensity=False,
    )

    intrinsic = o3d.camera.PinholeCameraIntrinsic(
        width=color_img.shape[1],
        height=color_img.shape[0],
        fx=K[0, 0],
        fy=K[1, 1],
        cx=K[0, 2],
        cy=K[1, 2],
    )

    pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd, intrinsic)
    return pcd

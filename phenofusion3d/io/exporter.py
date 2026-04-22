"""
PLY and metrics export.
"""
import csv
import open3d as o3d


def save_ply(pcd, output_path):
    """Save point cloud to PLY file."""
    return o3d.io.write_point_cloud(output_path, pcd)


def save_metrics_csv(metrics_list, output_path):
    """
    metrics_list: list of dicts with keys frame_idx, fitness, inlier_rmse, success
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_idx", "fitness", "inlier_rmse", "success"])
        for m in metrics_list:
            writer.writerow([
                m.get("frame_idx", -1),
                m.get("fitness", 0),
                m.get("inlier_rmse", 0),
                m.get("success", False),
            ])

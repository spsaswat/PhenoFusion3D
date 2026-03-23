import os
import csv
import open3d as o3d


def save_ply(pcd, output_path):
    """
    Save an Open3D PointCloud to a PLY file.
    Returns True on success, False on failure.
    """
    if pcd is None or pcd.is_empty():
        print('[exporter] WARNING: Point cloud is empty, nothing to save.')
        return False
    try:
        o3d.io.write_point_cloud(output_path, pcd)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f'[exporter] PLY saved: {output_path} ({size_mb:.2f} MB)')
        return True
    except Exception as e:
        print(f'[exporter] ERROR saving PLY: {e}')
        return False


def save_metrics_csv(metrics_list, output_path):
    """
    Save per-frame reconstruction metrics to a CSV file.

    metrics_list: list of dicts with keys: frame, fitness, rmse, (optional) reason
    Returns True on success, False on failure.
    """
    if not metrics_list:
        print('[exporter] WARNING: Empty metrics list, nothing to save.')
        return False
    try:
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['frame', 'status', 'fitness', 'rmse', 'note'],
                extrasaction='ignore'
            )
            writer.writeheader()
            for row in metrics_list:
                writer.writerow({
                    'frame':   row.get('frame', ''),
                    'status':  row.get('status', 'OK'),
                    'fitness': round(row.get('fitness', 0.0), 6),
                    'rmse':    round(row.get('rmse', 0.0), 6),
                    'note':    row.get('reason', '')
                })
        print(f'[exporter] CSV saved: {output_path} ({len(metrics_list)} rows)')
        return True
    except Exception as e:
        print(f'[exporter] ERROR saving CSV: {e}')
        return False
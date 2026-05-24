import csv
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable, Optional

import cv2
import numpy as np
import open3d as o3d


@dataclass
class CleanupResult:
    input_ply: str
    output_ply: str
    summary_json: str
    input_points: int
    downsampled_points: int
    green_points: int
    clustered_points: int
    cleaned_points: int


@dataclass
class PlyHeader:
    fmt: str
    vertex_count: int
    properties: list[tuple[str, str]]
    header_bytes: int


@dataclass
class TraitResult:
    input_ply: str
    traits_json: str
    traits_csv: str
    convex_hull_ply: str
    point_count: int
    bbox_width_m: float
    bbox_depth_m: float
    bbox_height_m: float
    bbox_volume_m3: float
    convex_hull_area_m2: float
    convex_hull_volume_m3: float
    height_max_m: float
    height_top_1_pct_m: float
    height_top_3_pct_m: float
    height_top_5_pct_m: float
    height_top_10_pct_m: float
    height_top_13_pct_m: float


def load_ply(path: str | os.PathLike) -> o3d.geometry.PointCloud:
    pcd = o3d.io.read_point_cloud(str(path))
    if pcd is None or pcd.is_empty():
        raise RuntimeError(f'Point cloud is empty or unreadable: {path}')
    return pcd


def write_json(path: str | os.PathLike, data) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def _emit(log: Optional[Callable[[str], None]], message: str) -> None:
    if log is not None:
        log(message)


def _read_ply_header(path: Path) -> Optional[PlyHeader]:
    try:
        with path.open('rb') as f:
            first = f.readline().decode('ascii', errors='replace').strip()
            if first != 'ply':
                return None

            fmt = ''
            vertex_count = 0
            properties: list[tuple[str, str]] = []
            in_vertex = False
            while True:
                line_b = f.readline()
                if not line_b:
                    return None
                line = line_b.decode('ascii', errors='replace').strip()
                if line == 'end_header':
                    return PlyHeader(fmt, vertex_count, properties, f.tell())

                parts = line.split()
                if len(parts) >= 3 and parts[0] == 'format':
                    fmt = parts[1]
                elif len(parts) >= 3 and parts[0] == 'element':
                    in_vertex = parts[1] == 'vertex'
                    if in_vertex:
                        vertex_count = int(parts[2])
                elif len(parts) >= 3 and parts[0] == 'property' and in_vertex:
                    if parts[1] == 'list':
                        return None
                    properties.append((parts[2], parts[1]))
    except OSError:
        return None


def _ply_dtype(header: PlyHeader) -> Optional[np.dtype]:
    dtype_map = {
        'char': 'i1',
        'int8': 'i1',
        'uchar': 'u1',
        'uint8': 'u1',
        'short': '<i2',
        'int16': '<i2',
        'ushort': '<u2',
        'uint16': '<u2',
        'int': '<i4',
        'int32': '<i4',
        'uint': '<u4',
        'uint32': '<u4',
        'float': '<f4',
        'float32': '<f4',
        'double': '<f8',
        'float64': '<f8',
    }
    fields = []
    for name, ply_type in header.properties:
        dtype = dtype_map.get(ply_type)
        if dtype is None:
            return None
        fields.append((name, dtype))
    return np.dtype(fields)


def _stream_voxel_filter_binary_ply(
    path: Path,
    header: PlyHeader,
    *,
    voxel_size_m: float,
    green_only: bool,
    hsv_lower: tuple[int, int, int],
    hsv_upper: tuple[int, int, int],
    log: Optional[Callable[[str], None]],
    chunk_points: int = 500_000,
) -> Optional[o3d.geometry.PointCloud]:
    if header.fmt != 'binary_little_endian' or voxel_size_m <= 0:
        return None

    dtype = _ply_dtype(header)
    required = {'x', 'y', 'z', 'red', 'green', 'blue'}
    if dtype is None or not required.issubset(dtype.names or ()):
        return None

    seen: set[tuple[int, int, int]] = set()
    point_chunks: list[np.ndarray] = []
    color_chunks: list[np.ndarray] = []
    processed = 0
    filtered = 0
    next_log = 5_000_000

    with path.open('rb') as f:
        f.seek(header.header_bytes)
        while processed < header.vertex_count:
            count = min(chunk_points, header.vertex_count - processed)
            data = np.fromfile(f, dtype=dtype, count=count)
            if data.size == 0:
                break
            processed += int(data.size)

            xyz = np.column_stack((data['x'], data['y'], data['z'])).astype(np.float64, copy=False)
            rgb_u8 = np.column_stack((data['red'], data['green'], data['blue'])).astype(np.uint8, copy=False)

            if green_only:
                hsv = cv2.cvtColor(np.expand_dims(rgb_u8, axis=0), cv2.COLOR_RGB2HSV)
                mask = cv2.inRange(
                    hsv,
                    np.array(hsv_lower, dtype=np.uint8),
                    np.array(hsv_upper, dtype=np.uint8),
                )[0].astype(bool)
                xyz = xyz[mask]
                rgb_u8 = rgb_u8[mask]

            filtered += int(len(xyz))
            if len(xyz) > 0:
                keys = np.floor(xyz / float(voxel_size_m)).astype(np.int64)
                unique_keys, unique_indices = np.unique(keys, axis=0, return_index=True)
                keep_indices: list[int] = []
                for key_row, point_index in zip(unique_keys, unique_indices):
                    key = (int(key_row[0]), int(key_row[1]), int(key_row[2]))
                    if key not in seen:
                        seen.add(key)
                        keep_indices.append(int(point_index))

                if keep_indices:
                    keep = np.asarray(keep_indices, dtype=np.int64)
                    point_chunks.append(xyz[keep])
                    color_chunks.append(rgb_u8[keep].astype(np.float64) / 255.0)

            if processed >= next_log:
                _emit(
                    log,
                    f'[cleanup] streamed {processed:,}/{header.vertex_count:,} points; '
                    f'kept {len(seen):,} voxels',
                )
                next_log += 5_000_000

    if not point_chunks:
        return o3d.geometry.PointCloud()

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.vstack(point_chunks))
    pcd.colors = o3d.utility.Vector3dVector(np.vstack(color_chunks))
    _emit(
        log,
        f'[cleanup] streaming prefilter kept {len(pcd.points):,} voxel points '
        f'from {filtered:,} filtered input points',
    )
    return pcd


def voxel_downsample(pcd: o3d.geometry.PointCloud, voxel_size_m: float) -> o3d.geometry.PointCloud:
    if voxel_size_m <= 0:
        return pcd
    return pcd.voxel_down_sample(float(voxel_size_m))


def statistical_clean(
    pcd: o3d.geometry.PointCloud,
    nb_neighbors: int = 10,
    std_ratio: float = 0.4,
) -> o3d.geometry.PointCloud:
    if pcd.is_empty():
        return pcd
    cleaned, _ = pcd.remove_statistical_outlier(
        nb_neighbors=int(nb_neighbors),
        std_ratio=float(std_ratio),
    )
    return cleaned


def radius_clean(
    pcd: o3d.geometry.PointCloud,
    nb_points: int = 20,
    radius_m: float = 0.03,
) -> o3d.geometry.PointCloud:
    if pcd.is_empty():
        return pcd
    cleaned, _ = pcd.remove_radius_outlier(
        nb_points=int(nb_points),
        radius=float(radius_m),
    )
    return cleaned


def filter_green_hsv(
    pcd: o3d.geometry.PointCloud,
    lower: tuple[int, int, int] = (35, 40, 40),
    upper: tuple[int, int, int] = (85, 255, 255),
) -> o3d.geometry.PointCloud:
    if pcd.is_empty() or not pcd.has_colors():
        return o3d.geometry.PointCloud()

    xyz = np.asarray(pcd.points)
    rgb = np.asarray(pcd.colors)
    rgb_u8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(np.expand_dims(rgb_u8, axis=0), cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))[0]
    keep = mask.astype(bool)

    out = o3d.geometry.PointCloud()
    if np.any(keep):
        out.points = o3d.utility.Vector3dVector(xyz[keep])
        out.colors = o3d.utility.Vector3dVector(rgb[keep])
    return out


def keep_largest_cluster(
    pcd: o3d.geometry.PointCloud,
    eps_m: float = 0.05,
    min_points: int = 30,
) -> o3d.geometry.PointCloud:
    if pcd.is_empty():
        return pcd

    labels = np.asarray(
        pcd.cluster_dbscan(eps=float(eps_m), min_points=int(min_points), print_progress=False)
    )
    valid = labels >= 0
    if not np.any(valid):
        return pcd

    unique, counts = np.unique(labels[valid], return_counts=True)
    largest = int(unique[np.argmax(counts)])
    indices = np.where(labels == largest)[0]
    return pcd.select_by_index(indices)


def cleanup_point_cloud(
    input_ply: str | os.PathLike,
    output_dir: str | os.PathLike,
    *,
    output_name: str = 'cleaned_plant.ply',
    voxel_size_m: float = 0.003,
    green_only: bool = True,
    largest_cluster: bool = True,
    hsv_lower: tuple[int, int, int] = (35, 40, 40),
    hsv_upper: tuple[int, int, int] = (85, 255, 255),
    cluster_eps_m: float = 0.05,
    cluster_min_points: int = 30,
    stat_neighbors: int = 10,
    stat_std_ratio: float = 0.4,
    radius_nb_points: int = 20,
    radius_m: float = 0.03,
    log: Optional[Callable[[str], None]] = None,
) -> CleanupResult:
    input_ply = Path(input_ply)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    header = _read_ply_header(input_ply)
    input_points = header.vertex_count if header is not None else 0
    pcd = None
    if header is not None:
        _emit(
            log,
            f'[cleanup] detected {header.fmt} PLY with {header.vertex_count:,} vertices',
        )
        pcd = _stream_voxel_filter_binary_ply(
            input_ply,
            header,
            voxel_size_m=voxel_size_m,
            green_only=green_only,
            hsv_lower=hsv_lower,
            hsv_upper=hsv_upper,
            log=log,
        )
        if pcd is not None and green_only and pcd.is_empty():
            _emit(log, '[cleanup] green filter removed all points; retrying stream without HSV filter')
            pcd = _stream_voxel_filter_binary_ply(
                input_ply,
                header,
                voxel_size_m=voxel_size_m,
                green_only=False,
                hsv_lower=hsv_lower,
                hsv_upper=hsv_upper,
                log=log,
            )

    if pcd is None:
        _emit(log, '[cleanup] loading point cloud with Open3D')
        pcd = load_ply(input_ply)
        input_points = len(pcd.points)

        _emit(log, f'[cleanup] voxel downsampling at {voxel_size_m:g} m')
        pcd = voxel_downsample(pcd, voxel_size_m)

        if green_only:
            _emit(log, '[cleanup] applying HSV green filter')
            green = filter_green_hsv(pcd, lower=hsv_lower, upper=hsv_upper)
            # If HSV thresholds are too strict for a dataset, do not destroy the run.
            pcd = green if not green.is_empty() else pcd

    downsampled_points = len(pcd.points)
    green_points = len(pcd.points)

    if largest_cluster:
        _emit(log, f'[cleanup] keeping largest DBSCAN cluster from {len(pcd.points):,} points')
        pcd = keep_largest_cluster(pcd, eps_m=cluster_eps_m, min_points=cluster_min_points)
    clustered_points = len(pcd.points)

    _emit(log, f'[cleanup] statistical cleanup on {len(pcd.points):,} points')
    pcd = statistical_clean(pcd, nb_neighbors=stat_neighbors, std_ratio=stat_std_ratio)
    _emit(log, f'[cleanup] radius cleanup on {len(pcd.points):,} points')
    pcd = radius_clean(pcd, nb_points=radius_nb_points, radius_m=radius_m)
    cleaned_points = len(pcd.points)

    output_ply = output_dir / output_name
    summary_json = output_dir / 'cleanup_summary.json'
    _emit(log, f'[cleanup] writing cleaned PLY with {cleaned_points:,} points')
    o3d.io.write_point_cloud(str(output_ply), pcd)

    result = CleanupResult(
        input_ply=str(input_ply),
        output_ply=str(output_ply),
        summary_json=str(summary_json),
        input_points=input_points,
        downsampled_points=downsampled_points,
        green_points=green_points,
        clustered_points=clustered_points,
        cleaned_points=cleaned_points,
    )
    write_json(summary_json, asdict(result))
    return result


def _axis_index(axis: str) -> int:
    axis = axis.lower()
    if axis not in ('x', 'y', 'z'):
        raise ValueError("height axis must be one of: x, y, z")
    return {'x': 0, 'y': 1, 'z': 2}[axis]


def _top_percent(sorted_desc: np.ndarray, pct: float) -> float:
    n = max(1, int(len(sorted_desc) * (pct / 100.0)))
    return float(np.mean(sorted_desc[:n]))


def extract_traits(
    cleaned_ply: str | os.PathLike,
    output_dir: str | os.PathLike,
    *,
    height_axis: str = 'z',
) -> TraitResult:
    cleaned_ply = Path(cleaned_ply)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pcd = load_ply(cleaned_ply)
    pts = np.asarray(pcd.points)
    if pts.shape[0] < 4:
        raise RuntimeError('Need at least 4 points to compute 3D traits.')

    bbox = pcd.get_axis_aligned_bounding_box()
    extent = np.asarray(bbox.get_extent(), dtype=float)

    hull, _ = pcd.compute_convex_hull()
    hull.compute_vertex_normals()

    convex_hull_ply = output_dir / 'convex_hull.ply'
    o3d.io.write_triangle_mesh(str(convex_hull_ply), hull)

    axis = _axis_index(height_axis)
    heights = np.sort(pts[:, axis])[::-1]
    base = float(np.min(pts[:, axis]))
    height_max = float(np.max(pts[:, axis]) - base)

    traits_json = output_dir / 'traits.json'
    traits_csv = output_dir / 'traits.csv'
    result = TraitResult(
        input_ply=str(cleaned_ply),
        traits_json=str(traits_json),
        traits_csv=str(traits_csv),
        convex_hull_ply=str(convex_hull_ply),
        point_count=int(pts.shape[0]),
        bbox_width_m=float(extent[0]),
        bbox_depth_m=float(extent[1]),
        bbox_height_m=float(extent[2]),
        bbox_volume_m3=float(np.prod(extent)),
        convex_hull_area_m2=float(hull.get_surface_area()),
        convex_hull_volume_m3=float(hull.get_volume()),
        height_max_m=height_max,
        height_top_1_pct_m=float(_top_percent(heights, 1) - base),
        height_top_3_pct_m=float(_top_percent(heights, 3) - base),
        height_top_5_pct_m=float(_top_percent(heights, 5) - base),
        height_top_10_pct_m=float(_top_percent(heights, 10) - base),
        height_top_13_pct_m=float(_top_percent(heights, 13) - base),
    )

    data = asdict(result)
    write_json(traits_json, data)
    with open(traits_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(data.keys()))
        writer.writeheader()
        writer.writerow(data)

    return result


def expand_inputs(patterns: Iterable[str], batch: bool = False) -> list[str]:
    import glob

    paths: list[str] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.extend(matches)
        elif not batch:
            paths.append(pattern)
    return sorted(set(paths))

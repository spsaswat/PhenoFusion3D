from __future__ import annotations

import argparse
import json
import glob
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _default_output_dir(input_ply: str) -> Path:
    path = Path(input_ply)
    dataset_dir = path.parent.parent if path.parent.name == 'merge_simple_full' else path.parent
    return dataset_dir / 'post_cleanup'


def expand_inputs(patterns: list[str], batch: bool = False) -> list[str]:
    paths: list[str] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.extend(matches)
        elif not batch:
            paths.append(pattern)
    return sorted(set(paths))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Clean reconstructed plant point cloud PLY files.')
    parser.add_argument('inputs', nargs='+', help='Input PLY path(s) or glob pattern(s).')
    parser.add_argument('--batch', action='store_true', help='Expand glob patterns and process all matches.')
    parser.add_argument('--output-dir', default=None, help='Output directory for single-file mode.')
    parser.add_argument('--voxel-size', type=float, default=0.003, help='Initial voxel downsample size in metres.')
    parser.add_argument('--green-only', action='store_true', help='Keep plant-like green HSV points.')
    parser.add_argument('--no-green-only', action='store_true', help='Disable HSV green filtering.')
    parser.add_argument('--largest-cluster', action='store_true', help='Keep largest DBSCAN cluster.')
    parser.add_argument('--cluster-eps', type=float, default=0.05, help='DBSCAN eps in metres.')
    parser.add_argument('--cluster-min-points', type=int, default=30, help='DBSCAN min_points.')
    parser.add_argument('--stat-neighbors', type=int, default=10, help='Statistical cleanup neighbours.')
    parser.add_argument('--stat-std-ratio', type=float, default=0.4, help='Statistical cleanup std ratio.')
    parser.add_argument('--radius-points', type=int, default=20, help='Radius cleanup neighbour count.')
    parser.add_argument('--radius', type=float, default=0.03, help='Radius cleanup distance in metres.')
    return parser.parse_args()


def _read_binary_ply_header(path: Path) -> tuple[int, int, list[tuple[str, str]]] | None:
    with path.open('rb') as f:
        if f.readline().strip() != b'ply':
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
                if fmt == 'binary_little_endian':
                    return f.tell(), vertex_count, properties
                return None

            parts = line.split()
            if len(parts) >= 3 and parts[0] == 'format':
                fmt = parts[1]
            elif len(parts) >= 3 and parts[0] == 'element':
                in_vertex = parts[1] == 'vertex'
                if in_vertex:
                    vertex_count = int(parts[2])
            elif len(parts) >= 3 and parts[0] == 'property' and in_vertex:
                properties.append((parts[2], parts[1]))


def _ply_dtype(properties: list[tuple[str, str]]):
    import numpy as np

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
    for name, ply_type in properties:
        dtype = dtype_map.get(ply_type)
        if dtype is None:
            return None
        fields.append((name, dtype))
    return np.dtype(fields)


def _rgb_to_hsv_green_mask(rgb_u8, lower=(35, 40, 40), upper=(85, 255, 255)):
    import numpy as np

    rgb = rgb_u8.astype(np.float32) / 255.0
    r = rgb[:, 0]
    g = rgb[:, 1]
    b = rgb[:, 2]
    maxc = np.max(rgb, axis=1)
    minc = np.min(rgb, axis=1)
    delta = maxc - minc

    hue = np.zeros_like(maxc)
    nonzero = delta > 1e-8
    red_max = (maxc == r) & nonzero
    green_max = (maxc == g) & nonzero
    blue_max = (maxc == b) & nonzero
    hue[red_max] = ((g[red_max] - b[red_max]) / delta[red_max]) % 6.0
    hue[green_max] = ((b[green_max] - r[green_max]) / delta[green_max]) + 2.0
    hue[blue_max] = ((r[blue_max] - g[blue_max]) / delta[blue_max]) + 4.0
    hue = hue * 30.0

    sat = np.where(maxc <= 1e-8, 0.0, delta / maxc) * 255.0
    val = maxc * 255.0
    return (
        (hue >= lower[0])
        & (hue <= upper[0])
        & (sat >= lower[1])
        & (sat <= upper[1])
        & (val >= lower[2])
        & (val <= upper[2])
    )


def _write_binary_ply(path: Path, points, colors) -> None:
    import numpy as np

    out_dtype = np.dtype([
        ('x', '<f8'),
        ('y', '<f8'),
        ('z', '<f8'),
        ('red', 'u1'),
        ('green', 'u1'),
        ('blue', 'u1'),
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        f.write(
            (
                'ply\n'
                'format binary_little_endian 1.0\n'
                'comment Created by PhenoFusion3D streaming cleanup\n'
                f'element vertex {len(points)}\n'
                'property double x\n'
                'property double y\n'
                'property double z\n'
                'property uchar red\n'
                'property uchar green\n'
                'property uchar blue\n'
                'end_header\n'
            ).encode('ascii')
        )
        out = np.empty(len(points), dtype=out_dtype)
        out['x'] = points[:, 0]
        out['y'] = points[:, 1]
        out['z'] = points[:, 2]
        out['red'] = colors[:, 0]
        out['green'] = colors[:, 1]
        out['blue'] = colors[:, 2]
        out.tofile(f)


def _keep_largest_voxel_component(points, colors, cell_size: float):
    import numpy as np
    from collections import deque

    if len(points) == 0 or cell_size <= 0:
        return points, colors

    print(f'[clean_pointcloud] Building coarse voxel graph at {cell_size:g} m...', flush=True)
    cells = np.floor(points / cell_size).astype(np.int64)
    unique_cells, inverse = np.unique(cells, axis=0, return_inverse=True)
    cell_lookup = {tuple(cell): idx for idx, cell in enumerate(unique_cells)}
    visited = np.zeros(len(unique_cells), dtype=bool)

    neighbor_offsets = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if not (dx == 0 and dy == 0 and dz == 0)
    ]

    largest_component: list[int] = []
    for start_idx, start_cell in enumerate(unique_cells):
        if visited[start_idx]:
            continue

        component: list[int] = []
        queue: deque[int] = deque([start_idx])
        visited[start_idx] = True
        while queue:
            idx = queue.popleft()
            component.append(idx)
            cell = unique_cells[idx]
            for offset in neighbor_offsets:
                neighbor_key = (
                    int(cell[0] + offset[0]),
                    int(cell[1] + offset[1]),
                    int(cell[2] + offset[2]),
                )
                neighbor_idx = cell_lookup.get(neighbor_key)
                if neighbor_idx is not None and not visited[neighbor_idx]:
                    visited[neighbor_idx] = True
                    queue.append(neighbor_idx)

        if len(component) > len(largest_component):
            largest_component = component

    keep_cells = np.zeros(len(unique_cells), dtype=bool)
    keep_cells[np.asarray(largest_component, dtype=np.int64)] = True
    keep = keep_cells[inverse]
    print(
        f'[clean_pointcloud] Largest component kept {int(np.count_nonzero(keep)):,}/'
        f'{len(points):,} points across {len(largest_component):,}/{len(unique_cells):,} cells',
        flush=True,
    )
    return points[keep], colors[keep]


def _stream_clean_huge_ply(
    input_ply: Path,
    output_dir: Path,
    *,
    voxel_size: float,
    green_only: bool,
    largest_cluster: bool,
    cluster_eps: float,
    chunk_points: int = 500_000,
) -> bool:
    import numpy as np

    header = _read_binary_ply_header(input_ply)
    if header is None:
        return False

    header_bytes, vertex_count, properties = header
    dtype = _ply_dtype(properties)
    if dtype is None or not {'x', 'y', 'z', 'red', 'green', 'blue'}.issubset(dtype.names or ()):
        return False

    print(f'[clean_pointcloud] Streaming binary PLY: {vertex_count:,} points', flush=True)
    print('[clean_pointcloud] Using stream cleanup: HSV green filter + voxel downsample', flush=True)
    if voxel_size <= 0:
        raise RuntimeError('Streaming cleanup requires --voxel-size > 0')

    seen: set[tuple[int, int, int]] = set()
    point_chunks = []
    color_chunks = []
    processed = 0
    green_points = 0
    next_log = 5_000_000

    with input_ply.open('rb') as f:
        f.seek(header_bytes)
        while processed < vertex_count:
            count = min(chunk_points, vertex_count - processed)
            data = np.fromfile(f, dtype=dtype, count=count)
            if data.size == 0:
                break
            processed += int(data.size)

            xyz = np.column_stack((data['x'], data['y'], data['z'])).astype(np.float64, copy=False)
            rgb = np.column_stack((data['red'], data['green'], data['blue'])).astype(np.uint8, copy=False)

            if green_only:
                mask = _rgb_to_hsv_green_mask(rgb)
                xyz = xyz[mask]
                rgb = rgb[mask]
            green_points += int(len(xyz))

            if len(xyz) > 0:
                keys = np.floor(xyz / voxel_size).astype(np.int64)
                unique_keys, unique_indices = np.unique(keys, axis=0, return_index=True)
                keep_indices = []
                for key_row, index in zip(unique_keys, unique_indices):
                    key = (int(key_row[0]), int(key_row[1]), int(key_row[2]))
                    if key not in seen:
                        seen.add(key)
                        keep_indices.append(int(index))
                if keep_indices:
                    keep = np.asarray(keep_indices, dtype=np.int64)
                    point_chunks.append(xyz[keep])
                    color_chunks.append(rgb[keep])

            if processed >= next_log:
                print(
                    f'[clean_pointcloud] streamed {processed:,}/{vertex_count:,}; '
                    f'kept {len(seen):,} voxel points',
                    flush=True,
                )
                next_log += 5_000_000

    if not point_chunks:
        raise RuntimeError('Streaming cleanup kept zero points. Try --no-green-only.')

    points = np.vstack(point_chunks)
    colors = np.vstack(color_chunks)
    downsampled_points = int(len(points))
    if largest_cluster:
        points, colors = _keep_largest_voxel_component(points, colors, cell_size=cluster_eps)

    output_ply = output_dir / 'cleaned_plant.ply'
    summary_json = output_dir / 'cleanup_summary.json'
    print(f'[clean_pointcloud] Writing {len(points):,} points...', flush=True)
    _write_binary_ply(output_ply, points, colors)
    with summary_json.open('w', encoding='utf-8') as f:
        json.dump(
            {
                'input_ply': str(input_ply),
                'output_ply': str(output_ply),
                'summary_json': str(summary_json),
                'input_points': vertex_count,
                'downsampled_points': downsampled_points,
                'green_points': green_points,
                'clustered_points': int(len(points)),
                'cleaned_points': int(len(points)),
                'note': 'Streaming cleanup used HSV green filtering, voxel downsampling, and optional coarse largest-component filtering.',
            },
            f,
            indent=2,
        )
    print(f'[clean_pointcloud] Wrote: {output_ply}', flush=True)
    print(f'[clean_pointcloud] Summary: {summary_json}', flush=True)
    return True


def main() -> None:
    args = parse_args()
    inputs = expand_inputs(args.inputs, batch=args.batch)
    if not inputs:
        raise SystemExit('No input PLY files matched.')

    green_only = args.green_only or not args.no_green_only
    for input_ply in inputs:
        output_dir = Path(args.output_dir) if args.output_dir and len(inputs) == 1 else _default_output_dir(input_ply)
        input_path = Path(input_ply)
        print(f'[clean_pointcloud] Input:  {input_ply}', flush=True)
        print(f'[clean_pointcloud] Output: {output_dir}', flush=True)
        if _stream_clean_huge_ply(
            input_path,
            output_dir,
            voxel_size=args.voxel_size,
            green_only=green_only,
            largest_cluster=args.largest_cluster,
            cluster_eps=args.cluster_eps,
        ):
            continue

        print('[clean_pointcloud] Loading Open3D cleanup engine...', flush=True)
        from processing.pointcloud_post import cleanup_point_cloud

        try:
            result = cleanup_point_cloud(
                input_ply,
                output_dir,
                voxel_size_m=args.voxel_size,
                green_only=green_only,
                largest_cluster=args.largest_cluster,
                cluster_eps_m=args.cluster_eps,
                cluster_min_points=args.cluster_min_points,
                stat_neighbors=args.stat_neighbors,
                stat_std_ratio=args.stat_std_ratio,
                radius_nb_points=args.radius_points,
                radius_m=args.radius,
                log=lambda message: print(message, flush=True),
            )
        except BaseException as exc:
            print(f'[clean_pointcloud] FAILED: {exc}', flush=True)
            traceback.print_exc()
            raise SystemExit(1) from exc
        print(
            '[clean_pointcloud] points: '
            f'{result.input_points:,} -> {result.downsampled_points:,} '
            f'-> {result.green_points:,} -> {result.clustered_points:,} '
            f'-> {result.cleaned_points:,}',
            flush=True,
        )
        print(f'[clean_pointcloud] Wrote: {result.output_ply}', flush=True)
        print(f'[clean_pointcloud] Summary: {result.summary_json}', flush=True)


if __name__ == '__main__':
    main()

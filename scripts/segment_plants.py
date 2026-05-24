from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Split a cleaned multi-plant PLY into per-plant PLY files.')
    parser.add_argument('input_ply', help='Cleaned input PLY path.')
    parser.add_argument('--output-dir', required=True, help='Directory for plant_*.ply outputs.')
    parser.add_argument('--expected-plants', type=int, default=None, help='Number of plant components to keep.')
    parser.add_argument('--cluster-eps', type=float, default=0.08, help='Coarse voxel connectivity size in metres.')
    parser.add_argument('--min-points', type=int, default=1000, help='Ignore components smaller than this.')
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


def _load_binary_ply(path: Path):
    import numpy as np

    header = _read_binary_ply_header(path)
    if header is None:
        raise RuntimeError('Only binary_little_endian PLY files are supported by this segmenter.')

    header_bytes, vertex_count, properties = header
    dtype = _ply_dtype(properties)
    if dtype is None or not {'x', 'y', 'z', 'red', 'green', 'blue'}.issubset(dtype.names or ()):
        raise RuntimeError('PLY must contain x/y/z and red/green/blue vertex properties.')

    print(f'[segment_plants] Loading {vertex_count:,} points...', flush=True)
    with path.open('rb') as f:
        f.seek(header_bytes)
        data = np.fromfile(f, dtype=dtype, count=vertex_count)

    points = np.column_stack((data['x'], data['y'], data['z'])).astype(np.float64, copy=False)
    colors = np.column_stack((data['red'], data['green'], data['blue'])).astype(np.uint8, copy=False)
    return points, colors


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
                'comment Created by PhenoFusion3D plant segmentation\n'
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


def _connected_components(points, cell_size: float):
    import numpy as np

    if cell_size <= 0:
        raise RuntimeError('--cluster-eps must be greater than 0.')

    print(f'[segment_plants] Building voxel graph at {cell_size:g} m...', flush=True)
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

    components = []
    for start_idx in range(len(unique_cells)):
        if visited[start_idx]:
            continue

        component_cells = []
        queue: deque[int] = deque([start_idx])
        visited[start_idx] = True
        while queue:
            idx = queue.popleft()
            component_cells.append(idx)
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

        component_cells = np.asarray(component_cells, dtype=np.int64)
        keep_cells = np.zeros(len(unique_cells), dtype=bool)
        keep_cells[component_cells] = True
        point_indices = np.where(keep_cells[inverse])[0]
        components.append(point_indices)

    components.sort(key=len, reverse=True)
    print(f'[segment_plants] Found {len(components):,} connected components.', flush=True)
    return components


def main() -> None:
    import numpy as np

    args = parse_args()
    input_ply = Path(args.input_ply)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    points, colors = _load_binary_ply(input_ply)
    components = [
        component
        for component in _connected_components(points, cell_size=args.cluster_eps)
        if len(component) >= args.min_points
    ]
    if args.expected_plants is not None:
        components = components[: args.expected_plants]

    if not components:
        raise SystemExit('[segment_plants] No plant components found. Try lowering --min-points or increasing --cluster-eps.')

    summary = {
        'input_ply': str(input_ply),
        'output_dir': str(output_dir),
        'cluster_eps': args.cluster_eps,
        'min_points': args.min_points,
        'expected_plants': args.expected_plants,
        'plants': [],
    }

    for idx, component in enumerate(components, start=1):
        plant_points = points[component]
        plant_colors = colors[component]
        output_ply = output_dir / f'plant_{idx}.ply'
        _write_binary_ply(output_ply, plant_points, plant_colors)

        bounds_min = np.min(plant_points, axis=0)
        bounds_max = np.max(plant_points, axis=0)
        extent = bounds_max - bounds_min
        plant_summary = {
            'plant_id': idx,
            'output_ply': str(output_ply),
            'point_count': int(len(plant_points)),
            'bounds_min': bounds_min.tolist(),
            'bounds_max': bounds_max.tolist(),
            'extent': extent.tolist(),
        }
        summary['plants'].append(plant_summary)
        print(
            f'[segment_plants] Wrote plant_{idx}.ply with {len(plant_points):,} points '
            f'(extent={extent[0]:.3f}, {extent[1]:.3f}, {extent[2]:.3f})',
            flush=True,
        )

    summary_json = output_dir / 'segmentation_summary.json'
    with summary_json.open('w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f'[segment_plants] Summary: {summary_json}', flush=True)


if __name__ == '__main__':
    main()

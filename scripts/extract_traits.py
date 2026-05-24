from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from processing.pointcloud_post import expand_inputs, extract_traits


def _default_output_dir(input_ply: str) -> Path:
    path = Path(input_ply)
    dataset_dir = path.parent.parent if path.parent.name == 'post_cleanup' else path.parent
    return dataset_dir / 'traits'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Extract plant traits from a cleaned point cloud PLY.')
    parser.add_argument('inputs', nargs='+', help='Cleaned PLY path(s) or glob pattern(s).')
    parser.add_argument('--batch', action='store_true', help='Expand glob patterns and process all matches.')
    parser.add_argument('--output-dir', default=None, help='Output directory for single-file mode.')
    parser.add_argument('--height-axis', choices=('x', 'y', 'z'), default='z', help='Axis used as plant height.')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = expand_inputs(args.inputs, batch=args.batch)
    if not inputs:
        raise SystemExit('No input PLY files matched.')

    for input_ply in inputs:
        output_dir = Path(args.output_dir) if args.output_dir and len(inputs) == 1 else _default_output_dir(input_ply)
        print(f'[extract_traits] Input:  {input_ply}')
        print(f'[extract_traits] Output: {output_dir}')
        result = extract_traits(input_ply, output_dir, height_axis=args.height_axis)
        print(f'[extract_traits] points: {result.point_count:,}')
        print(f'[extract_traits] convex hull area: {result.convex_hull_area_m2:.6f} m^2')
        print(f'[extract_traits] convex hull volume: {result.convex_hull_volume_m3:.6f} m^3')
        print(f'[extract_traits] max height: {result.height_max_m:.6f} m')
        print(f'[extract_traits] Wrote: {result.traits_json}')
        print(f'[extract_traits] Wrote: {result.traits_csv}')


if __name__ == '__main__':
    main()

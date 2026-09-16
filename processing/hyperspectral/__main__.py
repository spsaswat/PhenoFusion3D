"""CLI used by the isolated desktop analysis process."""
import argparse
from pathlib import Path
from .workflow import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['spectral', 'fusion', 'all', 'workspace'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--hsi', type=Path)
    parser.add_argument('--rgbd', type=Path)
    parser.add_argument('--spectral-results', type=Path)
    parser.add_argument('--inspect-only', action='store_true')
    args = parser.parse_args()
    if args.mode == 'workspace':
        from .workspace import open_workspace
        open_workspace(args.output)
    else:
        run(args.mode, args.output, *(p.resolve() if p else None for p in (args.hsi, args.rgbd, args.spectral_results)), inspect_only=args.inspect_only)


if __name__ == '__main__':
    main()

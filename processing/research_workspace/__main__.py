"""Create or rebuild a local research workspace without hardware access."""
import argparse
from .workflow import build, create_template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    template = modes.add_parser('template')
    template.add_argument('--output', required=True)
    run = modes.add_parser('build')
    run.add_argument('--manifest', required=True)
    run.add_argument('--annotations')
    run.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.mode == 'template': create_template(args.output)
    else: build(args.manifest, args.output, args.annotations)


if __name__ == '__main__': main()

#!/usr/bin/env bash
# install/install_linux.sh
# Lab Linux installer for PhenoFusion3D -- thin wrapper around ./setup.sh.
#
# This used to be a second, independent installer that apt-installed
# Python, ran `curl | sh` to fetch uv, and apt-installed Qt/X11/GL
# libraries with sudo. It no longer does any of that, and neither does
# setup.sh: nothing here may change the machine.
#
# What actually happens now (all of it inside the project directory):
#   1. .venv-linux/ is created with --system-site-packages, so the
#      system ROS distro's rospy stays importable from the venv.
#   2. The project + any MISSING Python dependencies are installed into
#      that venv. Packages that are already present are never upgraded,
#      downgraded or removed.
#   3. Missing system pieces (Qt/GL libraries, ROS, RealSense udev
#      rules) are detected and printed as MANUAL STEPS for you to run.
#
# System prerequisites are your lab SOP's job, not this script's:
# ROS Noetic/Humble installed and sourced, librealsense udev rules, and
# the Qt runtime libraries. See install/README.md.
#
# Usage:
#   chmod +x install/install_linux.sh
#   ./install/install_linux.sh              # same as ./setup.sh
#   ./install/install_linux.sh --dry-run    # print the pip commands only
#
# Every setup.sh flag is accepted and forwarded unchanged.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ./setup.sh ]; then
    if [ -f ./setup.sh ]; then
        exec bash ./setup.sh "$@"
    fi
    printf '[install] ERROR: setup.sh not found at %s\n' "$(pwd)" >&2
    exit 1
fi

printf '[install] Delegating to ./setup.sh (venv only -- your machine is not modified).\n' >&2
exec ./setup.sh "$@"

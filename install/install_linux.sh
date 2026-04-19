#!/usr/bin/env bash
# install/install_linux.sh
# Lab Linux installer for PhenoFusion3D (ROS + RealSense backend).
#
# Prereqs (system):
#   - ROS Noetic / Humble installed and sourced (`source /opt/ros/<distro>/setup.bash`)
#   - librealsense2 SDK runtime
#   - Python 3.10+
#
# Usage:
#   chmod +x install/install_linux.sh
#   ./install/install_linux.sh

set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found." >&2
    exit 1
fi

if [ ! -d venv ]; then
    echo "[install] Creating venv..."
    python3 -m venv venv
fi

# IMPORTANT: ROS workspaces ship rospy on the system PYTHONPATH.
# Use --system-site-packages so the venv can import rospy.
if [ ! -f venv/.has_system_site ]; then
    echo "[install] Recreating venv with --system-site-packages so rospy is visible..."
    rm -rf venv
    python3 -m venv --system-site-packages venv
    touch venv/.has_system_site
fi

# shellcheck disable=SC1091
source venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[ros]"

echo
echo "[install] Verifying imports..."
python - <<'PY'
import importlib, sys
ok = True
for mod in ("PyQt5", "open3d", "cv2", "numpy", "natsort"):
    try:
        importlib.import_module(mod); print(f"  OK  {mod}")
    except Exception as e:
        ok = False; print(f"  FAIL {mod}: {e}")

# rospy (system) and pyrealsense2 (pip)
for mod in ("rospy", "pyrealsense2"):
    try:
        importlib.import_module(mod); print(f"  OK  {mod}")
    except Exception as e:
        print(f"  WARN {mod}: {e} (capture backend may not work)")

sys.exit(0 if ok else 1)
PY

echo
echo "[install] Done. Launch the app with:"
echo "    source venv/bin/activate"
echo "    python main.py"

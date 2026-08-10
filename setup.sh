#!/usr/bin/env bash
# setup.sh -- PhenoFusion3D one-shot setup for Ubuntu 20.04 LTS (Focal Fossa)
#
# Targets a completely blank Ubuntu 20.04 install (incl. WSL2). Installs
# every dependency, creates the Python virtual environment (.venv-linux),
# installs the project, and verifies the result. Safe to re-run: every
# step is idempotent.
#
# Python strategy (in order):
#   1. Use any Python 3.10-3.12 already on PATH that can create venvs.
#   2. Else apt-install one via the deadsnakes PPA -- but only after
#      confirming apt can actually see the package (focal is past EOL,
#      so PPA coverage is checked, not assumed).
#   3. Else download a standalone CPython 3.11 via `uv` (no sudo, no apt).
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh                    # base install (GUI + reconstruction, no camera)
#   ./setup.sh --with-realsense   # + Intel librealsense2 SDK + pyrealsense2
#   ./setup.sh --l515             # + L515-compatible pyrealsense2 (<2.55, implies --with-realsense)
#   ./setup.sh --with-ros         # + ROS Noetic base (ROS 1 for focal) for the gantry backend
#   ./setup.sh --verify-only      # run only the verification step
#
# sudo: required for the apt steps only. Run as a normal user; the script
# invokes sudo itself where needed (or runs plain if already root).

set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"
VENV_DIR="${PHENOFUSION_LINUX_VENV:-.venv-linux}"

WITH_REALSENSE=false
WITH_ROS=false
L515=false
VERIFY_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --with-realsense) WITH_REALSENSE=true ;;
        --l515)           L515=true; WITH_REALSENSE=true ;;
        --with-ros)       WITH_ROS=true ;;
        --verify-only)    VERIFY_ONLY=true ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

log()  { printf '\033[1;32m[setup]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[setup] WARNING:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[setup] ERROR:\033[0m %s\n' "$*" >&2; }

# sudo handling: use sudo unless already root. DEBIAN_FRONTEND must ride
# through sudo (sudo strips exported env), otherwise tzdata & friends can
# hang a fresh install waiting for interactive input.
SUDO="sudo DEBIAN_FRONTEND=noninteractive"
[ "$(id -u)" -eq 0 ] && SUDO=""

IS_WSL=false
grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=true

###############################################################################
# 0. Sanity checks + verification (defined early so --verify-only can exit)
###############################################################################

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [ "${VERSION_ID:-}" != "20.04" ]; then
        warn "This script is written/tested for Ubuntu 20.04; detected ${PRETTY_NAME:-unknown}. Continuing anyway."
    fi
fi

verify() {
    log "Verifying installation..."
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        err "venv not found at $VENV_DIR. Run ./setup.sh first."
        return 1
    fi
    local rc=0
    "$VENV_DIR/bin/python" - <<'PY' || rc=$?
import importlib, sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless-safe Qt check

failures = []
required = ["PyQt5", "open3d", "cv2", "numpy", "natsort", "tqdm", "pyqtgraph", "matplotlib"]
for mod in required:
    try:
        m = importlib.import_module(mod)
        print(f"  OK    {mod:12s} {getattr(m, '__version__', '')}")
    except Exception as e:
        failures.append(mod)
        print(f"  FAIL  {mod}: {e}")

# Optional capture backends -- warn only.
for mod in ("pyrealsense2", "rospy"):
    try:
        importlib.import_module(mod)
        print(f"  OK    {mod} (capture backend available)")
    except Exception:
        print(f"  --    {mod} not available (capture backend disabled; fine for dev/no-camera use)")

# Smoke tests: Qt event loop + Open3D geometry, both headless.
try:
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    print("  OK    Qt QApplication (offscreen)")
except Exception as e:
    failures.append("QApplication")
    print(f"  FAIL  QApplication: {e}")
try:
    import open3d as o3d
    import numpy as np
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.random.rand(100, 3))
    pcd.estimate_normals()
    print("  OK    Open3D point-cloud smoke test")
except Exception as e:
    failures.append("open3d-smoke")
    print(f"  FAIL  Open3D smoke test: {e}")

try:
    import app as _app  # project package (editable install)
    print("  OK    phenofusion3d project package importable")
except Exception as e:
    print(f"  --    project package not importable yet: {e}")

sys.exit(1 if failures else 0)
PY
    if [ $rc -eq 0 ]; then
        log "VERIFICATION PASSED. Launch with: source $VENV_DIR/bin/activate && python main.py"
    else
        err "Verification failed (see FAIL lines above)."
    fi
    return $rc
}

if [ "$VERIFY_ONLY" = true ]; then
    verify
    exit $?
fi

###############################################################################
# 1. Base system packages (sudo required)
###############################################################################

export DEBIAN_FRONTEND=noninteractive
log "Updating apt package lists (sudo required)..."
$SUDO apt-get update -y || warn "apt update reported errors; continuing with cached lists."

log "Installing base tools..."
$SUDO apt-get install -y --no-install-recommends \
    software-properties-common ca-certificates curl gnupg lsb-release git \
    || warn "Some base tools failed to install; continuing."

###############################################################################
# 2. Find or install a Python 3.10-3.12 interpreter
###############################################################################

# A candidate must be 3.10-3.12 AND able to create venvs with pip
# (Debian/Ubuntu split ensurepip into pythonX.Y-venv, so check for it).
python_ok() {
    "$1" -c 'import sys, venv, ensurepip; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' \
        >/dev/null 2>&1
}

pick_python() {
    # Prefer 3.11 (matches existing .venv-linux and keeps the L515
    # pyrealsense2 <2.55 wheel available), then 3.12, 3.10, plain python3.
    local cand path
    for cand in python3.11 python3.12 python3.10 python3; do
        path="$(command -v "$cand" 2>/dev/null || true)"
        if [ -n "$path" ] && python_ok "$path"; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

# Does apt actually have this package? (Don't assume PPA coverage --
# deadsnakes may drop or lag EOL'd releases like focal.)
apt_provides() {
    apt-cache show "$1" 2>/dev/null | grep -q '^Version:'
}

apt_try_python() {
    local v="$1" pkgs
    apt_provides "python$v" || return 1
    pkgs=("python$v" "python$v-venv" "python$v-dev")
    apt_provides "python$v-distutils" && pkgs+=("python$v-distutils")  # gone in 3.12+
    log "Installing ${pkgs[*]} via apt..."
    $SUDO apt-get install -y --no-install-recommends "${pkgs[@]}" || return 1
    command -v "python$v" >/dev/null 2>&1 && python_ok "$(command -v "python$v")"
}

install_python_via_uv() {
    # Standalone CPython under $HOME -- no apt, no sudo, immune to PPA EOL.
    if ! command -v uv >/dev/null 2>&1; then
        log "Installing uv (standalone Python manager, no sudo)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh >&2
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null 2>&1 || return 1
    log "Downloading standalone CPython 3.11 via uv..."
    uv python install 3.11 >&2 || return 1
    local p
    p="$(uv python find 3.11 2>/dev/null || true)"
    [ -n "$p" ] && [ -x "$p" ] && python_ok "$p" && echo "$p"
}

if PYTHON_BIN="$(pick_python)"; then
    log "Using existing interpreter: $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1))"
else
    log "No usable Python 3.10-3.12 on PATH. Trying apt (deadsnakes PPA)..."
    if ! apt_provides python3.11 && ! apt_provides python3.10; then
        $SUDO add-apt-repository -y ppa:deadsnakes/ppa || warn "Could not add deadsnakes PPA."
        $SUDO apt-get update -y || true
    fi
    for v in 3.11 3.10 3.12; do
        apt_try_python "$v" && break || true
    done
    if ! PYTHON_BIN="$(pick_python)"; then
        warn "apt could not provide Python 3.10-3.12 (PPA may not cover this release). Falling back to uv..."
        if ! PYTHON_BIN="$(install_python_via_uv)"; then
            err "Could not obtain a Python 3.10-3.12 interpreter by any method."
            err "Install one manually, ensure it can 'import ensurepip', and re-run."
            exit 1
        fi
    fi
    log "Using interpreter: $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1))"
fi

# Compilers: only needed if pip has to build a package from source.
$SUDO apt-get install -y --no-install-recommends build-essential \
    || warn "build-essential unavailable; fine as long as all wheels are prebuilt."

###############################################################################
# 3. Native runtime libs for PyQt5 (xcb), Open3D (GL/EGL), OpenCV
###############################################################################

QT_LIBS=(
    libxcb1 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0
    libxcb-render0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0
    libxcb-xinerama0 libxcb-xkb1 libxcb-randr0 libxcb-util1 libxcb-cursor0
    libxkbcommon0 libxkbcommon-x11-0
    libx11-6 libx11-xcb1 libxext6 libxrender1 libsm6 libice6
    libegl1 libgl1 libglx0 libglu1-mesa libopengl0
    libfontconfig1 libfreetype6 libdbus-1-3 libgomp1
    libglib2.0-0 libusb-1.0-0
)
log "Installing Qt/X11/OpenGL runtime libraries..."
if ! $SUDO apt-get install -y --no-install-recommends "${QT_LIBS[@]}"; then
    warn "Batch install failed; retrying packages one by one..."
    for p in "${QT_LIBS[@]}"; do
        $SUDO apt-get install -y --no-install-recommends "$p" \
            || warn "Could not install $p (verification will show if it matters)."
    done
fi

###############################################################################
# 4. Optional: Intel RealSense SDK
###############################################################################

if [ "$WITH_REALSENSE" = true ]; then
    if [ ! -f /etc/apt/sources.list.d/librealsense.list ]; then
        log "Adding Intel librealsense apt repo (focal is supported)..."
        $SUDO mkdir -p /etc/apt/keyrings
        curl -sSf https://librealsense.intel.com/Debian/librealsense.pgp \
            | $SUDO tee /etc/apt/keyrings/librealsense.pgp >/dev/null
        echo "deb [signed-by=/etc/apt/keyrings/librealsense.pgp] https://librealsense.intel.com/Debian/apt-repo $(lsb_release -cs) main" \
            | $SUDO tee /etc/apt/sources.list.d/librealsense.list >/dev/null
        $SUDO apt-get update -y
    fi
    RS_PKGS=(librealsense2-utils librealsense2-dev)
    if [ "$IS_WSL" = true ]; then
        warn "WSL detected: skipping librealsense2-dkms (no custom kernel modules in WSL2). USB cameras need usbipd-win passthrough."
    else
        RS_PKGS+=(librealsense2-dkms)
    fi
    $SUDO apt-get install -y --no-install-recommends "${RS_PKGS[@]}" \
        || warn "librealsense2 install failed; camera capture will not work until fixed."
fi

###############################################################################
# 5. Optional: ROS Noetic (ROS 1 distro for Ubuntu 20.04)
###############################################################################

if [ "$WITH_ROS" = true ]; then
    if [ ! -f /etc/apt/sources.list.d/ros-latest.list ]; then
        log "Adding ROS Noetic apt repo..."
        echo "deb http://packages.ros.org/ros/ubuntu focal main" \
            | $SUDO tee /etc/apt/sources.list.d/ros-latest.list >/dev/null
        curl -sSf https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
            | $SUDO apt-key add -
        $SUDO apt-get update -y
    fi
    $SUDO apt-get install -y --no-install-recommends ros-noetic-ros-base \
        || warn "ROS Noetic install failed (it reached EOL May 2025; mirrors may have moved)."
    log "Remember to 'source /opt/ros/noetic/setup.bash' BEFORE re-running this script so the venv inherits rospy."
fi

###############################################################################
# 6. Virtual environment (no sudo from here on)
###############################################################################

venv_ok() {
    [ -x "$VENV_DIR/bin/python" ] && \
    "$VENV_DIR/bin/python" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" 2>/dev/null
}

if venv_ok; then
    log "Reusing existing venv at $VENV_DIR ($("$VENV_DIR/bin/python" -V))."
else
    [ -d "$VENV_DIR" ] && { warn "Recreating incompatible venv $VENV_DIR..."; rm -rf "$VENV_DIR"; }
    log "Creating venv at $VENV_DIR ($("$PYTHON_BIN" -V), --system-site-packages so system rospy is visible)..."
    "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel

###############################################################################
# 7. Project + Python dependencies
###############################################################################

if [ -f pyproject.toml ] || [ -f setup.py ]; then
    log "Installing project in editable mode..."
    if [ "$WITH_ROS" = true ]; then
        python -m pip install -e ".[ros]"
    else
        python -m pip install -e "."
    fi
elif [ -f install/appimage/requirements.txt ]; then
    warn "No pyproject.toml/setup.py at $ROOT_DIR -- project source appears incomplete."
    warn "Installing runtime deps from install/appimage/requirements.txt so the venv is ready;"
    warn "restore the project source (git clone / git checkout) and re-run to finish."
    grep -v '^\s*\.\s*$' install/appimage/requirements.txt | python -m pip install -r /dev/stdin
else
    err "Neither pyproject.toml nor install/appimage/requirements.txt found. Is $ROOT_DIR the repo root?"
    exit 1
fi

# opencv-python bundles its own Qt plugins which hijack PyQt5's xcb plugin
# ("Could not load the Qt platform plugin xcb in .../cv2/qt/plugins").
# The GUI uses PyQt5, so swap in the headless OpenCV build.
if python -m pip show opencv-python >/dev/null 2>&1; then
    log "Replacing opencv-python with opencv-python-headless (PyQt5/cv2 Qt conflict fix)..."
    python -m pip uninstall -y opencv-python
    python -m pip install opencv-python-headless
fi

if [ "$WITH_REALSENSE" = true ]; then
    if [ "$L515" = true ]; then
        log "Installing L515-compatible pyrealsense2 (<2.55)..."
        python -m pip install "pyrealsense2>=2.54.0,<2.55"
    else
        log "Installing pyrealsense2..."
        python -m pip install pyrealsense2
    fi
fi

###############################################################################
# 8. Verify
###############################################################################

verify

#!/usr/bin/env bash
# setup.sh -- PhenoFusion3D setup. Creates the project venv, and nothing else.
#
# HARD RULE -- do not relax this, ever:
#   This script MUST NOT modify the machine. No sudo. No apt-get /
#   apt / add-apt-repository / apt-key. No writes outside this project
#   directory: no /etc, no udev rules, no ~/.bashrc, no `curl | sh`
#   installers, no `uv python install`, no system Python packages.
#   The ONE thing it creates is the project virtual environment.
#
#   Anything that would need a system change is *printed* at the end as
#   a MANUAL STEPS list, with the exact command, for you to run (or not)
#   yourself. The script never runs those commands.
#
# Inside the venv it installs MISSING dependencies only. It never
# upgrades, downgrades, uninstalls or force-reinstalls a package that is
# already there: a lab rig pinned to pyrealsense2 2.54 stays on 2.54,
# and pip/setuptools/wheel are left at whatever version they are.
# This is enforced with a constraints file pinning every already-visible
# distribution to its installed version, so pip cannot move any of them.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh                 # create/reuse .venv-linux, install what's missing, verify
#   ./setup.sh --dry-run       # print the pip commands, run none of them
#   ./setup.sh --no-ros        # skip the ROS-side Python deps (rospkg, catkin_pkg, ...)
#   ./setup.sh --no-realsense  # skip the camera SDK entirely (dev box, no camera)
#   ./setup.sh --verify-only   # run only the verification step
#
# System prerequisites (ROS Noetic, the machine-wide librealsense SDK and
# its udev rules, Qt/GL runtime libraries) are NOT installed here -- they
# are system state and belong to your lab SOP. The script CHECKS them and
# tells you the exact command; see install/README.md and, for the pinned
# RealSense stack, docs/L515_SETUP.md.

set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"
VENV_DIR="${PHENOFUSION_LINUX_VENV:-.venv-linux}"

# The RealSense stack this project is pinned to. Both numbers describe the
# SAME release: 2.54.2 is what the machine-wide SDK reports, 2.54.2.5684 is
# how the Python wheel of that release is versioned on PyPI.
#
# Why 2.54.2 and not something newer: the D405 has had official support
# since 2.51.1, and 2.54.2 is the LAST release that still contains L515
# support (dropped in >= 2.55; L515 last formally validated in 2.50.0).
# 2.54.2 is therefore the only common version that drives both cameras.
#
# The machine-wide SDK must be a source build with FORCE_RSUSB_BACKEND=ON
# (user-space USB, no patched kernel modules / DKMS) -- see
# docs/L515_SETUP.md. This script CHECKS that state and reports; it never
# installs, purges or downgrades anything system-wide.
RS_SDK_VERSION="2.54.2"           # machine-wide librealsense
RS_WHEEL_VERSION="2.54.2.5684"    # pyrealsense2 wheel inside the venv

WITH_REALSENSE=true
WITH_ROS=true
VERIFY_ONLY=false
DRY_RUN=false
for arg in "$@"; do
    case "$arg" in
        --no-realsense)   WITH_REALSENSE=false ;;
        --no-ros)         WITH_ROS=false ;;
        # 2.54.2 already carries L515 support, so the pin is the same
        # for every camera; accepted as a no-op for old notes.
        --l515)           WITH_REALSENSE=true ;;
        --dry-run)        DRY_RUN=true ;;
        --verify-only)    VERIFY_ONLY=true ;;
        # Older invocations that used to switch on system-level work.
        # The system work is gone; accepted as no-ops so old notes and
        # CI lines keep running.
        --with-realsense|--with-ros|--lab-rig) ;;
        -h|--help)        sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

log()  { printf '\033[1;32m[setup]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[setup] WARNING:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[setup] ERROR:\033[0m %s\n' "$*" >&2; }

# Manual steps are collected here and printed once at the end. Nothing
# in this list is ever executed by the script.
MANUAL_STEPS=()
manual() { MANUAL_STEPS+=("$1"); }

print_manual_steps() {
    [ "${#MANUAL_STEPS[@]}" -eq 0 ] && return 0
    printf '\n' >&2
    printf '\033[1;33m====================== MANUAL STEPS ======================\033[0m\n' >&2
    printf 'These need to change your machine, so this script does NOT run\n' >&2
    printf 'them. Run the ones you actually want, yourself:\n\n' >&2
    local step
    for step in "${MANUAL_STEPS[@]}"; do
        printf '%s\n\n' "$step" >&2
    done
    printf '\033[1;33m==========================================================\033[0m\n' >&2
}

###############################################################################
# 0. Verification (defined early so --verify-only can use it)
###############################################################################

verify() {
    log "Verifying installation..."
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        err "venv not found at $VENV_DIR. Run ./setup.sh first."
        return 1
    fi
    # Verify under the same environment the app should run in: with ROS
    # sourced when it is installed (rospy reaches Python via PYTHONPATH).
    # Sourcing here affects this process only -- no persistent change.
    if [ -f /opt/ros/noetic/setup.bash ]; then
        set +u
        # shellcheck disable=SC1091
        source /opt/ros/noetic/setup.bash
        set -u
    fi
    local rc=0
    "$VENV_DIR/bin/python" - <<'PY' || rc=$?
import importlib, sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless-safe Qt check

failures = []
required = ["PyQt5", "cv2", "numpy", "natsort", "tqdm", "pyqtgraph", "matplotlib"]
for mod in required:
    try:
        m = importlib.import_module(mod)
        print(f"  OK    {mod:12s} {getattr(m, '__version__', '')}")
    except Exception as e:
        failures.append(mod)
        print(f"  FAIL  {mod}: {e}")
        if mod == "cv2":
            # Seen on the lab rig: pip's metadata says opencv is installed
            # but site-packages/cv2 is gone (interrupted install, or the
            # disk filled). Capture cannot write a single frame like this.
            print("        -> OpenCV is missing or half-installed. This script will")
            print("           not force-reinstall over your venv; run it yourself:")
            print("           .venv-linux/bin/pip install --force-reinstall "
                  "opencv-python-headless")

# open3d gets its own subprocess: on a CPU/VM without AVX the wheel dies
# with SIGILL, which would kill THIS process and report nothing useful.
import subprocess
_p = subprocess.run([sys.executable, "-c", "import open3d; print(open3d.__version__)"],
                    capture_output=True, text=True)
if _p.returncode == 0:
    print(f"  OK    {'open3d':12s} {_p.stdout.strip()}")
elif _p.returncode == -4:      # SIGILL
    print("  WARN  open3d installed but CRASHES on this CPU (Illegal instruction):")
    print("        the CPU/VM does not expose AVX. Capture, the gantry and Quick")
    print("        Scan all work; reconstruction and quality checks stay disabled")
    print("        until the host exposes AVX (VirtualBox >= 7.1, or disable")
    print("        Hyper-V / Core Isolation on the Windows host).")
else:
    failures.append("open3d")
    _tail = (_p.stderr or "").strip().splitlines()
    print(f"  FAIL  open3d: {_tail[-1] if _tail else _p.returncode}")

# Optional capture backends -- warn only.
try:
    import pyrealsense2 as rs
    try:
        devs = [d.get_info(rs.camera_info.name) for d in rs.context().devices]
    except Exception:
        devs = []
    ver = getattr(rs, "__version__", "?")
    if devs:
        print(f"  OK    pyrealsense2 {ver} (camera(s): {', '.join(devs)})")
    else:
        print(f"  OK    pyrealsense2 {ver} (no camera connected right now -- plug in to capture)")
except Exception:
    print("  --    pyrealsense2 not available (camera capture disabled; fine for dev use)")

try:
    import rospy
    origin = getattr(rospy, "__file__", "?")
    if "/opt/ros/" in origin:
        print(f"  OK    rospy (real ROS install: {origin})")
    else:
        print(f"  WARN  rospy imported from {origin}")
        print("        -> this looks like the unofficial PyPI shim, not ROS.")
        print("           This script never removes packages; if the gantry")
        print("           misbehaves, remove it yourself with:")
        print("           .venv-linux/bin/pip uninstall -y rospy rosgraph roslib rosmaster")
        print("           and 'source /opt/ros/noetic/setup.bash' instead.")
except Exception:
    print("  --    rospy not available (gantry backend disabled; fine for dev use)")
    if os.path.exists("/opt/ros/noetic/setup.bash"):
        print("        -> ROS IS installed; 'source /opt/ros/noetic/setup.bash' to enable it.")

# Informational: is a ROS master up right now? (Gantry needs roscore.)
import socket
from urllib.parse import urlparse
uri = os.environ.get("ROS_MASTER_URI", "http://localhost:11311")
p = urlparse(uri)
try:
    with socket.create_connection((p.hostname or "localhost", p.port or 11311), timeout=1.0):
        print(f"  OK    ROS master reachable at {uri}")
except OSError:
    print(f"  --    no ROS master at {uri} (start 'roscore' before using the gantry)")

# Smoke tests: Qt event loop + Open3D geometry, both headless.
try:
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    print("  OK    Qt QApplication (offscreen)")
except Exception as e:
    failures.append("QApplication")
    print(f"  FAIL  QApplication: {e}")
# Subprocess again, for the same reason as the version check above: a
# SIGILL here would kill this whole script and skip every later check.
_smoke = subprocess.run(
    [sys.executable, "-c",
     "import open3d as o3d, numpy as np;"
     "p = o3d.geometry.PointCloud();"
     "p.points = o3d.utility.Vector3dVector(np.random.rand(100, 3));"
     "p.estimate_normals()"],
    capture_output=True, text=True)
if _smoke.returncode == 0:
    print("  OK    Open3D point-cloud smoke test")
elif _smoke.returncode == -4:  # SIGILL -- same no-AVX CPU as above
    print("  WARN  Open3D smoke test skipped (no AVX on this CPU)")
else:
    failures.append("open3d-smoke")
    _tail = (_smoke.stderr or "").strip().splitlines()
    print(f"  FAIL  Open3D smoke test: {_tail[-1] if _tail else _smoke.returncode}")

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
# 1. Find a Python 3.10-3.12 interpreter (find only -- never install one)
###############################################################################

# A candidate must be 3.10-3.12 AND able to create venvs with pip
# (Debian/Ubuntu split ensurepip into pythonX.Y-venv, so check for it).
python_ok() {
    "$1" -c 'import sys, venv, ensurepip; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' \
        >/dev/null 2>&1
}

pick_python() {
    # Prefer 3.11 (matches the existing .venv-linux and keeps the L515
    # pyrealsense2 <2.55 wheel available), then 3.12, 3.10, plain python3.
    local cand path dir
    for cand in python3.11 python3.12 python3.10 python3; do
        path="$(command -v "$cand" 2>/dev/null || true)"
        if [ -n "$path" ] && python_ok "$path"; then
            echo "$path"; return 0
        fi
    done
    # Interpreters already downloaded by uv/conda, if the user has them.
    # We only USE what is already on the machine; we never fetch one.
    for dir in "$HOME/.local/share/uv/python" "$HOME/.cache/uv/python" \
               "$HOME/.miniforge3/bin" "$HOME/miniforge3/bin"; do
        [ -d "$dir" ] || continue
        for path in "$dir"/cpython-*/bin/python3 "$dir"/python3.1[012] "$dir"/python3; do
            if [ -x "$path" ] && python_ok "$path"; then
                echo "$path"; return 0
            fi
        done
    done
    return 1
}

if [ -n "${PHENOFUSION_PYTHON:-}" ]; then
    PYTHON_BIN="$PHENOFUSION_PYTHON"
    if ! python_ok "$PYTHON_BIN"; then
        err "PHENOFUSION_PYTHON=$PYTHON_BIN is not a venv-capable Python 3.10-3.12."
        exit 1
    fi
elif PYTHON_BIN="$(pick_python)"; then
    :
else
    err "No venv-capable Python 3.10-3.12 found on this machine."
    err "This script does not install one -- that would change your system."
    err "Install one yourself, then re-run (or point at it with"
    err "PHENOFUSION_PYTHON=/path/to/python3.11 ./setup.sh). For example:"
    err "    sudo apt install python3.11 python3.11-venv python3.11-dev"
    err "  or, without root:"
    err "    curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.11"
    exit 1
fi
log "Using interpreter: $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1))"

###############################################################################
# 2. Virtual environment -- the only thing this script creates
###############################################################################

venv_ok() {
    [ -x "$VENV_DIR/bin/python" ] && \
    "$VENV_DIR/bin/python" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" 2>/dev/null
}

if venv_ok; then
    log "Reusing existing venv at $VENV_DIR ($("$VENV_DIR/bin/python" -V 2>&1))."
elif [ -d "$VENV_DIR" ]; then
    # An existing directory is the user's data. Never delete it silently.
    err "$VENV_DIR exists but its Python is missing or outside 3.10-3.12."
    err "Not touching it. Remove or rename it yourself and re-run:"
    err "    rm -rf $VENV_DIR && ./setup.sh"
    exit 1
elif [ "$DRY_RUN" = true ]; then
    log "[dry-run] would create venv: $PYTHON_BIN -m venv --system-site-packages $VENV_DIR"
    err "Nothing else can be checked without a venv. Re-run without --dry-run."
    exit 0
else
    # --system-site-packages only lets the venv SEE system packages
    # (that is how the ROS distro's rospy becomes importable). It does
    # not let pip write to them: pip in a venv installs into the venv.
    log "Creating venv at $VENV_DIR ($("$PYTHON_BIN" -V 2>&1), --system-site-packages)..."
    "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"
fi

VPY="$VENV_DIR/bin/python"
log "pip: $("$VPY" -m pip --version 2>&1 | head -1) (left as-is -- this script never upgrades pip)"

###############################################################################
# 3. Install MISSING Python deps into the venv (never upgrade or replace)
###############################################################################

# Pin every distribution the venv can already see to its installed
# version. Passed to pip as constraints, this makes it impossible for
# any install below to move a package that already works -- pip can only
# add what is absent. If a new dependency genuinely conflicts with a
# pinned version, pip fails loudly instead of quietly upgrading.
CONSTRAINTS="$VENV_DIR/phenofusion-constraints.txt"
"$VPY" - > "$CONSTRAINTS" <<'PY'
from importlib.metadata import distributions
seen = {}
for dist in distributions():
    try:
        name = dist.metadata["Name"]
        version = dist.version
    except Exception:
        continue
    if not name or not version:
        continue
    key = name.lower().replace("_", "-")
    # The project itself is installed editable; constraining it would
    # make pip refuse the editable install.
    if key == "phenofusion3d":
        continue
    seen.setdefault(key, f"{name}=={version}")
print("\n".join(sorted(seen.values())))
PY
log "Pinned $(grep -c . "$CONSTRAINTS" || true) already-installed packages in $CONSTRAINTS (nothing below can move them)."

run_pip() {
    if [ "$DRY_RUN" = true ]; then
        printf '\033[1;36m[dry-run]\033[0m %s -m pip %s\n' "$VPY" "$*" >&2
        return 0
    fi
    "$VPY" -m pip "$@"
}

# 3a. The project itself (editable) + its core dependencies.
if [ ! -f pyproject.toml ] && [ ! -f setup.py ]; then
    err "Neither pyproject.toml nor setup.py found. Is $ROOT_DIR the repo root?"
    exit 1
fi
log "Installing the project (editable) and any missing core dependencies..."
if ! run_pip install --no-input -c "$CONSTRAINTS" -e .; then
    err "pip could not install the project without changing an existing package."
    err "Nothing was upgraded or removed. Inspect the resolver error above;"
    err "the offending pin is in $CONSTRAINTS."
    print_manual_steps
    exit 1
fi

# 3b. Extras, one package at a time, and only when the import is absent.
#     A module that already imports (from the venv, or from the system
#     via --system-site-packages) is left completely alone -- this is
#     what keeps a lab rig's pinned pyrealsense2 2.54 where it is.
have_module() { "$VPY" -c "import $1" >/dev/null 2>&1; }
module_version() { "$VPY" -c "import $1,sys; sys.stdout.write(getattr($1,'__version__','?'))" 2>/dev/null || true; }

install_if_missing() {
    local module="$1" requirement="$2" label="${3:-$2}"
    if have_module "$module"; then
        log "  $label already present ($(module_version "$module")) -- leaving it alone."
        return 0
    fi
    log "  $label missing -- installing $requirement into the venv..."
    run_pip install --no-input -c "$CONSTRAINTS" "$requirement" \
        || warn "  Could not install $requirement (see error above); continuing."
}

if [ "$WITH_ROS" = true ]; then
    # ROS itself (rospy, sensor_msgs) is a SYSTEM install and is never
    # touched here -- it reaches Python through PYTHONPATH when you
    # source /opt/ros/<distro>/setup.bash. These are rospy's pure-Python
    # PyPI dependencies, which the apt packages only provide for the
    # system Python 3.8 while this venv runs 3.10-3.12.
    log "ROS-side Python deps (the ROS distro itself is never installed here):"
    install_if_missing rospkg      "rospkg>=1.5"      "rospkg"
    install_if_missing catkin_pkg  "catkin_pkg>=1.0"  "catkin_pkg"
    install_if_missing yaml        "PyYAML>=5.1"      "PyYAML"
    install_if_missing defusedxml  "defusedxml>=0.7"  "defusedxml"
fi

if [ "$WITH_REALSENSE" = true ]; then
    # Exact pin, not a range: the newest wheel (2.58.x) cannot see an
    # L515 at all, and a wheel whose version differs from the
    # machine-wide SDK is the classic source of "no camera detected".
    log "Camera SDK (pinned to $RS_WHEEL_VERSION):"
    install_if_missing pyrealsense2 "pyrealsense2==$RS_WHEEL_VERSION" "pyrealsense2"
fi

###############################################################################
# 4. System-level checks -- REPORT ONLY, nothing is installed or changed
###############################################################################

# 4a. Native shared libraries needed by the Qt xcb plugin / Open3D /
#     pyrealsense2 wheels. Detected by ldd'ing what is actually in the
#     venv, so we name only the packages this machine really lacks.
declare -A SO_TO_PKG=(
    [libxcb-icccm.so.4]="libxcb-icccm4"        [libxcb-keysyms.so.1]="libxcb-keysyms1"
    [libxcb-image.so.0]="libxcb-image0"        [libxcb-render-util.so.0]="libxcb-render-util0"
    [libxcb-render.so.0]="libxcb-render0"      [libxcb-shape.so.0]="libxcb-shape0"
    [libxcb-shm.so.0]="libxcb-shm0"            [libxcb-sync.so.1]="libxcb-sync1"
    [libxcb-xfixes.so.0]="libxcb-xfixes0"      [libxcb-xinerama.so.0]="libxcb-xinerama0"
    [libxcb-xkb.so.1]="libxcb-xkb1"            [libxcb-randr.so.0]="libxcb-randr0"
    [libxcb-cursor.so.0]="libxcb-cursor0"      [libxcb-util.so.1]="libxcb-util1"
    [libxcb.so.1]="libxcb1"                    [libxkbcommon.so.0]="libxkbcommon0"
    [libxkbcommon-x11.so.0]="libxkbcommon-x11-0"
    [libX11.so.6]="libx11-6"                   [libX11-xcb.so.1]="libx11-xcb1"
    [libXext.so.6]="libxext6"                  [libXrender.so.1]="libxrender1"
    [libSM.so.6]="libsm6"                      [libICE.so.6]="libice6"
    [libEGL.so.1]="libegl1"                    [libGL.so.1]="libgl1"
    [libGLX.so.0]="libglx0"                    [libGLdispatch.so.0]="libglvnd0"
    [libOpenGL.so.0]="libopengl0"              [libGLU.so.1]="libglu1-mesa"
    [libfontconfig.so.1]="libfontconfig1"      [libfreetype.so.6]="libfreetype6"
    [libdbus-1.so.3]="libdbus-1-3"             [libgomp.so.1]="libgomp1"
    [libstdc++.so.6]="libstdc++6"              [libgcc_s.so.1]="libgcc-s1"
    [libusb-1.0.so.0]="libusb-1.0-0"           [libpng16.so.16]="libpng16-16"
    [libz.so.1]="zlib1g"                       [libglib-2.0.so.0]="libglib2.0-0"
    [libgthread-2.0.so.0]="libglib2.0-0"       [libgobject-2.0.so.0]="libglib2.0-0"
    [libgio-2.0.so.0]="libglib2.0-0"
)

SITE="$("$VPY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])' 2>/dev/null || echo "")"
SCAN_SOFILES=()
if [ -n "$SITE" ]; then
    for cand in \
        "$SITE/PyQt5/Qt5/plugins/platforms/libqxcb.so" \
        "$SITE/PyQt5/Qt5/lib/"libQt5*.so.5 \
        "$SITE/open3d/cpu/"pybind*.so \
        "$SITE/pyrealsense2/"pyrealsense2*.so
    do
        [ -f "$cand" ] && SCAN_SOFILES+=("$cand")
    done
fi

missing_pkgs=()
missing_sos=()
for sofile in "${SCAN_SOFILES[@]:-}"; do
    [ -f "$sofile" ] || continue
    while IFS= read -r soname; do
        [ -n "$soname" ] || continue
        pkg="${SO_TO_PKG[$soname]:-}"
        if [ -n "$pkg" ]; then
            case " ${missing_pkgs[*]:-} " in *" $pkg "*) ;; *) missing_pkgs+=("$pkg") ;; esac
        else
            case " ${missing_sos[*]:-} " in *" $soname "*) ;; *) missing_sos+=("$soname") ;; esac
        fi
    done < <(ldd "$sofile" 2>/dev/null | awk '/=> not found/ {print $1}')
done

if [ "${#missing_pkgs[@]}" -gt 0 ]; then
    warn "Native libraries are missing; the GUI will not open until they are installed."
    manual "# Missing shared libraries (Qt xcb / OpenGL / RealSense). Install them:
    sudo apt install ${missing_pkgs[*]}"
fi
if [ "${#missing_sos[@]}" -gt 0 ]; then
    warn "Missing shared libraries with no known apt package: ${missing_sos[*]}"
fi

# 4b. OpenCV's Qt plugin conflict. opencv-python bundles its own Qt
#     platform plugins, which hijack PyQt5's xcb plugin. The headless
#     build fixes it -- but that means removing a package, so we only
#     say so. (The app never calls cv2.imshow, so headless loses nothing.)
cv_builds="$("$VPY" -m pip list --format=freeze 2>/dev/null \
             | grep -E '^opencv-python(-headless)?==' | cut -d= -f1 | tr '\n' ' ' || true)"
if [ "$(printf '%s' "$cv_builds" | wc -w)" -gt 1 ]; then
    warn "Both OpenCV builds are installed ($cv_builds); they ship the same cv2 package and overwrite each other."
    manual "# Two OpenCV builds are fighting over the same cv2/ directory. Keep
# the headless one (the app never uses cv2's GUI functions):
    $VENV_DIR/bin/pip uninstall -y opencv-python
    $VENV_DIR/bin/pip install --force-reinstall opencv-python-headless"
elif [ -n "$SITE" ] && [ -d "$SITE/cv2/qt/plugins" ]; then
    warn "opencv-python bundles Qt plugins that can break the GUI ('Could not load the Qt platform plugin xcb')."
    manual "# Only if the GUI fails with a Qt xcb plugin error. Swaps OpenCV for
# the headless build INSIDE the venv (nothing system-wide; the app
# never uses cv2's GUI functions):
    $VENV_DIR/bin/pip uninstall -y opencv-python
    $VENV_DIR/bin/pip install opencv-python-headless"
fi

# 4c. ROS. Installing a ROS distro is a system change (apt repos, keys,
#     /opt/ros) and is out of scope for this script by design.
if [ "$WITH_ROS" = true ]; then
    ROS_SETUP=""
    for cand in /opt/ros/noetic/setup.bash /opt/ros/humble/setup.bash; do
        [ -f "$cand" ] && { ROS_SETUP="$cand"; break; }
    done
    if [ -n "$ROS_SETUP" ]; then
        log "Found ROS at $ROS_SETUP."
        if ! grep -qF "$ROS_SETUP" "$HOME/.bashrc" 2>/dev/null; then
            manual "# The gantry backend needs rospy, which only appears on PYTHONPATH
# once ROS is sourced. Do it per shell:
    source $ROS_SETUP
# ...or make it permanent yourself (this script does not edit ~/.bashrc):
    echo 'source $ROS_SETUP' >> ~/.bashrc"
        fi
    else
        log "No ROS distro found under /opt/ros (gantry backend stays offline; fine on a dev box)."
        manual "# Optional, lab rig only: ROS Noetic is a system install (apt repo +
# signing key + /opt/ros). Follow your lab SOP or:
#   http://wiki.ros.org/noetic/Installation/Ubuntu
# The app does NOT need rospy inside the venv -- it runs ROS work under
# whichever interpreter on the machine can already import it."
    fi

    # Which interpreters can import ROS right now? Report only.
    log "Interpreters that can import rospy (nothing is installed):"
    for candidate in "$VPY" /usr/bin/python3; do
        [ -x "$candidate" ] || continue
        if out="$("$candidate" -c 'import rospy, rosgraph; print(rospy.__file__)' 2>&1)"; then
            log "  OK    $candidate ($out)"
        else
            log "  --    $candidate cannot: $(printf '%s' "$out" | tail -1)"
        fi
    done

    # The PyPI 'rospy' is an unofficial shim, not ROS. Report, never remove:
    # on a lab machine ROS may legitimately be visible in the venv, and
    # uninstalling here would break a working rig.
    SHIM_FOUND=""
    for pkg in rospy rosgraph roslib rosmaster; do
        [ -n "$SITE" ] && [ -d "$SITE/$pkg" ] && SHIM_FOUND="$SHIM_FOUND $pkg"
    done
    if [ -n "$SHIM_FOUND" ]; then
        warn "ROS packages live in the venv's own site-packages:$SHIM_FOUND"
        manual "# Only if the gantry misbehaves AND these turn out to be the PyPI
# 'rospy' shim rather than a real ROS install (real rospy lives under
# /opt/ros). Removing packages is your call, not this script's:
    $VENV_DIR/bin/pip uninstall -y$SHIM_FOUND"
    fi
fi

# 4d. RealSense: is the machine in the state this project needs?
#     Required state (see docs/L515_SETUP.md for the full procedure):
#       - NO apt librealsense2* packages (they install 2.58.x + DKMS and
#         shadow the source build);
#       - a machine-wide librealsense built from source at RS_SDK_VERSION
#         with FORCE_RSUSB_BACKEND=ON, landing in /usr/local;
#       - the RealSense udev rules installed (else the camera is root-only);
#       - pyrealsense2 == RS_WHEEL_VERSION inside the venv.
#     Every one of those is a system change, so this only CHECKS and
#     reports. Nothing is installed, purged or downgraded here.

RS_STATE_OK=true
rs_problem() { RS_STATE_OK=false; err "RealSense: $1"; }

check_realsense_state() {
    local found_bin bin_ver lib_ver wheel_ver apt_pkgs

    # (a) apt-installed librealsense2 must be gone. dpkg-query is a
    #     read-only lookup -- nothing is installed or removed.
    if command -v dpkg-query >/dev/null 2>&1; then
        apt_pkgs="$(dpkg-query -W -f='${Package} ${Version}\n' 'librealsense2*' 2>/dev/null \
                    | awk 'NF >= 2 {print "      " $0}')"
        if [ -n "$apt_pkgs" ]; then
            rs_problem "apt packages are installed and will shadow the $RS_SDK_VERSION source build:"
            printf '%s\n' "$apt_pkgs" >&2
        fi
    fi

    # (b) machine-wide SDK version. Prefer the tool's own --version;
    #     fall back to the soname ldconfig knows about.
    found_bin="$(command -v rs-enumerate-devices 2>/dev/null || true)"
    if [ -z "$found_bin" ]; then
        rs_problem "no rs-enumerate-devices on PATH -- the machine-wide SDK is not installed."
    else
        case "$found_bin" in
            /usr/local/*) ;;
            *) rs_problem "rs-enumerate-devices is $found_bin, not /usr/local/bin/... -- that is a packaged SDK, not the source build." ;;
        esac
        bin_ver="$(timeout 15 "$found_bin" --version 2>&1 \
                   | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
        if [ -z "$bin_ver" ]; then
            lib_ver="$(ldconfig -p 2>/dev/null | grep -oE 'librealsense2\.so\.[0-9]+\.[0-9]+' \
                       | grep -oE '[0-9]+\.[0-9]+$' | head -1 || true)"
            [ -n "$lib_ver" ] && bin_ver="$lib_ver"
        fi
        if [ -z "$bin_ver" ]; then
            rs_problem "could not determine the machine-wide SDK version."
        elif [ "$bin_ver" != "$RS_SDK_VERSION" ] \
             && [ "$bin_ver" != "${RS_SDK_VERSION%.*}" ]; then
            rs_problem "machine-wide SDK reports $bin_ver, this project needs $RS_SDK_VERSION."
        else
            log "  OK    machine-wide librealsense $bin_ver ($found_bin)"
        fi
    fi

    # (c) udev rules -- without them the camera is only reachable as root.
    if [ ! -f /etc/udev/rules.d/99-realsense-libusb.rules ] \
       && ! ls /lib/udev/rules.d/*realsense* /usr/lib/udev/rules.d/*realsense* >/dev/null 2>&1; then
        rs_problem "udev rules are not installed -- the camera will only be reachable as root."
    fi

    # (d) the venv wheel must match the pinned release exactly.
    wheel_ver="$("$VPY" -c 'from importlib.metadata import version; print(version("pyrealsense2"))' 2>/dev/null || true)"
    if [ -z "$wheel_ver" ]; then
        rs_problem "pyrealsense2 is not installed in $VENV_DIR."
    elif [ "$wheel_ver" != "$RS_WHEEL_VERSION" ]; then
        rs_problem "venv has pyrealsense2 $wheel_ver, this project needs $RS_WHEEL_VERSION."
    else
        log "  OK    pyrealsense2 $wheel_ver in the venv"
    fi
}

if [ "$WITH_REALSENSE" = true ]; then
    log "Checking the RealSense stack (report only -- nothing is changed):"
    check_realsense_state
    if [ "$RS_STATE_OK" != true ]; then
        err "The RealSense stack is NOT in the state this project needs."
        err "Camera capture will misbehave (a 2.55+ SDK cannot see an L515 at all)."
        err "Fixing it means purging apt packages and building the SDK from"
        err "source, which changes your machine -- so this script will not do it."
        err "The full procedure is in docs/L515_SETUP.md, section"
        err "'Pinning the machine-wide SDK to $RS_SDK_VERSION on Linux'."
        manual "# Bring the RealSense stack to the pinned state ($RS_SDK_VERSION SDK +
# $RS_WHEEL_VERSION wheel). Unplug every RealSense camera first, then --
# full explanation and verification steps in docs/L515_SETUP.md:
    dpkg -l | grep librealsense                 # what is installed now
    sudo apt purge 'librealsense2*' && sudo apt autoremove
    sudo apt install -y git cmake build-essential libssl-dev \\
         libusb-1.0-0-dev libudev-dev pkg-config libgtk-3-dev libglfw3-dev
    git clone --branch v$RS_SDK_VERSION --depth 1 \\
        https://github.com/IntelRealSense/librealsense.git ~/librealsense-$RS_SDK_VERSION
    cd ~/librealsense-$RS_SDK_VERSION && sudo ./scripts/setup_udev_rules.sh
    sudo udevadm control --reload-rules && sudo udevadm trigger
    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release -DFORCE_RSUSB_BACKEND=ON \\
             -DBUILD_EXAMPLES=ON -DBUILD_GRAPHICAL_EXAMPLES=ON \\
             -DBUILD_PYTHON_BINDINGS=OFF
    make -j\$(nproc) && sudo make install && sudo ldconfig
# Then, for the venv wheel (this one is venv-local, safe to run yourself):
    $VENV_DIR/bin/pip install --force-reinstall pyrealsense2==$RS_WHEEL_VERSION"
    fi
fi

###############################################################################
# 5. Verify
###############################################################################

if [ "$DRY_RUN" = true ]; then
    log "[dry-run] skipping verification (nothing was installed)."
    print_manual_steps
    # The state checks above are real even in a dry run, so report the
    # off-pin RealSense stack in the exit code just like a full run does.
    [ "$WITH_REALSENSE" = true ] && [ "$RS_STATE_OK" != true ] && exit 2
    exit 0
fi

rc=0
verify || rc=$?
if [ "$WITH_REALSENSE" = true ] && [ "$RS_STATE_OK" != true ] && [ $rc -eq 0 ]; then
    # The venv is fine, but the camera stack is not in the pinned state.
    # Exit non-zero so this cannot be mistaken for a clean setup; pass
    # --no-realsense on a dev box with no camera to skip the check.
    rc=2
fi
print_manual_steps
exit $rc

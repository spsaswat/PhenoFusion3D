#!/usr/bin/env bash
# install/install_linux.sh
# Lab Linux installer for PhenoFusion3D (ROS + RealSense backend).
#
# Designed to take a freshly-imaged Ubuntu 20.04 / 22.04 lab machine and
# reach "the app launches" in one shot:
#   1. Pick a Python >= 3.10 interpreter (apt-installs python3.10 if none).
#   2. Create .venv-linux/ with --system-site-packages so the system rospy
#      is importable from inside the venv.
#   3. Install the project + Python deps in editable mode.
#   4. Install native runtime libs (Qt xcb / xkb / EGL / GL) detected by
#      ldd'ing the Qt platform plugin, so the first GUI launch does not
#      die with "Could not load the Qt platform plugin xcb".
#   5. Import each dependency to confirm the install is working.
#
# Prereqs (system, ROS-specific): ROS Noetic / Humble installed and
# sourced (`source /opt/ros/<distro>/setup.bash`), librealsense2 SDK
# runtime. ROS itself is out of scope for this installer because it
# touches global system state; install it per lab SOP first.
#
# Usage:
#   chmod +x install/install_linux.sh
#   ./install/install_linux.sh

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT_DIR="$(pwd)"

# All progress/diagnostic logging goes to stderr so that functions which
# return data via stdout (e.g. `PYTHON_BIN="$(pick_python)"`) are not
# polluted with log lines.
log() { printf '[install] %s\n' "$*" >&2; }
warn() { printf '[install] WARNING: %s\n' "$*" >&2; }
err() { printf '[install] ERROR: %s\n' "$*" >&2; }

###############################################################################
# 1. Python >= 3.10 selection (apt-install python3.10 as last resort).
###############################################################################

python_version_ok() {
    # Open3D / pyrealsense2 ship wheels only for 3.10-3.12 today, so we
    # cap selection there even though pyproject only floors at 3.10.
    local interp="$1"
    "$interp" - <<'PY' >/dev/null 2>&1
import sys
ver = sys.version_info[:2]
sys.exit(0 if (3, 10) <= ver <= (3, 12) else 1)
PY
}

apt_install() {
    if [ "$#" -eq 0 ]; then
        return 0
    fi
    if ! command -v apt-get >/dev/null 2>&1; then
        warn "apt-get not available; cannot auto-install: $*"
        return 1
    fi
    log "Installing system packages (may prompt for sudo): $*"
    if command -v sudo >/dev/null 2>&1; then
        sudo apt-get update -y
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
    else
        apt-get update -y
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
    fi
}

pick_python() {
    local venv_default="${PHENOFUSION_LINUX_VENV:-.venv-linux}"
    if [ -x "$venv_default/bin/python" ] && python_version_ok "$venv_default/bin/python"; then
        echo "$venv_default/bin/python"
        return 0
    fi
    local candidates=(python3.12 python3.11 python3.10 python3)
    local extra_dirs=(
        "$HOME/.local/share/uv/python"
        "$HOME/.cache/uv/python"
        "$HOME/.miniforge3/bin"
        "$HOME/miniforge3/bin"
    )
    for cand in "${candidates[@]}"; do
        if command -v "$cand" >/dev/null 2>&1 && python_version_ok "$cand"; then
            echo "$cand"
            return 0
        fi
    done
    if command -v uv >/dev/null 2>&1; then
        local uv_py
        uv_py="$(uv python find '>=3.10' 2>/dev/null || true)"
        if [ -n "$uv_py" ] && [ -x "$uv_py" ] && python_version_ok "$uv_py"; then
            echo "$uv_py"
            return 0
        fi
    fi
    for dir in "${extra_dirs[@]}"; do
        [ -d "$dir" ] || continue
        for cand in "$dir"/cpython-*/bin/python3 "$dir"/python3.1[0-9] "$dir"/python3; do
            if [ -x "$cand" ] && python_version_ok "$cand"; then
                echo "$cand"
                return 0
            fi
        done
    done
    return 1
}

apt_python_install_attempt() {
    local ver="$1"
    apt_install "python${ver}" "python${ver}-venv" "python${ver}-distutils" 2>/dev/null || true
    command -v "python${ver}" >/dev/null 2>&1 && python_version_ok "python${ver}"
}

install_uv() {
    if command -v uv >/dev/null 2>&1; then
        return 0
    fi
    log "Installing 'uv' (standalone Python downloader; no apt/sudo required)..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    else
        warn "Need curl or wget to install uv; please install one (e.g. 'sudo apt install curl')."
        return 1
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null 2>&1
}

install_python_via_uv() {
    # All progress goes to stderr; only the interpreter path is printed
    # on stdout for `$(install_python_via_uv)` to capture.
    install_uv || return 1
    log "Downloading CPython 3.11 via uv (this stays under $HOME, no sudo)..."
    if ! uv python install 3.11 >&2; then
        return 1
    fi
    local uv_py
    uv_py="$(uv python find 3.11 2>/dev/null || true)"
    if [ -n "$uv_py" ] && [ -x "$uv_py" ] && python_version_ok "$uv_py"; then
        echo "$uv_py"
        return 0
    fi
    return 1
}

PYTHON_BIN="${PHENOFUSION_PYTHON:-}"
if [ -n "$PYTHON_BIN" ]; then
    if ! python_version_ok "$PYTHON_BIN"; then
        err "PHENOFUSION_PYTHON=$PYTHON_BIN must be Python 3.10, 3.11, or 3.12."
        exit 1
    fi
else
    if ! PYTHON_BIN="$(pick_python)"; then
        warn "No Python >= 3.10 on PATH. Trying apt first..."
        installed_via_apt=false
        for ver in 3.10 3.11 3.12; do
            if apt_python_install_attempt "$ver"; then
                installed_via_apt=true
                break
            fi
        done
        if [ "$installed_via_apt" != true ] && command -v apt-get >/dev/null 2>&1; then
            warn "Plain apt could not provide Python >= 3.10; adding deadsnakes PPA..."
            apt_install software-properties-common || true
            if command -v sudo >/dev/null 2>&1; then
                sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
                sudo apt-get update -y >/dev/null 2>&1 || true
            else
                add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
                apt-get update -y >/dev/null 2>&1 || true
            fi
            for ver in 3.10 3.11 3.12; do
                if apt_python_install_attempt "$ver"; then
                    installed_via_apt=true
                    break
                fi
            done
        fi
        if ! PYTHON_BIN="$(pick_python)"; then
            warn "apt path failed. Falling back to uv (no apt, no sudo needed)..."
            if uv_py="$(install_python_via_uv)"; then
                PYTHON_BIN="$uv_py"
            fi
        fi
        if [ -z "${PYTHON_BIN:-}" ] || ! python_version_ok "$PYTHON_BIN"; then
            err "Could not find or install a Python >= 3.10 interpreter."
            err "Tried: existing PATH, apt python3.{10,11,12} (with deadsnakes PPA), uv."
            err "Install one manually and set PHENOFUSION_PYTHON=/path/to/python3.x"
            exit 1
        fi
    fi
fi

log "Using interpreter: $PYTHON_BIN ($("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])'))"

if ! "$PYTHON_BIN" -c "import venv" >/dev/null 2>&1; then
    pyver="$("$PYTHON_BIN" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
    warn "'$PYTHON_BIN -m venv' is unavailable; installing ${pyver}-venv..."
    apt_install "${pyver}-venv" || true
    if ! "$PYTHON_BIN" -c "import venv" >/dev/null 2>&1; then
        err "Cannot create venvs with $PYTHON_BIN. Install ${pyver}-venv and re-run."
        exit 1
    fi
fi

###############################################################################
# 2. Create the venv (always with --system-site-packages so rospy works).
###############################################################################

VENV_DIR="${PHENOFUSION_LINUX_VENV:-.venv-linux}"

venv_python_ok() {
    [ -x "$VENV_DIR/bin/python" ] || return 1
    "$VENV_DIR/bin/python" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >/dev/null 2>&1
}

if [ ! -f "$VENV_DIR/.has_system_site" ] || [ ! -f "$VENV_DIR/bin/activate" ] || ! venv_python_ok; then
    log "Creating venv at $VENV_DIR (Python $($PYTHON_BIN -c 'import sys; print(sys.version.split()[0])'), --system-site-packages)..."
    rm -rf "$VENV_DIR"
    "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"
    touch "$VENV_DIR/.has_system_site"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -e ".[ros]"

###############################################################################
# 3. Install native runtime libs needed by the Qt xcb platform plugin so
#    that `python main.py` does not die on first launch.
###############################################################################

declare -A SO_TO_PKG=(
    [libxcb-icccm.so.4]="libxcb-icccm4"
    [libxcb-keysyms.so.1]="libxcb-keysyms1"
    [libxcb-image.so.0]="libxcb-image0"
    [libxcb-render-util.so.0]="libxcb-render-util0"
    [libxcb-render.so.0]="libxcb-render0"
    [libxcb-shape.so.0]="libxcb-shape0"
    [libxcb-shm.so.0]="libxcb-shm0"
    [libxcb-sync.so.1]="libxcb-sync1"
    [libxcb-xfixes.so.0]="libxcb-xfixes0"
    [libxcb-xinerama.so.0]="libxcb-xinerama0"
    [libxcb-xkb.so.1]="libxcb-xkb1"
    [libxcb-randr.so.0]="libxcb-randr0"
    [libxcb-cursor.so.0]="libxcb-cursor0"
    [libxkbcommon.so.0]="libxkbcommon0"
    [libxkbcommon-x11.so.0]="libxkbcommon-x11-0"
    [libxcb.so.1]="libxcb1"
    [libxcb-util.so.1]="libxcb-util1"
    [libX11.so.6]="libx11-6"
    [libX11-xcb.so.1]="libx11-xcb1"
    [libXext.so.6]="libxext6"
    [libEGL.so.1]="libegl1"
    [libGL.so.1]="libgl1"
    [libGLX.so.0]="libglx0"
    [libGLdispatch.so.0]="libglvnd0"
    [libfontconfig.so.1]="libfontconfig1"
    [libfreetype.so.6]="libfreetype6"
    [libdbus-1.so.3]="libdbus-1-3"
    [libgomp.so.1]="libgomp1"
    [libstdc++.so.6]="libstdc++6"
    [libgcc_s.so.1]="libgcc-s1"
    [libGLU.so.1]="libglu1-mesa"
    [libusb-1.0.so.0]="libusb-1.0-0"
    [libpng16.so.16]="libpng16-16"
    [libz.so.1]="zlib1g"
    [libgthread-2.0.so.0]="libglib2.0-0"
    [libglib-2.0.so.0]="libglib2.0-0"
    [libgobject-2.0.so.0]="libglib2.0-0"
    [libgio-2.0.so.0]="libglib2.0-0"
)

PLUGIN_DIRS=()
for cand in "$VIRTUAL_ENV/lib/"python*"/site-packages/PyQt5/Qt5/plugins/platforms"; do
    [ -d "$cand" ] && PLUGIN_DIRS+=("$cand")
done

SCAN_SOFILES=()
for plugins_dir in "${PLUGIN_DIRS[@]:-}"; do
    for sofile in "$plugins_dir/libqxcb.so" "$plugins_dir/../../lib/libQt5XcbQpa.so.5"; do
        [ -f "$sofile" ] && SCAN_SOFILES+=("$sofile")
    done
done
for cand in "$VIRTUAL_ENV/lib/"python*"/site-packages/PyQt5/Qt5/lib/"libQt5*.so.5; do
    [ -f "$cand" ] && SCAN_SOFILES+=("$cand")
done
for cand in "$VIRTUAL_ENV/lib/"python*"/site-packages/open3d/cpu/"pybind*.so; do
    [ -f "$cand" ] && SCAN_SOFILES+=("$cand")
done
for cand in "$VIRTUAL_ENV/lib/"python*"/site-packages/pyrealsense2/"pyrealsense2*.so; do
    [ -f "$cand" ] && SCAN_SOFILES+=("$cand")
done

needs_pkgs=()
seen_pkgs=()
add_pkg() {
    local pkg="$1"
    for existing in "${seen_pkgs[@]:-}"; do
        [ "$existing" = "$pkg" ] && return 0
    done
    seen_pkgs+=("$pkg")
    needs_pkgs+=("$pkg")
}

for sofile in "${SCAN_SOFILES[@]:-}"; do
    [ -f "$sofile" ] || continue
    while IFS= read -r soname; do
        [ -n "$soname" ] || continue
        pkg="${SO_TO_PKG[$soname]:-}"
        if [ -n "$pkg" ]; then
            add_pkg "$pkg"
        else
            warn "Unknown apt package for missing library: $soname"
        fi
    done < <(ldd "$sofile" 2>/dev/null | awk '/=> not found/ {print $1}')
done

if [ "${#needs_pkgs[@]}" -gt 0 ]; then
    if apt_install "${needs_pkgs[@]}"; then
        log "Native runtime libraries installed."
    else
        warn "Could not auto-install: ${needs_pkgs[*]}"
        warn "Install manually: sudo apt install ${needs_pkgs[*]}"
    fi
fi

###############################################################################
# 4. Verify imports.
###############################################################################

log "Verifying imports..."
python - <<'PY'
import importlib, sys
ok = True
for mod in ("PyQt5", "open3d", "cv2", "numpy", "natsort"):
    try:
        importlib.import_module(mod); print(f"  OK  {mod}")
    except Exception as e:
        ok = False; print(f"  FAIL {mod}: {e}")

# rospy (system) and pyrealsense2 (pip) -- not fatal if missing on dev boxes.
for mod in ("rospy", "pyrealsense2"):
    try:
        importlib.import_module(mod); print(f"  OK  {mod}")
    except Exception as e:
        print(f"  WARN {mod}: {e} (capture backend may not work)")

sys.exit(0 if ok else 1)
PY

echo
log "Done. Launch the app with:"
echo "    bash launch.sh"
echo "  (or)"
echo "    source $VENV_DIR/bin/activate && python main.py"

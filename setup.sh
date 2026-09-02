#!/usr/bin/env bash
# Create the isolated PhenoFusion3D Linux UI venv and user launcher.
#
# This script NEVER installs system packages, ROS, RealSense drivers/SDKs,
# kernel modules, apt repositories, Python interpreters, or shell settings.
# Camera support is installed only as a Python package inside the project venv.
# Gantry support uses the lab's existing ROS installation through a helper
# process, so rospy does not belong in the GUI venv. A per-user desktop entry
# is installed under XDG_DATA_HOME so the app appears in Ubuntu Activities.
#
# Usage:
#   ./setup.sh             create/populate the venv, then verify camera + gantry
#   ./setup.sh --check     read-only verification; create or install nothing
#   ./setup.sh --verify-only   alias for --check

set -euo pipefail

cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"
VENV_DIR="${PHENOFUSION_VENV:-.venv-linux}"
CHECK_ONLY=false

for argument in "$@"; do
    case "$argument" in
        --check|--verify-only) CHECK_ONLY=true ;;
        -h|--help)
            sed -n '2,14p' "$0"
            exit 0
            ;;
        *)
            echo "[setup] ERROR: unknown option: $argument" >&2
            exit 2
            ;;
    esac
done

log()  { printf '[setup] %s\n' "$*" >&2; }
warn() { printf '[setup] WARNING: %s\n' "$*" >&2; }
err()  { printf '[setup] ERROR: %s\n' "$*" >&2; }

# The venv is the only project installation target and must remain directly
# below this checkout. The desktop entry is installed separately in the
# current user's XDG applications directory.
case "$VENV_DIR" in
    /*|../*|*/../*|*/..)
        err "PHENOFUSION_VENV must be a path inside $PROJECT_ROOT."
        exit 2
        ;;
esac

VENV_PYTHON="$VENV_DIR/bin/python"
CONSTRAINTS="$VENV_DIR/phenofusion-constraints.txt"

python_supported() {
    "$1" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    local candidate path
    if [ -n "${PHENOFUSION_PYTHON:-}" ]; then
        python_supported "$PHENOFUSION_PYTHON" && {
            printf '%s\n' "$PHENOFUSION_PYTHON"
            return 0
        }
        return 1
    fi
    for candidate in python3.11 python3.12 python3.10 python3; do
        path="$(command -v "$candidate" 2>/dev/null || true)"
        if [ -n "$path" ] && python_supported "$path"; then
            printf '%s\n' "$path"
            return 0
        fi
    done
    return 1
}

verify_import() {
    local module="$1"
    if "$VENV_PYTHON" -c "import $module" >/dev/null 2>&1; then
        printf '  OK    %s\n' "$module"
        return 0
    fi
    printf '  FAIL  %s\n' "$module"
    return 1
}

verify_gui_startup() {
    # Import checks alone do not exercise Qt platform-plugin selection.  Build
    # the real window offscreen so OpenCV/PyQt plugin conflicts fail setup
    # instead of aborting later when the operator launches the application.
    if QT_QPA_PLATFORM=offscreen "$VENV_PYTHON" - <<'PY' >/dev/null 2>&1
from main import create_application

application, window = create_application(["phenofusion3d-setup-check"])
assert application.platformName() == "offscreen"
window.close()
application.processEvents()
PY
    then
        printf '  OK    Qt application startup (offscreen)\n'
        return 0
    fi
    printf '  FAIL  Qt application startup (offscreen)\n'
    return 1
}

report_realsense_devices() {
    "$VENV_PYTHON" - <<'PY'
import os
import sys

# This validates pyrealsense2==2.54.2.5684 before touching USB discovery.
from capture.realsense_runtime import import_realsense

try:
    rs = import_realsense()
except RuntimeError as exc:
    print(f"  FAIL  {exc}")
    raise SystemExit(1)

devices = list(rs.context().query_devices())
selected = os.environ.get("PHENOFUSION_CAMERA_SERIAL", "").strip()
if not devices:
    print("  OK    RealSense SDK ready (no camera connected during setup)")
    raise SystemExit(0)

print(f"  OK    detected {len(devices)} RealSense camera(s):")
serials = []
for device in devices:
    def info(kind, fallback):
        try:
            return device.get_info(kind) if device.supports(kind) else fallback
        except Exception:
            return fallback

    name = info(rs.camera_info.name, "Unknown RealSense")
    serial = info(rs.camera_info.serial_number, "no serial")
    serials.append(serial)
    print(f"        - {name} (serial {serial})")

if selected:
    state = "detected" if selected in serials else "not currently detected"
    print(f"        PHENOFUSION_CAMERA_SERIAL={selected} ({state})")
elif len(devices) > 1:
    print("        Set PHENOFUSION_CAMERA_SERIAL before capture to choose one.")
PY
}

verify() {
    local failed=0 module
    if [ ! -x "$VENV_PYTHON" ]; then
        err "Project venv not found at $VENV_DIR. Run ./setup.sh first."
        return 2
    fi

    log "Verifying isolated GUI and camera packages..."
    for module in PyQt5 open3d cv2 numpy natsort tqdm pyqtgraph matplotlib; do
        verify_import "$module" || failed=1
    done
    report_realsense_devices || failed=1
    verify_import app.main_window || failed=1
    verify_gui_startup || failed=1

    log "Verifying the existing gantry ROS runtime (read-only)..."
    if "$VENV_PYTHON" - <<'PY'
from capture.ros_runtime import resolve
runtime = resolve(refresh=True)
print(f"  OK    ROS gantry runtime: {runtime.description}")
PY
    then
        :
    else
        failed=1
        warn "No compatible existing ROS runtime was found."
        warn "Source /opt/ros/noetic/setup.bash and the gantry catkin workspace."
        warn "For a non-standard workspace, set PHENOFUSION_ROS_WS=/path/to/workspace."
        warn "setup.sh will not install or alter ROS on the lab machine."
    fi

    # Go-to/home uses the custom message package; jog/stop only need core ROS.
    if "$VENV_PYTHON" - <<'PY' >/dev/null 2>&1
from capture.ros_runtime import CONTROL_MODULES, resolve
resolve(CONTROL_MODULES + ("position_controller_ros.msg",), refresh=True)
PY
    then
        printf '  OK    position_controller_ros (go-to/home enabled)\n'
    else
        warn "position_controller_ros was not found; jog/stop can work, but go-to/home needs the gantry workspace sourced."
    fi

    if [ "$failed" -ne 0 ]; then
        err "Verification failed. No system changes were attempted."
        return 2
    fi
    log "Verification passed for the GUI, camera, and gantry runtime."
}

install_user_launcher() {
    local data_home applications_dir desktop_file launcher_exec launcher_tmp
    data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
    applications_dir="$data_home/applications"
    desktop_file="$applications_dir/phenofusion3d.desktop"
    launcher_exec="$PROJECT_ROOT/$VENV_DIR/bin/phenofusion3d"

    if [ ! -x "$launcher_exec" ]; then
        err "Application entry point not found at $launcher_exec."
        return 2
    fi

    log "Installing Ubuntu Activities launcher at $desktop_file..."
    mkdir -p "$applications_dir"
    launcher_tmp="$(mktemp "$applications_dir/.phenofusion3d.desktop.XXXXXX")"

    if ! cat > "$launcher_tmp" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=PhenoFusion3D
GenericName=3D Plant Reconstruction
Comment=RGB-D capture, quality assessment, and 3D plant reconstruction
Exec="$launcher_exec"
TryExec=$launcher_exec
Path=$PROJECT_ROOT
Icon=applications-science
Terminal=false
Categories=Science;Education;Graphics;
Keywords=3D;reconstruction;plant;phenotyping;RGB-D;point-cloud;
StartupNotify=true
StartupWMClass=PhenoFusion3D
EOF
    then
        rm -f "$launcher_tmp"
        err "Could not write the Ubuntu Activities launcher."
        return 2
    fi

    chmod 0644 "$launcher_tmp"
    if command -v desktop-file-validate >/dev/null 2>&1; then
        if ! desktop-file-validate "$launcher_tmp"; then
            rm -f "$launcher_tmp"
            err "The generated Ubuntu Activities launcher is invalid."
            return 2
        fi
    fi
    mv -f "$launcher_tmp" "$desktop_file"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$applications_dir" >/dev/null 2>&1 || \
            warn "The desktop application cache could not be refreshed."
    fi
    log "Launcher installed. Search for PhenoFusion3D in Ubuntu Activities."
}

if [ "$CHECK_ONLY" = true ]; then
    verify
    exit $?
fi

if [ -e "$VENV_DIR" ] && [ ! -x "$VENV_PYTHON" ]; then
    err "$VENV_DIR already exists but is not a usable venv. It was left untouched."
    err "Move it yourself or choose another project path with PHENOFUSION_VENV."
    exit 2
fi

if [ ! -x "$VENV_PYTHON" ]; then
    if ! PYTHON_BIN="$(find_python)"; then
        err "An existing Python 3.10-3.12 with venv support is required."
        err "Install/choose it yourself, then set PHENOFUSION_PYTHON if needed."
        exit 2
    fi
    log "Creating isolated project venv at $VENV_DIR with $PYTHON_BIN..."
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        err "Could not create the venv. No system package was installed."
        err "Ensure the selected Python has its venv module, then retry."
        exit 2
    fi
else
    if ! python_supported "$VENV_PYTHON"; then
        err "Existing venv uses an unsupported Python. It was left untouched."
        err "Choose another path with PHENOFUSION_VENV."
        exit 2
    fi
    log "Reusing existing project venv at $VENV_DIR."
fi

# Pin every package already present in the venv. pip may add missing project
# requirements, but cannot silently upgrade/downgrade a working lab venv.
"$VENV_PYTHON" -m pip list --format=freeze --exclude-editable > "$CONSTRAINTS"

log "Installing the Linux GUI, camera binding, and bundled gantry bridge into the venv..."
"$VENV_PYTHON" -m pip install -c "$CONSTRAINTS" -e ".[lab]"

verify

install_user_launcher

log "Done. Open PhenoFusion3D from Ubuntu Activities, or launch with:"
printf '  source %s/bin/activate && python main.py\n' "$VENV_DIR"

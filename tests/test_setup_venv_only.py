"""Guardrails for the isolated venv and per-user Linux launcher."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup.sh"
LINUX_WRAPPER = ROOT / "install" / "install_linux.sh"
MAIN = ROOT / "main.py"
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"
REALSENSE_REQUIREMENT = "pyrealsense2==2.54.2.5684"


def _commands(text: str) -> str:
    """Discard comments and user-facing quoted text before command checks."""

    lines = []
    for raw in text.splitlines():
        line = re.sub(r"#.*$", "", raw)
        line = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', line)
        line = re.sub(r"'[^']*'", "''", line)
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def test_setup_has_no_system_mutation_commands():
    commands = _commands(SETUP.read_text())
    forbidden = [
        r"\bsudo\b",
        r"\bapt(?:-get)?\s+(?:install|update|remove)\b",
        r"\badd-apt-repository\b",
        r"\bapt-key\b",
        r"\budevadm\b",
        r"\bdpkg\b[^\n]*(?:-i|--install|--remove|--purge)",
        r">\s*/etc/",
        r"/usr/share/applications",
        r">>?\s*(?:\$HOME|~)/\.bashrc",
        r"\b(?:curl|wget)\b[^|]*\|\s*(?:sh|bash)\b",
    ]
    for pattern in forbidden:
        assert re.search(pattern, commands) is None, pattern


def test_setup_only_creates_an_isolated_project_venv():
    text = SETUP.read_text()
    assert '"$PYTHON_BIN" -m venv "$VENV_DIR"' in text
    assert "--system-site-packages" not in text
    assert not re.search(r"\brm\s+-rf\b", _commands(text))
    assert "PHENOFUSION_VENV must be a path inside" in text


def test_setup_installs_a_per_user_ubuntu_activities_launcher():
    text = SETUP.read_text()

    assert '${XDG_DATA_HOME:-$HOME/.local/share}' in text
    assert 'applications_dir="$data_home/applications"' in text
    assert 'desktop_file="$applications_dir/phenofusion3d.desktop"' in text
    assert '.phenofusion3d.XXXXXX.desktop' in text
    assert 'app_exec="$PROJECT_ROOT/$VENV_DIR/bin/phenofusion3d"' in text
    assert (
        'launcher_exec="$PROJECT_ROOT/$VENV_DIR/bin/phenofusion3d-activities"'
        in text
    )
    assert 'phenofusion3d = "main:main"' in PYPROJECT.read_text()
    assert "[Desktop Entry]" in text
    assert "Name=PhenoFusion3D" in text
    assert 'Exec="$launcher_exec"' in text
    assert "Terminal=false" in text
    assert "Icon=applications-science" in text
    assert "Categories=Science;DataVisualization;" in text
    assert text.rstrip().count("install_user_launcher") == 2


def test_activities_launcher_preserves_documented_hardware_settings():
    text = SETUP.read_text()

    assert (
        "for setting in PHENOFUSION_ROS_WS PHENOFUSION_CAMERA_SERIAL"
        in text
    )
    assert 'setting_value="${!setting:-}"' in text
    assert "printf -v setting_q '%q' \"$setting_value\"" in text
    assert "printf 'export %s=%s\\n' \"$setting\" \"$setting_q\"" in text
    assert "printf 'exec %s \"$@\"\\n' \"$app_exec_q\"" in text


def test_generated_activities_wrapper_forwards_setup_environment(tmp_path):
    text = SETUP.read_text()
    function_start = text.index("install_user_launcher() {")
    function_end = text.index('\n}\n\nif [ "$CHECK_ONLY"', function_start) + 2
    install_function = text[function_start:function_end]

    project_root = tmp_path / "checkout"
    bin_dir = project_root / ".venv-linux" / "bin"
    data_home = tmp_path / "xdg data"
    bin_dir.mkdir(parents=True)
    data_home.mkdir()
    app_exec = bin_dir / "phenofusion3d"
    shutil.copy2(shutil.which("env"), app_exec)

    ros_ws = str(tmp_path / "ROS workspace" / "with $dollar and 'quote'")
    camera_serial = "camera serial $42"
    environment = os.environ.copy()
    environment.update(
        PHENOFUSION_ROS_WS=ros_ws,
        PHENOFUSION_CAMERA_SERIAL=camera_serial,
    )
    command = f"""
set -euo pipefail
PROJECT_ROOT=$1
VENV_DIR=.venv-linux
XDG_DATA_HOME=$2
export PROJECT_ROOT VENV_DIR XDG_DATA_HOME
log() {{ :; }}
warn() {{ printf 'WARNING: %s\\n' "$*" >&2; }}
err() {{ printf 'ERROR: %s\\n' "$*" >&2; }}
{install_function}
install_user_launcher
"""
    subprocess.run(
        ["bash", "-c", command, "launcher-test", str(project_root), str(data_home)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    wrapper = bin_dir / "phenofusion3d-activities"
    completed = subprocess.run(
        [str(wrapper)],
        env={"PATH": os.defpath},
        check=True,
        capture_output=True,
        text=True,
    )
    launched_environment = dict(
        line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
    )
    assert launched_environment["PHENOFUSION_ROS_WS"] == ros_ws
    assert launched_environment["PHENOFUSION_CAMERA_SERIAL"] == camera_serial

    desktop_file = data_home / "applications" / "phenofusion3d.desktop"
    assert f'Exec="{wrapper}"' in desktop_file.read_text()


def test_check_mode_remains_read_only_and_skips_launcher_installation():
    text = SETUP.read_text()

    check_exit = text.index('if [ "$CHECK_ONLY" = true ]')
    launcher_call = text.rindex("\ninstall_user_launcher\n")
    assert check_exit < launcher_call


def test_setup_installs_camera_and_bundled_gantry_bridge_in_venv():
    text = SETUP.read_text()
    assert '-m pip install -c "$CONSTRAINTS" -e ".[lab]"' in text
    assert "pyrealsense2" in text
    assert "capture.ros_runtime" in text
    assert "pip install rospy" not in text
    assert "pip install --upgrade" not in text
    assert "pip uninstall" not in text
    assert "PHENOFUSION_CAMERA_SERIAL" in text
    assert "camera_info.serial_number" in text


def test_gui_initialises_qt_before_importing_opencv_consumers():
    text = MAIN.read_text()
    application = text.index("QApplication(")
    main_window = text.index("from app.main_window import MainWindow")

    assert application < main_window


def test_setup_smoke_checks_the_real_qt_application_startup():
    text = SETUP.read_text()

    assert "QT_QPA_PLATFORM=offscreen" in text
    assert "from main import create_application" in text
    assert "Qt application startup (offscreen)" in text


def test_realsense_dependency_is_exactly_pinned_everywhere():
    pyproject_specs = re.findall(r'"(pyrealsense2[^" ]*)"', PYPROJECT.read_text())
    assert pyproject_specs == [REALSENSE_REQUIREMENT] * 3

    requirements_specs = [
        line.strip()
        for line in REQUIREMENTS.read_text().splitlines()
        if line.strip().startswith("pyrealsense2")
    ]
    assert requirements_specs == [REALSENSE_REQUIREMENT]


def test_legacy_linux_installer_only_delegates_to_setup():
    commands = _commands(LINUX_WRAPPER.read_text())
    assert "exec ./setup.sh" in commands
    assert re.search(r"\bpip\b", commands) is None
    assert re.search(r"\bapt(?:-get)?\b", commands) is None


def test_setup_scripts_remain_executable():
    for script in (SETUP, LINUX_WRAPPER):
        assert script.stat().st_mode & stat.S_IXUSR

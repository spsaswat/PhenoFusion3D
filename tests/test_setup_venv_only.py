"""Guardrails ensuring Linux setup only changes the project venv."""

from __future__ import annotations

import re
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup.sh"
LINUX_WRAPPER = ROOT / "install" / "install_linux.sh"


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


def test_setup_installs_camera_and_bundled_gantry_bridge_in_venv():
    text = SETUP.read_text()
    assert '-m pip install -c "$CONSTRAINTS" -e ".[lab]"' in text
    assert "pyrealsense2" in text
    assert "capture.ros_runtime" in text
    assert "pip install rospy" not in text
    assert "pip install --upgrade" not in text
    assert "pip uninstall" not in text


def test_legacy_linux_installer_only_delegates_to_setup():
    commands = _commands(LINUX_WRAPPER.read_text())
    assert "exec ./setup.sh" in commands
    assert re.search(r"\bpip\b", commands) is None
    assert re.search(r"\bapt(?:-get)?\b", commands) is None


def test_setup_scripts_remain_executable():
    for script in (SETUP, LINUX_WRAPPER):
        assert script.stat().st_mode & stat.S_IXUSR

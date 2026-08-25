"""
tests/test_setup_scripts_no_system_changes.py
---------------------------------------------
Guard rail for the setup scripts: they may create and populate the
project venv, and nothing else.

setup.sh used to apt-install Python, Qt/X11/GL libraries, the Intel
librealsense SDK (repo + signing keys + dkms kernel modules) and ROS
Noetic, write /etc/udev rules, and append a `source
/opt/ros/noetic/setup.bash` line to the user's ~/.bashrc. On a shared
lab rig that silently replaced a pinned, working RealSense SDK and
mutated the machine behind the operator's back.

The rule now: no system mutation, and inside the venv install only what
is MISSING -- never upgrade, downgrade, uninstall or force-reinstall a
package that is already there. These tests fail if that creeps back.

Commands that appear inside *printed* help text (the MANUAL STEPS the
script tells the operator to run themselves) are fine; only executed
commands are forbidden, so every check here strips comments and the
quoted strings the script prints.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPTS = [REPO_ROOT / "setup.sh", REPO_ROOT / "install" / "install_linux.sh"]


def _executable_lines(script: Path) -> list[tuple[int, str]]:
    """Lines with comments and printed string literals removed.

    The scripts legitimately *print* `sudo apt install ...` as a manual
    step for the operator. That text lives in comments, in `err "..."` /
    `log "..."` calls, and in the `manual "..."` strings collected for
    the MANUAL STEPS block. None of it is executed, so it must not trip
    these tests -- but an actual `sudo apt-get install` must.
    """
    out: list[tuple[int, str]] = []
    in_manual_string = False
    for lineno, raw in enumerate(script.read_text().splitlines(), start=1):
        line = raw

        # Multi-line manual "..." / err "..." payloads: swallow until the
        # closing quote.
        if in_manual_string:
            if '"' in line:
                in_manual_string = False
            continue
        if re.match(r'^\s*(manual|log|warn|err|echo|printf)\s', line):
            if line.count('"') % 2 == 1:
                in_manual_string = True
            continue

        line = re.sub(r"#.*$", "", line)          # trailing comments
        line = re.sub(r'"[^"]*"', '""', line)      # double-quoted payloads
        line = re.sub(r"'[^']*'", "''", line)      # single-quoted payloads
        if line.strip():
            out.append((lineno, line))
    return out


# Commands that change the machine rather than the project directory.
FORBIDDEN = {
    "sudo": r"\bsudo\b",
    "apt-get": r"\bapt-get\b",
    "apt install": r"\bapt\s+(install|update|remove)\b",
    "add-apt-repository": r"\badd-apt-repository\b",
    "apt-key": r"\bapt-key\b",
    "udevadm": r"\budevadm\b",
    # `dpkg-query -W` / `dpkg -l` only LOOK at what is installed, which is
    # how the RealSense state check spots apt's librealsense2 packages.
    # Installing or removing with dpkg is what must never happen.
    "dpkg install/remove": r"\bdpkg\b[^\n]*(-i\b|--install\b|--purge\b|--remove\b|\s-r\b)",
    "tee into /etc": r"\btee\b[^|]*\s/etc/",
    "write to /etc": r">\s*/etc/",
    "write to ~/.bashrc": r">>?\s*(\$HOME|~)/\.bashrc",
    "curl-pipe-shell installer": r"\b(curl|wget)\b[^|]*\|\s*(sh|bash)\b",
    "uv python install": r"\buv\s+python\s+install\b",
}


@pytest.mark.parametrize("script", SETUP_SCRIPTS, ids=lambda p: p.name)
@pytest.mark.parametrize("label,pattern", sorted(FORBIDDEN.items()))
def test_script_does_not_mutate_the_system(script, label, pattern):
    offenders = [
        f"{script.name}:{lineno}: {text.strip()}"
        for lineno, text in _executable_lines(script)
        if re.search(pattern, text)
    ]
    assert not offenders, (
        f"{script.name} executes '{label}', which changes the machine. "
        "Setup may only create and populate the project venv; print the "
        "command as a MANUAL STEP instead.\n" + "\n".join(offenders)
    )


# pip operations that would move or remove a package that already works.
FORBIDDEN_PIP = {
    "pip install --upgrade": r"pip\s+install\b[^\n]*(--upgrade\b|-U\b)",
    "pip uninstall": r"pip\s+uninstall\b",
    "pip install --force-reinstall": r"pip\s+install\b[^\n]*--force-reinstall\b",
}


@pytest.mark.parametrize("script", SETUP_SCRIPTS, ids=lambda p: p.name)
@pytest.mark.parametrize("label,pattern", sorted(FORBIDDEN_PIP.items()))
def test_script_never_moves_an_installed_package(script, label, pattern):
    offenders = [
        f"{script.name}:{lineno}: {text.strip()}"
        for lineno, text in _executable_lines(script)
        if re.search(pattern, text)
    ]
    assert not offenders, (
        f"{script.name} runs '{label}'. Setup installs MISSING dependencies "
        "only -- a rig pinned to pyrealsense2 2.54 must stay on 2.54.\n"
        + "\n".join(offenders)
    )


def test_setup_installs_under_a_constraints_file():
    """Every pip install must carry `-c $CONSTRAINTS`.

    The constraints file pins every distribution the venv can already
    see to its installed version, which is what makes "install only what
    is missing" enforceable by pip itself rather than by convention.
    """
    text = (REPO_ROOT / "setup.sh").read_text()
    installs = [
        line.strip()
        for _lineno, line in _executable_lines(REPO_ROOT / "setup.sh")
        if re.search(r"pip\s+install\b", line) or re.search(r"run_pip\s+install\b", line)
    ]
    assert installs, "setup.sh no longer installs anything -- did the venv step get lost?"
    unconstrained = [line for line in installs if "-c " not in line]
    assert not unconstrained, (
        "pip install without a constraints file can upgrade an existing "
        "package:\n" + "\n".join(unconstrained)
    )
    assert 'CONSTRAINTS="$VENV_DIR/phenofusion-constraints.txt"' in text


def test_venv_is_the_only_thing_created():
    """The venv is created, and an unusable existing one is not deleted."""
    text = (REPO_ROOT / "setup.sh").read_text()
    assert "-m venv --system-site-packages" in text
    # A stale/incompatible venv is the operator's data: report, never rm -rf.
    assert not re.search(r"^\s*rm\s+-rf\s+\"?\$VENV_DIR", text, re.MULTILINE), (
        "setup.sh must not delete an existing venv on the operator's behalf."
    )


@pytest.mark.parametrize("script", SETUP_SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_executable(script):
    assert script.exists(), f"{script} is missing"
    assert script.stat().st_mode & stat.S_IXUSR, f"{script} is not executable"

"""
tests/test_stakeholder_backend.py
---------------------------------
The stakeholder script IS the capture backend, so what needs testing is
the plumbing wrapped around it, not the capture logic:

  - reading the script's hardcoded settings without being fooled by the
    commented-out ones it keeps around;
  - refusing to start with a per-interpreter account of what is missing
    (the "cannot import rospkg" failure gave no such account);
  - collecting the flat `rgb_<position>.png` files it writes into the
    `rgb/<i>.png` layout the rest of the app loads, in gantry order;
  - forwarding Stop as Ctrl-C.

A stand-in script reproduces the real one's output shape so this runs
with no camera, no gantry and no ROS.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import threading
import time

import pytest

from capture.base import CaptureParams
from capture import stakeholder_capture as sc


STAND_IN = textwrap.dedent('''
    """Mimics rospy_thread_fin_1.py's output shape: prints the gantry
    position each loop and writes position-named frames."""
    import os, sys, time
    from datetime import datetime

    save_fold_p = './data/test_plant_' + datetime.now().strftime("%Y%m%d%H%M%S") + '/'
    os.makedirs(save_fold_p, exist_ok=True)
    for name in ("kd_intrinsics.txt", "kdc_intrinsics.txt"):
        open(save_fold_p + name, "w").write("{}")

    # Same loop shape as the real script, so the end position is
    # discoverable the same way.
    try:
        current_position = 0.0
        while True:
            current_position += 0.26
            print(current_position, flush=True)
            key = int(current_position * 10**6)
            open(save_fold_p + 'rgb_%d.png' % key, 'wb').write(b'rgb')
            open(save_fold_p + 'depth_%d.png' % key, 'wb').write(b'depth')
            if current_position != 0.0 and current_position >= 0.78:
                print('All images captured, now saving', flush=True)
                break
            time.sleep(float(os.environ.get("STANDIN_DELAY", "0")))
    except KeyboardInterrupt:
        sys.exit(0)
''')


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """Point the backend at the stand-in, run by this interpreter."""
    script = tmp_path / "rospy_thread_fin_1.py"
    script.write_text(STAND_IN)
    monkeypatch.setattr(sc, "find_script", lambda: str(script))
    monkeypatch.setattr(
        sc, "choose_runtime",
        lambda path: (sys.executable, dict(os.environ), "stand-in"))
    return str(script)


def _run(tmp_path, backend):
    params = CaptureParams(out_root=str(tmp_path / "captures"))
    result = {}
    backend.start(
        params,
        on_done=lambda d, n: result.update(out_dir=d, frames=n),
        on_error=lambda m: result.update(error=m),
    )
    return result


# --------------------------------------------------------------- settings

def test_reads_the_scripts_real_settings():
    """Its commented-out history must not be mistaken for live settings."""
    settings = sc.script_parameters(sc.find_script())
    assert settings["end position (m)"] == "0.78"     # not the commented 0.006
    assert settings["velocity (m/s)"] == "0.038"
    assert settings["camera serial"] == "128422272123"


def test_imports_are_read_from_the_script():
    """Parsed, not hardcoded, so editing the script cannot desynchronise
    the preflight from what it actually needs."""
    modules = sc.script_imports(sc.find_script())
    assert {"rospy", "pyrealsense2", "cv2", "position_controller_ros"} <= set(modules)


def test_preflight_names_every_interpreter_and_its_fix(monkeypatch):
    """The old failure was a bare 'cannot import rospkg'."""
    monkeypatch.setattr(sc, "_candidate_interpreters", lambda: ["/usr/bin/python3"])
    monkeypatch.setattr(sc, "_setup_bash_scripts", lambda: [])
    monkeypatch.setattr(sc, "_probe_imports",
                        lambda interp, mods, env: {"rospkg": "ModuleNotFoundError"})

    with pytest.raises(RuntimeError) as excinfo:
        sc.choose_runtime(sc.find_script())

    message = str(excinfo.value)
    assert "/usr/bin/python3" in message
    assert "rospkg" in message
    assert "pip install rospkg" in message      # the actual fix, not just the symptom


# ------------------------------------------------------------- the run

def test_frames_land_in_the_layout_the_app_loads(tmp_path, stand_in):
    backend = sc.StakeholderScriptCapture()
    result = _run(tmp_path, backend)

    assert "error" not in result, result.get("error")
    out_dir = result["out_dir"]
    assert result["frames"] == 3

    for index in range(3):
        assert os.path.isfile(os.path.join(out_dir, "rgb", f"{index}.png"))
        assert os.path.isfile(os.path.join(out_dir, "depth", f"{index}.png"))
    # Intrinsics are lifted out of the script's own folder.
    assert os.path.isfile(os.path.join(out_dir, "kdc_intrinsics.txt"))


def test_frame_index_follows_gantry_order(tmp_path, stand_in):
    """The script names files by position, not by frame number, so the
    ordering has to be reconstructed -- and recorded."""
    backend = sc.StakeholderScriptCapture()
    result = _run(tmp_path, backend)

    session = json.load(open(os.path.join(result["out_dir"], "session.json")))
    positions = [session["frame_positions"][str(i)] for i in range(3)]
    assert positions == sorted(positions), "frames must be in gantry order"
    assert positions[0] == pytest.approx(0.26, abs=1e-6)
    assert positions[-1] == pytest.approx(0.78, abs=1e-6)
    assert session["backend"] == "stakeholder"


def test_progress_is_driven_by_the_printed_position(tmp_path, stand_in):
    backend = sc.StakeholderScriptCapture()
    seen = []
    params = CaptureParams(out_root=str(tmp_path / "captures"))
    backend.start(params, on_progress=lambda i, t: seen.append((i, t)))

    assert seen, "the script's position output produced no progress"
    assert seen[-1] == (100, 100), f"should finish at 100%: {seen[-1]}"


def test_stop_interrupts_the_script(tmp_path, stand_in, monkeypatch):
    monkeypatch.setenv("STANDIN_DELAY", "5")
    backend = sc.StakeholderScriptCapture()

    threading.Timer(2.0, backend.stop).start()
    started = time.monotonic()
    _run(tmp_path, backend)
    elapsed = time.monotonic() - started

    assert elapsed < 15, f"Stop did not interrupt the script ({elapsed:.1f}s)"
    assert backend._process.poll() is not None, "the script is still running"

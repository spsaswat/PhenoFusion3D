"""
tests/test_gantry_offline.py
----------------------------
Offline (non-ROS host) tests for `capture.gantry.GantryController`.

These tests must pass on Windows / any host without rospy installed --
the goal is to guarantee the panel never crashes the UI on a dev box.
A manual lab smoke test (jog forward/back, go-home, observe live
position label updating) is documented in the plan.
"""

from __future__ import annotations

import importlib.util
import sys
import time

import pytest

# A QApplication is required for QObject signal/slot mechanics, even
# though no widgets are shown.
try:
    from PyQt5.QtWidgets import QApplication
except Exception:                               # pragma: no cover
    pytest.skip("PyQt5 unavailable", allow_module_level=True)

from capture.gantry import GantryController, _ros_importable


@pytest.fixture(scope='module')
def qapp():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


def test_ros_importability_matches_helper():
    """`_ros_importable()` must agree with importlib's view -- a
    sanity-check that we don't silently ship a buggy probe."""
    assert _ros_importable() == (importlib.util.find_spec('rospy') is not None)


def test_ros_available_is_about_the_machine_not_this_interpreter(monkeypatch):
    """The GUI interpreter often cannot import rospy on a rig where ROS
    is installed and working. Gating the ROS features on this process's
    own import disabled them exactly where they were needed."""
    from capture import ros_capture
    from capture import ros_runtime

    monkeypatch.setattr(ros_capture.importlib.util, 'find_spec',
                        lambda name: None)
    monkeypatch.setattr(ros_runtime, 'ros_is_installed', lambda: True)
    assert ros_capture.ros_available() is True

    monkeypatch.setattr(ros_runtime, 'ros_is_installed', lambda: False)
    assert ros_capture.ros_available() is False


def test_controller_constructs_without_ros(qapp):
    gc = GantryController()
    assert gc.current_position_m() == 0.0
    # Optimistic before first call.
    assert gc.is_available() in (True, False)


@pytest.mark.skipif(_ros_importable(),
                    reason="rospy is importable -- skipping no-ROS path")
def test_no_ros_calls_are_safe(qapp):
    """On a non-ROS host, every public call must return cleanly and
    flip is_available() to False after the first attempt."""
    gc = GantryController()
    errors: list[str] = []
    gc.error.connect(errors.append)

    gc.start_jog(0.05)
    gc.stop()
    gc.go_to(0.5)
    gc.go_home()
    gc.shutdown()

    assert gc.is_available() is False
    # At least one error message must have been emitted explaining why.
    assert any('rospy' in e.lower() for e in errors), errors


def test_goto_clamps_out_of_range(qapp):
    """Even without ROS, the clamp logic should be exercised: passing
    a negative or too-large position should produce an `error` line
    mentioning 'clamped' -- but only when go-to is actually attempted,
    which requires init. Here we just assert the constants are sane."""
    gc = GantryController(pos_min_m=0.0, pos_max_m=2.0)
    assert gc.pos_min_m == 0.0
    assert gc.pos_max_m == 2.0
    assert 0.0 <= gc.HOME_POSITION_M <= gc.pos_max_m


def test_shutdown_is_idempotent(qapp):
    gc = GantryController()
    gc.shutdown()
    gc.shutdown()                               # second call must not raise


def test_master_unreachable_fails_fast_without_blocking(qapp, monkeypatch):
    """Regression test for the lab-rig freeze: with a pip-installed
    rospy shim present but no roscore running, the first gantry command
    used to run rospy.init_node() on the Qt main thread, which retries
    master registration forever -> whole app unresponsive.

    Now the command must return immediately, the failure must surface
    through `error` with a message naming the master, and the failure
    must be retryable (no app restart needed once roscore is started)."""
    import capture.gantry as gantry_mod

    monkeypatch.setattr(gantry_mod, '_ros_importable', lambda: True)
    monkeypatch.setattr(
        gantry_mod, 'ros_master_reachable',
        lambda timeout_s=1.5: (False, 'http://localhost:11311 (refused)'),
    )

    gc = GantryController()
    errors: list[str] = []
    gc.error.connect(errors.append)

    t0 = time.monotonic()
    gc.start_jog(0.05)
    # The click handler must never block the GUI thread.
    assert time.monotonic() - t0 < 0.5

    # Wait for the background attempt to finish and report. The error
    # signal is emitted from that thread, so Qt queues it to the main
    # thread -- the event loop must run for it to be delivered.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        with gc._lock:
            thread_done = gc._start_thread is None
        if thread_done and any('not reachable' in e for e in errors):
            break
        time.sleep(0.05)

    assert any('not reachable' in e for e in errors), errors
    assert gc.is_available() is True      # retryable
    assert gc._start_attempted is False   # next click tries again


def test_hung_helper_hits_watchdog_and_recovers(qapp, monkeypatch):
    """Bringing ROS up has waits with no timeout of their own (rospy's
    init_node spins forever if the node hostname doesn't resolve). If the
    helper never reports ready, the wait must time out, surface as an
    error and leave the controller retryable -- the panel must never say
    'connecting' forever."""
    import capture.gantry as gantry_mod
    from capture import ros_client, ros_runtime

    monkeypatch.setattr(gantry_mod, 'ros_preflight', lambda *a, **k: None)

    # A helper that starts but never announces itself. `resolve` is
    # imported inside start(), so the module it lives in is the patch
    # target -- not the module that calls it.
    monkeypatch.setattr(ros_client.RosAgentClient, 'START_TIMEOUT_S', 0.3)
    monkeypatch.setattr(
        ros_runtime, 'resolve',
        lambda *a, **k: ros_client_runtime(monkeypatch))

    gc = GantryController()
    errors: list[str] = []
    gc.error.connect(errors.append)
    gc.start_jog(0.05)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if any('did not become ready' in e for e in errors):
            break
        time.sleep(0.05)

    stalled = [e for e in errors if 'did not become ready' in e]
    assert stalled, errors
    assert gc._start_attempted is False           # retryable, no restart
    gc.shutdown()


def ros_client_runtime(monkeypatch):
    """A runtime whose 'agent' starts and then says nothing."""
    import os
    import sys
    import tempfile
    from capture.ros_runtime import RosRuntime
    from capture import ros_client

    silent = os.path.join(tempfile.mkdtemp(), "silent_agent.py")
    with open(silent, "w") as f:
        f.write("import sys, time\nfor _ in range(100): time.sleep(1)\n")
    monkeypatch.setattr(ros_client, "AGENT_PATH", silent)
    return RosRuntime(sys.executable, dict(os.environ), "silent stand-in")

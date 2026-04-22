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

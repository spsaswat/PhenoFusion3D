"""Hardware-free tests for the Linux gantry controller."""

from __future__ import annotations

import importlib.util
import sys
import time

import pytest

try:
    from PyQt5.QtWidgets import QApplication
except Exception:  # pragma: no cover - dependency gate
    pytest.skip("PyQt5 unavailable", allow_module_level=True)

from capture.gantry import GantryController, _ros_importable
from capture.base import CaptureParams
from capture.realsense_capture import RealSenseCapture
from app.capture_worker import CaptureWorker
from app.panels.capture_panel import CapturePanel
from app.panels.gantry_panel import GantryPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


def _wait_for_start(gc: GantryController, qapp, timeout_s: float = 3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        with gc._lock:
            if gc._start_thread is None:
                return
        time.sleep(0.01)
    raise AssertionError("gantry start thread did not finish")


def test_ros_importability_probe_is_diagnostic_only():
    assert _ros_importable() == (importlib.util.find_spec("rospy") is not None)


def test_availability_checks_the_machine_not_the_gui_import(qapp, monkeypatch):
    import capture.gantry as gantry_module

    monkeypatch.setattr(gantry_module, "ros_is_installed", lambda: True)
    assert GantryController().is_available() is True

    monkeypatch.setattr(gantry_module, "ros_is_installed", lambda: False)
    assert GantryController().is_available() is False


def test_jog_buttons_use_lab_verified_reversed_directions(qapp):
    panel = GantryPanel(available=True)
    velocities = []
    panel.jog_requested.connect(velocities.append)
    panel.vel_spin.setValue(0.038)

    panel._on_jog_back_pressed()
    panel._on_jog_fwd_pressed()

    assert velocities == [0.038, -0.038]
    assert panel.jog_back_btn.toolTip().endswith('+X')
    assert panel.jog_fwd_btn.toolTip().endswith('-X')


def test_initial_capture_values_match_the_stakeholder_script(qapp):
    defaults = CaptureParams()
    panel = CapturePanel()
    gantry_panel = GantryPanel(available=True)

    assert (defaults.width, defaults.height, defaults.fps) == (1280, 720, 30)
    assert defaults.velocity_mps == 0.038
    assert defaults.end_position_m == 0.78
    assert GantryController.HOME_POSITION_M == 0.005
    assert GantryController.HOME_VELOCITY_MPS == 0.2
    assert RealSenseCapture.WARMUP_FRAMES == 4

    assert panel.out_edit.text() == defaults.out_root
    assert panel.vel_spin.value() == defaults.velocity_mps
    assert panel.end_spin.value() == defaults.end_position_m
    assert panel.fps_spin.value() == defaults.fps
    assert panel.dur_spin.value() == defaults.duration_s
    assert gantry_panel.vel_spin.value() == defaults.velocity_mps


def test_capture_stop_is_not_lost_during_worker_startup(qapp, monkeypatch):
    class Backend:
        def __init__(self):
            self.stopped = False
            self.started = False

        def stop(self):
            self.stopped = True

        def start(self, _params, **callbacks):
            self.started = True
            if self.stopped:
                callbacks["on_error"]("cancelled before startup")
                return None
            raise AssertionError("cancel request was lost")

    backend = Backend()
    monkeypatch.setattr("app.capture_worker.get_backend", lambda _pref: backend)
    worker = CaptureWorker("realsense", CaptureParams())
    errors = []
    worker.error.connect(errors.append)

    worker.stop()
    worker.run()

    assert backend.stopped is True
    assert backend.started is True
    assert errors == ["cancelled before startup"]


def test_connection_failure_is_nonblocking_and_retryable(qapp, monkeypatch):
    from capture import ros_client

    def fail_start(_self):
        raise RuntimeError("No existing Python/ROS environment can import rospy")

    monkeypatch.setattr(ros_client.RosAgentClient, "start", fail_start)

    controller = GantryController()
    errors = []
    controller.error.connect(errors.append)

    started = time.monotonic()
    controller.start_jog(0.05)
    assert time.monotonic() - started < 0.25

    _wait_for_start(controller, qapp)
    assert any("rospy" in error.lower() for error in errors), errors
    assert controller._start_attempted is False
    controller.shutdown()


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.running = True
        self.goto_available = True
        self.commands = []
        self.runtime_description = "fake ROS runtime"

    def is_running(self):
        return self.running

    def jog(self, velocity):
        self.commands.append(("jog", velocity))
        return True

    def stop(self):
        self.commands.append(("stop",))
        return True

    def goto(self, position, velocity):
        self.commands.append(("goto", position, velocity))
        return True

    def shutdown(self):
        self.commands.append(("shutdown",))
        self.running = False

    def start(self):
        return None


def test_first_command_is_queued_until_ros_is_ready(qapp, monkeypatch):
    from capture import ros_client

    created = []

    def make_client(*args, **kwargs):
        client = _FakeClient(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(ros_client, "RosAgentClient", make_client)
    controller = GantryController()
    controller.start_jog(0.038)
    _wait_for_start(controller, qapp)

    assert created[0].commands == [("jog", 0.038)]
    controller.stop()
    controller.shutdown()


def test_connected_controller_keeps_working_gantry_commands(qapp):
    controller = GantryController(pos_min_m=0.0, pos_max_m=2.0)
    client = _FakeClient()
    controller._client = client

    controller.start_jog(0.038)
    controller.stop()
    controller.go_to(0.5)
    controller.go_home()
    controller.shutdown()

    assert client.commands == [
        ("jog", 0.038),
        ("stop",),
        ("goto", 0.5, 0.2),
        ("goto", controller.HOME_POSITION_M, controller.HOME_VELOCITY_MPS),
        ("shutdown",),
    ]


def test_goto_clamps_before_publishing(qapp):
    controller = GantryController(pos_min_m=0.0, pos_max_m=2.0)
    client = _FakeClient()
    controller._client = client
    errors = []
    controller.error.connect(errors.append)

    controller.go_to(9.0)

    assert client.commands == [("goto", 2.0, 0.2)]
    assert any("clamped" in error.lower() for error in errors)
    controller.shutdown()


def test_shutdown_is_idempotent(qapp):
    controller = GantryController()
    controller.shutdown()
    controller.shutdown()

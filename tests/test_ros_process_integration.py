"""Offline regression tests for the ROS/PyQt process boundary."""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from PyQt5.QtWidgets import QApplication
except Exception:  # pragma: no cover
    pytest.skip("PyQt5 unavailable", allow_module_level=True)

from app.capture_worker import CaptureWorker
from app.panels.capture_panel import CapturePanel
from capture.base import CaptureParams
from capture.realsense_capture import RealSenseCapture
from capture.ros_runtime import EVENT_PREFIX, parse_event
from capture.ros_capture import RosCapture, RosCaptureError


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


def test_json_event_protocol_ignores_normal_ros_output():
    assert parse_event("roslaunch chatter") is None
    assert parse_event(EVENT_PREFIX + '{"event":"ready","port":1}') == {
        "event": "ready",
        "port": 1,
    }
    assert parse_event(EVENT_PREFIX + "not-json") is None


def test_ros_helpers_remain_python_38_syntax_compatible():
    capture_dir = Path(__file__).resolve().parents[1] / "capture"
    for name in ("ros_capture_process.py", "ros_gantry_process.py"):
        source = (capture_dir / name).read_text(encoding="utf-8")
        ast.parse(source, filename=name, feature_version=(3, 8))


def test_stakeholder_motion_contract_is_kept_in_capture_helper():
    helper = (
        Path(__file__).resolve().parents[1] / "capture" / "ros_capture_process.py"
    ).read_text(encoding="utf-8")
    assert '"/cmd_vel"' in helper
    assert '"/joint_states"' in helper
    assert '"/go_to_position_server/goal"' in helper
    assert "capture_one(align)" in helper
    assert "go_home()" in helper
    assert 'KNOWN_SERIALS = ("128422272123", "017322071325", "f1230450")' in helper
    assert "strict=args.strict_serial" in helper


def test_auto_capture_falls_back_without_emitting_failure(qapp, monkeypatch, tmp_path):
    calls: list[str] = []

    class FailedRos:
        name = "ros"
        session = SimpleNamespace(n_frames=0)

        def start(self, _params, on_progress=None, on_error=None):
            calls.append("ros")
            on_error("ROS init failed")
            return None

        def stop(self):
            pass

    class WorkingCamera:
        name = "realsense"
        session = SimpleNamespace(n_frames=7)

        def start(self, _params, on_progress=None, on_error=None):
            calls.append("realsense")
            on_progress(7, 7)
            return str(tmp_path / "capture")

        def stop(self):
            pass

    def backend(preference):
        return FailedRos() if preference == "auto" else WorkingCamera()

    monkeypatch.setattr("app.capture_worker.get_backend", backend)
    worker = CaptureWorker("auto", CaptureParams(out_root=str(tmp_path)))
    statuses: list[str] = []
    errors: list[str] = []
    finished: list[tuple[str, int]] = []
    worker.status.connect(statuses.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda path, count: finished.append((path, count)))

    worker.run()

    assert calls == ["ros", "realsense"]
    assert not errors
    assert finished == [(str(tmp_path / "capture"), 7)]
    assert any("camera-only" in status for status in statuses)


def test_explicit_ros_failure_does_not_silently_fallback(qapp, monkeypatch):
    class FailedRos:
        name = "ros"
        session = SimpleNamespace(n_frames=0)

        def start(self, _params, on_progress=None, on_error=None):
            on_error("ROS init failed")
            return None

        def stop(self):
            pass

    monkeypatch.setattr("app.capture_worker.get_backend", lambda _pref: FailedRos())
    worker = CaptureWorker("ros", CaptureParams())
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()
    assert errors == ["ROS init failed"]


def test_auto_does_not_restart_camera_after_partial_gantry_scan(qapp, monkeypatch):
    calls: list[str] = []

    class PartialRos:
        name = "ros"
        frames_captured = 3
        session = SimpleNamespace(n_frames=3)

        def start(self, _params, on_progress=None, on_error=None):
            calls.append("ros")
            on_error("ROS master disconnected after frame 3")
            return None

        def stop(self):
            pass

    monkeypatch.setattr("app.capture_worker.get_backend", lambda _pref: PartialRos())
    worker = CaptureWorker("auto", CaptureParams())
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()
    assert calls == ["ros"]
    assert errors == ["ROS master disconnected after frame 3"]


def test_capture_panel_emits_selected_camera_serial(qapp):
    panel = CapturePanel()
    panel.serial_combo.setCurrentText("017322071325")
    requests: list[tuple] = []
    panel.capture_requested.connect(lambda *args: requests.append(args))
    panel._on_capture()
    assert requests
    assert requests[0][2] == "017322071325"


def test_realsense_explicit_serial_is_strict(monkeypatch):
    first, second = object(), object()

    class Stream:
        color = "color"
        depth = "depth"

    class Context:
        def query_devices(self):
            return [first, second]

    class FakeRs:
        stream = Stream()

        @staticmethod
        def context():
            return Context()

    backend = RealSenseCapture()
    monkeypatch.setattr(backend, "_has_stream", lambda *_args: True)
    monkeypatch.setattr(
        backend,
        "_device_serial",
        lambda device, _rs: "one" if device is first else "two",
    )
    monkeypatch.setattr(backend, "_device_label", lambda *_args: "fake camera")
    assert backend._select_device(FakeRs, "two") is second
    with pytest.raises(RuntimeError, match="missing"):
        backend._select_device(FakeRs, "missing")


def test_hung_ros_helper_is_terminated_within_timeout(monkeypatch, tmp_path):
    fake_helper = tmp_path / "hung_ros.py"
    fake_helper.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(
        "capture.ros_capture.helper_path", lambda _name: str(fake_helper)
    )
    monkeypatch.setenv("PHENOFUSION_ROS_TIMEOUT", "0.01")
    backend = RosCapture()
    backend.out_dir = str(tmp_path)

    started = time.monotonic()
    with pytest.raises(RosCaptureError) as failure:
        backend._run_helper(sys.executable, CaptureParams(), lambda *_args: None)

    assert failure.value.stage == "startup_timeout"
    assert time.monotonic() - started < 4.0


def test_l515_sdk_is_exactly_pinned_in_active_install_paths():
    root = Path(__file__).resolve().parents[1]
    exact_pin = "pyrealsense2==2.54.2.5684"
    for relative_path in (
        "constraints.txt",
        "requirements.txt",
        "pyproject.toml",
        "setup.sh",
    ):
        content = (root / relative_path).read_text(encoding="utf-8")
        assert exact_pin in content, relative_path
        assert "pyrealsense2>=2.54" not in content, relative_path

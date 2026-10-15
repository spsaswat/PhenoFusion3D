"""D405 forward pass plus L515 return pass, with fake cameras and gantry."""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

from capture.base import CaptureParams
from capture.realsense_capture import RealSenseCapture
from capture.ros_capture import (
    RETURN_DIR_NAME,
    ReturnPassSession,
    RosCapture,
)
from capture.ros_client import HOME_POSITION_M


D405 = ("Intel RealSense D405", "d405-serial")
L515 = ("Intel RealSense L515", "l515-serial")
DEPTH_SCALES = {D405[1]: 0.0001, L515[1]: 0.00025}


class _Device:
    def __init__(self, name, serial):
        self.name = name
        self.serial = serial

    def supports(self, _kind):
        return True

    def get_info(self, kind):
        return self.name if kind == "name" else self.serial


def _rs_with(devices, pipeline_factory=None):
    class Rs:
        class camera_info:
            name = "name"
            serial_number = "serial"

        class stream:
            color = "color"
            depth = "depth"

        class format:
            rgb8 = "rgb8"

        @staticmethod
        def context():
            class Context:
                @staticmethod
                def query_devices():
                    return [_Device(*device) for device in devices]

            return Context()

        @staticmethod
        def pipeline():
            return pipeline_factory()

        @staticmethod
        def align(_stream):
            return _Align()

    return Rs


class _Frame:
    def __init__(self, data):
        self.data = data

    def get_data(self):
        return self.data


class _Frames:
    def get_color_frame(self):
        return _Frame(np.ones((2, 2, 3), dtype=np.uint8))

    def get_depth_frame(self):
        return _Frame(np.ones((2, 2), dtype=np.uint16))


class _Align:
    @staticmethod
    def process(frames):
        return frames


class _Profile:
    def __init__(self, depth_scale):
        self.depth_scale = depth_scale

    def get_device(self):
        profile = self

        class Device:
            @staticmethod
            def first_depth_sensor():
                class Sensor:
                    @staticmethod
                    def get_depth_scale():
                        return profile.depth_scale

                return Sensor()

        return Device()


# ---------------------------------------------------------------- pairing

@pytest.mark.parametrize(
    ("devices", "paired"),
    [
        ([D405, L515], True),
        ([L515, D405], True),
        ([D405, L515, ("Intel RealSense D435", "d435")], True),
        ([D405], False),
        ([L515], False),
        ([D405, ("Intel RealSense D405", "other"), L515], False),
        ([D405, L515, ("Intel RealSense L515", "other")], False),
    ],
)
def test_return_camera_pairs_one_d405_with_one_l515(
    monkeypatch, devices, paired
):
    monkeypatch.delenv("PHENOFUSION_CAMERA_SERIAL", raising=False)
    monkeypatch.setattr(RealSenseCapture, "_has_stream", lambda *_args: True)
    camera = RealSenseCapture()

    return_camera = RosCapture()._pair_return_camera(_rs_with(devices), camera)

    if paired:
        assert camera.serial_number == D405[1]
        assert return_camera.serial_number == L515[1]
    else:
        assert return_camera is None
        assert camera.serial_number is None


def test_a_requested_serial_keeps_the_single_camera_pass(monkeypatch):
    monkeypatch.setenv("PHENOFUSION_CAMERA_SERIAL", L515[1])
    monkeypatch.setattr(RealSenseCapture, "_has_stream", lambda *_args: True)
    camera = RealSenseCapture()

    assert RosCapture()._pair_return_camera(_rs_with([D405, L515]), camera) is None
    assert camera.serial_number == L515[1]


def test_cameras_without_depth_are_not_paired(monkeypatch):
    monkeypatch.delenv("PHENOFUSION_CAMERA_SERIAL", raising=False)
    monkeypatch.setattr(
        RealSenseCapture,
        "_has_stream",
        lambda _self, device, _rs, stream: not (
            device.serial == L515[1] and stream == "depth"
        ),
    )
    camera = RealSenseCapture()

    assert RosCapture()._pair_return_camera(_rs_with([D405, L515]), camera) is None


def test_enumeration_failure_leaves_selection_to_the_camera(monkeypatch):
    monkeypatch.delenv("PHENOFUSION_CAMERA_SERIAL", raising=False)

    class Rs:
        @staticmethod
        def context():
            raise RuntimeError("usb enumeration failed")

    camera = RealSenseCapture()
    assert RosCapture()._pair_return_camera(Rs, camera) is None
    assert camera.serial_number is None


# ---------------------------------------------------------------- full pass

def _run_dual_capture(
    tmp_path,
    monkeypatch,
    return_failure=None,
    goto_available=True,
):
    """Drive RosCapture.start with a D405 and an L515 connected.

    return_failure: None, "camera" (L515 cannot start), "silent" (L515
    fails with an empty message), "stall" (gantry does not move after go-to),
    "stop" (operator stops during the return pass) or "stop_warmup" (operator
    stops while the L515 warms up, before any return motion).
    """
    monkeypatch.delenv("PHENOFUSION_CAMERA_SERIAL", raising=False)
    events = []
    progress = []
    errors = []
    capture = RosCapture()

    class Gantry:
        def __init__(self, on_position=None, **_kwargs):
            self.on_position = on_position
            self.goto_available = goto_available
            self.returning = False
            self.position = 0.0
            Gantry.instance = self

        def move(self, position):
            self.position = position
            self.on_position(position)

        def start(self):
            self.move(HOME_POSITION_M)

        @staticmethod
        def wait_for_position(_timeout):
            return True

        @staticmethod
        def is_running():
            return True

        def start_moving(self, _velocity):
            self.move(2.0)

        @staticmethod
        def stop_moving():
            events.append("gantry stopped")

        @staticmethod
        def shutdown():
            events.append("gantry shutdown")

        def go_home(self):
            events.append("gantry home")
            self.move(HOME_POSITION_M)
            return True

        def goto(self, position, velocity):
            events.append(("gantry goto", position, velocity))
            self.returning = return_failure != "stall"
            return True

    class Pipeline:
        def __init__(self):
            self.serial = None
            self.frames = 0

        def wait_for_frames(self):
            gantry = getattr(Gantry, "instance", None)  # None during D405 warm-up
            if gantry is not None and gantry.returning:
                gantry.move(max(HOME_POSITION_M, gantry.position - 0.5))
                if return_failure == "stop" and self.frames == 5:
                    capture.stop()
            if (
                return_failure == "stop_warmup"
                and self.serial == L515[1]
                and self.frames == 1
            ):
                capture.stop()
            self.frames += 1
            return _Frames()

        def stop(self):
            events.append(("camera stopped", self.serial))

    def start_pipeline(self, pipeline, device, _rs, _params):
        if device == L515[1]:
            events.append((
                "forward session on disk",
                os.path.isfile(os.path.join(capture.out_dir, "session.json")),
            ))
            if return_failure == "camera":
                raise RuntimeError("L515 would not start")
            if return_failure == "silent":
                raise RuntimeError()
        pipeline.serial = device
        events.append(("camera started", device))
        return _Profile(DEPTH_SCALES[device]), "bgr8"

    def read_intrinsics(self, _profile, _rs):
        return {
            "kdc_intrinsics.txt": {"camera": self.serial_number},
            "kd_intrinsics.txt": {"camera": self.serial_number},
        }

    import capture.realsense_capture as realsense_capture

    original_write = realsense_capture.write_frame_batch

    def write_frame_batch(out_dir, pairs, cv2_module):
        events.append(("frames saved", out_dir, len(pairs)))
        original_write(out_dir, pairs, cv2_module=cv2_module)

    monkeypatch.setattr("capture.ros_capture.ros_available", lambda: True)
    monkeypatch.setattr(
        "capture.ros_capture.import_realsense",
        lambda: _rs_with([D405, L515], Pipeline),
    )
    monkeypatch.setattr("capture.ros_client.RosAgentClient", Gantry)
    monkeypatch.setattr(RealSenseCapture, "_has_stream", lambda *_args: True)
    monkeypatch.setattr(
        RealSenseCapture, "_select_device", lambda self, _rs: self.serial_number
    )
    monkeypatch.setattr(
        RealSenseCapture,
        "_device_label",
        lambda _self, device, _rs: f"camera {device}",
    )
    monkeypatch.setattr(RealSenseCapture, "_start_pipeline", start_pipeline)
    monkeypatch.setattr(
        RealSenseCapture, "_apply_visual_preset", lambda *_args: None
    )
    monkeypatch.setattr(
        RealSenseCapture, "_update_session_from_profile", lambda *_args: None
    )
    monkeypatch.setattr(RealSenseCapture, "_read_intrinsics", read_intrinsics)
    monkeypatch.setattr(realsense_capture, "write_frame_batch", write_frame_batch)
    if return_failure == "stall":
        clock = iter(float(tick) for tick in range(1000))
        monkeypatch.setattr(
            "capture.ros_capture.time.monotonic", lambda: next(clock)
        )

    out_dir = capture.start(
        CaptureParams(out_root=str(tmp_path), width=2, height=2, fps=30),
        on_progress=lambda current, total: progress.append((current, total)),
        on_error=errors.append,
    )
    assert errors == []
    return out_dir, events, progress


def _session(directory):
    with open(directory / "session.json") as session_file:
        return json.load(session_file)


def _intrinsics_camera(directory):
    with open(directory / "kdc_intrinsics.txt") as intrinsics_file:
        return json.load(intrinsics_file)["camera"]


def _pngs(directory):
    return sorted(path.name for path in directory.iterdir())


def test_d405_scans_out_and_l515_scans_home_then_saves_there(
    tmp_path, monkeypatch
):
    out_dir, events, progress = _run_dual_capture(tmp_path, monkeypatch)
    forward = tmp_path / out_dir
    back = forward / RETURN_DIR_NAME

    started = [event for event in events if event[0] == "camera started"]
    assert started == [("camera started", D405[1]), ("camera started", L515[1])]

    # Forward pass is stopped and saved before the L515 starts.
    d405_saved = events.index(("frames saved", str(forward), 1))
    assert events.index(("camera stopped", D405[1])) < d405_saved
    assert d405_saved < events.index(("camera started", L515[1]))

    # The return trip runs at the scan velocity, and the L515 batch is saved
    # only after the camera has stopped at home.
    goto = events.index(("gantry goto", HOME_POSITION_M, 0.038))
    l515_saved = events.index(("frames saved", str(back), 4))
    assert events.index(("camera started", L515[1])) < goto
    assert goto < events.index(("camera stopped", L515[1])) < l515_saved
    assert l515_saved < events.index("gantry shutdown")
    assert "gantry home" not in events

    assert progress == [
        (1, 0), (1, -1),
        (0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (4, -1),
    ]
    assert ("forward session on disk", True) in events

    assert _pngs(forward / "rgb") == ["0.png"]
    assert _pngs(back / "rgb") == ["0.png", "1.png", "2.png", "3.png"]
    assert _pngs(back / "depth") == ["0.png", "1.png", "2.png", "3.png"]
    assert _intrinsics_camera(forward) == D405[1]
    assert _intrinsics_camera(back) == L515[1]

    forward_session = _session(forward)
    assert forward_session["n_frames"] == 1
    assert forward_session["termination_reason"] == "endpoint_reached"
    assert forward_session["home_returned"] is True

    return_session = _session(back)
    assert return_session["n_frames"] == 4
    assert return_session["camera"] == f"camera {L515[1]}"
    assert return_session["error"] is None
    assert return_session["termination_reason"] == "home_reached"
    assert return_session["home_returned"] is True
    assert return_session["end_position_m"] == HOME_POSITION_M
    assert return_session["depth_scale_m"] == DEPTH_SCALES[L515[1]]
    assert return_session["frame_positions"] == {
        "0": 1.5, "1": 1.0, "2": 0.5, "3": HOME_POSITION_M,
    }


def test_an_l515_that_will_not_start_keeps_the_d405_pass_and_goes_home(
    tmp_path, monkeypatch
):
    out_dir, events, progress = _run_dual_capture(
        tmp_path, monkeypatch, return_failure="camera"
    )
    forward = tmp_path / out_dir
    back = forward / RETURN_DIR_NAME

    assert _pngs(forward / "rgb") == ["0.png"]
    assert _session(forward)["home_returned"] is True
    assert "gantry home" in events
    assert not any(event[0] == "gantry goto" for event in events)
    assert progress == [(1, 0), (1, -1), (0, 0)]

    return_session = _session(back)
    assert return_session["n_frames"] == 0
    assert return_session["termination_reason"] == "failed"
    assert "L515 would not start" in return_session["error"]
    assert _pngs(back / "rgb") == []


def test_without_go_to_the_return_pass_is_skipped_but_home_is_still_tried(
    tmp_path, monkeypatch
):
    out_dir, events, _progress = _run_dual_capture(
        tmp_path, monkeypatch, goto_available=False
    )
    back = tmp_path / out_dir / RETURN_DIR_NAME

    assert not any(event[0] == "camera started" and event[1] == L515[1]
                   for event in events if isinstance(event, tuple))
    assert "gantry home" in events
    assert "position_controller_ros" in _session(back)["error"]


def test_a_stalled_return_falls_back_to_the_proven_go_home(
    tmp_path, monkeypatch
):
    """A slow go-to the controller ignores must not strand the gantry."""
    out_dir, events, _progress = _run_dual_capture(
        tmp_path, monkeypatch, return_failure="stall"
    )
    forward = tmp_path / out_dir
    back = forward / RETURN_DIR_NAME

    goto = events.index(("gantry goto", HOME_POSITION_M, 0.038))
    home = events.index("gantry home")
    assert goto < home < events.index(("frames saved", str(back), 4))

    return_session = _session(back)
    assert return_session["termination_reason"] == "failed"
    assert "did not move toward home" in return_session["error"]
    assert return_session["home_returned"] is True
    assert return_session["n_frames"] == len(_pngs(back / "rgb")) == 4

    forward_session = _session(forward)
    assert forward_session["home_returned"] is True
    assert forward_session["termination_reason"] == "endpoint_reached"


def test_stopping_during_the_return_pass_saves_it_without_going_home(
    tmp_path, monkeypatch
):
    out_dir, events, _progress = _run_dual_capture(
        tmp_path, monkeypatch, return_failure="stop"
    )
    forward = tmp_path / out_dir
    back = forward / RETURN_DIR_NAME

    assert "gantry home" not in events
    goto = events.index(("gantry goto", HOME_POSITION_M, 0.038))
    assert "gantry stopped" in events[goto:]
    return_session = _session(back)
    assert return_session["termination_reason"] == "user_stop"
    assert return_session["home_returned"] is False
    assert return_session["n_frames"] == 2
    assert _pngs(back / "rgb") == ["0.png", "1.png"]
    assert _session(forward)["home_returned"] is False


def test_stopping_while_the_l515_warms_up_never_starts_the_return_motion(
    tmp_path, monkeypatch
):
    out_dir, events, progress = _run_dual_capture(
        tmp_path, monkeypatch, return_failure="stop_warmup"
    )
    back = tmp_path / out_dir / RETURN_DIR_NAME

    assert ("camera started", L515[1]) in events
    assert not any(event[0] == "gantry goto" for event in events)
    assert "gantry home" not in events
    assert progress[-1] == (0, 0)

    return_session = _session(back)
    assert return_session["termination_reason"] == "user_stop"
    assert return_session["n_frames"] == 0


def test_a_failure_without_a_message_is_still_reported_as_failed(
    tmp_path, monkeypatch
):
    out_dir, events, _progress = _run_dual_capture(
        tmp_path, monkeypatch, return_failure="silent"
    )
    return_session = _session(tmp_path / out_dir / RETURN_DIR_NAME)

    assert return_session["termination_reason"] == "failed"
    assert return_session["error"] == "RuntimeError"
    assert "gantry home" in events


def test_return_pass_session_keeps_the_capture_session_schema():
    session = ReturnPassSession(
        backend="ros",
        started_at="now",
        width=1280,
        height=720,
        fps=30,
        velocity_mps=0.038,
        gantry_axis=0,
        end_position_m=HOME_POSITION_M,
    )
    assert session.frame_positions == {}
    assert session.camera == ""
    assert session.error is None
    assert session.depth_scale_m is None


# ---------------------------------------------------------------- panel

@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("PyQt5.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication(sys.argv[:1])


def _write_return_session(out_dir, **fields):
    back = out_dir / RETURN_DIR_NAME
    back.mkdir()
    (back / "session.json").write_text(json.dumps(fields))
    return back


def test_panel_reports_nothing_extra_for_a_single_camera_capture(tmp_path):
    pytest.importorskip("PyQt5.QtWidgets")
    from app.panels.capture_panel import CapturePanel

    assert CapturePanel._return_pass_summary(str(tmp_path)) == ""


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (
            {"n_frames": 4, "termination_reason": "home_reached", "error": None},
            "L515 return pass: 4 frames -> ",
        ),
        (
            {"n_frames": 2, "termination_reason": "buffer_limit", "error": None},
            "L515 return pass stopped at the safe RAM/disk limit. "
            "Saved 2 frames -> ",
        ),
        (
            {
                "n_frames": 0,
                "termination_reason": "failed",
                "error": "L515 would not start",
            },
            "WARNING: L515 return pass failed (L515 would not start); "
            "saved 0 frames -> ",
        ),
        (
            {"n_frames": 0, "termination_reason": "failed", "error": ""},
            "WARNING: L515 return pass failed (unknown error); "
            "saved 0 frames -> ",
        ),
        (
            {"n_frames": 2, "termination_reason": "user_stop", "error": None},
            "L515 return pass stopped early by the operator. "
            "Saved 2 frames -> ",
        ),
    ],
)
def test_panel_summarises_the_return_pass(tmp_path, fields, expected):
    pytest.importorskip("PyQt5.QtWidgets")
    from app.panels.capture_panel import CapturePanel

    back = _write_return_session(tmp_path, **fields)
    assert CapturePanel._return_pass_summary(str(tmp_path)) == f" {expected}{back}"


def test_finished_message_includes_the_return_pass(qapp, tmp_path):
    from app.panels.capture_panel import CapturePanel

    (tmp_path / "session.json").write_text(json.dumps({
        "termination_reason": "endpoint_reached", "home_returned": True,
    }))
    back = _write_return_session(
        tmp_path, n_frames=4, termination_reason="home_reached", error=None
    )
    panel = CapturePanel()
    panel.on_finished(str(tmp_path), 1)

    assert panel.status_lbl.text() == (
        f"Done. 1 frames -> {tmp_path} L515 return pass: 4 frames -> {back}"
    )


def test_stop_is_available_again_while_the_return_pass_records(qapp):
    from app.panels.capture_panel import CapturePanel

    panel = CapturePanel()
    panel.set_running(True)
    panel.on_progress(1, 0)
    assert panel.stop_btn.isEnabled()
    panel.on_progress(1, -1)    # forward pass saving
    assert not panel.stop_btn.isEnabled()
    panel.on_progress(1, 0)     # L515 return pass recording
    assert panel.stop_btn.isEnabled()
    panel.on_progress(4, -1)    # return pass saving
    assert not panel.stop_btn.isEnabled()

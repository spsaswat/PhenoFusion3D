"""Hardware-free checks for the shared L515/D405 RealSense safeguards."""

from __future__ import annotations

import numpy as np
import pytest

from capture.base import CaptureBackend, CaptureParams, ensure_capture_capacity
from capture.realsense_capture import (
    CaptureFrameBuffer,
    RealSenseCapture,
    capture_frame_pair,
    write_frame_batch,
    write_frame_pair,
)
from capture.ros_capture import RosCapture
from capture.realsense_runtime import (
    REQUIRED_PYREALSENSE_VERSION,
    import_realsense,
    validate_version,
)


def test_exact_shared_camera_version_is_accepted():
    assert validate_version("2.54.2.5684") == REQUIRED_PYREALSENSE_VERSION


@pytest.mark.parametrize("version", ["2.54.2", "2.55.1", "2.58.3.10794"])
def test_every_other_camera_version_is_rejected(version):
    with pytest.raises(RuntimeError, match="required 2.54.2.5684"):
        validate_version(version)


def test_native_import_failure_keeps_offline_workflows_available(monkeypatch):
    monkeypatch.setattr(
        "capture.realsense_runtime.validate_version",
        lambda: REQUIRED_PYREALSENSE_VERSION,
    )

    def fail_import(_name):
        raise ImportError("could not initialize udev monitor")

    monkeypatch.setattr("capture.realsense_runtime.importlib.import_module", fail_import)

    with pytest.raises(RuntimeError, match="GUI.*existing datasets.*remain available"):
        import_realsense()


class _Sensor:
    def __init__(self):
        self.value = None

    def set_option(self, _option, value):
        self.value = value


class _Device:
    def __init__(self, name, serial):
        self.name = name
        self.serial = serial
        self.sensor = _Sensor()

    def supports(self, _kind):
        return True

    def get_info(self, kind):
        return self.name if kind == "name" else self.serial

    def first_depth_sensor(self):
        return self.sensor


class _Profile:
    def __init__(self, device):
        self.device = device

    def get_device(self):
        return self.device


class _Rs:
    class camera_info:
        name = "name"
        serial_number = "serial"

    class option:
        visual_preset = "visual_preset"


@pytest.mark.parametrize(
    ("model", "expected"),
    [("Intel RealSense L515", 5), ("Intel RealSense D405", 4)],
)
def test_model_specific_visual_preset(model, expected):
    device = _Device(model, "serial")
    RealSenseCapture()._apply_visual_preset(_Profile(device), _Rs)
    assert device.sensor.value == expected


def test_missing_intrinsics_fail_the_capture_instead_of_reporting_success():
    class BrokenProfile:
        @staticmethod
        def get_stream(_kind):
            raise RuntimeError("profile unavailable")

    class Rs(_Rs):
        class stream:
            depth = "depth"
            color = "color"

    with pytest.raises(RuntimeError, match="required camera intrinsics"):
        RealSenseCapture()._read_intrinsics(BrokenProfile(), Rs)


def test_intrinsics_write_failure_is_reported(tmp_path):
    capture = RealSenseCapture()
    capture.out_dir = str(tmp_path / "missing" / "capture")

    with pytest.raises(RuntimeError, match="required camera intrinsics"):
        capture._save_intrinsics({"kdc_intrinsics.txt": {"K": []}})


def test_requested_serial_selects_the_matching_rgbd_device(monkeypatch):
    devices = [_Device("Intel RealSense L515", "l515"),
               _Device("Intel RealSense D405", "d405")]

    class Context:
        def query_devices(self):
            return devices

    class Rs(_Rs):
        class stream:
            color = "color"
            depth = "depth"

        @staticmethod
        def context():
            return Context()

    capture = RealSenseCapture(serial_number="l515")
    monkeypatch.setattr(capture, "_has_stream", lambda *_args: True)
    assert capture._select_device(Rs).serial == "l515"


def test_one_rgbd_device_is_selected_automatically(monkeypatch):
    device = _Device("Intel RealSense D435", "d435")

    class Rs(_Rs):
        class stream:
            color = "color"
            depth = "depth"

        class Context:
            @staticmethod
            def query_devices():
                return [device]

        @staticmethod
        def context():
            return Rs.Context()

    capture = RealSenseCapture()
    monkeypatch.setattr(capture, "_has_stream", lambda *_args: True)
    assert capture._select_device(Rs) is device


def test_multiple_devices_require_an_explicit_serial(monkeypatch):
    devices = [
        _Device("Intel RealSense L515", "l515"),
        _Device("Intel RealSense D405", "d405"),
    ]

    class Rs(_Rs):
        class stream:
            color = "color"
            depth = "depth"

        class Context:
            @staticmethod
            def query_devices():
                return devices

        @staticmethod
        def context():
            return Rs.Context()

    capture = RealSenseCapture()
    monkeypatch.setattr(capture, "_has_stream", lambda *_args: True)
    with pytest.raises(RuntimeError, match="PHENOFUSION_CAMERA_SERIAL") as excinfo:
        capture._select_device(Rs)
    assert "l515" in str(excinfo.value)
    assert "d405" in str(excinfo.value)


def test_environment_serial_selects_among_multiple_devices(monkeypatch):
    devices = [
        _Device("Intel RealSense L515", "l515"),
        _Device("Intel RealSense D405", "d405"),
    ]

    class Rs(_Rs):
        class stream:
            color = "color"
            depth = "depth"

        class Context:
            @staticmethod
            def query_devices():
                return devices

        @staticmethod
        def context():
            return Rs.Context()

    monkeypatch.setenv("PHENOFUSION_CAMERA_SERIAL", "d405")
    capture = RealSenseCapture()
    monkeypatch.setattr(capture, "_has_stream", lambda *_args: True)
    assert capture._select_device(Rs).serial == "d405"


def test_ros_capture_has_no_default_hardware_serial():
    assert RosCapture().serial_number is None


def test_ros_stop_immediately_stops_active_gantry_motion():
    class Gantry:
        stopped = False

        def stop_moving(self):
            self.stopped = True

    capture = RosCapture()
    gantry = Gantry()
    capture._gantry = gantry

    capture.stop()

    assert capture._stop_flag is True
    assert gantry.stopped is True


def test_output_directories_do_not_collide_within_the_same_second(
    tmp_path, monkeypatch
):
    class FixedNow:
        @staticmethod
        def strftime(_format):
            return "20260901120000"

    class FixedDatetime:
        @staticmethod
        def now():
            return FixedNow()

    monkeypatch.setattr("capture.base.datetime", FixedDatetime)
    first = CaptureBackend._make_out_dir(str(tmp_path))
    second = CaptureBackend._make_out_dir(str(tmp_path))

    assert first != second
    assert second.endswith("-1")


def test_capture_capacity_rejects_an_unsafe_memory_request(tmp_path):
    out_dir = CaptureBackend._make_out_dir(str(tmp_path))
    params = CaptureParams(max_buffer_gib=0.000001)

    with pytest.raises(RuntimeError, match="safe RAM/disk limit"):
        ensure_capture_capacity(out_dir, params, 2, 100, 100)


def test_frame_buffer_stops_before_exceeding_its_limit():
    color = np.ones((2, 2, 3), dtype=np.uint8)
    depth = np.ones((2, 2), dtype=np.uint16)
    pair_bytes = color.nbytes + depth.nbytes
    buffer = CaptureFrameBuffer(pair_bytes)

    assert buffer.append((color, depth)) is True
    assert buffer.append((color.copy(), depth.copy())) is False
    assert len(buffer) == 1


class _ImageWriter:
    def __init__(self, fail_kind=None):
        self.fail_kind = fail_kind

    def imwrite(self, path, _image):
        with open(path, "wb") as image_file:
            image_file.write(b"image")
        kind = "depth" if ".depth.part.png" in path else "RGB"
        return kind != self.fail_kind


class _SecondDepthWriteFails(_ImageWriter):
    def imwrite(self, path, image):
        super().imwrite(path, image)
        return ".1.depth.part.png" not in path


class _Frame:
    def __init__(self, data):
        self.data = data

    def get_data(self):
        return self.data


class _Frames:
    def __init__(self, color, depth):
        self.color = _Frame(color)
        self.depth = _Frame(depth)

    def get_color_frame(self):
        return self.color

    def get_depth_frame(self):
        return self.depth


class _Align:
    @staticmethod
    def process(frames):
        return frames


def test_capture_pair_is_copied_into_memory_without_writing():
    color_source = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    depth_source = np.arange(4, dtype=np.uint16).reshape(2, 2)

    class Pipeline:
        @staticmethod
        def wait_for_frames():
            return _Frames(color_source, depth_source)

    class Rs:
        class format:
            rgb8 = "rgb8"

    color, depth = capture_frame_pair(
        Pipeline(), _Align(), "bgr8", Rs, cv2_module=object()
    )
    color_source.fill(0)
    depth_source.fill(0)

    assert color.any()
    assert depth.any()


def test_realsense_stops_camera_before_saving_buffered_frames(
    tmp_path, monkeypatch
):
    capture = RealSenseCapture()
    events = []
    progress = []
    color = np.ones((2, 2, 3), dtype=np.uint8)
    depth = np.ones((2, 2), dtype=np.uint16)

    class Pipeline:
        calls = 0

        def wait_for_frames(self):
            self.calls += 1
            if self.calls == capture.WARMUP_FRAMES + 1:
                capture._stop_flag = True
            return _Frames(color, depth)

        @staticmethod
        def stop():
            events.append("camera stopped")

    pipeline = Pipeline()

    class Rs:
        class stream:
            color = "color"

        class format:
            rgb8 = "rgb8"

        @staticmethod
        def pipeline():
            return pipeline

        @staticmethod
        def align(_stream):
            return _Align()

    monkeypatch.setattr("capture.realsense_capture.import_realsense", lambda: Rs)
    monkeypatch.setattr(capture, "_select_device", lambda _rs: object())
    monkeypatch.setattr(
        capture,
        "_start_pipeline",
        lambda _pipeline, _device, _rs, _params: (object(), "bgr8"),
    )
    monkeypatch.setattr(capture, "_apply_visual_preset", lambda *_args: None)
    monkeypatch.setattr(capture, "_update_session_from_profile", lambda *_args: None)
    monkeypatch.setattr(
        capture, "_read_intrinsics", lambda *_args: {"intrinsics": {}}
    )
    monkeypatch.setattr(
        "capture.realsense_capture.write_frame_batch",
        lambda _out, pairs: events.append(("saved batch", len(pairs))),
    )
    monkeypatch.setattr(
        capture,
        "_save_intrinsics",
        lambda payloads: events.append(("saved intrinsics", payloads)),
    )
    capture.out_dir = str(tmp_path)

    count = capture._run(
        CaptureParams(duration_s=0),
        lambda current, total: progress.append((current, total)),
    )

    assert count == 1
    assert progress == [(1, 1), (1, -1)]
    assert events == [
        "camera stopped",
        ("saved batch", 1),
        ("saved intrinsics", {"intrinsics": {}}),
    ]


def test_ros_stops_gantry_and_camera_before_saving_buffered_frames(
    tmp_path, monkeypatch
):
    events = []
    progress = []

    class Pipeline:
        @staticmethod
        def wait_for_frames():
            return _Frames(
                np.ones((2, 2, 3), dtype=np.uint8),
                np.ones((2, 2), dtype=np.uint16),
            )

        @staticmethod
        def stop():
            events.append("camera stopped")

    pipeline = Pipeline()

    class Rs:
        class stream:
            color = "color"

        class format:
            rgb8 = "rgb8"

        @staticmethod
        def pipeline():
            return pipeline

        @staticmethod
        def align(_stream):
            return _Align()

    class Gantry:
        def __init__(self, on_position=None, **_kwargs):
            self.on_position = on_position

        def start(self):
            self.on_position(0.0)

        @staticmethod
        def wait_for_position(_timeout):
            return True

        @staticmethod
        def is_running():
            return True

        def start_moving(self, _velocity):
            self.on_position(2.0)

        @staticmethod
        def stop_moving():
            events.append("gantry stopped")

        @staticmethod
        def shutdown():
            events.append("gantry shutdown")

        def go_home(self):
            events.append("gantry home")
            self.on_position(0.005)

    monkeypatch.setattr("capture.ros_capture.ros_available", lambda: True)
    monkeypatch.setattr("capture.ros_capture.import_realsense", lambda: Rs)
    monkeypatch.setattr("capture.ros_client.RosAgentClient", Gantry)
    monkeypatch.setattr(
        RealSenseCapture, "_select_device", lambda _self, _rs: object()
    )
    monkeypatch.setattr(
        RealSenseCapture,
        "_start_pipeline",
        lambda _self, _pipeline, _device, _rs, _params: (object(), "bgr8"),
    )
    monkeypatch.setattr(
        RealSenseCapture, "_apply_visual_preset", lambda *_args: None
    )
    monkeypatch.setattr(
        RealSenseCapture, "_update_session_from_profile", lambda *_args: None
    )
    monkeypatch.setattr(
        RealSenseCapture,
        "_read_intrinsics",
        lambda *_args: {"intrinsics": {}},
    )
    monkeypatch.setattr(
        RealSenseCapture,
        "_save_intrinsics",
        lambda _self, payloads: events.append(("saved intrinsics", payloads)),
    )
    monkeypatch.setattr(
        "capture.realsense_capture.write_frame_batch",
        lambda _out, pairs, cv2_module: events.append(
            ("saved batch", len(pairs))
        ),
    )
    capture = RosCapture()
    capture.out_dir = str(tmp_path)

    count = capture._run(
        CaptureParams(
            width=2,
            height=2,
            fps=30,
            end_position_m=1.64,
        ),
        lambda current, total: progress.append((current, total)),
    )

    assert count == 1
    assert progress == [(1, 0), (1, -1)]
    save_index = events.index(("saved batch", 1))
    assert events.index("gantry stopped") < save_index
    assert events.index("camera stopped") < save_index
    assert events[save_index + 1] == ("saved intrinsics", {"intrinsics": {}})
    assert events.index("gantry home") > save_index
    assert events.index("gantry shutdown") > events.index("gantry home")


def test_completed_frame_batch_is_written_with_numeric_names(tmp_path):
    (tmp_path / "rgb").mkdir()
    (tmp_path / "depth").mkdir()
    pairs = [(object(), object()), (object(), object())]

    write_frame_batch(str(tmp_path), pairs, cv2_module=_ImageWriter())

    assert sorted(path.name for path in (tmp_path / "rgb").iterdir()) == [
        "0.png", "1.png"
    ]
    assert sorted(path.name for path in (tmp_path / "depth").iterdir()) == [
        "0.png", "1.png"
    ]


def test_failed_batch_save_does_not_leave_a_partial_capture(tmp_path):
    (tmp_path / "rgb").mkdir()
    (tmp_path / "depth").mkdir()
    pairs = [(object(), object()), (object(), object())]

    with pytest.raises(RuntimeError, match="depth.*frame 1"):
        write_frame_batch(
            str(tmp_path), pairs, cv2_module=_SecondDepthWriteFails()
        )

    assert not list((tmp_path / "rgb").iterdir())
    assert not list((tmp_path / "depth").iterdir())
    assert not list(tmp_path.glob("*.part.png"))


def test_frame_pair_is_published_only_after_both_images_are_written(tmp_path):
    (tmp_path / "rgb").mkdir()
    (tmp_path / "depth").mkdir()

    write_frame_pair(
        str(tmp_path), 3, object(), object(), cv2_module=_ImageWriter()
    )

    assert (tmp_path / "rgb" / "3.png").is_file()
    assert (tmp_path / "depth" / "3.png").is_file()
    assert not list(tmp_path.rglob("*.part.png"))


@pytest.mark.parametrize("failed_kind", ["RGB", "depth"])
def test_failed_image_write_removes_the_incomplete_pair(tmp_path, failed_kind):
    (tmp_path / "rgb").mkdir()
    (tmp_path / "depth").mkdir()

    with pytest.raises(RuntimeError, match=f"Failed to save {failed_kind}"):
        write_frame_pair(
            str(tmp_path),
            4,
            object(),
            object(),
            cv2_module=_ImageWriter(fail_kind=failed_kind),
        )

    assert not list((tmp_path / "rgb").iterdir())
    assert not list((tmp_path / "depth").iterdir())


def test_ros_missing_frame_is_not_reported_as_saved():
    class Frames:
        @staticmethod
        def get_depth_frame():
            return None

        @staticmethod
        def get_color_frame():
            return object()

    class Pipeline:
        @staticmethod
        def wait_for_frames():
            return Frames()

    class Align:
        @staticmethod
        def process(frames):
            return frames

    capture = RosCapture()
    capture._cv2 = object()
    assert capture._capture_one(Pipeline(), Align(), object(), object()) is None

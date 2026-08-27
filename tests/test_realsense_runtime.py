"""Hardware-free checks for the shared L515/D405 RealSense safeguards."""

from __future__ import annotations

import pytest

from capture.realsense_capture import RealSenseCapture, write_frame_pair
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


class _ImageWriter:
    def __init__(self, fail_kind=None):
        self.fail_kind = fail_kind

    def imwrite(self, path, _image):
        with open(path, "wb") as image_file:
            image_file.write(b"image")
        kind = "depth" if ".depth.part.png" in path else "RGB"
        return kind != self.fail_kind


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
    assert capture._capture_one(Pipeline(), Align(), 0, object(), object()) is False

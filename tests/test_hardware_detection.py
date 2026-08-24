"""
tests/test_hardware_detection.py
--------------------------------
Regression tests for the two ways the app decides "is the hardware
actually there?", both of which silently misreported on the lab rig:

  - node registration: rospy advertised whatever the machine's hostname
    resolved to, so on a VM the master could never call back and the
    gantry sat at "Connecting to ROS..." forever;
  - camera detection: one cached librealsense context was reused for the
    whole session, so a camera plugged in after start-up was never seen.
"""

from __future__ import annotations

import os

import pytest

from capture import gantry as gantry_mod
from capture import simulation as sim


@pytest.fixture(autouse=True)
def clean_ros_env(monkeypatch):
    """Each test decides the ROS environment for itself."""
    monkeypatch.delenv("ROS_HOSTNAME", raising=False)
    monkeypatch.delenv("ROS_IP", raising=False)
    monkeypatch.setattr(gantry_mod, "_node_address_source", None)
    yield


# ------------------------------------------------------- node registration

@pytest.mark.parametrize("master", ["http://localhost:11311",
                                    "http://127.0.0.1:11311"])
def test_local_master_registers_as_localhost(monkeypatch, master):
    """A master on this machine must be joined over pure loopback, with
    no hostname resolution involved at all."""
    monkeypatch.setenv("ROS_MASTER_URI", master)
    choice = gantry_mod.configure_ros_node_address()
    assert os.environ["ROS_HOSTNAME"] == "localhost"
    assert "ROS_IP" not in os.environ
    assert "localhost" in choice


def test_remote_master_registers_routable_ip(monkeypatch):
    """A master on another machine must be given an address it can call
    back on -- never a loopback or a VM-only hostname."""
    monkeypatch.setenv("ROS_MASTER_URI", "http://192.0.2.10:11311")
    monkeypatch.setattr(gantry_mod, "_local_ip_towards",
                        lambda host, port: "10.1.2.3")
    gantry_mod.configure_ros_node_address()
    assert os.environ["ROS_IP"] == "10.1.2.3"
    assert "ROS_HOSTNAME" not in os.environ


def test_explicit_setting_is_never_overridden(monkeypatch):
    monkeypatch.setenv("ROS_MASTER_URI", "http://localhost:11311")
    monkeypatch.setenv("ROS_HOSTNAME", "chosen-by-the-user")
    gantry_mod.configure_ros_node_address()
    assert os.environ["ROS_HOSTNAME"] == "chosen-by-the-user"


def test_undeterminable_address_does_not_raise(monkeypatch):
    """No route to the master must degrade to 'let rospy guess', not
    blow up the preflight."""
    monkeypatch.setenv("ROS_MASTER_URI", "http://192.0.2.10:11311")
    monkeypatch.setattr(gantry_mod, "_local_ip_towards",
                        lambda host, port: None)
    choice = gantry_mod.configure_ros_node_address()
    assert "ROS_IP" not in os.environ
    assert "guess" in choice


# ------------------------------------------------------- camera detection

class _FakeRS:
    """Minimal stand-in for pyrealsense2: the first context sees nothing,
    a rebuilt one sees the camera (what a missed hotplug looks like)."""

    class camera_info:
        name = "name"

    def __init__(self, devices_per_context):
        self._queue = list(devices_per_context)
        self.contexts_built = 0

    def context(self):
        self.contexts_built += 1
        devices = self._queue.pop(0) if self._queue else []
        return _FakeContext(devices)


class _FakeContext:
    def __init__(self, devices):
        self._devices = devices

    def query_devices(self):
        return self._devices


class _FakeDevice:
    def get_info(self, _kind):
        return "Intel RealSense D405"


@pytest.fixture(autouse=True)
def reset_rs_context(monkeypatch):
    monkeypatch.setattr(sim, "_rs_context", None)
    yield


def test_stale_context_is_rebuilt_before_reporting_no_camera(monkeypatch):
    """The regression: a camera connected after start-up was invisible
    because the cached context was queried forever."""
    fake = _FakeRS([[], [_FakeDevice()]])
    monkeypatch.setitem(__import__("sys").modules, "pyrealsense2", fake)

    present, detail = sim.detect_camera()

    assert present, detail
    assert "D405" in detail
    assert fake.contexts_built == 2, "expected the stale context to be rebuilt"


def test_no_camera_reports_why_not_just_that(monkeypatch):
    """'no camera' on its own is unactionable -- the detail must say what
    the OS sees on the USB bus."""
    fake = _FakeRS([[], []])
    monkeypatch.setitem(__import__("sys").modules, "pyrealsense2", fake)
    monkeypatch.setattr(sim, "usb_diagnosis",
                        lambda: " -- nothing on the USB bus")

    present, detail = sim.detect_camera()

    assert not present
    assert "nothing on the USB bus" in detail


def test_usb_diagnosis_never_raises():
    """It runs inside every probe and every capture error path."""
    assert isinstance(sim.usb_diagnosis(), str)

"""Tests for selecting the lab's existing ROS interpreter."""

from __future__ import annotations

import os

import pytest

from capture import ros_runtime
from capture.ros_client import RosAgentClient


def test_runtime_selection_uses_interpreter_that_passes_all_imports(monkeypatch):
    monkeypatch.setattr(
        ros_runtime,
        "_candidate_environments",
        lambda: iter([("sourced lab ROS", {"ROS_DISTRO": "noetic"})]),
    )
    monkeypatch.setattr(
        ros_runtime,
        "_candidate_interpreters",
        lambda: ["/gui/python", "/usr/bin/python3"],
    )

    def probe(interpreter, _environment, _modules):
        if interpreter == "/gui/python":
            return {"rospy": "ModuleNotFoundError"}
        return {}

    monkeypatch.setattr(ros_runtime, "_probe_imports", probe)

    runtime = ros_runtime.choose_runtime()
    assert runtime.interpreter == "/usr/bin/python3"
    assert runtime.env["ROS_DISTRO"] == "noetic"


def test_runtime_failure_never_recommends_pip_installing_rospy(monkeypatch):
    monkeypatch.setattr(
        ros_runtime,
        "_candidate_environments",
        lambda: iter([("current", dict(os.environ))]),
    )
    monkeypatch.setattr(
        ros_runtime, "_candidate_interpreters", lambda: ["/usr/bin/python3"]
    )
    monkeypatch.setattr(
        ros_runtime,
        "_probe_imports",
        lambda *_args: {"rospy": "ModuleNotFoundError"},
    )

    with pytest.raises(RuntimeError) as caught:
        ros_runtime.choose_runtime()

    message = str(caught.value)
    assert "Do not pip-install rospy" in message
    assert "source" in message.lower()


def test_ros_install_detection_accepts_sourced_environment(monkeypatch):
    monkeypatch.setenv("ROS_DISTRO", "noetic")
    monkeypatch.setattr(ros_runtime, "_ros_setup_files", lambda: [])
    monkeypatch.setattr(ros_runtime.shutil, "which", lambda _name: None)
    assert ros_runtime.ros_is_installed() is True


def test_ros_install_detection_is_false_without_any_evidence(monkeypatch):
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    monkeypatch.delenv("ROS_PACKAGE_PATH", raising=False)
    monkeypatch.setattr(ros_runtime, "_ros_setup_files", lambda: [])
    monkeypatch.setattr(ros_runtime.shutil, "which", lambda _name: None)
    assert ros_runtime.ros_is_installed() is False


def test_ros_client_dispatches_ready_position_and_errors():
    positions = []
    errors = []
    client = RosAgentClient(on_position=positions.append, on_error=errors.append)

    client._dispatch({"event": "ready", "goto": True, "node": "/test"})
    client._dispatch({"event": "position", "value": 0.42})
    client._dispatch({"event": "warning", "message": "workspace missing"})

    assert client.goto_available is True
    assert client.position() == 0.42
    assert positions == [0.42]
    assert errors == ["workspace missing"]


def test_ros_client_prepares_local_node_address_and_bounds_master_probe(monkeypatch):
    environment = {"ROS_MASTER_URI": "http://localhost:11311"}
    RosAgentClient._prepare_node_address(environment)
    assert environment["ROS_HOSTNAME"] == "localhost"

    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def connect(address, timeout):
        calls.append((address, timeout))
        return Connection()

    monkeypatch.setattr("capture.ros_client.socket.create_connection", connect)
    RosAgentClient._check_master(environment)
    assert calls == [(('localhost', 11311), 1.5)]

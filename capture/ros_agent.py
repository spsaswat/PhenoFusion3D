"""Small ROS-only gantry helper executed outside the GUI virtualenv.

The protocol is one JSON object per line over stdin/stdout.  This file uses
only the standard library and ROS packages so it can run under the lab's
existing system ROS interpreter.
"""

from __future__ import annotations

import json
import sys
import threading
import time


HOME_POSITION_M = 0.005
HOME_VELOCITY_MPS = 0.15

TOPIC_CMD_VEL = "/cmd_vel"
TOPIC_JOINT_STATES = "/joint_states"
TOPIC_GOTO_GOAL = "/go_to_position_server/goal"

_write_lock = threading.Lock()


def emit(**payload) -> None:
    """Write one protocol message without letting a closed pipe escape."""

    try:
        with _write_lock:
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()
    except (OSError, ValueError):
        pass


class GantryAgent:
    """ROS publishers/subscriber matching the proven stakeholder loop."""

    def __init__(self):
        self.rospy = None
        self.Twist = None
        self.cmd_vel_publisher = None
        self.goto_publisher = None
        self.GotoActionGoal = None
        self.Header = None
        self.GoalID = None
        self.goto_available = False

    def start(self) -> None:
        import rospy
        from geometry_msgs.msg import Twist
        from sensor_msgs.msg import JointState

        self.rospy = rospy
        self.Twist = Twist
        rospy.init_node(
            "phenofusion_gantry", anonymous=True, disable_signals=True
        )
        self.cmd_vel_publisher = rospy.Publisher(
            TOPIC_CMD_VEL, Twist, queue_size=10
        )

        try:
            from actionlib_msgs.msg import GoalID
            from position_controller_ros.msg import GotoActionGoal
            from std_msgs.msg import Header

            self.GotoActionGoal = GotoActionGoal
            self.Header = Header
            self.GoalID = GoalID
            self.goto_publisher = rospy.Publisher(
                TOPIC_GOTO_GOAL, GotoActionGoal, queue_size=10
            )
            self.goto_available = True
        except Exception as exc:
            emit(
                event="warning",
                message=(
                    "position_controller_ros is unavailable "
                    f"({exc}); jog and stop still work, but go-to and "
                    "go-home require the gantry catkin workspace to be sourced."
                ),
            )

        rospy.Subscriber(
            TOPIC_JOINT_STATES, JointState, self._on_joint_states
        )
        time.sleep(0.3)
        emit(
            event="ready",
            goto=self.goto_available,
            node=rospy.get_name(),
        )

    def _on_joint_states(self, message) -> None:
        if message.position:
            emit(event="position", value=float(message.position[0]))

    def jog(self, velocity_mps: float) -> None:
        message = self.Twist()
        message.linear.x = float(velocity_mps)
        self.cmd_vel_publisher.publish(message)

    def stop(self) -> None:
        self.cmd_vel_publisher.publish(self.Twist())

    def go_to(self, position_m: float, velocity_mps: float) -> None:
        if not self.goto_available:
            raise RuntimeError(
                "Go-to/go-home require position_controller_ros. Source the "
                "gantry catkin workspace before launching the app."
            )
        message = self.GotoActionGoal()
        message.header = self.Header()
        message.goal_id = self.GoalID()
        message.goal.position = float(position_m)
        message.goal.velocity = float(velocity_mps)
        self.goto_publisher.publish(message)

    def handle(self, request: dict) -> bool:
        command = request.get("cmd")
        if command == "quit":
            return False
        try:
            if command == "jog":
                self.jog(request.get("velocity", 0.0))
            elif command == "stop":
                self.stop()
            elif command == "goto":
                self.go_to(
                    request.get("position", 0.0),
                    request.get("velocity", HOME_VELOCITY_MPS),
                )
            elif command == "home":
                self.go_to(HOME_POSITION_M, HOME_VELOCITY_MPS)
            elif command != "ping":
                raise ValueError(f"unknown command {command!r}")
            emit(event="ack", cmd=command)
        except Exception as exc:
            emit(event="error", message=f"{command} failed: {exc}")
        return True

    def serve(self) -> int:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                request = json.loads(raw)
            except ValueError as exc:
                emit(event="error", message=f"Invalid command: {exc}")
                continue
            if not self.handle(request):
                break
        try:
            self.stop()
        except Exception:
            pass
        return 0


def main() -> int:
    agent = GantryAgent()
    try:
        agent.start()
    except Exception as exc:
        emit(event="error", message=f"ROS gantry startup failed: {exc}", fatal=True)
        return 1
    return agent.serve()


if __name__ == "__main__":
    raise SystemExit(main())

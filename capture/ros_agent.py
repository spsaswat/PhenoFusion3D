"""
capture/ros_agent.py
--------------------
The app's ROS side, as a standalone helper process.

Run by `capture/gantry.py` under the interpreter `capture/ros_runtime.py`
picks -- which is usually NOT the interpreter running the GUI. On a lab
rig the app's venv often cannot import rospy at all (rospy comes from
/opt/ros via PYTHONPATH, but its pure-Python dependencies were
apt-installed for the system Python), so doing ROS work in the GUI
process meant the gantry could never connect no matter what the hardware
was doing.

Keeping ROS out of the GUI process buys three other things: rospy's
init_node can no longer steal the Qt process's logging handlers or its
signal handlers, a wedged ROS call can no longer freeze the event loop,
and the gantry is driven by the same runtime that runs the stakeholder
capture script.

IMPORTANT: this file must not import anything from the app -- it runs
under a different interpreter. Standard library and ROS only.

Protocol: one JSON object per line, both directions.

  in : {"cmd": "jog",  "velocity": 0.038}
       {"cmd": "stop"}
       {"cmd": "goto", "position": 0.4, "velocity": 0.2}
       {"cmd": "home"}
       {"cmd": "quit"}
  out: {"event": "ready",    "goto": true, "node": "..."}
       {"event": "position", "value": 0.1234}
       {"event": "driver",   "publishing": true}
       {"event": "error",    "message": "..."}
       {"event": "ack",      "cmd": "jog"}

Also runs one-shot as `python ros_agent.py --probe`, printing a single
JSON line describing whether the master and the gantry driver are up.
"""

from __future__ import annotations

import json
import sys
import threading
import time

HOME_POSITION_M = 0.005      # matches the stakeholder script's go_home()
HOME_VELOCITY_MPS = 0.2

TOPIC_CMD_VEL = "/cmd_vel"
TOPIC_JOINT_STATES = "/joint_states"
TOPIC_GOTO_GOAL = "/go_to_position_server/goal"

_write_lock = threading.Lock()


def emit(**payload) -> None:
    """One JSON line to the parent. Never let a broken pipe raise."""
    try:
        with _write_lock:
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()
    except (OSError, ValueError):
        pass


# ------------------------------------------------------------------- probe

def probe() -> int:
    """Report master + driver status as one JSON line, then exit.

    Used for the periodic hardware check, which must not need a node.
    """
    try:
        import rosgraph
    except Exception as e:
        emit(event="probe", master=False, driver=False,
             detail=f"rosgraph unavailable: {e}")
        return 1
    try:
        master = rosgraph.Master("/phenofusion_probe")
        publishers = dict(master.getSystemState()[0])
    except Exception as e:
        emit(event="probe", master=False, driver=False,
             detail=f"could not query the ROS master: {e}")
        return 1

    nodes = publishers.get(TOPIC_JOINT_STATES) or []
    if not nodes:
        emit(event="probe", master=True, driver=False,
             detail="roscore is up but nothing publishes /joint_states -- "
                    "the gantry driver is not running")
        return 0
    emit(event="probe", master=True, driver=True,
         detail="publishers: " + ", ".join(nodes))
    return 0


# ------------------------------------------------------------------- agent

class Agent:
    def __init__(self):
        self.rospy = None
        self.Twist = None
        self.cmd_vel = None
        self.goto_pub = None
        self.GotoActionGoal = self.Header = self.GoalID = None
        self.goto_available = False
        self._last_sent = None

    # -- setup --

    def start(self) -> None:
        import rospy
        from geometry_msgs.msg import Twist
        from sensor_msgs.msg import JointState
        self.rospy, self.Twist = rospy, Twist

        rospy.init_node("phenofusion_gantry", anonymous=True,
                        disable_signals=True)

        self.cmd_vel = rospy.Publisher(TOPIC_CMD_VEL, Twist, queue_size=10)

        # Optional: without the gantry's own message package, jog and stop
        # still work and only go-to / go-home are unavailable.
        try:
            from position_controller_ros.msg import GotoActionGoal
            from std_msgs.msg import Header
            from actionlib_msgs.msg import GoalID
            self.GotoActionGoal, self.Header, self.GoalID = (
                GotoActionGoal, Header, GoalID)
            self.goto_pub = rospy.Publisher(TOPIC_GOTO_GOAL, GotoActionGoal,
                                            queue_size=10)
            self.goto_available = True
        except Exception as e:
            emit(event="error", message=(
                f"position_controller_ros messages are not available ({e}); "
                "jog and stop work, go-to and go-home are disabled."))

        rospy.Subscriber(TOPIC_JOINT_STATES, JointState, self._on_joint_states)

        # Let subscribers discover our publishers before the first command,
        # or that command is silently dropped.
        time.sleep(0.3)
        emit(event="ready", goto=self.goto_available,
             node=rospy.get_name())

    def _on_joint_states(self, message) -> None:
        if message.position:
            emit(event="position", value=float(message.position[0]))

    # -- commands --

    def jog(self, velocity: float) -> None:
        message = self.Twist()
        message.linear.x = float(velocity)
        self.cmd_vel.publish(message)

    def stop(self) -> None:
        self.cmd_vel.publish(self.Twist())

    def goto(self, position: float, velocity: float) -> None:
        if not self.goto_available:
            emit(event="error", message=(
                "Go-to and go-home need the position_controller_ros message "
                "package, which is not on this interpreter's path. Source "
                "your catkin workspace's devel/setup.bash before launching."))
            return
        message = self.GotoActionGoal()
        message.header = self.Header()
        message.goal_id = self.GoalID()
        message.goal.position = float(position)
        message.goal.velocity = float(velocity)
        self.goto_pub.publish(message)

    def handle(self, request: dict) -> bool:
        """Returns False when asked to quit."""
        command = request.get("cmd")
        if command == "quit":
            return False
        try:
            if command == "jog":
                self.jog(request.get("velocity", 0.0))
            elif command == "stop":
                self.stop()
            elif command == "goto":
                self.goto(request.get("position", 0.0),
                          request.get("velocity", HOME_VELOCITY_MPS))
            elif command == "home":
                self.goto(HOME_POSITION_M, HOME_VELOCITY_MPS)
            elif command == "ping":
                pass
            else:
                emit(event="error", message=f"unknown command {command!r}")
                return True
            emit(event="ack", cmd=command)
        except Exception as e:
            emit(event="error", message=f"{command} failed: {e}")
        return True

    def serve(self) -> int:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                emit(event="error", message=f"malformed request: {line[:120]}")
                continue
            if not self.handle(request):
                break
        # Whatever ends this process, leave the axis stopped.
        try:
            self.stop()
        except Exception:
            pass
        return 0


def main(argv) -> int:
    if "--probe" in argv:
        return probe()
    agent = Agent()
    try:
        agent.start()
    except Exception as e:
        emit(event="error", message=f"ROS init failed: {e}", fatal=True)
        return 1
    return agent.serve()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Line-oriented ROS gantry bridge. Compatible with ROS Noetic Python 3.8."""

import json
import signal
import sys
import threading


EVENT_PREFIX = "PHENOFUSION_JSON "
stop_requested = False


def emit(event, **payload):
    message = {"event": event}
    message.update(payload)
    print(EVENT_PREFIX + json.dumps(message), flush=True)


def request_stop(_signum, _frame):
    global stop_requested
    stop_requested = True


def main():
    try:
        import rospy
        from actionlib_msgs.msg import GoalID
        from geometry_msgs.msg import Twist
        from position_controller_ros.msg import GotoActionGoal
        from sensor_msgs.msg import JointState
        from std_msgs.msg import Header
    except Exception as exc:
        emit(
            "error",
            stage="import_ros",
            message=(
                "ROS gantry imports failed: %s. Source ROS Noetic and the "
                "position_controller_ros workspace before launching the app." % exc
            ),
        )
        return 20

    try:
        rospy.init_node("phenofusion_gantry", anonymous=True, disable_signals=True)
        velocity_publisher = rospy.Publisher("/cmd_vel", Twist, queue_size=10)
        goto_publisher = rospy.Publisher(
            "/go_to_position_server/goal", GotoActionGoal, queue_size=10
        )

        def on_position(message):
            if message.position:
                emit("position", position_m=float(message.position[0]))

        subscriber = rospy.Subscriber("/joint_states", JointState, on_position)
        rospy.sleep(0.3)
    except Exception as exc:
        emit("error", stage="ros_init", message="ROS gantry init failed: %s" % exc)
        return 21

    def publish_stop():
        velocity_publisher.publish(Twist())

    def read_commands():
        global stop_requested
        for line in sys.stdin:
            try:
                command = json.loads(line)
                action = command.get("command")
                if action == "jog":
                    message = Twist()
                    message.linear.x = float(command["velocity_mps"])
                    velocity_publisher.publish(message)
                elif action == "stop":
                    publish_stop()
                elif action in ("goto", "home"):
                    message = GotoActionGoal()
                    message.header = Header()
                    message.goal_id = GoalID()
                    message.goal.position = float(command["position_m"])
                    message.goal.velocity = float(command.get("velocity_mps", 0.2))
                    goto_publisher.publish(message)
                elif action == "shutdown":
                    publish_stop()
                    stop_requested = True
                    return
                else:
                    emit("error", stage="command", message="Unknown gantry command: %s" % action)
            except Exception as exc:
                emit("error", stage="command", message="Invalid gantry command: %s" % exc)
        stop_requested = True

    reader = threading.Thread(target=read_commands)
    reader.daemon = True
    reader.start()
    emit("ready", interpreter=sys.executable)
    try:
        while not rospy.is_shutdown() and not stop_requested:
            rospy.sleep(0.05)
    finally:
        try:
            publish_stop()
        except Exception:
            pass
        try:
            subscriber.unregister()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    sys.exit(main())

#!/usr/bin/env python3
"""ROS + RealSense capture child process for the lab gantry.

This intentionally follows ``rospy_thread_fin_1.py``: D405 high-accuracy
preset, aligned RGB-D, two captures per motion loop, the stakeholder topics,
and a go-home goal after the end position.  It is a process so an incompatible
or slow rospy import cannot freeze the PyQt application or camera-only mode.

Keep this file compatible with the Python 3.8 supplied by ROS Noetic.
"""

import argparse
import json
import os
import signal
import sys
import traceback


EVENT_PREFIX = "PHENOFUSION_JSON "
KNOWN_SERIALS = ("128422272123", "017322071325", "f1230450")
stop_requested = False


def emit(event, **payload):
    message = {"event": event}
    message.update(payload)
    print(EVENT_PREFIX + json.dumps(message), flush=True)


def request_stop(_signum, _frame):
    global stop_requested
    stop_requested = True


def save_intrinsics(profile, rs, output_dir):
    for stream_kind, filename in (
        (rs.stream.depth, "kd_intrinsics.txt"),
        (rs.stream.color, "kdc_intrinsics.txt"),
    ):
        video_profile = rs.video_stream_profile(profile.get_stream(stream_kind))
        intrinsics = video_profile.get_intrinsics()
        payload = {
            "K": [
                [intrinsics.fx, 0, intrinsics.ppx],
                [0, intrinsics.fy, intrinsics.ppy],
                [0, 0, 1],
            ],
            "dist": list(intrinsics.coeffs),
            "height": intrinsics.height,
            "width": intrinsics.width,
        }
        with open(os.path.join(output_dir, filename), "w") as handle:
            json.dump(payload, handle, indent=4)


def device_text(device, rs, kind, default=""):
    try:
        if device.supports(kind):
            return device.get_info(kind)
    except Exception:
        pass
    return default


def has_stream(device, rs, stream):
    for sensor in device.query_sensors():
        for profile in sensor.get_stream_profiles():
            if profile.stream_type() == stream:
                return True
    return False


def select_device(rs, preferred_serials, strict=False):
    devices = list(rs.context().query_devices())
    rgbd_devices = [
        device
        for device in devices
        if has_stream(device, rs, rs.stream.color)
        and has_stream(device, rs, rs.stream.depth)
    ]
    if not rgbd_devices:
        raise RuntimeError("No connected RealSense device exposes color and depth streams")
    by_serial = {
        device_text(device, rs, rs.camera_info.serial_number): device
        for device in rgbd_devices
    }
    for serial in preferred_serials:
        if serial in by_serial:
            return by_serial[serial]
    if strict:
        available = ", ".join(sorted(by_serial)) or "none"
        raise RuntimeError(
            "Requested RealSense serial was not found. Connected RGB-D serials: %s"
            % available
        )
    return rgbd_devices[0]


def choose_profile(device, rs, stream, width, height, fps, formats):
    candidates = []
    for sensor in device.query_sensors():
        for profile in sensor.get_stream_profiles():
            if profile.stream_type() != stream or profile.format() not in formats:
                continue
            try:
                video = profile.as_video_stream_profile()
            except RuntimeError:
                continue
            score = (
                formats.index(profile.format()),
                abs(video.width() - width) + abs(video.height() - height),
                abs(profile.fps() - fps),
            )
            candidates.append((score, profile, video))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


def start_pipeline(rs, args, device):
    serial = device_text(device, rs, rs.camera_info.serial_number)
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(serial)
    config.enable_stream(
        rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps
    )
    config.enable_stream(
        rs.stream.depth, args.width, args.height, rs.format.z16, args.fps
    )
    try:
        return pipeline, pipeline.start(config)
    except RuntimeError as requested_error:
        color = choose_profile(
            device,
            rs,
            rs.stream.color,
            args.width,
            args.height,
            args.fps,
            (rs.format.bgr8, rs.format.rgb8),
        )
        depth = choose_profile(
            device,
            rs,
            rs.stream.depth,
            args.width,
            args.height,
            args.fps,
            (rs.format.z16,),
        )
        if color is None or depth is None:
            raise RuntimeError(
                "Requested stream profile failed and no compatible fallback was found: %s"
                % requested_error
            )
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(serial)
        _, color_profile, color_video = color
        _, depth_profile, depth_video = depth
        config.enable_stream(
            rs.stream.color,
            color_video.width(),
            color_video.height(),
            color_profile.format(),
            color_profile.fps(),
        )
        config.enable_stream(
            rs.stream.depth,
            depth_video.width(),
            depth_video.height(),
            depth_profile.format(),
            depth_profile.fps(),
        )
        return pipeline, pipeline.start(config)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--velocity", type=float, default=0.038)
    parser.add_argument("--end-position", type=float, default=0.78)
    parser.add_argument("--serial", action="append", dest="serials")
    parser.add_argument("--strict-serial", action="store_true")
    args = parser.parse_args()

    try:
        import rospy
        from actionlib_msgs.msg import GoalID
        from geometry_msgs.msg import Twist
        from position_controller_ros.msg import GotoActionGoal
        from sensor_msgs.msg import JointState
        from std_msgs.msg import Header, UInt16
    except Exception as exc:
        emit(
            "error",
            stage="import_ros",
            message=(
                "ROS imports failed: %s. Start PhenoFusion3D from a terminal "
                "that has sourced /opt/ros/noetic/setup.bash and the gantry "
                "workspace devel/setup.bash." % exc
            ),
        )
        return 20

    try:
        import cv2
        import numpy as np
        import pyrealsense2 as rs
    except Exception as exc:
        emit("error", stage="import_camera", message="Camera imports failed: %s" % exc)
        return 21

    os.makedirs(os.path.join(args.output, "rgb"), exist_ok=True)
    os.makedirs(os.path.join(args.output, "depth"), exist_ok=True)

    pipeline = None
    joint_subscriber = None
    cmd_vel_publisher = None
    goto_publisher = None
    current_position = [0.0]
    rgb_images = []
    natural_finish = False
    frame_index = 0

    def joint_states_callback(message):
        if message.position:
            current_position[0] = float(message.position[0])

    def stop_motion():
        if cmd_vel_publisher is not None:
            cmd_vel_publisher.publish(Twist())

    def go_home():
        if goto_publisher is None:
            return
        message = GotoActionGoal()
        message.header = Header()
        message.goal_id = GoalID()
        message.goal.position = 0.005
        message.goal.velocity = 0.2
        goto_publisher.publish(message)

    def capture_one(align):
        nonlocal frame_index
        frames = pipeline.wait_for_frames()
        aligned = align.process(frames)
        depth_frame = aligned.get_depth_frame()
        color_frame = aligned.get_color_frame()
        if not depth_frame or not color_frame:
            return
        depth_image = np.asanyarray(depth_frame.get_data())
        color_image = np.asanyarray(color_frame.get_data()).copy()
        if color_format == rs.format.rgb8:
            color_image = cv2.cvtColor(color_image, cv2.COLOR_RGB2BGR)
        rgb_path = os.path.join(args.output, "rgb", "%d.png" % frame_index)
        depth_path = os.path.join(args.output, "depth", "%d.png" % frame_index)
        # Match the stakeholder script: depth is persisted immediately and RGB
        # is buffered so disk encoding does not disturb gantry/frame spacing.
        if not cv2.imwrite(depth_path, depth_image):
            raise RuntimeError("Could not write %s" % depth_path)
        rgb_images.append((color_image, rgb_path))
        emit("frame", index=frame_index, position_m=current_position[0])
        frame_index += 1

    try:
        try:
            device = select_device(
                rs, args.serials or KNOWN_SERIALS, strict=args.strict_serial
            )
            selected_serial = device_text(
                device, rs, rs.camera_info.serial_number, "unknown"
            )
            selected_model = device_text(
                device, rs, rs.camera_info.name, "Unknown RealSense"
            )
            pipeline, profile = start_pipeline(rs, args, device)
            color_format = profile.get_stream(rs.stream.color).format()
        except Exception as exc:
            emit("error", stage="camera_start", message="RealSense start failed: %s" % exc)
            return 22

        try:
            profile.get_device().first_depth_sensor().set_option(rs.option.visual_preset, 4)
        except Exception:
            pass
        save_intrinsics(profile, rs, args.output)
        align = rs.align(rs.stream.color)
        for _ in range(2):
            pipeline.wait_for_frames()
            pipeline.wait_for_frames()

        try:
            rospy.init_node("robot_controller", anonymous=True, disable_signals=True)
            cmd_vel_publisher = rospy.Publisher("/cmd_vel", Twist, queue_size=10)
            # Keep /write_pin publisher from the stakeholder implementation so
            # the ROS graph and future light control remain compatible.
            rospy.Publisher("/write_pin", UInt16, queue_size=10)
            joint_subscriber = rospy.Subscriber(
                "/joint_states", JointState, joint_states_callback
            )
            goto_publisher = rospy.Publisher(
                "/go_to_position_server/goal", GotoActionGoal, queue_size=10
            )
            rospy.sleep(0.3)
        except Exception as exc:
            emit("error", stage="ros_init", message="ROS initialisation failed: %s" % exc)
            return 23

        color_stream = rs.video_stream_profile(profile.get_stream(rs.stream.color))
        color_intrinsics = color_stream.get_intrinsics()
        emit(
            "ready",
            interpreter=sys.executable,
            serial=selected_serial,
            model=selected_model,
            width=color_intrinsics.width,
            height=color_intrinsics.height,
            fps=color_stream.fps(),
        )
        while not rospy.is_shutdown() and not stop_requested:
            command = Twist()
            command.linear.x = args.velocity
            cmd_vel_publisher.publish(command)
            capture_one(align)
            if current_position[0] != 0.0 and current_position[0] >= args.end_position:
                natural_finish = True
                break
            capture_one(align)

        stop_motion()
        for image, path in rgb_images:
            if not cv2.imwrite(path, image):
                raise RuntimeError("Could not write %s" % path)
        if natural_finish:
            go_home()
            rospy.sleep(0.2)
        emit("complete", frames=frame_index, homing=natural_finish)
        return 0
    except Exception as exc:
        emit(
            "error",
            stage="capture",
            message="Capture failed: %s" % exc,
            traceback=traceback.format_exc(),
        )
        return 24
    finally:
        try:
            stop_motion()
        except Exception:
            pass
        if joint_subscriber is not None:
            try:
                joint_subscriber.unregister()
            except Exception:
                pass
        if pipeline is not None:
            try:
                pipeline.stop()
            except Exception:
                pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    sys.exit(main())

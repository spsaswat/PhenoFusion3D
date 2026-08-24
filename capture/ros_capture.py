"""
capture/ros_capture.py
----------------------
ROS + RealSense + gantry capture backend.

The capture loop is a faithful port of the stakeholder-provided
`stakeholder_reference/rospy_thread_fin_1.py`: same ROS topics, same
velocity command, same two-captures-per-iteration cadence, same
intrinsics files, same stop-and-go-home ending.

The loop talks to two small adapters -- a camera and a gantry -- so the
SAME verified loop runs against real hardware, against simulated
hardware (`capture/simulation.py`), or a mix of the two. That is how the
rig stays testable when the D405 isn't passed through or the gantry
driver isn't running; a simulated run is always announced to the UI and
recorded in session.json.

Output layout (identical for real and simulated runs):
    <out>/rgb/<idx>.png, <out>/depth/<idx>.png
    <out>/kd_intrinsics.txt, <out>/kdc_intrinsics.txt
    <out>/session.json   (records frame_idx -> gantry position)
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import queue
import threading
import time
from typing import Callable, Optional, Tuple

import numpy as np

from capture.base import CaptureBackend, CaptureParams
from capture.ros_client import RosAgentClient

log = logging.getLogger("phenofusion.capture")


def ros_available() -> bool:
    """True when this MACHINE has ROS -- not necessarily this interpreter.

    The GUI process no longer talks to ROS itself; capture/ros_agent.py
    does, under whichever interpreter can import it. So gating the ROS
    features on `import rospy` working *here* wrongly disabled them on
    exactly the rigs they were needed on: the app's venv frequently
    cannot import rospy while the system Python can.

    Kept cheap (filesystem checks only) -- it runs while building the UI.
    """
    if importlib.util.find_spec("rospy") is not None:
        return True
    from capture.ros_runtime import ros_is_installed
    return ros_is_installed()


def _available_ram_bytes() -> int:
    """MemAvailable from /proc/meminfo (Linux); 2 GiB fallback."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 2 << 30


# ============================================================== adapters ===

class RealCamera:
    """Intel RealSense D405 via pyrealsense2, configured exactly as the
    stakeholder script does (aligned to color, high-accuracy preset)."""

    simulated = False
    label = "Intel RealSense"

    # D405 serial used in the stakeholder script
    DEFAULT_SERIAL = "128422272123"

    def __init__(self, serial_number: Optional[str], width: int,
                 height: int, fps: int):
        self.serial_number = serial_number or self.DEFAULT_SERIAL
        self.width, self.height, self.fps = width, height, fps
        self._rs = None
        self._pipeline = None
        self._align = None
        self._profile = None

    def start(self) -> None:
        import pyrealsense2 as rs
        self._rs = rs

        # Resolve the device BEFORE touching the pipeline: pipeline.start()
        # waits ~15 s for a missing camera and holds the GIL the whole
        # time, which freezes the Qt GUI, not just the capture thread.
        serial = self._resolve_serial(rs)

        pipeline = rs.pipeline()
        config = rs.config()
        if serial:
            try:
                config.enable_device(serial)
            except Exception:
                pass
        config.enable_stream(rs.stream.color, self.width, self.height,
                             rs.format.bgr8, self.fps)
        config.enable_stream(rs.stream.depth, self.width, self.height,
                             rs.format.z16, self.fps)

        self._profile = pipeline.start(config)
        self._pipeline = pipeline
        self._align = rs.align(rs.stream.color)

        try:
            depth_sensor = self._profile.get_device().first_depth_sensor()
            depth_sensor.set_option(rs.option.visual_preset, 4)  # high accuracy
        except Exception:
            pass

        # Warm-up (matches stakeholder: two frames, twice)
        for _ in range(2):
            pipeline.wait_for_frames()
            pipeline.wait_for_frames()

    def _resolve_serial(self, rs) -> str:
        from capture.simulation import (no_camera_message, usb_diagnosis,
                                        _query_devices)
        # Go through the shared enumerator: it retries with a fresh
        # librealsense context, so a camera plugged in after the app
        # started is still found.
        devices = _query_devices(rs)
        if not devices:
            devices = _query_devices(rs, rebuild=True)
        if not devices:
            raise RuntimeError(
                no_camera_message("librealsense enumerated no devices"
                                  + usb_diagnosis())
                + " Capture was not started and the gantry was not moved."
            )
        serials = []
        for dev in devices:
            try:
                if dev.supports(rs.camera_info.serial_number):
                    serials.append(dev.get_info(rs.camera_info.serial_number))
            except Exception:
                pass
        if self.serial_number in serials:
            return self.serial_number
        if serials:
            log.warning("configured camera serial %s not connected "
                        "(found: %s); using %s instead",
                        self.serial_number, ", ".join(serials), serials[0])
            return serials[0]
        return ""

    def wait_for_frames(self):
        frames = self._pipeline.wait_for_frames()
        aligned = self._align.process(frames)
        depth_frame = aligned.get_depth_frame()
        color_frame = aligned.get_color_frame()
        if not depth_frame or not color_frame:
            return None
        return (np.asanyarray(color_frame.get_data()),
                np.asanyarray(depth_frame.get_data()))

    def intrinsics(self) -> dict:
        rs = self._rs
        out = {}
        for key, stream_kind in (("depth", rs.stream.depth),
                                 ("color", rs.stream.color)):
            try:
                vsp = rs.video_stream_profile(self._profile.get_stream(stream_kind))
                intr = vsp.get_intrinsics()
                out[key] = {
                    "K": [[intr.fx, 0, intr.ppx],
                          [0, intr.fy, intr.ppy],
                          [0, 0, 1]],
                    "dist": list(intr.coeffs),
                    "height": intr.height,
                    "width": intr.width,
                }
            except Exception as e:
                log.warning("could not read %s intrinsics: %s", key, e)
        return out

    def stop(self) -> None:
        try:
            if self._pipeline is not None:
                self._pipeline.stop()
        except Exception:
            pass


class RealGantry(RosAgentClient):
    """The lab gantry over ROS: /cmd_vel out, /joint_states in.

    Thin adapter over `RosAgentClient`, so the self-test and this capture
    loop drive the gantry through the same out-of-process runtime as the
    panel and the stakeholder script -- rather than an in-process rospy
    that the app's venv often cannot import at all.
    """

    simulated = False
    label = "ROS gantry"


# ================================================================ backend ===

class RosCapture(CaptureBackend):
    name = "ros"

    DEFAULT_SERIAL = RealCamera.DEFAULT_SERIAL

    # The gantry driver must be publishing /joint_states before we command
    # any motion -- without it the position stays 0.0 forever and the loop
    # would never terminate.
    JOINT_STATES_TIMEOUT_S = 8.0

    # Number of background PNG-writer threads draining the RGB queue.
    # cv2.imwrite releases the GIL while encoding, so these genuinely run
    # in parallel with the capture thread.
    N_RGB_WRITERS = 3

    def __init__(self,
                 serial_number: Optional[str] = None,
                 allow_sim_camera: bool = False,
                 allow_sim_gantry: bool = False):
        super().__init__()
        self.serial_number = serial_number or self.DEFAULT_SERIAL
        self.allow_sim_camera = allow_sim_camera
        self.allow_sim_gantry = allow_sim_gantry
        # Color frames queue: the capture thread enqueues, writer threads
        # drain to disk during the pass. Bounded so a long or runaway pass
        # applies backpressure instead of eating all RAM -- on the 5.6 GB
        # lab VM an unbounded buffer froze the whole machine.
        self._rgb_queue: Optional[queue.Queue] = None
        self._writer_threads: list = []
        self._cv2 = None

    # ------------------------------------------------------ device choice

    def _build_camera(self, params: CaptureParams):
        """Real camera when one is attached; simulated when allowed."""
        from capture.simulation import detect_camera, SimCamera
        present, detail = detect_camera()
        if present:
            log.info("camera: real (%s)", detail)
            return RealCamera(self.serial_number, params.width,
                              params.height, params.fps)
        if not self.allow_sim_camera:
            raise RuntimeError(
                f"No camera available ({detail}). Connect the D405 to a "
                "USB 3 port, or use Quick Scan, which falls back to a "
                "simulated camera for testing."
            )
        log.warning("camera: SIMULATED (%s)", detail)
        return SimCamera(params.width, params.height, params.fps)

    def _build_gantry(self, params: CaptureParams):
        """Real gantry when the driver is publishing; simulated when
        allowed."""
        from capture.simulation import detect_gantry, SimGantry
        present, detail = detect_gantry()
        if present:
            log.info("gantry: real (%s)", detail)
            return RealGantry()
        if not self.allow_sim_gantry:
            raise RuntimeError(
                f"No gantry available ({detail}). Start roscore and the "
                "gantry driver (the node publishing /joint_states and "
                "listening on /cmd_vel), or use Quick Scan, which falls "
                "back to a simulated gantry for testing."
            )
        log.warning("gantry: SIMULATED (%s)", detail)
        return SimGantry()

    # ------------------------------------------------------------- the run

    def _run(
        self,
        params: CaptureParams,
        on_progress: Callable[[int, int], None],
    ) -> int:
        from capture.realsense_capture import _import_cv2
        self._cv2 = _import_cv2()

        # Choose hardware first so a missing device fails before anything
        # is opened or the gantry is commanded to move.
        gantry = self._build_gantry(params)
        camera = self._build_camera(params)

        self.simulated = bool(camera.simulated or gantry.simulated)
        if self.session is not None:
            self.session.camera_source = "simulated" if camera.simulated else "real"
            self.session.gantry_source = "simulated" if gantry.simulated else "real"
        if self.simulated:
            fake = [n for n, o in (("camera", camera), ("gantry", gantry))
                    if o.simulated]
            self._notice(
                "SIMULATED " + " and ".join(fake) + " -- no real hardware "
                "detected for " + " and ".join(fake) + ". This run produces "
                "synthetic data for testing only."
            )

        gantry.start()
        try:
            camera.start()
            self._save_intrinsics(camera)

            # Refuse to command motion until the gantry proves it is alive.
            # Without this gate a missing driver means the position stays
            # 0.0, the end condition never fires, and the loop captures
            # (and buffers) forever.
            log.info("waiting up to %.0fs for gantry position...",
                     self.JOINT_STATES_TIMEOUT_S)
            if not gantry.wait_alive(self.JOINT_STATES_TIMEOUT_S):
                raise RuntimeError(
                    "No gantry position received on /joint_states within "
                    f"{self.JOINT_STATES_TIMEOUT_S:.0f}s. roscore is up, but "
                    "the gantry driver does not appear to be running -- "
                    "start it (the node that publishes /joint_states and "
                    "listens on /cmd_vel), check with 'rostopic hz "
                    "/joint_states', then try again. No motion was commanded."
                )
            log.info("gantry alive at %.3f m", gantry.position())

            # Hard wall-clock guard: the pass should take roughly
            # end_position/velocity seconds; if the gantry stalls or never
            # reaches the end, abort instead of running (and commanding
            # motion) forever.
            expected_s = params.end_position_m / max(params.velocity_mps, 1e-6)
            max_runtime_s = expected_s * 3.0 + 30.0

            # ---------------- capture loop (mirrors stakeholder) ----------
            # The stakeholder buffers COLOR frames in RAM and writes them
            # after the run (depth is written immediately) -- PNG-encoding
            # color inline is too slow and drops the frame rate. We keep the
            # capture thread encode-free but drain the buffer with
            # background writer threads through a RAM-bounded queue.
            self._start_rgb_writers(params)
            i = 0
            completed = False
            t_loop_start = time.monotonic()
            try:
                while not self._stop_flag:
                    if getattr(gantry, "is_shutdown", lambda: False)():
                        log.info("ROS shutdown requested; ending capture")
                        break
                    if time.monotonic() - t_loop_start > max_runtime_s:
                        gantry.stop_moving()
                        raise RuntimeError(
                            f"Capture aborted after {int(max_runtime_s)}s: "
                            f"gantry position is {gantry.position():.3f} m but "
                            f"never reached the end position "
                            f"({params.end_position_m:.3f} m). The gantry may "
                            "be stalled or the driver not moving it. "
                            f"{i} frames were still saved to {self.out_dir}."
                        )

                    gantry.start_moving(params.velocity_mps)
                    if self._capture_one(camera, i):
                        self._record_position(i, gantry.position())
                        i += 1
                        on_progress(i, 0)      # unknown total -> 0

                    pos = gantry.position()
                    if pos != 0.0 and pos >= params.end_position_m:
                        gantry.stop_moving()
                        completed = True
                        break

                    # Stakeholder calls capture_images twice per loop
                    if self._capture_one(camera, i):
                        self._record_position(i, gantry.position())
                        i += 1
                        on_progress(i, 0)
            finally:
                gantry.stop_moving()
                log.info("capture loop ended after %d frames (position "
                         "%.3f m); draining %d queued RGB frames",
                         i, gantry.position(),
                         self._rgb_queue.qsize() if self._rgb_queue else 0)
                self._flush_rgb()
                if completed:
                    gantry.go_home()    # stakeholder: home once the pass ends

            return i
        finally:
            camera.stop()
            gantry.shutdown()

    # ------------------------------------------------------------------ I/O

    def _capture_one(self, camera, idx: int) -> bool:
        """Capture one aligned frame pair. Returns True iff the frame was
        actually saved -- the caller must not advance the index otherwise
        (a skipped frame would leave a numbering gap and overcount
        n_frames in session.json)."""
        frames = camera.wait_for_frames()
        if frames is None:
            return False
        color_img, depth_img = frames

        # Stakeholder parity: write depth now, hand color off so the
        # capture thread never PNG-encodes inline (too slow, drops the
        # frame rate). put() blocks when the bounded queue is full --
        # backpressure instead of unbounded RAM growth.
        self._rgb_queue.put(
            (color_img.copy(), os.path.join(self.out_dir, "rgb", f"{idx}.png"))
        )
        self._cv2.imwrite(
            os.path.join(self.out_dir, "depth", f"{idx}.png"), depth_img)
        return True

    def _start_rgb_writers(self, params: CaptureParams) -> None:
        """Bound the queue to ~half the currently-available RAM (1.5 GiB at
        most) worth of frames, then start the writer threads."""
        frame_bytes = max(1, params.width * params.height * 3)
        cap_bytes = min(3 << 29, _available_ram_bytes() // 2)   # <= 1.5 GiB
        maxsize = max(32, cap_bytes // frame_bytes)
        log.info("RGB write queue: up to %d frames (%.0f MiB) buffered, "
                 "%d writer threads", maxsize,
                 maxsize * frame_bytes / 2**20, self.N_RGB_WRITERS)
        self._rgb_queue = queue.Queue(maxsize=maxsize)
        self._writer_threads = []
        for n in range(self.N_RGB_WRITERS):
            t = threading.Thread(target=self._rgb_writer_loop,
                                 name=f"rgb-writer-{n}", daemon=True)
            t.start()
            self._writer_threads.append(t)

    def _rgb_writer_loop(self) -> None:
        while True:
            item = self._rgb_queue.get()
            if item is None:
                self._rgb_queue.task_done()
                return
            img, path = item
            try:
                self._cv2.imwrite(path, img)
            except Exception:
                log.exception("failed writing %s", path)
            finally:
                self._rgb_queue.task_done()

    def _flush_rgb(self) -> None:
        """Wait until every queued RGB frame is on disk, then stop the
        writer threads. Safe to call when writers never started."""
        if self._rgb_queue is None:
            return
        self._rgb_queue.join()
        for _ in self._writer_threads:
            self._rgb_queue.put(None)
        for t in self._writer_threads:
            t.join(timeout=10.0)
        self._writer_threads = []
        self._rgb_queue = None

    def _save_intrinsics(self, camera) -> None:
        intr = camera.intrinsics() or {}
        for key, fname in (("depth", "kd_intrinsics.txt"),
                           ("color", "kdc_intrinsics.txt")):
            payload = intr.get(key)
            if payload is None:
                continue
            try:
                with open(os.path.join(self.out_dir, fname), "w") as f:
                    json.dump(payload, f, indent=4)
            except OSError as e:
                log.warning("failed to save %s: %s", fname, e)


class QuickScanCapture(RosCapture):
    """Camera + gantry together, falling back to simulated hardware for
    whichever piece isn't present. This is the one-click 'does the whole
    scan work?' path."""

    name = "quickscan"

    def __init__(self, serial_number: Optional[str] = None):
        super().__init__(serial_number,
                         allow_sim_camera=True, allow_sim_gantry=True)

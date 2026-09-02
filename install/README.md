# Linux lab setup

PhenoFusion3D uses an isolated project venv for its GUI, reconstruction code,
and RealSense Python binding. The gantry runs through the ROS installation that
already belongs to the lab computer.

## Safety boundary

`setup.sh` may create and populate `.venv-linux/` inside this repository. It
also writes `phenofusion3d.desktop` to the current user's XDG applications
directory (normally `~/.local/share/applications`) so PhenoFusion3D appears in
Ubuntu Activities. It does not run `sudo` or `apt`, install ROS or RealSense
system components, add repositories or signing keys, load drivers, write
`/etc`, change shell startup files, or install a system-wide launcher. It also
does not pip-install `rospy` into the GUI venv.

The compatibility entry point `install/install_linux.sh` simply delegates to
the same root script.

## Existing lab prerequisites

- Linux with an existing Python 3.10–3.12 and its `venv` module.
- The lab's working RealSense USB/system configuration.
- ROS 1 and the gantry driver already installed.
- The catkin workspace containing `position_controller_ros` when Go-to and
  Go-home are needed. Jog and Stop use the core ROS message packages.

These machine-level prerequisites are deliberately verified rather than
installed.

## Install the project venv

From the repository root:

```bash
./setup.sh
```

The script installs the `lab` project extra in `.venv-linux`. This includes the
GUI/reconstruction dependencies and `pyrealsense2` inside that venv. The ROS
gantry helper remains outside the venv and selects an existing compatible ROS
interpreter at runtime.

To use a different venv directory inside the repository:

```bash
PHENOFUSION_VENV=.venv-ui ./setup.sh
```

The setup script never deletes or recreates an existing directory. If an
existing target is not a usable compatible venv, choose another path or move it
yourself.

After setup succeeds, press the Super key and search for **PhenoFusion3D** in
Ubuntu Activities. The launcher is updated safely whenever `setup.sh` is run
again and always points to the venv in the current checkout.

## ROS workspace discovery

The application checks the current environment, `/opt/ros/*/setup.bash`, and
the conventional `~/catkin_ws`, `~/ros_ws`, `~/workspace`, and `~/ws`
workspaces. For another location, point to it before launch:

```bash
export PHENOFUSION_ROS_WS=/path/to/gantry_workspace
```

You may also source ROS and the workspace normally before starting the app.
No shell profile is edited automatically.

## Check without changing anything

```bash
./setup.sh --check
```

This verifies the existing venv imports and resolves a compatible ROS runtime.
It also reports every currently connected RealSense model and serial. It
creates and installs nothing.

One RGB-D camera is selected automatically at capture time. When several are
connected, choose one before launching:

```bash
export PHENOFUSION_CAMERA_SERIAL=<serial>
```

## Launch

Open **PhenoFusion3D** from Ubuntu Activities, or launch it from a terminal:

```bash
source .venv-linux/bin/activate
python main.py
```

Camera-only operation and manual gantry operation are independent. Choose
`RealSense Only` to capture without motion, use the Gantry Control panel to move
without opening the camera, or explicitly choose `ROS + Gantry` for a combined
capture pass.

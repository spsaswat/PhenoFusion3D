# PhenoFusion3D -- Lab install guide

This page is for sysadmins / lab operators setting up PhenoFusion3D on a
new machine. End-users only need to run the launcher script.

## Two supported environments

| Target | Backend used | Hardware |
|---|---|---|
| Lab Linux machine (rover / gantry rig) | `ros` -- ROS + RealSense + gantry | Intel RealSense D405 + ROS-controlled linear gantry |
| Windows dev / testing | `realsense` -- RealSense camera only | Intel RealSense D405 connected via USB |

The ROS backend is only available where `rospy` can be imported. On
Windows the Capture panel automatically falls back to the RealSense-only
backend.

## Prerequisites

### Lab Linux
- Ubuntu 20.04 or 22.04
- ROS Noetic (Ubuntu 20) or ROS Humble (Ubuntu 22), already sourced via `source /opt/ros/<distro>/setup.bash`
- `librealsense2` SDK runtime (`sudo apt install librealsense2-dkms librealsense2-utils librealsense2-dev`)
- Python 3.10+

### Windows (dev / sanity testing)
- Windows 10/11
- Python 3.10+ from python.org or Microsoft Store
- [Intel RealSense SDK 2.0 runtime](https://github.com/IntelRealSense/librealsense/releases) (only required if you actually want to plug a camera in)

## Install

### Linux

```bash
git clone <repo-url>
cd PhenoFusion3D
chmod +x install/install_linux.sh
./install/install_linux.sh
```

The script:
- creates `venv/` with `--system-site-packages` so it can see the
  ROS-installed `rospy`,
- installs the package in editable mode with `pip install -e ".[ros]"`,
- imports each dependency to confirm the install is working.

### Windows

```powershell
git clone <repo-url>
cd PhenoFusion3D
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install\install_windows.ps1
```

The script:
- creates `venv\`,
- installs the package in editable mode with `pip install -e ".[windows]"`,
- imports each dependency to confirm the install is working.

## Launch

```bash
# Linux
source venv/bin/activate
python main.py

# Windows
.\venv\Scripts\Activate.ps1
python main.py
```

## Smoke test the camera

Open the app, look at the **Data Capture** panel:

1. Pick **RealSense Only** as the backend.
2. Set **Duration (s)** = `2`.
3. Click **Capture**.
4. After 2 s, the panel should report `Done. ~60 frames -> data/captures/<timestamp>`.
5. The **RGB Images** / **Depth Images** fields in the Data Loading panel
   should auto-populate with the new folder.
6. Click **Quick Check** in the Data Quality panel. It should return
   verdict **PASS** within ~30 s for a healthy capture.

If the camera isn't detected, verify:

```bash
# Linux
realsense-viewer

# Windows
"Intel RealSense Viewer.exe"
```

## Building a portable AppImage (Linux)

For lab Linux machines that don't have Python set up, or for handing the
app to a collaborator without making them run the install script, build
a single-file AppImage:

```bash
chmod +x install/build_appimage.sh
./install/build_appimage.sh
```

Output: `dist/PhenoFusion3D-<version>-x86_64.AppImage` (~600-800 MB --
Open3D and PyQt5 are heavy).

The script:

- Uses [`python-appimage`](https://github.com/niess/python-appimage) to
  pull a manylinux Python interpreter (default 3.11; override with
  `PY_VERSION=3.10 ./install/build_appimage.sh`).
- Stages a clean copy of the repo (excluding `venv/`, `data/`, `.git/`,
  captured datasets, etc.) so the bundle stays small.
- `pip install`s the project + runtime deps from
  [install/appimage/requirements.txt](install/appimage/requirements.txt)
  into the AppDir.
- Wraps it with the launcher in
  [install/appimage/entrypoint.sh](install/appimage/entrypoint.sh),
  which clears any host Qt env vars and conditionally exposes
  `/opt/ros/<distro>/lib/python3/dist-packages` so the ROS capture
  backend keeps working when the AppImage runs on the lab Linux box.
- Produces a self-contained, single-file executable.

### Build host requirements

- Linux x86_64 (AppImage is glibc-only; cannot be built on Windows or macOS).
- Python 3.10+ on PATH (for running `python-appimage` itself; the
  bundled runtime is independent).
- `rsync`.
- Internet access on first build.

### Running the AppImage

```bash
chmod +x PhenoFusion3D-0.2.0-x86_64.AppImage
./PhenoFusion3D-0.2.0-x86_64.AppImage
```

If the target machine lacks FUSE 2 (some minimal containers /
hardened distros), use the extract-and-run mode:

```bash
./PhenoFusion3D-0.2.0-x86_64.AppImage --appimage-extract-and-run
```

### Capture backends inside the AppImage

The AppImage intentionally does **not** bundle `rospy` or
`pyrealsense2`:

- `rospy` requires a matching ROS distribution on the host; the
  entrypoint adds `/opt/ros/<distro>/lib/python3/dist-packages` to
  `PYTHONPATH` automatically when present (looks for `noetic`,
  `humble`, `jazzy`).
- `pyrealsense2` needs the `librealsense2` userspace SDK + udev rules
  installed on the host. Install it system-wide once
  (`sudo apt install librealsense2-utils python3-pyrealsense2`) and
  the entrypoint will pick it up via the same ROS dist-packages path
  on lab machines, or via the host site-packages on dev machines.

For dev-only / no-camera use the AppImage works out of the box --
loading existing RGB-D folders and reconstructing them needs none of
the above.

## Common issues

- **`rospy` import fails on Linux**
  - Make sure ROS is sourced *before* running `install_linux.sh` so the
    venv inherits the ROS PYTHONPATH.
- **`PyQt5` plugin error on Windows**
  - Re-install PyQt5: `pip install --force-reinstall PyQt5`.
- **`pyrealsense2` not found**
  - On Linux x86_64 / Windows, `pip install pyrealsense2` should just
    work. On ARM Linux you need to build librealsense from source.
- **AppImage build fails with `python-appimage: command not found`**
  - The build script installs `python-appimage` into a private build
    venv at `build/appimage/venv/`. Delete that directory and rerun
    `./install/build_appimage.sh` to recreate it cleanly.
- **AppImage launches but crashes with `qt.qpa.plugin: Could not load
  the Qt platform plugin "xcb"`**
  - The host is missing X11 client libs. Install them with
    `sudo apt install libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0`
    (Ubuntu / Debian). This is a host requirement, not a build bug --
    PyQt5 wheels assume xcb is present.

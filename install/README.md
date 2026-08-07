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

#### L515 (LiDAR Camera) owners: extra steps

Intel discontinued the L515 in August 2021 and dropped its enumeration
from librealsense in releases >= 2.55. The default `pyrealsense2` wheel
on PyPI is now too new to see an L515; `rs.context().query_devices()`
returns 0 devices even when Windows clearly sees the camera.

To use an L515 with PhenoFusion3D:

1. **Use Python 3.10 or 3.11** (not 3.12+). The L515-compatible
   `pyrealsense2==2.54.2.5684` wheel is only built up to Python 3.11.
2. **Install Intel RealSense SDK 2.0 v2.54.2** for Windows from
   [the librealsense releases page](https://github.com/IntelRealSense/librealsense/releases/tag/v2.54.2).
   This also gives you `Intel RealSense Viewer` for sanity-testing the
   camera independent of Python.
3. **Install the L515 extras** instead of plain `windows`:

    ```powershell
    py -3.11 -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -e ".[windows,l515]"
    ```

   This pins `pyrealsense2>=2.54.0,<2.55`, which keeps L515 enumeration
   working. D400 / D500 series users do not need this extras group.

## Install

### Linux

```bash
git clone <repo-url>
cd PhenoFusion3D
chmod +x install/install_linux.sh
./install/install_linux.sh
```

The script:
- picks a Python >= 3.10 interpreter (prefers `python3.12`, then `3.11`,
  then `3.10`, then `python3`); if none is available it apt-installs
  `python3.10` (using the `deadsnakes` PPA as a fallback on Ubuntu 20.04),
- creates `.venv-linux/` with `--system-site-packages` so it can see the
  ROS-installed `rospy`,
- installs the package in editable mode with `pip install -e ".[ros]"`,
- detects missing native runtime libs by `ldd`-ing the Qt xcb platform
  plugin and apt-installs them in a single sudo call (the most common
  fresh-Ubuntu offenders are `libxcb-icccm4`, `libxcb-keysyms1`,
  `libxcb-cursor0`, `libxkbcommon-x11-0`, `libegl1`, `libgl1`),
- imports each dependency to confirm the install is working.

The same Python-picking and native-lib install logic is duplicated in
`launch.sh`, so on a fresh lab machine **just `bash launch.sh` is
enough** -- it will create the venv, install Python deps, install
missing system libs, and open the GUI in one shot. `install_linux.sh`
exists primarily as the "ROS-first" path that sysadmins prefer to run
once before any user touches the box.

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
bash launch.sh

# (manual alternative)
# source .venv-linux/bin/activate
# python main.py

# Windows
.\venv\Scripts\Activate.ps1
python main.py
```

`launch.sh` is the recommended Linux/WSL path for day-to-day usage. It uses a dedicated Linux environment (`.venv-linux`), installs missing Python packages, and applies a PyQt plugin-path fix to avoid common Qt `xcb` startup failures.

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
- **L515 plugged in but capture says "No Intel RealSense camera was found"**
  - Symptom: Windows Device Manager shows the L515 healthy, but
    `rs.context().query_devices()` returns 0. Cause: `pyrealsense2 >= 2.55`
    dropped L515 support after Intel EOL'd the camera. Fix: use Python
    3.10 / 3.11 and install with `pip install -e ".[windows,l515]"`
    (see the L515 section above). On startup, `main.py` runs a self-check
    that surfaces this diagnosis as a modal dialog before you click Capture.
- **AppImage build fails with `python-appimage: command not found`**
  - The build script installs `python-appimage` into a private build
    venv at `build/appimage/venv/`. Delete that directory and rerun
    `./install/build_appimage.sh` to recreate it cleanly.
- **AppImage launches but crashes with `qt.qpa.plugin: Could not load
  the Qt platform plugin "xcb"`**
  - The host is missing X11 client libs. The dev install path
    (`bash launch.sh` / `./install/install_linux.sh`) auto-detects and
    apt-installs them; for the AppImage you need to install them
    manually on the host. The full set commonly required on a fresh
    Ubuntu is:
    ```bash
    sudo apt install libxcb-icccm4 libxcb-keysyms1 libxcb-image0 \
        libxcb-render-util0 libxcb-render0 libxcb-shape0 libxcb-shm0 \
        libxcb-sync1 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
        libxcb-randr0 libxcb-cursor0 libxkbcommon0 libxkbcommon-x11-0 \
        libegl1 libgl1
    ```
    This is a host requirement, not a build bug -- PyQt5 wheels assume
    xcb is present.

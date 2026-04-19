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

## Common issues

- **`rospy` import fails on Linux**
  - Make sure ROS is sourced *before* running `install_linux.sh` so the
    venv inherits the ROS PYTHONPATH.
- **`PyQt5` plugin error on Windows**
  - Re-install PyQt5: `pip install --force-reinstall PyQt5`.
- **`pyrealsense2` not found**
  - On Linux x86_64 / Windows, `pip install pyrealsense2` should just
    work. On ARM Linux you need to build librealsense from source.

<#
install/install_windows.ps1
---------------------------
Windows installer for PhenoFusion3D (RealSense-only capture, no ROS).

Prereqs:
  - Python 3.10+
  - Intel RealSense SDK 2.0 runtime installed (for camera capture only)

Usage (PowerShell):
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\install\install_windows.ps1
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found on PATH. Install Python 3.10+ first."
    exit 1
}

if (-not (Test-Path "venv")) {
    Write-Host "[install] Creating venv..."
    python -m venv venv
}

. .\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[windows]"

Write-Host ""
Write-Host "[install] Verifying imports..."
@'
import importlib
import os
import sys
from importlib.metadata import version

ok = True
for mod in ("PyQt5", "open3d", "cv2", "numpy", "natsort"):
    try:
        importlib.import_module(mod); print(f"  OK  {mod}")
    except Exception as e:
        ok = False; print(f"  FAIL {mod}: {e}")

# Every supported camera uses this exact RealSense wheel.
try:
    required = "2.54.2.5684"
    actual = version("pyrealsense2")
    if actual != required:
        raise RuntimeError(f"found {actual}, required {required}")
    rs = importlib.import_module("pyrealsense2")
    devices = list(rs.context().query_devices())
    print(f"  OK  pyrealsense2 {actual}; detected {len(devices)} camera(s)")
    serials = []
    for device in devices:
        name = device.get_info(rs.camera_info.name)
        serial = device.get_info(rs.camera_info.serial_number)
        serials.append(serial)
        print(f"      - {name} (serial {serial})")
    selected = os.environ.get("PHENOFUSION_CAMERA_SERIAL", "").strip()
    if selected:
        state = "detected" if selected in serials else "not currently detected"
        print(f"      PHENOFUSION_CAMERA_SERIAL={selected} ({state})")
    elif len(devices) > 1:
        print('      Choose one before launch:')
        print('      $env:PHENOFUSION_CAMERA_SERIAL = "<serial>"')
except Exception as e:
    ok = False
    print(f"  FAIL pyrealsense2: {e}")

sys.exit(0 if ok else 1)
'@ | python -
if ($LASTEXITCODE -ne 0) {
    throw "Dependency verification failed."
}

Write-Host ""
Write-Host "[install] Done. Launch the app with:"
Write-Host "    .\venv\Scripts\Activate.ps1"
Write-Host "    python main.py"

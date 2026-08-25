<#
install/install_windows.ps1
---------------------------
Windows installer for PhenoFusion3D (RealSense-only capture, no ROS).

This script only ever creates and populates the project venv. It does
not install anything machine-wide -- no winget, no MSI, no PATH edits.

Prereqs (install these yourself first):
  - Python 3.10 or 3.11 (the pinned pyrealsense2 2.54.2.5684 has no
    wheel for 3.12+)
  - Intel RealSense SDK 2.0 v2.54.2 runtime, for camera capture
    (see docs/L515_SETUP.md)

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

# Pin every package the venv already has to its installed version and
# pass that to pip as constraints. pip can then only ADD what is
# missing -- it cannot upgrade, downgrade or replace anything that
# already works (notably a pinned pyrealsense2). pip itself is left at
# whatever version the venv was created with, on purpose.
$constraints = Join-Path $root "venv\phenofusion-constraints.txt"
python -m pip freeze --exclude-editable |
    Where-Object { $_ -match '^[A-Za-z0-9._-]+==' } |
    Set-Content -Encoding ascii $constraints

python -m pip install --no-input -c $constraints -e ".[windows]"

Write-Host ""
Write-Host "[install] Verifying imports..."
python - <<'PY'
import importlib, sys
ok = True
for mod in ("PyQt5", "open3d", "cv2", "numpy", "natsort"):
    try:
        importlib.import_module(mod); print(f"  OK  {mod}")
    except Exception as e:
        ok = False; print(f"  FAIL {mod}: {e}")

# pyrealsense2 is optional but expected on Windows
try:
    importlib.import_module("pyrealsense2")
    print("  OK  pyrealsense2")
except Exception as e:
    print(f"  WARN pyrealsense2: {e} (camera capture won't work without it)")

sys.exit(0 if ok else 1)
PY

Write-Host ""
Write-Host "[install] Done. Launch the app with:"
Write-Host "    .\venv\Scripts\Activate.ps1"
Write-Host "    python main.py"

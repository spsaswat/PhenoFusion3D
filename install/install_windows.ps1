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

# L515 setup on Windows + session change log

This document is the durable record of the L515-on-Windows fix and the
related changes made to make PhenoFusion3D usable with the Intel
RealSense LiDAR Camera **L515**. It is intentionally specific to the
L515 because the L515 is end-of-life and needs a different software
stack than the D-series cameras the project was originally written for.

D400 / D500 owners do not need to read most of this document; the
default install instructions in [`install/README.md`](../install/README.md)
still apply to them.

---

## TL;DR

If you have an Intel RealSense L515 and a Windows host:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e ".[windows,l515]"
.\launch.bat
```

If you see the warning dialog "PhenoFusion3D -- launched from WSL,
camera will not work" or "no RealSense camera detected", the dialog
itself tells you which trap you hit. The most common ones are below.

---

## The underlying problem

Intel discontinued the L515 in **August 2021**. The L515 enumeration
code path was dropped from `librealsense` in releases **>= 2.55**. The
default `pyrealsense2` wheel pulled by `pip install pyrealsense2` (and
by `requirements.txt`'s `pyrealsense2>=2.54.0` with no upper bound) is
now `2.57.7` or newer, which **physically cannot see an L515** even
when Windows itself has the camera fully enumerated and healthy on the
USB bus. The error surfaced by the app is:

```
ERROR: No Intel RealSense camera was found by pyrealsense2/librealsense.
```

Intel has not released firmware for the L515 since `1.5.8.1` (2022)
and is not going to fix this regression. Three constraints follow
directly from this and shape everything below:

1. The **last L515-compatible release is `2.54.2.5684`**.
2. PyPI **only ships `pyrealsense2 2.54.2.5684` for Python 3.10 and
   3.11** -- there is no Python 3.12+ wheel for the 2.54 line.
3. WSL2 does not pass USB through to Linux by default, so no
   pyrealsense2 install inside WSL can see an L515 plugged into the
   Windows host (regardless of SDK version). The L515 is a Windows
   device for the purposes of this project.

---

## Files added or modified in this fix

### `pyproject.toml`

Added a new optional-dependencies group `l515` that pins the SDK to
`>=2.54.0,<2.55` so an L515 owner explicitly opts into the L515-stable
line:

```toml
[project.optional-dependencies]
windows = [
    "pyrealsense2>=2.54.0",
]
l515 = [
    "pyrealsense2>=2.54.0,<2.55",
]
```

Also added `[tool.pytest.ini_options] testpaths = ["tests"]` so plain
`pytest` from the repo root no longer crashes at collection on the
manual-test scripts `test_with_one_img.py` / `test_with_whole_seq.py`
that live in the repo root and raise `SystemExit` at import time.

### `requirements.txt`

Added an inline comment block above `pyrealsense2>=2.54.0` documenting
the L515 caveat, so an L515 owner sees the warning at the same place
where they would otherwise pin the dependency.

### `install/README.md`

Added an "L515 (LiDAR Camera) owners: extra steps" section under the
Windows prerequisites, plus a matching entry under "Common issues" so
the next person who hits this can find their way out.

### `main.py`

Replaced the bare entry point with one that runs a small **startup
self-check** before the GUI opens:

- Logs the active Python interpreter, the working directory, and
  whether we appear to be running under WSL.
- Imports `pyrealsense2` (if available), reports its version, and
  notes whether that version supports L515 enumeration.
- Calls `rs.context().query_devices()` and reports the count plus
  device name / firmware / USB type / serial for each.

If the self-check finds something clearly wrong, a modal `QMessageBox`
explains the cause and the exact remediation **before** the user
clicks Capture. Three branches cover the common cases, in priority
order:

1. **Running under WSL** -- WSL-specific message ("WSL2 doesn't pass
   USB through to Linux by default; launch from PowerShell instead",
   with the exact PowerShell commands).
2. **`pyrealsense2` not installed** -- camera capture is disabled;
   shows the right `pip install` command for D-series vs L515.
3. **`pyrealsense2` installed but `query_devices()` returns 0** --
   generic camera-not-found troubleshooting (USB 3, no hubs, no other
   app holding the camera). If the detected SDK version is `>= 2.55`
   the dialog **automatically appends an L515-specific hint** pointing
   at the `[l515]` extras and Python 3.10 / 3.11.

WSL detection uses three signals (the env vars `WSL_DISTRO_NAME` /
`WSL_INTEROP`, plus `/proc/version` containing "microsoft"); any one
is enough. The detection is conservative -- false positives only
result in a more-helpful dialog, not a blocked launch.

#### Subtle: COM apartment ordering

The self-check must run **after** `QApplication(sys.argv)`, not
before. Both Qt and `pyrealsense2`'s Windows backend init COM, but
they want different threading apartments:

- `QApplication` calls `OleInitialize`, which insists on the
  **single-threaded apartment (STA)** for the GUI thread.
- `librealsense`'s Media Foundation backend touches MF on the calling
  thread, which initialises COM as **multi-threaded (MTA)**.

Whichever runs second loses with `RPC_E_CHANGED_MODE` (`0x80010106`).
If the self-check ran first, Qt then died at startup with:

```
QWindowsContext: OleInitialize() failed:  "COM error 0xffffffff80010106
RPC_E_CHANGED_MODE (Unknown error 0x080010106)"
```

`main()` therefore creates `QApplication` first and only then runs
`_startup_self_check()`. MF in STA is fine; MF after MTA-then-STA is
not.

### `launch.ps1` (new)

Tiny PowerShell launcher at the repo root. Resolves to repo root via
`$PSScriptRoot`, activates `.\venv\Scripts\Activate.ps1`, sanity-checks
that `$env:VIRTUAL_ENV` is now set, and runs `python main.py`. Prints
`[launch] active venv: <path>` so the user can see at a glance whether
they're in the right env.

### `launch.bat` (new)

CMD wrapper around `launch.ps1`. The motivation is purely friction:
this Windows machine has `Get-ExecutionPolicy LocalMachine = AllSigned`,
which refuses to run unsigned `.ps1` scripts. CMD `.bat` files are
not subject to PowerShell's execution policy, so `launch.bat`:

```bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" %*
```

…runs the launcher with policy bypassed for that single invocation
without changing any persistent setting. Double-clickable from
Explorer; runnable from any shell as `.\launch.bat`.

### `docs/L515_SETUP.md` (this file)

Durable record of all of the above so the institutional knowledge
doesn't live only in chat history or commit messages.

---

## System-level changes made on this machine

These are not in the repo; they are changes made to the developer's
Windows install during the fix.

| Action | Where | Why |
|---|---|---|
| Installed Python 3.11.9 | `C:\Users\hc240\AppData\Local\Programs\Python\Python311\` (via `winget install Python.Python.3.11 --scope user`) | `pyrealsense2 2.54.2.5684` only has wheels for Python <= 3.11. |
| Created Windows venv `venv\` on Python 3.11 | repo root | Replaces a broken WSL/Linux venv that was previously in `venv\`. |
| `pip install -e ".[windows,dev]"` inside the new `venv\` | repo root | Full app deps incl. the L515-compatible `pyrealsense2 2.54.2.5684`. |
| Downloaded Intel RealSense SDK 2.0 v2.54.2 installer | `%TEMP%\Intel.RealSense.SDK-WIN10-2.54.2.5684.exe` | Install was cancelled at UAC; not required for the app, but useful for diagnostics via `Intel RealSense Viewer`. Run with `Start-Process -FilePath "$env:TEMP\Intel.RealSense.SDK-WIN10-2.54.2.5684.exe" -ArgumentList '/S' -Verb RunAs -Wait` if/when desired. |
| Deleted `venv\` (the original WSL/Linux one) | repo root | Could not run from PowerShell; could not see USB devices from WSL. |
| Deleted `venv-win\` | repo root | Throwaway diagnostic venv on Python 3.12; useless for L515. |

The user has separately accumulated `.\.venv\`, `.\.venv312\`, and
`.\venv_win\` directories in the repo. These are **not used by this
project** and can be removed at any time:

```powershell
Remove-Item -Recurse -Force .\.venv, .\.venv312, .\venv_win
```

---

## How to verify the install

After `.\launch.bat`, the terminal should print:

```
[launch] active venv: C:\COMP3500\PhenoFusion3DFork\Howard-sPhenoFusion3D\venv
[startup] Python:       C:\COMP3500\PhenoFusion3DFork\Howard-sPhenoFusion3D\venv\Scripts\python.exe
[startup] Working dir:  C:\COMP3500\PhenoFusion3DFork\Howard-sPhenoFusion3D
[startup] pyrealsense2: 2.54.2.5684
[startup] RealSense devices visible: 1
[startup]   - Intel RealSense L515 (fw 1.5.8.1, USB 3.2, sn <serial>)
```

…then the GUI opens with no warning dialog. From the Data Capture
panel, set Duration = 2 s and click Capture; you should get
~17 frames in `data\captures\<timestamp>\` with `rgb\`, `depth\`,
`session.json`, `kdc_intrinsics.txt`, and `kd_intrinsics.txt`.

A non-GUI sanity check, equivalent to what the startup self-check
does:

```powershell
.\venv\Scripts\python.exe -c "import pyrealsense2 as rs; ds = list(rs.context().query_devices()); print('count:', len(ds)); [print(' ', d.get_info(rs.camera_info.name), '| fw', d.get_info(rs.camera_info.firmware_version), '| usb', d.get_info(rs.camera_info.usb_type_descriptor)) for d in ds]"
```

Expected:

```
count: 1
  Intel RealSense L515 | fw 1.5.8.1 | usb 3.2
```

---

## Decision log: things considered and not done

- **Pinning `pyrealsense2>=2.54.0,<2.55` in the default `[windows]` /
  `[ros]` extras**: rejected. D400 / D500 owners benefit from the
  newer SDK and are the project's primary target. The `[l515]`
  opt-in is correct here.
- **Bundling the Intel RealSense SDK 2.0 installer**: rejected.
  Distributing Intel's installer is a licensing question and the wheel
  alone is sufficient for capture; the installer only helps with the
  Intel Viewer, which is a diagnostic-time tool.
- **usbipd-win passthrough so the app can run from WSL**: rejected.
  The L515 is a 5+ Gbps USB 3 device; usbipd-win works but adds real
  overhead and complexity, and the project already has a clean
  Windows-native path. WSL is an explicitly-warned-against trap in
  the new self-check rather than a supported configuration.
- **`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`**: not done
  automatically. It is a per-user persistent setting and may be
  against IT policy on managed machines. `launch.bat` sidesteps the
  policy without changing it; users who prefer `.\launch.ps1`
  directly can opt in by running the `Set-ExecutionPolicy` command
  themselves.

---

## Provenance

- All file edits and verifications were performed in PowerShell on the
  developer's Windows host on **2026-05-04** while the L515 was
  plugged in (firmware `1.5.8.1`, USB 3.2). The full project test
  suite (`pytest tests/`) reports **45 passed, 1 deselected** with
  the changes in place.
- Real 2-second L515 capture via `RealSenseCapture.start(...)`
  produced 17 RGB + 17 depth PNGs plus `session.json` and intrinsics
  files under `data\captures\<timestamp>\`.
- Headless smoke (`launch.bat` with `QT_QPA_PLATFORM=offscreen`)
  produced clean diagnostic output and no `OleInitialize` /
  `RPC_E_CHANGED_MODE` errors after the COM-ordering fix.

"""
app/o3d_check.py
----------------
Guard for Open3D on machines where importing it kills the process.

On the lab rig (a VirtualBox VM without AVX passthrough) `import open3d`
dies with SIGILL (Illegal instruction) -- not an ImportError, the whole
process is gone. So the import is probed in a THROWAWAY subprocess
first; only if that survives is it safe to import open3d in-process.

Capture (camera + gantry) never needs open3d; only reconstruction,
quality checks, post-processing, and PLY export do. Those features call
`open3d_usable()` first and show this module's error message instead of
taking the app down.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional, Tuple

_cached: Optional[Tuple[bool, str]] = None


def open3d_usable(timeout_s: float = 90.0) -> Tuple[bool, str]:
    """(ok, error_message). Probes `import open3d` in a subprocess once
    per app run; the result is cached."""
    global _cached
    if _cached is not None:
        return _cached

    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import open3d"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        _cached = (False, "Probing 'import open3d' timed out -- open3d "
                          "looks unusable on this machine.")
        return _cached

    if proc.returncode == 0:
        _cached = (True, "")
    elif proc.returncode == -4:  # SIGILL
        _cached = (False,
                   "open3d crashes this machine's Python with 'Illegal "
                   "instruction' (SIGILL): the CPU (or VM) does not expose "
                   "the AVX instructions the open3d wheel was built with. "
                   "On the lab VirtualBox VM this needs a host-side fix "
                   "(disable Hyper-V / Core Isolation on the Windows host "
                   "so VirtualBox can pass AVX through). Capture still "
                   "works; reconstruction is disabled until then.")
    else:
        detail = (proc.stderr or "").strip().splitlines()
        detail = detail[-1] if detail else f"exit code {proc.returncode}"
        _cached = (False, f"open3d failed to import: {detail}")
    return _cached

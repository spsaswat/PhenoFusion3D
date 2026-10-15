"""Capacity preconditions for a capture, isolated from any camera import."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import base  # noqa: E402
from capture.base import (  # noqa: E402
    GIB,
    CaptureParams,
    ensure_capture_capacity,
    frame_pair_bytes,
)


class _DiskUsage:
    def __init__(self, free):
        self.free = free
        self.total = free
        self.used = 0


# ---------------------------------------------------------------- memory read

def test_available_memory_prefers_memavailable_over_memfree(
    monkeypatch, tmp_path
):
    """MemFree excludes the reclaimable page cache; MemAvailable does not.

    Reading MemFree made a capture that fits comfortably look impossible on any
    machine that had been running long enough to fill its page cache.
    """
    meminfo = tmp_path / 'meminfo'
    meminfo.write_text(
        'MemTotal:       16384000 kB\n'
        'MemFree:          400000 kB\n'
        'MemAvailable:   12000000 kB\n'
        'Cached:         11000000 kB\n'
    )
    monkeypatch.setattr(base, 'MEMINFO_PATH', str(meminfo))

    assert base._meminfo_bytes('MemAvailable') == 12000000 * 1024
    assert base._meminfo_bytes('MemFree') == 400000 * 1024
    assert base._available_memory_bytes() == 12000000 * 1024


def test_available_memory_falls_back_when_meminfo_is_absent(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(base, 'MEMINFO_PATH', str(tmp_path / 'missing'))
    assert base._meminfo_bytes('MemAvailable') is None
    # No /proc/meminfo: either the sysconf fallback answers or nothing does.
    fallback = base._available_memory_bytes()
    assert fallback is None or fallback > 0


def test_unparsable_meminfo_field_does_not_raise(monkeypatch, tmp_path):
    meminfo = tmp_path / 'meminfo'
    meminfo.write_text('MemAvailable:\nMemFree: not-a-number kB\n')
    monkeypatch.setattr(base, 'MEMINFO_PATH', str(meminfo))
    assert base._meminfo_bytes('MemAvailable') is None
    assert base._meminfo_bytes('MemFree') is None


def test_a_full_gantry_pass_fits_on_a_machine_with_a_warm_page_cache(
    monkeypatch, tmp_path
):
    """The reported regression: 16 GiB host, page cache full, capture refused."""
    meminfo = tmp_path / 'meminfo'
    meminfo.write_text(
        'MemTotal:       16384000 kB\n'
        'MemFree:          400000 kB\n'      # 0.38 GiB -- what was being read
        'MemAvailable:   13000000 kB\n'      # 12.4 GiB -- what is really usable
    )
    monkeypatch.setattr(base, 'MEMINFO_PATH', str(meminfo))
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(40 * GIB)
    )

    params = CaptureParams()
    # 0.005 m to 1.65 m at 38 mm/s, 30 fps.
    frames = 1299
    required = frame_pair_bytes(params.width, params.height) * frames
    assert required / GIB == pytest.approx(5.57, abs=0.01)

    # Must not raise.
    limit = ensure_capture_capacity(
        str(tmp_path), params, frames, params.width, params.height
    )
    assert limit >= required

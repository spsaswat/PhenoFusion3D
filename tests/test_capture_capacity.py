"""Capacity preconditions for a capture, isolated from any camera import."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import base  # noqa: E402
from capture.base import (  # noqa: E402
    DISK_RESERVE_BYTES,
    GIB,
    MEMORY_HEADROOM_FRACTION,
    PNG_DISK_FACTOR,
    CaptureParams,
    capture_buffer_limit_bytes,
    ensure_capture_capacity,
    frame_pair_bytes,
)


class _DiskUsage:
    def __init__(self, free):
        self.free = free
        self.total = free
        self.used = 0


@pytest.fixture
def plenty(monkeypatch, tmp_path):
    """A host with ample memory and disk, so one limit can be varied alone."""
    monkeypatch.setattr(base, '_available_memory_bytes', lambda: 64 * GIB)
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(64 * GIB)
    )
    return str(tmp_path)


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


# ---------------------------------------------------------------- disk factor

def test_png_output_is_not_assumed_larger_than_the_raw_frames():
    """A 1.1 factor demanded 10% more disk than the raw frames can produce."""
    assert PNG_DISK_FACTOR <= 1.0


def test_a_capture_matching_the_usable_disk_is_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(base, '_available_memory_bytes', lambda: 64 * GIB)
    width = height = 1000
    frames = 100
    required = frame_pair_bytes(width, height) * frames
    monkeypatch.setattr(
        base.shutil,
        'disk_usage',
        lambda _path: _DiskUsage(required + DISK_RESERVE_BYTES),
    )
    params = CaptureParams(max_buffer_gib=64.0)

    limit = ensure_capture_capacity(
        str(tmp_path), params, frames, width, height
    )
    assert limit >= required


def test_a_capture_exceeding_the_usable_disk_is_still_rejected(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(base, '_available_memory_bytes', lambda: 64 * GIB)
    width = height = 1000
    frames = 100
    required = frame_pair_bytes(width, height) * frames
    monkeypatch.setattr(
        base.shutil,
        'disk_usage',
        lambda _path: _DiskUsage(required // 2 + DISK_RESERVE_BYTES),
    )
    params = CaptureParams(max_buffer_gib=64.0)

    with pytest.raises(RuntimeError, match='output disk'):
        ensure_capture_capacity(str(tmp_path), params, frames, width, height)


def test_a_disk_below_the_safety_reserve_is_reported_as_such(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(DISK_RESERVE_BYTES)
    )
    with pytest.raises(RuntimeError, match='512 MiB safety reserve'):
        capture_buffer_limit_bytes(str(tmp_path), 6.0)


# ---------------------------------------------------------------- messages

def test_the_rejection_names_memory_when_memory_is_what_ran_out(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(base, '_available_memory_bytes', lambda: 1 * GIB)
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(64 * GIB)
    )
    params = CaptureParams(max_buffer_gib=64.0)

    with pytest.raises(RuntimeError) as failure:
        ensure_capture_capacity(str(tmp_path), params, 1000, 1280, 720)
    message = str(failure.value)
    assert 'available memory' in message
    assert 'Close other applications' in message
    assert 'output disk' not in message


def test_the_rejection_names_the_disk_when_the_disk_is_what_ran_out(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(base, '_available_memory_bytes', lambda: 64 * GIB)
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(GIB)
    )
    params = CaptureParams(max_buffer_gib=64.0)

    with pytest.raises(RuntimeError) as failure:
        ensure_capture_capacity(str(tmp_path), params, 1000, 1280, 720)
    message = str(failure.value)
    assert 'output disk' in message
    assert 'Free space on the output disk' in message
    assert 'available memory' not in message


def test_the_rejection_names_the_configured_ceiling_when_that_binds(plenty):
    params = CaptureParams(max_buffer_gib=0.001)
    with pytest.raises(RuntimeError) as failure:
        ensure_capture_capacity(plenty, params, 1000, 1280, 720)
    message = str(failure.value)
    assert 'configured ceiling' in message
    assert 'Raise max_buffer_gib' in message


def test_the_rejection_reports_what_the_capture_actually_needs(plenty):
    params = CaptureParams(max_buffer_gib=0.001)
    required = frame_pair_bytes(1280, 720) * 1000
    with pytest.raises(RuntimeError) as failure:
        ensure_capture_capacity(plenty, params, 1000, 1280, 720)
    assert f'{required / GIB:.2f} GiB' in str(failure.value)


# ---------------------------------------------------------------- invariants

def test_the_limit_is_the_smallest_of_the_three(monkeypatch, tmp_path):
    monkeypatch.setattr(base, '_available_memory_bytes', lambda: 8 * GIB)
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(20 * GIB)
    )
    limit = capture_buffer_limit_bytes(str(tmp_path), 6.0)
    memory_limit = int(8 * GIB * MEMORY_HEADROOM_FRACTION)
    assert limit == min(
        int(6.0 * GIB),
        memory_limit,
        int((20 * GIB - DISK_RESERVE_BYTES) / PNG_DISK_FACTOR),
    )
    assert limit == memory_limit


def test_a_non_positive_buffer_ceiling_is_rejected(tmp_path):
    for bad in (0.0, -1.0):
        with pytest.raises(RuntimeError, match='greater than zero'):
            capture_buffer_limit_bytes(str(tmp_path), bad)


def test_zero_frames_are_always_allowed(plenty):
    params = CaptureParams()
    assert ensure_capture_capacity(plenty, params, 0, 1280, 720) > 0

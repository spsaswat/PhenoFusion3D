"""The one capacity precondition for a capture: free output-disk storage."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import base  # noqa: E402
from capture.base import GIB, ensure_free_storage  # noqa: E402


class _DiskUsage:
    def __init__(self, free):
        self.free = free
        self.total = free
        self.used = 0


def test_a_capture_is_refused_with_less_than_1_gb_free(monkeypatch, tmp_path):
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(GIB // 2)
    )

    with pytest.raises(RuntimeError, match=r'Only 0\.50 GB .*at least 1 GB'):
        ensure_free_storage(str(tmp_path))


@pytest.mark.parametrize('free', [0, GIB - 1])
def test_anything_below_1_gb_is_refused(monkeypatch, tmp_path, free):
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(free)
    )

    with pytest.raises(RuntimeError, match='at least 1 GB'):
        ensure_free_storage(str(tmp_path))


# From the 1 GB minimum up to just below 5 GB, and well beyond.
@pytest.mark.parametrize(
    'free', [GIB, 2 * GIB, 3 * GIB, 4 * GIB, 5 * GIB - 1, 40 * GIB]
)
def test_a_capture_starts_with_1_gb_or_more_free(monkeypatch, tmp_path, free):
    monkeypatch.setattr(
        base.shutil, 'disk_usage', lambda _path: _DiskUsage(free)
    )

    ensure_free_storage(str(tmp_path))  # must not raise

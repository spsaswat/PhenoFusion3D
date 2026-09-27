"""Closing the window must not abandon a running reconstruction.

The reconstruction writes its point cloud incrementally, so exiting
underneath it loses the run and can leave a half-written PLY -- the same
file the post-processing panel is handed afterwards.
"""

import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from PyQt5.QtWidgets import QApplication

from app.worker import ProcessingWorker


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    from app.main_window import MainWindow
    win = MainWindow()
    win.controller.viewer.start = lambda: None
    win.show()
    yield app, win
    win.controller.worker = None
    win.close()
    app.processEvents()


class _StubWorker(ProcessingWorker):
    """Checks the stop flag between frames, as Reconstructor.run() does."""

    def __init__(self):
        super().__init__(pairs=[], K=None, dist=None)
        self._stop = False
        self.saved = False

    def run(self):
        for _ in range(200):
            if self._stop:
                self.saved = True       # stands in for _emergency_save()
                break
            time.sleep(0.05)
        self.reconstruction_finished.emit(None, [], [])

    def stop(self):
        self._stop = True


def _attach(window, worker):
    controller = window.controller
    controller.worker = worker
    worker.reconstruction_finished.connect(controller._on_finished)
    worker.finished.connect(
        lambda: controller._on_reconstruction_thread_stopped(worker)
    )
    worker.start()


def _pump(app, window, predicate, timeout_s=10):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not predicate():
        app.processEvents()
        time.sleep(0.02)
    return predicate()


def test_processing_worker_does_not_shadow_qthread_finished():
    """QThread.finished is how the window learns the thread really stopped."""
    assert ProcessingWorker.finished is not ProcessingWorker.reconstruction_finished


def test_close_stops_the_reconstruction_and_waits_for_it(window):
    app, win = window
    worker = _StubWorker()
    _attach(win, worker)
    assert _pump(app, win, win.controller.is_reconstructing)

    win.close()
    app.processEvents()

    # The window stays up while the run winds down.
    assert win.isVisible()
    assert worker._stop, 'close must request a stop'
    assert 'Stopping reconstruction' in win.status.currentMessage()

    assert _pump(app, win, lambda: not win.isVisible()), 'window never closed'
    assert not worker.isRunning()
    assert worker.saved, 'the run must get its chance to save'
    assert win.controller.worker is None


def test_idle_close_is_not_deferred(window):
    app, win = window
    assert not win.controller.is_reconstructing()
    win.close()
    app.processEvents()
    assert not win.isVisible()


def test_shutdown_waits_for_a_running_reconstruction(window):
    app, win = window
    worker = _StubWorker()
    _attach(win, worker)
    assert _pump(app, win, win.controller.is_reconstructing)

    win.controller.shutdown()

    assert not worker.isRunning()
    assert worker.saved


def test_intermediate_save_is_atomic(tmp_path):
    """A torn write must never replace a good merge_pcd_live.ply."""
    numpy = pytest.importorskip('numpy')
    o3d = pytest.importorskip('open3d')
    from processing.reconstructor import Reconstructor

    recon = Reconstructor.__new__(Reconstructor)
    recon.save_path = str(tmp_path)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(numpy.random.rand(500, 3))
    recon.reference_pcd = cloud

    recon._save_intermediate()
    out = tmp_path / 'merge_pcd_live.ply'
    assert len(o3d.io.read_point_cloud(str(out)).points) == 500
    # No partial file is left lying around next to the result.
    assert [p.name for p in tmp_path.iterdir()] == ['merge_pcd_live.ply']

    cloud.points = o3d.utility.Vector3dVector(numpy.random.rand(900, 3))
    recon._save_intermediate()
    assert len(o3d.io.read_point_cloud(str(out)).points) == 900
    assert [p.name for p in tmp_path.iterdir()] == ['merge_pcd_live.ply']

    # A failed write leaves the previous good file untouched.
    recon.save_path = str(tmp_path / 'missing')
    recon._save_intermediate()
    assert len(o3d.io.read_point_cloud(str(out)).points) == 900

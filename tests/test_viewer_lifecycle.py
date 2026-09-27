"""The Open3D preview must be one window, not one window per run.

Only destroy_window() closes an Open3D window, so replacing the
Visualizer on each run left the previous window on screen with nothing
driving it.
"""

import pytest

from visualiser.viewer import PointCloudViewer


class _FakeVisualizer:
    """Stands in for o3d.visualization.Visualizer, counting the calls."""

    instances = []

    def __init__(self):
        self.created = False
        self.destroyed = False
        self.geometries = []
        self.alive = True
        self.calls = []
        self.render_option = type('opt', (), {})()
        _FakeVisualizer.instances.append(self)

    def create_window(self, **kwargs):
        self.created = True
        return True

    def get_render_option(self):
        return self.render_option

    def add_geometry(self, geometry):
        self.geometries.append(geometry)

    def update_geometry(self, geometry):
        pass

    def clear_geometries(self):
        self.geometries.clear()

    def poll_events(self):
        self.calls.append('poll')
        return self.alive

    def update_renderer(self):
        self.calls.append('render')

    def destroy_window(self):
        self.destroyed = True
        self.alive = False


class _Cloud:
    def is_empty(self):
        return False


@pytest.fixture
def fake_o3d(monkeypatch):
    import visualiser.viewer as module

    _FakeVisualizer.instances = []
    monkeypatch.setattr(
        module.o3d.visualization, 'Visualizer', _FakeVisualizer
    )
    return _FakeVisualizer


def test_repeated_runs_reuse_one_window(fake_o3d):
    viewer = PointCloudViewer()
    viewer.start()
    viewer.update(_Cloud())
    viewer.start()
    viewer.update(_Cloud())
    viewer.start()

    assert len(fake_o3d.instances) == 1, 'a run must not open a second window'
    assert not fake_o3d.instances[0].destroyed


def test_restart_clears_the_previous_cloud(fake_o3d):
    viewer = PointCloudViewer()
    viewer.start()
    viewer.update(_Cloud())
    assert fake_o3d.instances[0].geometries

    viewer.start()
    assert fake_o3d.instances[0].geometries == []
    assert viewer._has_geom is False


def test_close_destroys_the_window_and_is_idempotent(fake_o3d):
    viewer = PointCloudViewer()
    viewer.start()
    viewer.close()

    assert fake_o3d.instances[0].destroyed
    assert viewer.vis is None
    viewer.close()          # must not raise
    assert viewer.vis is None


def test_a_window_closed_by_the_user_is_released(fake_o3d):
    viewer = PointCloudViewer()
    viewer.start()
    fake_o3d.instances[0].alive = False     # user clicked the X

    viewer.update(_Cloud())

    assert viewer.vis is None, 'a dead window must not keep being driven'
    assert viewer._started is False

    viewer.start()
    assert len(fake_o3d.instances) == 2, 'the next run opens a fresh window'


def test_failure_to_open_leaves_the_viewer_inert(monkeypatch, fake_o3d):
    """No display is not a reason to break the reconstruction."""
    monkeypatch.setattr(_FakeVisualizer, 'create_window',
                        lambda self, **kwargs: False)
    viewer = PointCloudViewer()
    viewer.start()

    assert viewer.vis is None
    assert viewer._started is False
    viewer.update(_Cloud())     # must not raise
    viewer.close()


def test_update_marks_dirty_before_polling(fake_o3d):
    """poll_events() performs the redraw; update_renderer() only marks the
    scene dirty. Marking after the poll would draw each frame a tick late."""
    viewer = PointCloudViewer()
    viewer.start()
    fake_o3d.instances[0].calls.clear()

    viewer.update(_Cloud())

    assert fake_o3d.instances[0].calls == ['render', 'poll']


def test_keep_alive_tick_does_not_force_a_redraw(fake_o3d):
    """A redraw costs a full re-render of the cloud; an idle tick must not."""
    viewer = PointCloudViewer()
    viewer.start()
    viewer.update(_Cloud())
    fake_o3d.instances[0].calls.clear()

    for _ in range(5):
        assert viewer.pump() is True

    assert fake_o3d.instances[0].calls == ['poll'] * 5
    assert 'render' not in fake_o3d.instances[0].calls


def test_pump_reports_a_window_that_went_away(fake_o3d):
    viewer = PointCloudViewer()
    viewer.start()
    fake_o3d.instances[0].alive = False

    assert viewer.pump() is False
    assert viewer.vis is None


def test_pump_is_safe_with_no_window():
    assert PointCloudViewer().pump() is False

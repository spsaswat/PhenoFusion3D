import open3d as o3d
import numpy as np


class PointCloudViewer:
    """
    Non-blocking Open3D visualiser window.
    Updated from the Qt controller thread via update().

    A single window is reused across runs.  Creating one per run would
    leave the previous window on screen with nothing driving it, since
    only destroy_window() closes an Open3D window.
    """

    WINDOW_NAME = 'PhenoFusion3D - Point Cloud'

    def __init__(self):
        self.vis      = None
        self._started = False
        self._has_geom = False

    def start(self):
        """Show an empty viewer, reusing the existing window if there is one."""
        if self._reuse_window():
            return
        vis = o3d.visualization.Visualizer()
        try:
            created = vis.create_window(
                window_name=self.WINDOW_NAME, width=900, height=700
            )
        except Exception as exc:          # no display, no GL, ...
            created = False
            print(f'[viewer] WARNING: could not open the viewer window: {exc}')
        if not created:
            # The preview is optional; reconstruction continues without it.
            self.vis      = None
            self._started = False
            return
        self.vis = vis
        opt = self.vis.get_render_option()
        opt.background_color = np.array([0.1, 0.1, 0.15])
        opt.point_size = 1.5
        self._started   = True
        self._has_geom  = False

    def _reuse_window(self) -> bool:
        """Clear and keep the current window; False if there isn't a live one."""
        if not self.is_open():
            return False
        if not self._poll():
            # The user closed it -- release it and let the caller open a new one.
            self.close()
            return False
        self.vis.clear_geometries()
        self._has_geom = False
        self.vis.update_renderer()
        return True

    def is_open(self) -> bool:
        return self._started and self.vis is not None

    def pump(self) -> bool:
        """Service window events once; False when the window has gone away.

        Open3D windows are only interactive while something calls this.
        Driving it solely from incoming frames leaves the window frozen
        between frames, and permanently once a run has finished.

        Only poll_events() is called here.  update_renderer() merely marks
        the scene dirty and poll_events() performs the redraw, so pairing
        them on every tick would re-render the whole cloud ~30 times a
        second for no reason.  Open3D's own mouse handlers mark the scene
        dirty, so rotating and zooming still repaint.
        """
        if not self.is_open():
            return False
        if not self._poll():
            # The user closed the preview; stop driving a dead window.
            self.close()
            return False
        return True

    def update(self, pcd):
        if not self.is_open():
            return
        if pcd is None or pcd.is_empty():
            return
        if not self._has_geom:
            self.vis.add_geometry(pcd)
            self._has_geom = True
        else:
            self.vis.update_geometry(pcd)
        # New data to show: mark it dirty, then let pump() draw it.
        self.vis.update_renderer()
        self.pump()

    def _poll(self) -> bool:
        """poll_events(), reporting False once the window has gone away."""
        try:
            return bool(self.vis.poll_events())
        except Exception:
            return False

    def close(self):
        if self.vis:
            try:
                self.vis.destroy_window()
            except Exception:
                pass
            self.vis      = None
            self._started = False
            self._has_geom = False

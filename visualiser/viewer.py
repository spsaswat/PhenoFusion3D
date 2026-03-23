import open3d as o3d
import numpy as np


class PointCloudViewer:
    """
    Non-blocking Open3D visualiser window.
    Updated from the Qt controller thread via update().
    """

    def __init__(self):
        self.vis      = None
        self._started = False
        self._has_geom = False

    def start(self):
        self.vis = o3d.visualization.Visualizer()
        self.vis.create_window(
            window_name='PhenoFusion3D - Point Cloud',
            width=900, height=700
        )
        opt = self.vis.get_render_option()
        opt.background_color = np.array([0.1, 0.1, 0.15])
        opt.point_size = 1.5
        self._started   = True
        self._has_geom  = False

    def update(self, pcd):
        if not self._started or self.vis is None:
            return
        if pcd is None or pcd.is_empty():
            return
        if not self._has_geom:
            self.vis.add_geometry(pcd)
            self._has_geom = True
        else:
            self.vis.update_geometry(pcd)
        self.vis.poll_events()
        self.vis.update_renderer()

    def close(self):
        if self.vis:
            self.vis.destroy_window()
            self.vis      = None
            self._started = False
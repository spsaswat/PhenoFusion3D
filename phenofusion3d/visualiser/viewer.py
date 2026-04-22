"""
Open3D visualiser - Option A: separate window. Updates via update_geometry.
"""
import open3d as o3d


class PointCloudViewer:
    """Non-blocking Open3D visualiser window."""

    def __init__(self, title="PhenoFusion3D - Point Cloud"):
        self.vis = None
        self.title = title
        self._created = False

    def create(self, pcd=None):
        """Create window and optionally add initial geometry."""
        self.vis = o3d.visualization.Visualizer()
        self.vis.create_window(window_name=self.title, width=800, height=600)
        if pcd is not None and not pcd.is_empty():
            self.vis.add_geometry(pcd)
        self._created = True

    def update(self, pcd):
        """Update displayed point cloud."""
        if not self._created or self.vis is None:
            return
        # First clear and add, or update geometry
        self.vis.clear_geometries()
        if pcd is not None and not pcd.is_empty():
            self.vis.add_geometry(pcd)
        self.vis.poll_events()
        self.vis.update_renderer()

    def destroy(self):
        """Close window."""
        if self.vis is not None:
            self.vis.destroy_window()
            self.vis = None
        self._created = False

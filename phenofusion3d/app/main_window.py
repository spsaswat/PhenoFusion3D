"""
Main window - QMainWindow with split layout. Left: data + controls. Right: 3D view + metrics + log.
"""
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QFileDialog,
    QMessageBox,
    QMenuBar,
    QAction,
)
from PyQt5.QtCore import Qt

from .panels import DataPanel, ControlsPanel, MetricsPanel, LogPanel


class MainWindow(QMainWindow):
    """PhenoFusion3D main application window."""

    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self._viewer = None
        self.setWindowTitle("PhenoFusion3D")
        self.setMinimumSize(1200, 800)
        self.resize(1280, 900)
        self._setup_menu()
        self._setup_layout()
        self._connect_signals()

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        export_ply = QAction("Export PLY...", self)
        export_ply.triggered.connect(self._export_ply)
        file_menu.addAction(export_ply)
        export_csv = QAction("Export Metrics CSV...", self)
        export_csv.triggered.connect(self._export_metrics)
        file_menu.addAction(export_csv)

    def _setup_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)

        # Left: data panel + controls + metrics
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.data_panel = DataPanel()
        left_layout.addWidget(self.data_panel)
        self.controls_panel = ControlsPanel()
        left_layout.addWidget(self.controls_panel)
        self.metrics_panel = MetricsPanel()
        left_layout.addWidget(self.metrics_panel)
        left_layout.addStretch()
        splitter.addWidget(left)

        # Right: 3D view placeholder + log
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.view_placeholder = QWidget()
        self.view_placeholder.setMinimumSize(600, 400)
        self.view_placeholder.setStyleSheet("background-color: #2b2b2b;")
        right_layout.addWidget(self.view_placeholder)
        self.log_panel = LogPanel()
        right_layout.addWidget(self.log_panel)
        splitter.addWidget(right)

        splitter.setSizes([400, 800])
        main_layout.addWidget(splitter)

        self.statusBar().showMessage("Ready. Select RGB folder and click Run.")

    def _connect_signals(self):
        self.data_panel.run_requested.connect(self._on_run_requested)
        if self.controller:
            self.controller.main_window = self

    def _on_run_requested(self, rgb_dir, depth_dir, intrinsics_path, step_size):
        if self.controller:
            self.controller.on_run_requested(
                rgb_dir, depth_dir, intrinsics_path, step_size
            )

    def _connect_controller_stop(self):
        if self.controller and self.controller.worker:
            self.controls_panel.stop_requested.disconnect()
            self.controls_panel.stop_requested.connect(self.controller.worker.stop)

    def update_viewer(self, pcd):
        """Update 3D point cloud display. Option A: separate Open3D window."""
        if pcd is None or pcd.is_empty():
            return
        try:
            import open3d as o3d
            if self._viewer is None:
                self._viewer = o3d.visualization.Visualizer()
                self._viewer.create_window(
                    window_name="PhenoFusion3D - Point Cloud",
                    width=800,
                    height=600,
                )
                self._viewer.add_geometry(pcd)
            else:
                self._viewer.clear_geometries()
                self._viewer.add_geometry(pcd)
            self._viewer.poll_events()
            self._viewer.update_renderer()
        except Exception:
            pass  # Viewer may fail on headless or certain platforms

    def _export_ply(self):
        if not self.controller or not self.controller.current_pcd:
            QMessageBox.warning(
                self, "Export", "No point cloud to export. Run reconstruction first."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PLY", "", "PLY (*.ply);;All (*)"
        )
        if path:
            try:
                from phenofusion3d.io import save_ply
                save_ply(self.controller.current_pcd, path)
                self.statusBar().showMessage(f"Saved: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def _export_metrics(self):
        if not self.controller or not self.controller.metrics_list:
            QMessageBox.warning(
                self, "Export", "No metrics to export. Run reconstruction first."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Metrics CSV", "", "CSV (*.csv);;All (*)"
        )
        if path:
            try:
                from phenofusion3d.io import save_metrics_csv
                save_metrics_csv(self.controller.metrics_list, path)
                self.statusBar().showMessage(f"Saved: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

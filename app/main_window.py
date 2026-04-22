from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout,
    QHBoxLayout, QStatusBar, QMenuBar, QAction,
    QFileDialog, QMessageBox, QLabel
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont

from app.panels.data_panel    import DataPanel
from app.panels.metrics_panel import MetricsPanel
from app.panels.log_panel     import LogPanel
from app.panels.capture_panel import CapturePanel
from app.panels.quality_panel import QualityPanel
from app.panels.gantry_panel  import GantryPanel
from app.controller           import Controller


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('PhenoFusion3D')
        self.setMinimumSize(1280, 800)
        self.resize(1400, 900)

        self.controller = Controller(self)

        self._build_menu()
        self._build_layout()
        self._build_statusbar()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # Main horizontal splitter
        splitter = QSplitter(Qt.Horizontal)

        # --- Left pane: data + controls ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        from PyQt5.QtWidgets import QScrollArea

        self.capture_panel = CapturePanel()
        self.gantry_panel  = GantryPanel(
            available=self.controller.gantry.is_available()
        )
        self.data_panel    = DataPanel()
        self.quality_panel = QualityPanel()

        # Stack into a scroll area so the left pane stays usable on small screens
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(6)
        inner_layout.addWidget(self.capture_panel)
        inner_layout.addWidget(self.gantry_panel)
        inner_layout.addWidget(self.data_panel)
        inner_layout.addWidget(self.quality_panel)
        inner_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QScrollArea.NoFrame)
        left_layout.addWidget(scroll)
        left_widget.setFixedWidth(360)

        # --- Right pane: placeholder + metrics + log ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Viewer placeholder (Open3D opens its own window for now)
        self.viewer_placeholder = QLabel(
            'Point cloud viewer will appear in a\n'
            'separate Open3D window when reconstruction starts.'
        )
        self.viewer_placeholder.setAlignment(Qt.AlignCenter)
        self.viewer_placeholder.setStyleSheet(
            'background:#1e1e2e; color:#888; border-radius:6px; font-size:13px;'
        )
        self.viewer_placeholder.setMinimumHeight(380)

        self.metrics_panel = MetricsPanel()
        self.log_panel     = LogPanel()

        right_layout.addWidget(self.viewer_placeholder, stretch=3)
        right_layout.addWidget(self.metrics_panel,      stretch=1)
        right_layout.addWidget(self.log_panel,          stretch=1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter)

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu('File')

        self.action_export_ply = QAction('Export PLY...', self)
        self.action_export_ply.setEnabled(False)
        file_menu.addAction(self.action_export_ply)

        self.action_export_csv = QAction('Export Metrics CSV...', self)
        self.action_export_csv.setEnabled(False)
        file_menu.addAction(self.action_export_csv)

        file_menu.addSeparator()
        action_exit = QAction('Exit', self)
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

    def _build_statusbar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage('Ready')

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        # Data panel -> controller
        self.data_panel.run_requested.connect(self.controller.on_run_clicked)
        self.data_panel.run_requested.connect(self.controller.on_quality_paths)
        self.data_panel.stop_requested.connect(self.controller.on_stop_clicked)

        # Capture panel -> controller -> capture panel
        self.capture_panel.capture_requested.connect(self.controller.on_capture_clicked)
        self.capture_panel.capture_stop_requested.connect(self.controller.on_capture_stop)
        self.controller.capture_progress.connect(self.capture_panel.on_progress)
        self.controller.capture_complete.connect(self._on_capture_complete)
        self.controller.capture_error.connect(self.capture_panel.on_error)

        # Gantry panel -> controller -> gantry panel
        self.gantry_panel.jog_requested.connect(self.controller.on_gantry_jog)
        self.gantry_panel.stop_requested.connect(self.controller.on_gantry_stop)
        self.gantry_panel.goto_requested.connect(self.controller.on_gantry_goto)
        self.gantry_panel.go_home_requested.connect(self.controller.on_gantry_home)
        self.controller.gantry.position_changed.connect(self.gantry_panel.update_position)
        self.controller.gantry.error.connect(self.gantry_panel.show_status)
        # Disable jog/go-to during capture so two motion sources don't fight.
        self.controller.capture_started.connect(
            lambda: self.gantry_panel.set_capture_active(True)
        )
        self.controller.capture_complete.connect(
            lambda *_: self.gantry_panel.set_capture_active(False)
        )
        self.controller.capture_error.connect(
            lambda *_: self.gantry_panel.set_capture_active(False)
        )

        # Quality panel -> controller -> quality panel
        self.quality_panel.quick_requested.connect(self._on_quick_check_requested)
        self.quality_panel.full_requested.connect(self._on_full_report_requested)
        self.controller.quality_progress.connect(self.quality_panel.on_progress)
        self.controller.quality_ready.connect(self.quality_panel.show_report)
        self.controller.quality_error.connect(self.quality_panel.on_error)

        # Controller -> UI updates
        self.controller.status_changed.connect(self.status.showMessage)
        self.controller.frame_processed.connect(self._on_frame)
        self.controller.reconstruction_complete.connect(self._on_complete)
        self.controller.error_occurred.connect(self._on_error)

        # Export actions -> controller
        self.action_export_ply.triggered.connect(self._export_ply)
        self.action_export_csv.triggered.connect(self._export_csv)

    @pyqtSlot(str, int)
    def _on_capture_complete(self, out_dir, n_frames):
        # Auto-populate DataPanel with the freshly captured paths
        rgb_dir   = f'{out_dir}/rgb'
        depth_dir = f'{out_dir}/depth'
        intr      = f'{out_dir}/kdc_intrinsics.txt'
        import os
        if not os.path.exists(intr):
            intr = ''
        self.data_panel.set_paths(rgb_dir, depth_dir, intr)
        self.capture_panel.on_finished(out_dir, n_frames)
        # Tell the controller about these paths so Quality Check can use them too
        self.controller.on_quality_paths(rgb_dir, depth_dir, intr, 1)

    def _on_quick_check_requested(self):
        # Push current paths into controller before triggering the worker
        self.controller.on_quality_paths(
            self.data_panel.rgb_edit.text(),
            self.data_panel.depth_edit.text(),
            self.data_panel.intr_edit.text(),
            self.data_panel.step_spin.value(),
        )
        self.quality_panel.set_running(True)
        self.controller.on_quick_check_clicked()

    def _on_full_report_requested(self):
        self.controller.on_quality_paths(
            self.data_panel.rgb_edit.text(),
            self.data_panel.depth_edit.text(),
            self.data_panel.intr_edit.text(),
            self.data_panel.step_spin.value(),
        )
        self.quality_panel.set_running(True)
        self.controller.on_full_report_clicked()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(int, int, object, float, float, str)
    def _on_frame(self, idx, total, pcd, fitness, rmse, status):
        self.metrics_panel.update_metrics(idx, total, fitness, rmse,
                                          self.controller.n_success,
                                          self.controller.n_fail)
        self.log_panel.append_row(idx, status, fitness, rmse)

    @pyqtSlot(object, list, list)
    def _on_complete(self, final_pcd, succeed, fail):
        self.action_export_ply.setEnabled(True)
        self.action_export_csv.setEnabled(True)
        self.data_panel.set_running(False)

    @pyqtSlot(str)
    def _on_error(self, msg):
        QMessageBox.critical(self, 'Processing Error', msg)
        self.data_panel.set_running(False)
        self.status.showMessage('Error - see dialog')

    def _export_ply(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export PLY', 'output.ply', 'Point Cloud (*.ply)'
        )
        if path:
            self.controller.export_ply(path)

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Metrics CSV', 'metrics.csv', 'CSV (*.csv)'
        )
        if path:
            self.controller.export_csv(path)

    def closeEvent(self, event):
        # Final safety stop on the gantry before the process exits.
        try:
            self.controller.shutdown()
        except Exception:
            pass
        super().closeEvent(event)
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout,
    QHBoxLayout, QStatusBar, QAction, QApplication,
    QFileDialog, QMessageBox, QLabel, QPushButton, QScrollArea, QTabWidget
)
from PyQt5.QtCore import QTimer, Qt, pyqtSlot

from app import theme
from app.panels.data_panel    import DataPanel
from app.panels.metrics_panel import MetricsPanel
from app.panels.log_panel     import LogPanel
from app.panels.capture_panel import CapturePanel
from app.panels.quality_panel import QualityPanel
from app.panels.gantry_panel  import GantryPanel
from app.panels.postprocess_panel import PostProcessPanel
from app.controller           import Controller
from capture.base              import MILLIMETRES_PER_METRE


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('PhenoFusion3D')
        self.setMinimumSize(1180, 760)
        self.resize(1440, 920)
        self._close_pending = False

        # Style the UI even when the window is built directly (tests,
        # embedding) instead of through main.create_application().
        app = QApplication.instance()
        if not theme.is_applied(app):
            theme.apply(app)

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
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                       theme.MARGIN, theme.MARGIN)
        root_layout.setSpacing(theme.GAP)

        root_layout.addWidget(self._build_header())

        # Main horizontal splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(theme.GAP)
        splitter.setChildrenCollapsible(False)

        splitter.addWidget(self._build_left_pane())
        splitter.addWidget(self._build_right_pane())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 960])

        root_layout.addWidget(splitter, stretch=1)

    def _build_header(self):
        """Slim title strip, plus the always-visible gantry safety controls.

        The workflow panels live in tabs, so the emergency STOP must not
        sit inside one of them -- it stays here, reachable from every tab
        and never scrolled out of view.
        """
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)

        name = QLabel('PhenoFusion3D')
        theme.role(name, 'appTitle')
        row.addWidget(name)

        subtitle = QLabel('RGB-D capture, quality assessment and 3D plant reconstruction')
        theme.role(subtitle, 'appSubtitle')
        row.addWidget(subtitle)
        row.addStretch()

        gantry_available = self.controller.gantry.is_available()

        row.addWidget(theme.role(QLabel('Gantry'), 'section'))
        self.header_position_lbl = QLabel('--- mm')
        self.header_position_lbl.setAlignment(Qt.AlignCenter)
        self.header_position_lbl.setMinimumWidth(110)
        theme.role(self.header_position_lbl, 'readout')
        row.addWidget(self.header_position_lbl)

        self.header_stop_btn = QPushButton('STOP')
        self.header_stop_btn.setMinimumWidth(96)
        theme.variant(self.header_stop_btn, 'danger')
        self.header_stop_btn.setEnabled(gantry_available)
        self.header_stop_btn.setToolTip(
            'Stop all gantry motion immediately.' if gantry_available
            else GantryPanel._OFFLINE_TOOLTIP
        )
        row.addWidget(self.header_stop_btn)
        return header

    def _build_left_pane(self):
        """Workflow controls, grouped into tabs.

        The panels themselves are unchanged -- stacking all five in one
        column was what made the window feel crowded, so related steps
        now share a tab and only one group is visible at a time.
        """
        self.capture_panel = CapturePanel()
        self.gantry_panel  = GantryPanel(
            available=self.controller.gantry.is_available()
        )
        self.data_panel    = DataPanel()
        self.quality_panel = QualityPanel()
        self.postprocess_panel = PostProcessPanel()

        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.setDocumentMode(False)
        self.workflow_tabs.addTab(
            self._tab_page(self.capture_panel, self.gantry_panel), 'Capture'
        )
        self.workflow_tabs.addTab(
            self._tab_page(self.data_panel, self.quality_panel), 'Reconstruct'
        )
        self.workflow_tabs.addTab(
            self._tab_page(self.postprocess_panel), 'Analyse'
        )

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.workflow_tabs)
        left_widget.setMinimumWidth(390)
        left_widget.setMaximumWidth(560)
        return left_widget

    def _tab_page(self, *panels):
        """Put panels in a scrollable page so a small screen still works."""
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(theme.GAP)
        for panel in panels:
            inner_layout.addWidget(panel)
        inner_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(theme.GAP, theme.GAP,
                                       theme.GAP, theme.GAP)
        page_layout.addWidget(scroll)
        return page

    def _build_right_pane(self):
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(theme.GAP)

        # Viewer placeholder (Open3D opens its own window for now)
        self.viewer_placeholder = QLabel(
            'Point cloud viewer\n\n'
            'The 3D view opens in a separate Open3D window\n'
            'when reconstruction starts.'
        )
        self.viewer_placeholder.setAlignment(Qt.AlignCenter)
        theme.role(self.viewer_placeholder, 'viewer')
        self.viewer_placeholder.setMinimumHeight(240)

        self.metrics_panel = MetricsPanel()
        self.log_panel     = LogPanel()

        right_layout.addWidget(self.viewer_placeholder, stretch=5)
        right_layout.addWidget(self.metrics_panel,      stretch=0)
        right_layout.addWidget(self.log_panel,          stretch=2)
        return right_widget

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
        action_exit.setShortcut('Ctrl+Q')
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        analysis_menu = menubar.addMenu('Analysis')
        self.action_analysis = QAction('Offline reconstruction, traits and hyperspectral fusion...', self)
        self.action_analysis.triggered.connect(self._open_analysis)
        analysis_menu.addAction(self.action_analysis)

    def _open_analysis(self):
        # Import only the lightweight dialog here. Heavy processing is isolated
        # in a child process and never imported by the lab startup/capture path.
        from app.analysis_dialog import AnalysisDialog
        if not hasattr(self, 'analysis_dialog'):
            self.analysis_dialog = AnalysisDialog(self.controller, self)
            # Capture always has priority over an optional offline computation.
            self.controller.capture_started.connect(self.analysis_dialog.cancel)
        rgb_dir = self.data_panel.rgb_edit.text()
        if rgb_dir and not self.analysis_dialog.dataset.text():
            from pathlib import Path
            root = str(Path(rgb_dir).parent)
            self.analysis_dialog.dataset.setText(root)
            self.analysis_dialog.ref_dataset.setText(root)
            self.analysis_dialog.leaf_dataset.setText(root)
        self.analysis_dialog.show()
        self.analysis_dialog.raise_()

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
        self.controller.capture_stopped.connect(self._continue_pending_close)
        self.controller.reconstruction_stopped.connect(
            self._continue_pending_close
        )

        # Gantry panel -> controller -> gantry panel
        self.gantry_panel.jog_requested.connect(self.controller.on_gantry_jog)
        self.gantry_panel.stop_requested.connect(self.controller.on_gantry_stop)
        self.gantry_panel.goto_requested.connect(self.controller.on_gantry_goto)
        self.gantry_panel.go_home_requested.connect(self.controller.on_gantry_home)
        self.controller.gantry.position_changed.connect(self.gantry_panel.update_position)
        self.controller.gantry.position_changed.connect(
            self.capture_panel.update_gantry_position
        )
        # Always-visible safety controls in the header use the same paths.
        self.header_stop_btn.clicked.connect(self.controller.on_gantry_stop)
        self.controller.gantry.position_changed.connect(
            self._update_header_position
        )
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

        # Post-processing panel -> controller -> post-processing panel
        self.postprocess_panel.clean_requested.connect(self.controller.on_clean_ply_requested)
        self.postprocess_panel.segment_requested.connect(self.controller.on_segment_requested)
        self.postprocess_panel.traits_requested.connect(self.controller.on_traits_requested)
        self.postprocess_panel.pipeline_requested.connect(self.controller.on_pipeline_requested)
        self.controller.postprocess_ready.connect(self.postprocess_panel.on_postprocess_done)
        self.controller.postprocess_error.connect(self.postprocess_panel.on_postprocess_error)

        # Controller -> UI updates
        self.controller.status_changed.connect(self.status.showMessage)
        self.controller.frame_processed.connect(self._on_frame)
        self.controller.reconstruction_complete.connect(self._on_complete)
        self.controller.error_occurred.connect(self._on_error)

        # Export actions -> controller
        self.action_export_ply.triggered.connect(self._export_ply)
        self.action_export_csv.triggered.connect(self._export_csv)

    @pyqtSlot(float)
    def _update_header_position(self, position_m):
        self.header_position_lbl.setText(
            f'{position_m * MILLIMETRES_PER_METRE:+.1f} mm'
        )

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
        import os

        self.action_export_ply.setEnabled(True)
        self.action_export_csv.setEnabled(True)
        self.data_panel.set_running(False)
        recon_ply = os.path.join(os.path.dirname(self.data_panel.rgb_edit.text()), 'output', 'merge_pcd_live.ply')
        if os.path.exists(recon_ply):
            self.postprocess_panel.ply_edit.setText(recon_ply)

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
        capture_worker = self.controller.capture_worker
        if capture_worker is not None and capture_worker.isRunning():
            self._close_pending = True
            self.controller.on_capture_stop()
            self.capture_panel.status_lbl.setText(
                'Stopping capture and finishing the save before closing...'
            )
            event.ignore()
            return

        # A reconstruction writes its point cloud incrementally, so it gets
        # the same courtesy as a capture: ask it to stop, stay open until it
        # has, then close. Exiting underneath it would abandon the run and
        # could leave a half-written PLY behind.
        if self.controller.is_reconstructing():
            self._close_pending = True
            self.controller.on_stop_clicked()
            self.status.showMessage(
                'Stopping reconstruction and finishing the save before closing...'
            )
            event.ignore()
            return
        # Final safety stop on the gantry before the process exits.
        try:
            self.controller.shutdown()
        except Exception:
            pass
        if hasattr(self, 'analysis_dialog'):
            self.analysis_dialog.close()
        super().closeEvent(event)

    @pyqtSlot()
    def _continue_pending_close(self):
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

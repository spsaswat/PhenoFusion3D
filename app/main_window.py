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

        self.data_panel = DataPanel()
        left_layout.addWidget(self.data_panel)
        left_layout.addStretch()
        left_widget.setFixedWidth(320)

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
        self.data_panel.stop_requested.connect(self.controller.on_stop_clicked)

        # Controller -> UI updates
        self.controller.status_changed.connect(self.status.showMessage)
        self.controller.frame_processed.connect(self._on_frame)
        self.controller.reconstruction_complete.connect(self._on_complete)
        self.controller.error_occurred.connect(self._on_error)

        # Export actions -> controller
        self.action_export_ply.triggered.connect(self._export_ply)
        self.action_export_csv.triggered.connect(self._export_csv)

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
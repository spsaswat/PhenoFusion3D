"""
app/panels/capture_panel.py
---------------------------
UI panel for triggering RGB-D capture.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from capture import ros_available


class CapturePanel(QWidget):

    # backend_pref, out_root, velocity_mps, end_position_m, fps, duration_s
    capture_requested      = pyqtSignal(str, str, float, float, int, float)
    capture_stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel('Data Capture')
        title.setStyleSheet('font-weight:bold; font-size:14px;')
        layout.addWidget(title)

        # Backend selector
        backend_row = QHBoxLayout()
        backend_row.addWidget(QLabel('Backend:'))
        self.backend_combo = QComboBox()
        self.backend_combo.addItem('Auto', 'auto')
        ros_item = 'ROS + Gantry' if ros_available() else 'ROS + Gantry (unavailable)'
        self.backend_combo.addItem(ros_item, 'ros')
        self.backend_combo.addItem('RealSense Only', 'realsense')
        if not ros_available():
            self.backend_combo.model().item(1).setEnabled(False)
            self.backend_combo.setToolTip(
                'rospy not importable on this machine -- ROS backend disabled.'
            )
            self.backend_combo.setCurrentIndex(2)  # RealSense
        backend_row.addWidget(self.backend_combo, stretch=1)
        layout.addLayout(backend_row)

        # Output root
        layout.addWidget(QLabel('Output folder:'))
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit('data/captures')
        browse = QPushButton('Browse')
        browse.setFixedWidth(60)
        browse.clicked.connect(self._browse_out)
        out_row.addWidget(self.out_edit)
        out_row.addWidget(browse)
        layout.addLayout(out_row)

        # Velocity / end position (ROS only)
        vel_row = QHBoxLayout()
        vel_row.addWidget(QLabel('Velocity (m/s):'))
        self.vel_spin = QDoubleSpinBox()
        self.vel_spin.setRange(0.001, 1.0)
        self.vel_spin.setSingleStep(0.005)
        self.vel_spin.setDecimals(3)
        self.vel_spin.setValue(0.038)
        vel_row.addWidget(self.vel_spin)
        vel_row.addWidget(QLabel('End (m):'))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.05, 5.0)
        self.end_spin.setSingleStep(0.05)
        self.end_spin.setDecimals(2)
        self.end_spin.setValue(0.78)
        vel_row.addWidget(self.end_spin)
        layout.addLayout(vel_row)

        # FPS / duration
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel('FPS:'))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(30)
        fps_row.addWidget(self.fps_spin)
        fps_row.addWidget(QLabel('Duration (s, RealSense):'))
        self.dur_spin = QDoubleSpinBox()
        self.dur_spin.setRange(0.0, 600.0)
        self.dur_spin.setSingleStep(1.0)
        self.dur_spin.setDecimals(1)
        self.dur_spin.setValue(10.0)
        self.dur_spin.setToolTip('Used by RealSense-only backend. Set 0 to capture until Stop.')
        fps_row.addWidget(self.dur_spin)
        layout.addLayout(fps_row)

        # Buttons
        btn_row = QHBoxLayout()
        self.capture_btn = QPushButton('Capture')
        self.capture_btn.setStyleSheet(
            'QPushButton { background:#16a34a; color:white; border-radius:4px; padding:6px; font-weight:bold; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.capture_btn.clicked.connect(self._on_capture)

        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            'QPushButton { background:#dc2626; color:white; border-radius:4px; padding:6px; font-weight:bold; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.stop_btn.clicked.connect(self.capture_stop_requested.emit)
        btn_row.addWidget(self.capture_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        # Progress + status
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.status_lbl = QLabel('')
        self.status_lbl.setStyleSheet('color:#64748b; font-size:11px;')
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        # "Open captured folder" button (hidden until capture finishes)
        self.open_btn = QPushButton('Open captured folder')
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_last)
        layout.addWidget(self.open_btn)

        self._last_out = None

    def _browse_out(self):
        path = QFileDialog.getExistingDirectory(self, 'Output folder root')
        if path:
            self.out_edit.setText(path)

    def _on_capture(self):
        backend_pref = self.backend_combo.currentData()
        self.set_running(True)
        self.progress.setValue(0)
        self.status_lbl.setText('Starting capture...')
        self.open_btn.setVisible(False)
        self.capture_requested.emit(
            backend_pref,
            self.out_edit.text(),
            self.vel_spin.value(),
            self.end_spin.value(),
            self.fps_spin.value(),
            self.dur_spin.value(),
        )

    def set_running(self, running: bool):
        self.capture_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.backend_combo.setEnabled(not running)

    def on_progress(self, idx: int, total: int):
        if total > 0:
            pct = min(100, int(100 * idx / max(1, total)))
            self.progress.setValue(pct)
            self.status_lbl.setText(f'Captured {idx}/{total} frames')
        else:
            # Unknown total (ROS / manual) -- pulse
            self.progress.setRange(0, 0)
            self.status_lbl.setText(f'Captured {idx} frames')

    def on_finished(self, out_dir: str, n_frames: int):
        self.set_running(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_lbl.setText(f'Done. {n_frames} frames -> {out_dir}')
        self._last_out = out_dir
        self.open_btn.setVisible(True)

    def on_error(self, msg: str):
        self.set_running(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_lbl.setText(f'ERROR: {msg}')

    def _open_last(self):
        if not self._last_out:
            return
        try:
            os.startfile(self._last_out)  # Windows
        except AttributeError:
            import subprocess, sys
            opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
            subprocess.Popen([opener, self._last_out])

"""
app/panels/capture_panel.py
---------------------------
UI panel for triggering RGB-D capture.
"""

from __future__ import annotations

import json
import math
import os

from PyQt5.QtCore import Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from app import theme
from capture import CaptureParams, ros_available
from capture.base import MILLIMETRES_PER_METRE


class CapturePanel(QWidget):

    CAMERA_WEB_UI_URL = 'http://localhost:9976/scm/v1/ui'
    CAMERA_WEB_UI_MIN_POSITION_M = 0.001
    CAMERA_WEB_UI_MAX_POSITION_M = 0.0019

    # backend_pref, out_root, velocity_mps, end_position_m, fps, duration_s
    capture_requested      = pyqtSignal(str, str, float, float, int, float)
    capture_stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._defaults = CaptureParams()
        self._gantry_position_m = None
        self._build_ui()

    def _build_ui(self):
        theme.card(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                  theme.MARGIN, theme.MARGIN)
        layout.setSpacing(theme.GAP)

        layout.addWidget(theme.title('Data Capture'))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Backend selector
        self.backend_combo = QComboBox()
        self.backend_combo.addItem('Auto', 'auto')
        ros_item = 'ROS + Gantry' if ros_available() else 'ROS + Gantry (unavailable)'
        self.backend_combo.addItem(ros_item, 'ros')
        self.backend_combo.addItem('RealSense Only', 'realsense')
        if not ros_available():
            self.backend_combo.model().item(1).setEnabled(False)
            self.backend_combo.setToolTip(
                'No ROS installation was detected -- ROS + Gantry is disabled.'
            )
            self.backend_combo.setCurrentIndex(2)  # RealSense
        form.addRow('Backend', self.backend_combo)

        # Output root
        self.out_edit = QLineEdit(self._defaults.out_root)
        browse = QPushButton('Browse')
        browse.setFixedWidth(72)
        browse.clicked.connect(self._browse_out)
        form.addRow('Output folder', self._with_button(self.out_edit, browse))

        # Velocity / end position (ROS only)
        self.vel_spin = QDoubleSpinBox()
        self.vel_spin.setRange(1.0, 1000.0)
        self.vel_spin.setSingleStep(5.0)
        self.vel_spin.setDecimals(1)
        self.vel_spin.setValue(
            self._defaults.velocity_mps * MILLIMETRES_PER_METRE
        )
        form.addRow('Velocity (mm/s)', self.vel_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(50.0, 5000.0)
        self.end_spin.setSingleStep(50.0)
        self.end_spin.setDecimals(1)
        self.end_spin.setValue(
            self._defaults.end_position_m * MILLIMETRES_PER_METRE
        )
        form.addRow('End position (mm)', self.end_spin)

        # FPS / duration
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(self._defaults.fps)
        form.addRow('Frame rate (FPS)', self.fps_spin)

        self.dur_spin = QDoubleSpinBox()
        self.dur_spin.setRange(0.0, 600.0)
        self.dur_spin.setSingleStep(1.0)
        self.dur_spin.setDecimals(1)
        self.dur_spin.setValue(self._defaults.duration_s)
        self.dur_spin.setToolTip('Used by RealSense-only backend. Set 0 to capture until Stop.')
        form.addRow('Duration (s)', self.dur_spin)
        layout.addLayout(form)

        layout.addWidget(theme.hint(
            'Velocity and end position drive the ROS gantry pass. '
            'Duration applies to the RealSense-only backend; 0 captures until Stop.'
        ))

        layout.addWidget(theme.separator())

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.capture_btn = QPushButton('Capture')
        theme.variant(self.capture_btn, 'primary')
        self.capture_btn.clicked.connect(self._on_capture)

        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        theme.variant(self.stop_btn, 'danger')
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
        theme.role(self.status_lbl, 'hint')
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        # Secondary actions kept out of the main action row.
        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)
        self.camera_web_ui_btn = QPushButton('Hypercam UI')
        self.camera_web_ui_btn.setToolTip(self.CAMERA_WEB_UI_URL)
        self.camera_web_ui_btn.clicked.connect(self._open_camera_web_ui)
        tool_row.addWidget(self.camera_web_ui_btn)

        # "Open captured folder" button (hidden until capture finishes)
        self.open_btn = QPushButton('Open captured folder')
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_last)
        tool_row.addWidget(self.open_btn)
        tool_row.addStretch()
        layout.addLayout(tool_row)

        self._last_out = None

    def _with_button(self, edit, button):
        """Pair an input with its Browse button inside one form field."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(edit)
        row_layout.addWidget(button)
        return row

    def _browse_out(self):
        path = QFileDialog.getExistingDirectory(self, 'Output folder root')
        if path:
            self.out_edit.setText(path)

    def _open_camera_web_ui(self):
        position_m = self._gantry_position_m
        if position_m is None or not math.isfinite(position_m):
            position_detail = 'The current gantry position is unavailable.'
        elif not (
            self.CAMERA_WEB_UI_MIN_POSITION_M
            <= position_m
            <= self.CAMERA_WEB_UI_MAX_POSITION_M
        ):
            position_detail = (
                f'The gantry is currently at '
                f'{position_m * MILLIMETRES_PER_METRE:.1f} mm.'
            )
        else:
            position_detail = None

        if position_detail is not None:
            minimum_mm = (
                self.CAMERA_WEB_UI_MIN_POSITION_M * MILLIMETRES_PER_METRE
            )
            maximum_mm = (
                self.CAMERA_WEB_UI_MAX_POSITION_M * MILLIMETRES_PER_METRE
            )
            message = (
                f'{position_detail} Use the Jog controls to move the gantry '
                f'and keep its position between {minimum_mm:.1f} mm and '
                f'{maximum_mm:.1f} mm, then try again.'
            )
            theme.role(self.status_lbl, 'error')
            self.status_lbl.setText(message)
            QMessageBox.warning(self, 'Gantry Position Required', message)
            return

        if not QDesktopServices.openUrl(QUrl(self.CAMERA_WEB_UI_URL)):
            theme.role(self.status_lbl, 'error')
            self.status_lbl.setText(
                f'ERROR: Could not open {self.CAMERA_WEB_UI_URL}'
            )
        else:
            theme.role(self.status_lbl, 'hint')
            self.status_lbl.setText('Opened Hypercam UI.')

    @pyqtSlot(float)
    def update_gantry_position(self, position_m: float) -> None:
        self._gantry_position_m = float(position_m)

    def _on_capture(self):
        backend_pref = self.backend_combo.currentData()
        self.set_running(True)
        self.progress.setValue(0)
        theme.role(self.status_lbl, 'hint')
        self.status_lbl.setText('Starting capture...')
        self.open_btn.setVisible(False)
        self.capture_requested.emit(
            backend_pref,
            self.out_edit.text(),
            self.vel_spin.value() / MILLIMETRES_PER_METRE,
            self.end_spin.value() / MILLIMETRES_PER_METRE,
            self.fps_spin.value(),
            self.dur_spin.value(),
        )

    def set_running(self, running: bool):
        self.capture_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.backend_combo.setEnabled(not running)

    def on_progress(self, idx: int, total: int):
        if total < 0:
            self.progress.setRange(0, 0)
            self.stop_btn.setEnabled(False)
            self.status_lbl.setText(
                f'Capture finished. Saving {idx} RGB/depth frames...'
            )
            return
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
        message = f'Done. {n_frames} frames -> {out_dir}'
        try:
            with open(os.path.join(out_dir, 'session.json')) as session_file:
                session = json.load(session_file)
            if session.get('termination_reason') == 'buffer_limit':
                message = (
                    f'Stopped at the safe RAM/disk limit. Saved {n_frames} '
                    f'frames -> {out_dir}'
                )
            if session.get('home_returned') is False:
                message += ' WARNING: the gantry did not confirm its return home.'
        except (OSError, ValueError, TypeError):
            pass
        theme.role(self.status_lbl, 'hint')
        self.status_lbl.setText(message)
        self._last_out = out_dir
        self.open_btn.setVisible(True)

    def on_error(self, msg: str):
        self.set_running(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        theme.role(self.status_lbl, 'error')
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

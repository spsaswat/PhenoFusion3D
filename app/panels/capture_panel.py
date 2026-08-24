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
    # "camera" / "gantry" -- run that piece on its own
    selftest_requested     = pyqtSignal(str)
    # re-probe what hardware is attached
    rescan_requested       = pyqtSignal()

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
        # The lab's own program is the primary gantry capture path; the
        # in-app port of the same loop stays available behind it.
        script_item = ('Stakeholder script (rospy_thread_fin_1.py)'
                       if ros_available() else
                       'Stakeholder script (unavailable -- no rospy)')
        self.backend_combo.addItem(script_item, 'stakeholder')
        ros_item = ('ROS + Gantry (built-in loop)' if ros_available()
                    else 'ROS + Gantry (unavailable)')
        self.backend_combo.addItem(ros_item, 'ros')
        self.backend_combo.addItem('RealSense Only', 'realsense')
        if not ros_available():
            for index in (1, 2):
                self.backend_combo.model().item(index).setEnabled(False)
            self.backend_combo.setToolTip(
                'rospy not importable on this machine -- ROS backends disabled.'
            )
            self.backend_combo.setCurrentIndex(3)  # RealSense
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        backend_row.addWidget(self.backend_combo, stretch=1)
        layout.addLayout(backend_row)

        # What the stakeholder script hardcodes. Shown so its settings are
        # visible rather than silently overriding the fields below.
        self.script_lbl = QLabel('')
        self.script_lbl.setWordWrap(True)
        self.script_lbl.setVisible(False)
        self.script_lbl.setStyleSheet('font-size:11px; padding:4px; '
                                      'border-radius:4px; background:#1e293b; '
                                      'color:#cbd5e1;')
        layout.addWidget(self.script_lbl)

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

        # ---- hardware status: is each piece real or simulated? ----
        self.hw_lbl = QLabel('Hardware: checking...')
        self.hw_lbl.setWordWrap(True)
        self.hw_lbl.setStyleSheet('font-size:11px; padding:4px; '
                                  'border-radius:4px; background:#1e293b; '
                                  'color:#cbd5e1;')
        layout.addWidget(self.hw_lbl)

        # ---- Quick Scan: camera + gantry together, one click ----
        self.quick_btn = QPushButton('Quick Scan  (camera + gantry)')
        self.quick_btn.setToolTip(
            'Run a full scan: the gantry moves while the camera captures. '
            'Falls back to simulated hardware for whichever piece is not '
            'connected, and tells you when it does.'
        )
        self.quick_btn.setStyleSheet(
            'QPushButton { background:#2563eb; color:white; border-radius:4px; '
            'padding:8px; font-weight:bold; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.quick_btn.clicked.connect(self._on_quick_scan)
        layout.addWidget(self.quick_btn)

        # ---- individual checks ----
        test_row = QHBoxLayout()
        self.test_cam_btn = QPushButton('Test Camera')
        self.test_cam_btn.setToolTip('Grab a burst of frames and report '
                                     'resolution, rate and depth validity.')
        self.test_cam_btn.clicked.connect(
            lambda: self.selftest_requested.emit('camera'))
        test_row.addWidget(self.test_cam_btn)

        self.test_gantry_btn = QPushButton('Test Gantry')
        self.test_gantry_btn.setToolTip('Jog the axis 5 cm and report the '
                                        'distance actually measured.')
        self.test_gantry_btn.clicked.connect(
            lambda: self.selftest_requested.emit('gantry'))
        test_row.addWidget(self.test_gantry_btn)

        self.rescan_btn = QPushButton('Re-detect')
        self.rescan_btn.setFixedWidth(80)
        self.rescan_btn.setToolTip('Re-check which hardware is connected.')
        self.rescan_btn.clicked.connect(self.rescan_requested.emit)
        test_row.addWidget(self.rescan_btn)
        layout.addLayout(test_row)

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
        self._simulated = False

    def _on_backend_changed(self, _index: int) -> None:
        """Show the stakeholder script's own settings when it is selected,
        and grey out the fields it ignores."""
        is_script = self.backend_combo.currentData() == 'stakeholder'
        self.script_lbl.setVisible(is_script)
        for widget in (self.vel_spin, self.end_spin, self.fps_spin,
                       self.dur_spin):
            widget.setEnabled(not is_script)
        if not is_script:
            return
        try:
            from capture.stakeholder_capture import (find_script,
                                                     script_parameters)
            script = find_script()
            settings = script_parameters(script)
            rows = ''.join(f'<br>&nbsp;&nbsp;{key}: <b>{value}</b>'
                           for key, value in settings.items())
            self.script_lbl.setText(
                f'Capture runs <b>{os.path.basename(script)}</b> unmodified. '
                f'It uses its own settings:{rows}'
                '<br><i>The velocity / end / FPS fields above do not apply.</i>'
            )
        except Exception as e:
            self.script_lbl.setText(f'Stakeholder script unavailable: {e}')

    def _browse_out(self):
        path = QFileDialog.getExistingDirectory(self, 'Output folder root')
        if path:
            self.out_edit.setText(path)

    def _on_capture(self):
        self._emit_capture(self.backend_combo.currentData())

    def _on_quick_scan(self):
        """Camera + gantry in one pass, simulating whichever is missing."""
        self._emit_capture('quickscan')

    def _emit_capture(self, backend_pref: str):
        self._simulated = False
        self._clear_notice()
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
        self.quick_btn.setEnabled(not running)
        self.test_cam_btn.setEnabled(not running)
        self.test_gantry_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.backend_combo.setEnabled(not running)

    # ---- hardware status / simulation reporting -------------------------

    def show_hardware(self, camera_ok: bool, camera_detail: str,
                      gantry_ok: bool, gantry_detail: str) -> None:
        """Render the REAL/SIMULATED status of each piece of hardware."""
        def row(name, ok, detail):
            tag = 'REAL' if ok else 'SIMULATED'
            colour = '#4ade80' if ok else '#fbbf24'
            return (f'<b>{name}:</b> <span style="color:{colour}">{tag}</span>'
                    f' &mdash; {detail}')
        self.hw_lbl.setText(
            row('Camera', camera_ok, camera_detail) + '<br>' +
            row('Gantry', gantry_ok, gantry_detail) +
            ('' if (camera_ok and gantry_ok) else
             '<br><i>Quick Scan will simulate whatever is not connected.</i>')
        )

    def show_notice(self, text: str) -> None:
        """Loud, unmissable banner while a simulated run is in progress."""
        self._simulated = True
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(
            'color:#78350f; background:#fcd34d; font-size:11px; '
            'font-weight:bold; padding:4px; border-radius:4px;'
        )

    def _clear_notice(self) -> None:
        self.status_lbl.setStyleSheet('color:#64748b; font-size:11px;')

    def on_progress(self, idx: int, total: int):
        prefix = 'SIMULATED - ' if self._simulated else ''
        if total > 0:
            pct = min(100, int(100 * idx / max(1, total)))
            self.progress.setValue(pct)
            self.status_lbl.setText(f'{prefix}Captured {idx}/{total} frames')
        else:
            # Unknown total (ROS / manual) -- pulse
            self.progress.setRange(0, 0)
            self.status_lbl.setText(f'{prefix}Captured {idx} frames')

    def on_finished(self, out_dir: str, n_frames: int):
        self.set_running(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        prefix = 'SIMULATED run - ' if self._simulated else ''
        self.status_lbl.setText(f'{prefix}Done. {n_frames} frames -> {out_dir}')
        self._last_out = out_dir
        self.open_btn.setVisible(True)

    def on_error(self, msg: str):
        self.set_running(False)
        self._simulated = False
        self._clear_notice()
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

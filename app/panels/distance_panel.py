"""
app/panels/distance_panel.py
----------------------------
UI panel reporting whether the camera is at a good height above the plant.

The RealSense D405 is trustworthy between 7 cm and 50 cm. This panel measures
where the plant actually sits -- from the attached camera, or from a recording
already on disk -- and says whether to raise or lower the camera.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from processing.capture_distance import (
    CENTIMETRES_PER_METRE,
    D405_MAX_RANGE_M,
    D405_MIN_RANGE_M,
    VERDICT_ADJUST,
    VERDICT_GOOD,
    VERDICT_NO_DATA,
    VERDICT_OUT_OF_RANGE,
)


VERDICT_STYLES = {
    VERDICT_GOOD:         ('#16a34a', 'DISTANCE GOOD'),
    VERDICT_ADJUST:       ('#d97706', 'ADJUST HEIGHT'),
    VERDICT_OUT_OF_RANGE: ('#dc2626', 'OUT OF RANGE'),
    VERDICT_NO_DATA:      ('#475569', 'NO DEPTH DATA'),
}


class DistancePanel(QWidget):

    # n_frames
    camera_check_requested  = pyqtSignal(int)
    # depth_scale_units_per_m, n_frames
    dataset_check_requested = pyqtSignal(float, int)

    DEFAULT_FRAMES = 10
    DEFAULT_DEPTH_SCALE = 10000.0

    def __init__(self):
        super().__init__()
        self._last_check = None
        self._running = False
        self._camera_available = True
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel('Capture Distance')
        title.setStyleSheet('font-weight:bold; font-size:14px;')
        layout.addWidget(title)

        target = QLabel(
            f'Keep the plant {D405_MIN_RANGE_M * CENTIMETRES_PER_METRE:.0f}-'
            f'{D405_MAX_RANGE_M * CENTIMETRES_PER_METRE:.0f} cm from the D405, '
            'with the camera low enough that most of it is in that range.'
        )
        target.setStyleSheet('color:#64748b; font-size:11px;')
        target.setWordWrap(True)
        layout.addWidget(target)

        # Frames to sample / depth unit for the on-disk mode
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel('Frames:'))
        self.frames_spin = QSpinBox()
        self.frames_spin.setRange(1, 120)
        self.frames_spin.setValue(self.DEFAULT_FRAMES)
        self.frames_spin.setToolTip(
            'Depth frames to measure. More frames average over sensor noise.'
        )
        settings_row.addWidget(self.frames_spin)
        settings_row.addWidget(QLabel('Depth units/m:'))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(1.0, 100000.0)
        self.scale_spin.setDecimals(1)
        self.scale_spin.setSingleStep(1000.0)
        self.scale_spin.setValue(self.DEFAULT_DEPTH_SCALE)
        self.scale_spin.setToolTip(
            'Raw depth units per metre, used for the saved-recording check '
            'only. A D405 reporting 0.0001 m per unit is 10000; millimetre '
            'depth is 1000. The camera check reads this from the device.'
        )
        settings_row.addWidget(self.scale_spin)
        layout.addLayout(settings_row)

        # Buttons
        btn_row = QHBoxLayout()
        self.camera_btn = QPushButton('Check Camera')
        self.camera_btn.setToolTip(
            'Open the camera briefly and measure the current distance. '
            'Nothing is captured or saved.'
        )
        self.camera_btn.setStyleSheet(
            'QPushButton { background:#0d9488; color:white; border-radius:4px; padding:6px; font-weight:bold; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.camera_btn.clicked.connect(self._request_camera_check)

        self.dataset_btn = QPushButton('Check Recording')
        self.dataset_btn.setToolTip(
            'Measure the depth folder selected under Data Loading.'
        )
        self.dataset_btn.setStyleSheet(
            'QPushButton { background:#4f46e5; color:white; border-radius:4px; padding:6px; font-weight:bold; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.dataset_btn.clicked.connect(self._request_dataset_check)

        btn_row.addWidget(self.camera_btn)
        btn_row.addWidget(self.dataset_btn)
        layout.addLayout(btn_row)

        # Verdict banner
        self.verdict_lbl = QLabel('No distance check run yet.')
        self.verdict_lbl.setAlignment(Qt.AlignCenter)
        self.verdict_lbl.setStyleSheet(
            'background:#1e1e2e; color:#94a3b8; padding:8px; '
            'border-radius:6px; font-weight:bold;'
        )
        layout.addWidget(self.verdict_lbl)

        # Advice + measured numbers
        self.detail_lbl = QLabel('')
        self.detail_lbl.setStyleSheet('color:#cbd5e1; font-size:11px;')
        self.detail_lbl.setWordWrap(True)
        layout.addWidget(self.detail_lbl)

    # ------------------------------------------------------------------ state

    def set_running(self, running: bool):
        self._running = bool(running)
        self._refresh_buttons()

    def set_camera_available(self, available: bool):
        """Disable the live probe while the camera belongs to a capture."""
        self._camera_available = bool(available)
        self._refresh_buttons()

    def on_status(self, message: str):
        self._set_banner('#1e1e2e', '#94a3b8', 'MEASURING')
        self.detail_lbl.setText(message)

    def on_error(self, message: str):
        self._last_check = None
        self.set_running(False)
        self._set_banner('#dc2626', 'white', 'DISTANCE CHECK FAILED')
        self.detail_lbl.setText(message)

    def show_check(self, check):
        """Render a DistanceCheck."""
        self._last_check = check
        self.set_running(False)
        colour, headline = VERDICT_STYLES.get(
            check.verdict, ('#475569', check.verdict)
        )
        self._set_banner(colour, 'white', headline)
        self.detail_lbl.setText(self._details(check))

    @property
    def last_check(self):
        return self._last_check

    # ---------------------------------------------------------------- private

    def _request_camera_check(self):
        self.set_running(True)
        self.camera_check_requested.emit(self.frames_spin.value())

    def _request_dataset_check(self):
        self.set_running(True)
        self.dataset_check_requested.emit(
            self.scale_spin.value(), self.frames_spin.value()
        )

    def _refresh_buttons(self):
        self.camera_btn.setEnabled(not self._running and self._camera_available)
        self.dataset_btn.setEnabled(not self._running)
        self.camera_btn.setToolTip(
            'Open the camera briefly and measure the current distance. '
            'Nothing is captured or saved.'
            if self._camera_available else
            'The camera is in use by the running capture.'
        )

    def _set_banner(self, background: str, colour: str, text: str):
        self.verdict_lbl.setStyleSheet(
            f'background:{background}; color:{colour}; padding:8px; '
            'border-radius:6px; font-weight:bold;'
        )
        self.verdict_lbl.setText(text)

    def _details(self, check) -> str:
        lines = [check.advice]
        if check.nearest_m is not None:
            lines.append(
                'Whole frame: nearest '
                f'{check.nearest_m * CENTIMETRES_PER_METRE:.1f} cm, median '
                f'{check.median_m * CENTIMETRES_PER_METRE:.1f} cm, farthest '
                f'{check.farthest_m * CENTIMETRES_PER_METRE:.1f} cm; '
                f'{check.in_range_fraction * 100:.0f}% in range, '
                f'{check.too_near_fraction * 100:.0f}% too near, '
                f'{check.too_far_fraction * 100:.0f}% too far.'
            )
        lines.append(
            f'{check.frames_evaluated} frame(s), '
            f'{check.valid_fraction * 100:.0f}% of sampled pixels carried '
            f'depth, {check.depth_scale_units_per_m:.0f} units/m'
            + (f', {check.camera_model}' if check.camera_model else '')
            + '.'
        )
        lines.extend(check.notes)
        return '\n'.join(lines)

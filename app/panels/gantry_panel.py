"""
app/panels/gantry_panel.py
--------------------------
Manual gantry control panel for the lab Linux rig.

Hold-to-move jog (mouse press = move, release = stop), absolute
go-to-position with safety clamp, go-home, big red stop button, and a
live position read-back driven by /joint_states.

When rospy isn't importable on the host (Windows / WSL without ROS),
all controls disable themselves and a tooltip explains why -- no crash,
no popup spam.
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget, QFrame,
)


class GantryPanel(QWidget):
    """
    Signals (panel -> Controller):
        jog_requested(velocity_mps)   signed velocity, 0 = stop
        goto_requested(position_m)    absolute target position
        go_home_requested()           shorthand for go-to-home
        stop_requested()              emergency stop
    """

    jog_requested     = pyqtSignal(float)
    goto_requested    = pyqtSignal(float)
    go_home_requested = pyqtSignal()
    stop_requested    = pyqtSignal()

    _OFFLINE_TOOLTIP = (
        "rospy not importable on this machine -- gantry controls are "
        "only available on the lab Linux rig with ROS sourced."
    )

    def __init__(self, available: bool = True):
        super().__init__()
        self._available = available
        self._build_ui()
        self._apply_availability(available)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel('Gantry Control')
        title.setStyleSheet('font-weight:bold; font-size:14px;')
        layout.addWidget(title)

        # ---- status row: live position + READY/OFFLINE badge ----
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel('Position:'))
        self.pos_lbl = QLabel('--- m')
        self.pos_lbl.setStyleSheet(
            'font-family: monospace; font-size:13px; font-weight:bold;'
        )
        status_row.addWidget(self.pos_lbl)
        status_row.addStretch()
        self.badge = QLabel('READY')
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedWidth(70)
        self.badge.setStyleSheet(
            'background:#16a34a; color:white; border-radius:4px; '
            'padding:2px; font-weight:bold; font-size:11px;'
        )
        status_row.addWidget(self.badge)
        layout.addLayout(status_row)

        # ---- jog row: hold-to-move buttons + velocity ----
        jog_row = QHBoxLayout()
        self.jog_back_btn = QPushButton('<<  Jog')
        self.jog_back_btn.setToolTip('Hold to move the gantry in -X')
        self.jog_back_btn.pressed.connect(self._on_jog_back_pressed)
        self.jog_back_btn.released.connect(self._on_jog_released)
        jog_row.addWidget(self.jog_back_btn)

        self.jog_fwd_btn = QPushButton('Jog  >>')
        self.jog_fwd_btn.setToolTip('Hold to move the gantry in +X')
        self.jog_fwd_btn.pressed.connect(self._on_jog_fwd_pressed)
        self.jog_fwd_btn.released.connect(self._on_jog_released)
        jog_row.addWidget(self.jog_fwd_btn)
        layout.addLayout(jog_row)

        vel_row = QHBoxLayout()
        vel_row.addWidget(QLabel('Velocity (m/s):'))
        self.vel_spin = QDoubleSpinBox()
        self.vel_spin.setRange(0.001, 0.2)
        self.vel_spin.setSingleStep(0.005)
        self.vel_spin.setDecimals(3)
        self.vel_spin.setValue(0.038)
        vel_row.addWidget(self.vel_spin)
        vel_row.addStretch()
        layout.addLayout(vel_row)

        # ---- separator ----
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('color:#334155;')
        layout.addWidget(sep)

        # ---- absolute go-to row ----
        goto_row = QHBoxLayout()
        goto_row.addWidget(QLabel('Go to (m):'))
        self.goto_spin = QDoubleSpinBox()
        self.goto_spin.setRange(0.0, 5.0)
        self.goto_spin.setSingleStep(0.05)
        self.goto_spin.setDecimals(3)
        self.goto_spin.setValue(0.0)
        goto_row.addWidget(self.goto_spin)
        self.goto_btn = QPushButton('Go')
        self.goto_btn.setFixedWidth(50)
        self.goto_btn.clicked.connect(
            lambda: self.goto_requested.emit(self.goto_spin.value())
        )
        goto_row.addWidget(self.goto_btn)
        layout.addLayout(goto_row)

        # ---- go-home + stop ----
        action_row = QHBoxLayout()
        self.home_btn = QPushButton('Go Home')
        self.home_btn.clicked.connect(self.go_home_requested.emit)
        action_row.addWidget(self.home_btn)

        self.stop_btn = QPushButton('STOP')
        self.stop_btn.setStyleSheet(
            'QPushButton { background:#dc2626; color:white; border-radius:4px; '
            'padding:6px; font-weight:bold; font-size:13px; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        action_row.addWidget(self.stop_btn)
        layout.addLayout(action_row)

        # ---- last error / status string ----
        self.status_lbl = QLabel('')
        self.status_lbl.setStyleSheet('color:#64748b; font-size:11px;')
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

    # ----------------------------------------------------------- behaviour

    def _on_jog_fwd_pressed(self):
        self.jog_requested.emit(+self.vel_spin.value())

    def _on_jog_back_pressed(self):
        self.jog_requested.emit(-self.vel_spin.value())

    def _on_jog_released(self):
        # Always emit a stop on release -- this is the only safety
        # guarantee that prevents a runaway jog if the user drags off
        # the button while holding.
        self.stop_requested.emit()

    def _apply_availability(self, available: bool) -> None:
        widgets = [
            self.jog_back_btn, self.jog_fwd_btn, self.vel_spin,
            self.goto_spin, self.goto_btn, self.home_btn, self.stop_btn,
        ]
        for w in widgets:
            w.setEnabled(available)
        if available:
            self.badge.setText('READY')
            self.badge.setStyleSheet(
                'background:#16a34a; color:white; border-radius:4px; '
                'padding:2px; font-weight:bold; font-size:11px;'
            )
            self.setToolTip('')
        else:
            self.badge.setText('OFFLINE')
            self.badge.setStyleSheet(
                'background:#94a3b8; color:white; border-radius:4px; '
                'padding:2px; font-weight:bold; font-size:11px;'
            )
            self.setToolTip(self._OFFLINE_TOOLTIP)
            self.status_lbl.setText(self._OFFLINE_TOOLTIP)

    # ------------------------------------------------------------- public

    def update_position(self, position_m: float) -> None:
        self.pos_lbl.setText(f'{position_m:+.4f} m')

    def show_status(self, text: str) -> None:
        self.status_lbl.setText(text)

    def set_capture_active(self, active: bool) -> None:
        """Disable jog / go-to during an active capture so the user
        can't command motion that fights the capture loop. Stop stays
        enabled as an emergency hatch."""
        if not self._available:
            return
        for w in (self.jog_back_btn, self.jog_fwd_btn,
                  self.goto_btn, self.home_btn):
            w.setEnabled(not active)

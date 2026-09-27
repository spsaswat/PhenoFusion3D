"""
app/panels/gantry_panel.py
--------------------------
Manual gantry control panel for the lab Linux rig.

Hold-to-move jog (mouse press = move, release = stop), absolute
go-to-position with safety clamp, go-home, big red stop button, and a
live position read-back driven by /joint_states.

When the Linux machine has no ROS installation, all controls disable
themselves and a tooltip explains why -- no crash or popup spam.
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from app import theme
from capture.base import DEFAULT_END_POSITION_M, MILLIMETRES_PER_METRE


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

    DEFAULT_JOG_VELOCITY_MPS = 0.005
    DEFAULT_GOTO_POSITION_M = DEFAULT_END_POSITION_M

    _OFFLINE_TOOLTIP = (
        "No ROS installation was detected for the gantry. Source the lab "
        "ROS distribution and gantry workspace before launching."
    )

    def __init__(self, available: bool = True):
        super().__init__()
        self._available = available
        self._default_velocity_mps = self.DEFAULT_JOG_VELOCITY_MPS
        self._build_ui()
        self._apply_availability(available)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        theme.card(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                  theme.MARGIN, theme.MARGIN)
        layout.setSpacing(theme.GAP)

        # ---- header row: title + READY/OFFLINE badge ----
        header_row = QHBoxLayout()
        header_row.addWidget(theme.title('Gantry Control'))
        header_row.addStretch()
        self.badge = QLabel('READY')
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedWidth(76)
        theme.role(self.badge, 'badge')
        header_row.addWidget(self.badge)
        layout.addLayout(header_row)

        # ---- live position read-back ----
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(QLabel('Position'))
        self.pos_lbl = QLabel('--- mm')
        self.pos_lbl.setAlignment(Qt.AlignCenter)
        theme.role(self.pos_lbl, 'readout')
        status_row.addWidget(self.pos_lbl, stretch=1)
        layout.addLayout(status_row)

        # ---- jog row: hold-to-move buttons + velocity ----
        layout.addWidget(theme.role(QLabel('JOG'), 'section'))
        jog_row = QHBoxLayout()
        jog_row.setSpacing(8)
        self.jog_back_btn = QPushButton('<<  Jog')
        self.jog_back_btn.setToolTip('Hold to move the gantry in +X')
        self.jog_back_btn.pressed.connect(self._on_jog_back_pressed)
        self.jog_back_btn.released.connect(self._on_jog_released)
        jog_row.addWidget(self.jog_back_btn)

        self.jog_fwd_btn = QPushButton('Jog  >>')
        self.jog_fwd_btn.setToolTip('Hold to move the gantry in -X')
        self.jog_fwd_btn.pressed.connect(self._on_jog_fwd_pressed)
        self.jog_fwd_btn.released.connect(self._on_jog_released)
        jog_row.addWidget(self.jog_fwd_btn)
        layout.addLayout(jog_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.vel_spin = QDoubleSpinBox()
        self.vel_spin.setRange(1.0, 200.0)
        self.vel_spin.setSingleStep(5.0)
        self.vel_spin.setDecimals(1)
        self.vel_spin.setValue(
            self._default_velocity_mps * MILLIMETRES_PER_METRE
        )
        form.addRow('Velocity (mm/s)', self.vel_spin)

        # ---- absolute go-to row ----
        self.goto_spin = QDoubleSpinBox()
        self.goto_spin.setRange(0.0, 5000.0)
        self.goto_spin.setSingleStep(50.0)
        self.goto_spin.setDecimals(1)
        self.goto_spin.setValue(
            self.DEFAULT_GOTO_POSITION_M * MILLIMETRES_PER_METRE
        )
        self.goto_btn = QPushButton('Go')
        self.goto_btn.setFixedWidth(56)
        self.goto_btn.clicked.connect(
            lambda: self.goto_requested.emit(
                self.goto_spin.value() / MILLIMETRES_PER_METRE
            )
        )
        goto_field = QWidget()
        goto_layout = QHBoxLayout(goto_field)
        goto_layout.setContentsMargins(0, 0, 0, 0)
        goto_layout.setSpacing(6)
        goto_layout.addWidget(self.goto_spin)
        goto_layout.addWidget(self.goto_btn)
        form.addRow('Go to (mm)', goto_field)
        layout.addLayout(form)

        layout.addWidget(theme.separator())

        # ---- go-home + stop ----
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.home_btn = QPushButton('Go Home')
        self.home_btn.clicked.connect(self.go_home_requested.emit)
        action_row.addWidget(self.home_btn)

        self.stop_btn = QPushButton('STOP')
        theme.variant(self.stop_btn, 'danger')
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        action_row.addWidget(self.stop_btn)
        layout.addLayout(action_row)

        # ---- last error / status string ----
        self.status_lbl = QLabel('')
        theme.role(self.status_lbl, 'hint')
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

    # ----------------------------------------------------------- behaviour

    def _on_jog_fwd_pressed(self):
        self.jog_requested.emit(
            -self.vel_spin.value() / MILLIMETRES_PER_METRE
        )

    def _on_jog_back_pressed(self):
        self.jog_requested.emit(
            self.vel_spin.value() / MILLIMETRES_PER_METRE
        )

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
            theme.role(self.badge, 'badge')
            self.setToolTip('')
        else:
            self.badge.setText('OFFLINE')
            theme.role(self.badge, 'badgeOffline')
            self.setToolTip(self._OFFLINE_TOOLTIP)
            self.status_lbl.setText(self._OFFLINE_TOOLTIP)

    # ------------------------------------------------------------- public

    def update_position(self, position_m: float) -> None:
        position_mm = position_m * MILLIMETRES_PER_METRE
        self.pos_lbl.setText(f'{position_mm:+.1f} mm')

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

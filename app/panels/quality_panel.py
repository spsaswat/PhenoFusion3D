"""
app/panels/quality_panel.py
---------------------------
UI panel for running data-quality checks on the currently loaded
RGB-D sequence.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QFileDialog,
)

from app import theme


class QualityPanel(QWidget):

    quick_requested = pyqtSignal()
    full_requested  = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._last_report = None
        self._build_ui()

    def _build_ui(self):
        theme.card(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                  theme.MARGIN, theme.MARGIN)
        layout.setSpacing(theme.GAP)

        layout.addWidget(theme.title('Data Quality'))

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.quick_btn = QPushButton('Quick Check')
        self.quick_btn.setToolTip('Sample ~15 random pairs (10-30 s)')
        theme.variant(self.quick_btn, 'primary')
        self.quick_btn.clicked.connect(self.quick_requested.emit)

        self.full_btn = QPushButton('Full Report')
        self.full_btn.setToolTip('Evaluate every consecutive pair (slow)')
        self.full_btn.clicked.connect(self.full_requested.emit)

        btn_row.addWidget(self.quick_btn)
        btn_row.addWidget(self.full_btn)
        layout.addLayout(btn_row)

        # Verdict banner
        self.verdict_lbl = QLabel('No quality check run yet.')
        self.verdict_lbl.setAlignment(Qt.AlignCenter)
        self.verdict_lbl.setWordWrap(True)
        theme.role(self.verdict_lbl, 'banner')
        layout.addWidget(self.verdict_lbl)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Metrics table (rows: metrics; cols: mean / median / p25 / p75)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['mean', 'median', 'p25', 'p75'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(150)
        layout.addWidget(self.table)

        # Save report
        self.save_btn = QPushButton('Save report (CSV + TXT)')
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_report)
        layout.addWidget(self.save_btn)

    def set_running(self, running: bool):
        self.quick_btn.setEnabled(not running)
        self.full_btn.setEnabled(not running)

    def on_progress(self, idx: int, total: int):
        if total > 0:
            self.progress.setValue(min(100, int(100 * idx / total)))
        else:
            self.progress.setRange(0, 0)

    def show_report(self, report) -> None:
        self._last_report = report
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.set_running(False)
        self.save_btn.setEnabled(True)

        # Verdict banner colour. Result semantics stay conventional
        # (green/amber/red) so a reading is never ambiguous.
        v = report.verdict
        colour = {
            'PASS': theme.SUCCESS,
            'WARN': theme.WARNING,
            'FAIL': theme.DANGER,
        }.get(v, theme.TEXT_MUTED)
        msg = f'{v}  --  {report.n_pairs_evaluated} pairs evaluated'
        if report.failing_metrics:
            msg += '\n' + '; '.join(report.failing_metrics)
        self.verdict_lbl.setText(msg)
        self.verdict_lbl.setStyleSheet(
            f'background:{colour}; color:{theme.TEXT_INVERTED}; padding:10px; '
            f'border:1px solid {colour}; border-radius:8px; font-weight:600;'
        )

        # Table
        rows = list(report.aggregate.items())
        self.table.setRowCount(len(rows))
        for r, (name, stats) in enumerate(rows):
            self.table.setVerticalHeaderItem(r, QTableWidgetItem(name))
            for c, key in enumerate(('mean', 'median', 'p25', 'p75')):
                self.table.setItem(r, c, QTableWidgetItem(f'{stats[key]:.4f}'))

    def on_error(self, msg: str):
        self.set_running(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.verdict_lbl.setText(f'ERROR: {msg}')
        self.verdict_lbl.setStyleSheet(
            f'background:{theme.DANGER}; color:{theme.TEXT_INVERTED}; '
            f'padding:10px; border:1px solid {theme.DANGER}; '
            f'border-radius:8px; font-weight:600;'
        )

    def _save_report(self):
        if self._last_report is None:
            return
        path = QFileDialog.getExistingDirectory(self, 'Save report to folder')
        if not path:
            return
        self._last_report.write_csv(os.path.join(path, 'quality_report.csv'))
        self._last_report.write_summary(os.path.join(path, 'quality_report.txt'))

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtGui import QColor


class MetricsPanel(QWidget):

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background:#f8fafc; border-radius:4px;')
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel('Reconstruction Metrics')
        title.setStyleSheet('font-weight:bold; font-size:13px;')
        layout.addWidget(title)

        row1 = QHBoxLayout()
        self.frame_lbl   = self._metric_label('Frame: -')
        self.fitness_lbl = self._metric_label('Fitness: -')
        self.rmse_lbl    = self._metric_label('RMSE: -')
        row1.addWidget(self.frame_lbl)
        row1.addWidget(self.fitness_lbl)
        row1.addWidget(self.rmse_lbl)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.success_lbl = self._metric_label('Success: 0')
        self.fail_lbl    = self._metric_label('Failed: 0')
        row2.addWidget(self.success_lbl)
        row2.addWidget(self.fail_lbl)
        row2.addStretch()
        layout.addLayout(row2)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

    def _metric_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet('font-size:12px; padding:2px 6px; background:#e2e8f0; border-radius:3px;')
        return lbl

    @pyqtSlot(int, int, float, float, int, int)
    def update_metrics(self, frame_idx, total, fitness, rmse, n_success, n_fail):
        self.frame_lbl.setText(f'Frame: {frame_idx + 1} / {total}')
        self.rmse_lbl.setText(f'RMSE: {rmse:.5f}')
        self.success_lbl.setText(f'Success: {n_success}')
        self.fail_lbl.setText(f'Failed: {n_fail}')

        # Colour-coded fitness
        fit_text = f'Fitness: {fitness:.4f}'
        if fitness >= 0.5:
            colour = '#16a34a'   # green
        elif fitness >= 0.1:
            colour = '#d97706'   # orange
        else:
            colour = '#dc2626'   # red
        self.fitness_lbl.setText(fit_text)
        self.fitness_lbl.setStyleSheet(
            f'font-size:12px; padding:2px 6px; background:{colour}22; '
            f'color:{colour}; border-radius:3px; font-weight:bold;'
        )

        if n_fail > 0:
            self.fail_lbl.setStyleSheet('font-size:12px; padding:2px 6px; background:#fee2e2; color:#dc2626; border-radius:3px;')

        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(frame_idx + 1)
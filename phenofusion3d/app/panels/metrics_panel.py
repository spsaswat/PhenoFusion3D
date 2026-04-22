"""
Metrics panel - ICP fitness and RMSE display. Updates per frame.
"""
from PyQt5.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QWidget
from PyQt5.QtCore import Qt


class MetricsPanel(QWidget):
    """Displays fitness and inlier RMSE per frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        grp = QGroupBox("Registration Metrics")
        inner = QVBoxLayout(grp)

        self.fitness_label = QLabel("Fitness: —")
        self.rmse_label = QLabel("Inlier RMSE: —")
        self.frame_label = QLabel("Frame: — / —")

        inner.addWidget(self.frame_label)
        inner.addWidget(self.fitness_label)
        inner.addWidget(self.rmse_label)
        layout.addWidget(grp)

    def update_metrics(self, frame_idx, total_frames, fitness, inlier_rmse):
        self.frame_label.setText(f"Frame: {frame_idx + 1} / {total_frames}")
        self.fitness_label.setText(f"Fitness: {fitness:.4f}")
        self.rmse_label.setText(f"Inlier RMSE: {inlier_rmse:.4f}")

    def reset(self):
        self.frame_label.setText("Frame: — / —")
        self.fitness_label.setText("Fitness: —")
        self.rmse_label.setText("Inlier RMSE: —")

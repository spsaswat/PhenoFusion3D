"""
Controls panel - Step size, Run, Stop buttons. Stop interrupts processing.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import pyqtSignal


class ControlsPanel(QWidget):
    """Run and Stop controls."""

    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        layout.addWidget(self.stop_btn)
        layout.addStretch()

    def set_stop_enabled(self, enabled):
        self.stop_btn.setEnabled(enabled)

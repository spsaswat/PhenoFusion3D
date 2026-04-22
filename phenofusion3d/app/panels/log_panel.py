"""
Log panel - Per-frame success/fail log. Scrollable text.
"""
from PyQt5.QtWidgets import QGroupBox, QVBoxLayout, QTextEdit, QWidget


class LogPanel(QWidget):
    """Scrollable log of processing events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        grp = QGroupBox("Log")
        inner = QVBoxLayout(grp)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        inner.addWidget(self.log_text)
        layout.addWidget(grp)

    def append(self, text):
        self.log_text.append(text)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log_success(self, frame_idx, fitness, rmse):
        self.append(f"[Frame {frame_idx}] OK  fitness={fitness:.4f} rmse={rmse:.4f}")

    def log_fail(self, frame_idx):
        self.append(f"[Frame {frame_idx}] FAIL - ICP low fitness, skipped")

    def clear(self):
        self.log_text.clear()

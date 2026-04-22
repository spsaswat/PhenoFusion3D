"""
Data loading panel - RGB folder, Depth folder, Intrinsics file, Step size, Run button.
"""
import os
from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QSpinBox,
    QWidget,
)
from PyQt5.QtCore import pyqtSignal


class DataPanel(QWidget):
    """File/folder selection and run controls."""

    run_requested = pyqtSignal(str, str, str, int)  # rgb_dir, depth_dir, intrinsics_path, step_size

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # RGB folder row
        rgb_row = QHBoxLayout()
        rgb_row.addWidget(QLabel("RGB Image Folder:"))
        self.rgb_edit = QLineEdit()
        self.rgb_edit.setReadOnly(True)
        self.rgb_edit.setPlaceholderText("Select folder containing rgb_*.png")
        rgb_row.addWidget(self.rgb_edit)
        rgb_btn = QPushButton("Browse...")
        rgb_btn.clicked.connect(self._browse_rgb)
        rgb_row.addWidget(rgb_btn)
        layout.addLayout(rgb_row)

        # Depth folder row (optional - same as RGB if blank)
        depth_row = QHBoxLayout()
        depth_row.addWidget(QLabel("Depth Image Folder:"))
        self.depth_edit = QLineEdit()
        self.depth_edit.setReadOnly(True)
        self.depth_edit.setPlaceholderText("Optional - same as RGB if blank")
        depth_row.addWidget(self.depth_edit)
        depth_btn = QPushButton("Browse...")
        depth_btn.clicked.connect(self._browse_depth)
        depth_row.addWidget(depth_btn)
        layout.addLayout(depth_row)

        # Intrinsics file row
        intr_row = QHBoxLayout()
        intr_row.addWidget(QLabel("Intrinsics JSON:"))
        self.intr_edit = QLineEdit()
        self.intr_edit.setReadOnly(True)
        self.intr_edit.setPlaceholderText("Optional - default intrinsics if blank")
        intr_row.addWidget(self.intr_edit)
        intr_btn = QPushButton("Browse...")
        intr_btn.clicked.connect(self._browse_intrinsics)
        intr_row.addWidget(intr_btn)
        layout.addLayout(intr_row)

        # Step size + Run
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Step Size:"))
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 10)
        self.step_spin.setValue(2)
        self.step_spin.setToolTip("1=every frame, 2=every 2nd frame, etc.")
        ctrl_row.addWidget(self.step_spin)
        ctrl_row.addStretch()
        self.run_btn = QPushButton("Run Reconstruction")
        self.run_btn.clicked.connect(self._on_run)
        ctrl_row.addWidget(self.run_btn)
        layout.addLayout(ctrl_row)

    def _browse_rgb(self):
        path = QFileDialog.getExistingDirectory(self, "Select RGB Image Folder")
        if path:
            self.rgb_edit.setText(path)
            if not self.depth_edit.text().strip():
                self.depth_edit.setText(path)

    def _browse_depth(self):
        path = QFileDialog.getExistingDirectory(self, "Select Depth Image Folder")
        if path:
            self.depth_edit.setText(path)

    def _browse_intrinsics(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Intrinsics JSON", "", "JSON (*.json *.txt);;All (*)"
        )
        if path:
            self.intr_edit.setText(path)

    def _on_run(self):
        rgb = self.rgb_edit.text().strip()
        if not rgb or not os.path.isdir(rgb):
            self.run_requested.emit("", "", "", 0)  # Controller can show error
            return
        depth = self.depth_edit.text().strip() or rgb
        intr = self.intr_edit.text().strip()
        step = self.step_spin.value()
        self.run_requested.emit(rgb, depth, intr, step)

    def set_run_enabled(self, enabled):
        self.run_btn.setEnabled(enabled)

    def get_paths(self):
        return {
            "rgb_dir": self.rgb_edit.text().strip(),
            "depth_dir": self.depth_edit.text().strip() or self.rgb_edit.text().strip(),
            "intrinsics": self.intr_edit.text().strip(),
            "step_size": self.step_spin.value(),
        }

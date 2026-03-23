from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QSpinBox, QFileDialog, QMessageBox
)
from PyQt5.QtCore import pyqtSignal, Qt
import os


class DataPanel(QWidget):

    run_requested  = pyqtSignal(str, str, str, int)  # rgb_dir, depth_dir, intrinsics, step
    stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        title = QLabel('Data Loading')
        title.setStyleSheet('font-weight:bold; font-size:14px;')
        layout.addWidget(title)

        self.rgb_edit   = self._add_folder_row(layout, 'RGB Images:')
        self.depth_edit = self._add_folder_row(layout, 'Depth Images:')
        self.intr_edit  = self._add_file_row(layout,   'Intrinsics JSON:', optional=True)

        # Step size
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel('Step Size:'))
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 20)
        self.step_spin.setValue(2)
        self.step_spin.setToolTip('Use every Nth frame (2 = every other frame)')
        step_row.addWidget(self.step_spin)
        step_row.addStretch()
        layout.addLayout(step_row)

        # Run / Stop buttons
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton('Run Reconstruction')
        self.run_btn.setEnabled(False)
        self.run_btn.setStyleSheet(
            'QPushButton { background:#2563eb; color:white; border-radius:4px; padding:6px; font-weight:bold; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.run_btn.clicked.connect(self._on_run)

        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            'QPushButton { background:#dc2626; color:white; border-radius:4px; padding:6px; font-weight:bold; }'
            'QPushButton:disabled { background:#94a3b8; }'
        )
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

    def _add_folder_row(self, parent_layout, label):
        parent_layout.addWidget(QLabel(label))
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.setPlaceholderText('Select folder...')
        browse = QPushButton('Browse')
        browse.setFixedWidth(60)
        browse.clicked.connect(lambda: self._browse_folder(edit))
        row.addWidget(edit)
        row.addWidget(browse)
        parent_layout.addLayout(row)
        return edit

    def _add_file_row(self, parent_layout, label, optional=False):
        lbl_row = QHBoxLayout()
        lbl_row.addWidget(QLabel(label))
        if optional:
            opt = QLabel('(optional)')
            opt.setStyleSheet('color:#94a3b8; font-size:11px;')
            lbl_row.addWidget(opt)
        lbl_row.addStretch()
        parent_layout.addLayout(lbl_row)

        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.setPlaceholderText('Select file... (default intrinsics used if blank)')
        browse = QPushButton('Browse')
        browse.setFixedWidth(60)
        browse.clicked.connect(lambda: self._browse_file(edit))
        row.addWidget(edit)
        row.addWidget(browse)
        parent_layout.addLayout(row)
        return edit

    def _browse_folder(self, edit):
        path = QFileDialog.getExistingDirectory(self, 'Select Folder')
        if path:
            edit.setText(path)
            self._validate()

    def _browse_file(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, 'Select File', '', 'JSON/Text (*.txt *.json)')
        if path:
            edit.setText(path)

    def _validate(self):
        rgb_ok   = bool(self.rgb_edit.text())
        depth_ok = bool(self.depth_edit.text())
        self.run_btn.setEnabled(rgb_ok and depth_ok)

    def _on_run(self):
        rgb_dir   = self.rgb_edit.text()
        depth_dir = self.depth_edit.text()
        intr_path = self.intr_edit.text()
        step      = self.step_spin.value()

        # Quick count check
        import glob
        rgb_count = len(glob.glob(os.path.join(rgb_dir, '*.png')))
        if rgb_count == 0:
            QMessageBox.warning(self, 'No Images', f'No PNG files found in:\n{rgb_dir}')
            return

        self.set_running(True)
        self.run_requested.emit(rgb_dir, depth_dir, intr_path, step)

    def set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
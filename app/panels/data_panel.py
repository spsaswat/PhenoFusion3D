from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFormLayout,
    QPushButton, QLineEdit, QSpinBox, QFileDialog, QMessageBox
)
from PyQt5.QtCore import pyqtSignal, Qt
import os

from app import theme


class DataPanel(QWidget):

    run_requested  = pyqtSignal(str, str, str, int)  # rgb_dir, depth_dir, intrinsics, step
    stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        theme.card(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                  theme.MARGIN, theme.MARGIN)
        layout.setSpacing(theme.GAP)

        layout.addWidget(theme.title('Data Loading'))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.rgb_edit   = self._add_folder_row(form, 'RGB images')
        self.depth_edit = self._add_folder_row(form, 'Depth images')
        self.intr_edit  = self._add_file_row(form,   'Intrinsics JSON')

        # Step size
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 20)
        self.step_spin.setValue(2)
        self.step_spin.setToolTip('Use every Nth frame (2 = every other frame)')
        form.addRow('Step size', self.step_spin)
        layout.addLayout(form)

        layout.addWidget(theme.hint(
            'Intrinsics are optional - the default camera intrinsics are used '
            'when the field is blank.'
        ))

        layout.addWidget(theme.separator())

        # Run / Stop buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.run_btn = QPushButton('Run Reconstruction')
        self.run_btn.setEnabled(False)
        theme.variant(self.run_btn, 'primary')
        self.run_btn.clicked.connect(self._on_run)

        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        theme.variant(self.stop_btn, 'danger')
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

    def _add_folder_row(self, form, label):
        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.setPlaceholderText('Select folder...')
        browse = QPushButton('Browse')
        browse.setFixedWidth(72)
        browse.clicked.connect(lambda: self._browse_folder(edit))
        form.addRow(label, self._field(edit, browse))
        return edit

    def _add_file_row(self, form, label):
        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.setPlaceholderText('Optional - default intrinsics if blank')
        browse = QPushButton('Browse')
        browse.setFixedWidth(72)
        browse.clicked.connect(lambda: self._browse_file(edit))
        form.addRow(label, self._field(edit, browse))
        return edit

    def _field(self, edit, button):
        """Pair an input with its Browse button inside one form field."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(edit)
        row_layout.addWidget(button)
        return row

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

    def set_paths(self, rgb_dir: str, depth_dir: str, intrinsics: str = ''):
        """Programmatically populate paths (called after a successful capture)."""
        self.rgb_edit.setText(rgb_dir or '')
        self.depth_edit.setText(depth_dir or '')
        self.intr_edit.setText(intrinsics or '')
        self._validate()

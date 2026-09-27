import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from app import theme


class PostProcessPanel(QWidget):
    clean_requested = pyqtSignal(str, str)
    segment_requested = pyqtSignal(str, str, int)
    traits_requested = pyqtSignal(str, str)
    pipeline_requested = pyqtSignal(str, str, int)

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        theme.card(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                  theme.MARGIN, theme.MARGIN)
        layout.setSpacing(theme.GAP)

        layout.addWidget(theme.title('Post Processing'))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.ply_edit = QLineEdit()
        self.ply_edit.setReadOnly(True)
        self.ply_edit.setPlaceholderText('Select reconstructed or cleaned PLY...')
        browse = QPushButton('Browse')
        browse.setFixedWidth(72)
        browse.clicked.connect(self._browse_ply)
        ply_field = QWidget()
        ply_layout = QHBoxLayout(ply_field)
        ply_layout.setContentsMargins(0, 0, 0, 0)
        ply_layout.setSpacing(6)
        ply_layout.addWidget(self.ply_edit)
        ply_layout.addWidget(browse)
        form.addRow('PLY file', ply_field)

        self.expected_spin = QSpinBox()
        self.expected_spin.setRange(1, 20)
        self.expected_spin.setValue(1)
        form.addRow('Expected plants', self.expected_spin)
        layout.addLayout(form)

        layout.addWidget(theme.separator())

        # Two-by-two grid: four actions no longer fight for one narrow row.
        btn_grid = QGridLayout()
        btn_grid.setHorizontalSpacing(8)
        btn_grid.setVerticalSpacing(8)
        self.clean_btn = QPushButton('Clean PLY')
        self.segment_btn = QPushButton('Segment')
        self.traits_btn = QPushButton('Extract Traits')
        self.pipeline_btn = QPushButton('Full Analysis')
        theme.variant(self.pipeline_btn, 'primary')
        self.clean_btn.clicked.connect(self._on_clean)
        self.segment_btn.clicked.connect(self._on_segment)
        self.traits_btn.clicked.connect(self._on_traits)
        self.pipeline_btn.clicked.connect(self._on_pipeline)
        btn_grid.addWidget(self.clean_btn, 0, 0)
        btn_grid.addWidget(self.segment_btn, 0, 1)
        btn_grid.addWidget(self.traits_btn, 1, 0)
        btn_grid.addWidget(self.pipeline_btn, 1, 1)
        layout.addLayout(btn_grid)

        # Busy indicator: these jobs can run for minutes.
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_lbl = QLabel('No post-processing run yet.')
        self.status_lbl.setWordWrap(True)
        theme.role(self.status_lbl, 'hint')
        layout.addWidget(self.status_lbl)

        self.points_lbl = theme.tile('Points: -')
        self.hull_lbl = theme.tile('Hull: -')
        self.height_lbl = theme.tile('Height: -')
        for lbl in (self.points_lbl, self.hull_lbl, self.height_lbl):
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

    def _browse_ply(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select PLY', '', 'Point Cloud (*.ply)')
        if path:
            self.ply_edit.setText(path)

    def _output_dir(self, leaf: str):
        ply = self.ply_edit.text()
        if not ply:
            return ''
        parent = os.path.dirname(ply)
        dataset = os.path.dirname(parent) if os.path.basename(parent) in ('merge_simple_full', 'post_cleanup', 'output') else parent
        return os.path.join(dataset, leaf)

    def _dataset_dir(self):
        ply = self.ply_edit.text()
        if not ply:
            return ''
        parent = os.path.dirname(ply)
        if os.path.basename(parent) in ('merge_simple_full', 'post_cleanup', 'plants', 'output'):
            return os.path.dirname(parent)
        return parent

    def _traits_output_dir(self):
        ply = self.ply_edit.text()
        if not ply:
            return ''
        parent = os.path.dirname(ply)
        name = os.path.splitext(os.path.basename(ply))[0]
        if os.path.basename(parent) == 'plants':
            return os.path.join(os.path.dirname(parent), 'traits', name)
        return self._output_dir('traits')

    def _on_clean(self):
        ply = self.ply_edit.text()
        if ply:
            self.set_running(True, 'Cleaning point cloud...')
            self.clean_requested.emit(ply, self._output_dir('post_cleanup'))

    def _on_segment(self):
        ply = self.ply_edit.text()
        if ply:
            self.set_running(True, 'Segmenting plants...')
            self.segment_requested.emit(ply, self._output_dir('plants'), self.expected_spin.value())

    def _on_traits(self):
        ply = self.ply_edit.text()
        if ply:
            self.set_running(True, 'Extracting traits...')
            self.traits_requested.emit(ply, self._traits_output_dir())

    def _on_pipeline(self):
        ply = self.ply_edit.text()
        if ply:
            self.set_running(True, 'Running cleanup, segmentation, and traits...')
            self.pipeline_requested.emit(ply, self._dataset_dir(), self.expected_spin.value())

    def set_running(self, running: bool, message: str = ''):
        for btn in (self.clean_btn, self.segment_btn, self.traits_btn, self.pipeline_btn):
            btn.setEnabled(not running)
        # Indeterminate while a job runs; hidden when idle.
        self.progress.setVisible(running)
        self.progress.setRange(0, 0 if running else 100)
        if not running:
            self.progress.setValue(0)
        if message:
            theme.role(self.status_lbl, 'hint')
            self.status_lbl.setText(message)

    def on_postprocess_done(self, mode: str, result):
        self.set_running(False)
        theme.role(self.status_lbl, 'hint')
        if mode == 'clean':
            self.ply_edit.setText(result.output_ply)
            self.status_lbl.setText(f'Cleaned PLY: {result.output_ply}')
            self.points_lbl.setText(
                f'Points: {result.input_points:,} -> {result.cleaned_points:,}'
            )
            self.hull_lbl.setText('Hull: -')
            self.height_lbl.setText('Height: -')
        elif mode == 'segment':
            n_plants = len(result.plants)
            self.status_lbl.setText(f'Segmented {n_plants} plants in: {result.output_dir}')
            self.points_lbl.setText(
                'Points: ' + ', '.join(f"P{p['plant_id']}={p['point_count']:,}" for p in result.plants)
            )
            self.hull_lbl.setText('Hull: run traits per plant')
            self.height_lbl.setText('Height: -')
        elif mode == 'pipeline':
            n_plants = len(result.traits)
            self.status_lbl.setText(f'Full analysis complete for {n_plants} plants.')
            self.points_lbl.setText(
                'Points: ' + ', '.join(f"P{i + 1}={t['point_count']:,}" for i, t in enumerate(result.traits))
            )
            self.hull_lbl.setText(
                'Hull volume: ' + ', '.join(f"P{i + 1}={t['convex_hull_volume_m3']:.4f}" for i, t in enumerate(result.traits))
            )
            self.height_lbl.setText(
                'Height: ' + ', '.join(f"P{i + 1}={t['height_max_m']:.4f}" for i, t in enumerate(result.traits))
            )
        else:
            self.status_lbl.setText(f'Traits: {result.traits_json}')
            self.points_lbl.setText(f'Points: {result.point_count:,}')
            self.hull_lbl.setText(
                f'Hull area: {result.convex_hull_area_m2:.4f} m2 | '
                f'volume: {result.convex_hull_volume_m3:.4f} m3'
            )
            self.height_lbl.setText(
                f'Height max: {result.height_max_m:.4f} m | '
                f'top5: {result.height_top_5_pct_m:.4f} m'
            )

    def on_postprocess_error(self, msg: str):
        self.set_running(False)
        theme.role(self.status_lbl, 'error')
        self.status_lbl.setText(f'ERROR: {msg}')

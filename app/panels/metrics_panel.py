from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt5.QtCore import pyqtSlot

from app import theme


class MetricsPanel(QWidget):

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        theme.card(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                  theme.MARGIN, theme.MARGIN)
        layout.setSpacing(theme.GAP)

        header = QHBoxLayout()
        header.addWidget(theme.title('Reconstruction Metrics'))
        header.addStretch()
        layout.addLayout(header)

        # One tile row: the readings stay on a single line at the widths
        # the right-hand pane actually gets.
        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self.frame_lbl   = theme.tile('Frame: -')
        self.fitness_lbl = theme.tile('Fitness: -')
        self.rmse_lbl    = theme.tile('RMSE: -')
        self.success_lbl = theme.tile('Success: 0')
        self.fail_lbl    = theme.tile('Failed: 0')
        for tile in (self.frame_lbl, self.fitness_lbl, self.rmse_lbl,
                     self.success_lbl, self.fail_lbl):
            tiles.addWidget(tile)
        tiles.addStretch()
        layout.addLayout(tiles)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

    def _tile_style(self, colour: str) -> str:
        """Inline override for a tile that carries a semantic colour."""
        return (
            f'background:{theme.tint(colour, 0.10)}; color:{colour}; '
            f'border:1px solid {theme.tint(colour, 0.35)}; border-radius:6px; '
            f'padding:6px 10px; font-size:12px; font-weight:600;'
        )

    @pyqtSlot(int, int, float, float, int, int)
    def update_metrics(self, frame_idx, total, fitness, rmse, n_success, n_fail):
        self.frame_lbl.setText(f'Frame: {frame_idx + 1} / {total}')
        self.rmse_lbl.setText(f'RMSE: {rmse:.5f}')
        self.success_lbl.setText(f'Success: {n_success}')
        self.fail_lbl.setText(f'Failed: {n_fail}')

        # Colour-coded fitness. Result semantics stay conventional
        # (green/amber/red) rather than following the blue chrome.
        fit_text = f'Fitness: {fitness:.4f}'
        if fitness >= 0.5:
            colour = theme.SUCCESS
        elif fitness >= 0.1:
            colour = theme.WARNING
        else:
            colour = theme.DANGER
        self.fitness_lbl.setText(fit_text)
        self.fitness_lbl.setStyleSheet(self._tile_style(colour))

        # Failures are highlighted, and the highlight clears again when a
        # fresh run reports no failures.
        if n_fail > 0:
            self.fail_lbl.setStyleSheet(self._tile_style(theme.DANGER))
        else:
            self.fail_lbl.setStyleSheet('')

        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(frame_idx + 1)

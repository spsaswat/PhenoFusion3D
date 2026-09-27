from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from app import theme


class LogPanel(QWidget):

    def __init__(self):
        super().__init__()
        self._collapsed = False
        self._build_ui()

    def _build_ui(self):
        theme.card(self)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(theme.MARGIN, theme.MARGIN,
                                       theme.MARGIN, theme.MARGIN)
        self._outer.setSpacing(theme.GAP)

        # Header row with toggle
        h_row = QHBoxLayout()
        h_row.setContentsMargins(0, 0, 0, 0)
        h_row.addWidget(theme.title('Frame Log'))
        h_row.addStretch()
        self.toggle_btn = QPushButton('Hide')
        self.toggle_btn.setFixedWidth(58)
        theme.variant(self.toggle_btn, 'quiet')
        self.toggle_btn.clicked.connect(self._toggle)
        h_row.addWidget(self.toggle_btn)
        self._outer.addLayout(h_row)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Frame', 'Status', 'Fitness', 'RMSE', 'Note'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        # Small floor only: on a 768 px screen the log is the panel least
        # worth reserving space for, so it yields to the viewer and metrics.
        self.table.setMinimumHeight(80)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self._outer.addWidget(self.table)

    def append_row(self, frame_idx, status, fitness, rmse, note=''):
        row = self.table.rowCount()
        self.table.insertRow(row)

        items = [
            str(frame_idx),
            status,
            f'{fitness:.4f}',
            f'{rmse:.5f}',
            note
        ]
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            if status == 'FAILED':
                item.setForeground(QColor(theme.DANGER))
            else:
                item.setForeground(QColor(theme.TEXT))
            self.table.setItem(row, col, item)

        self.table.scrollToBottom()

    def _toggle(self):
        self._collapsed = not self._collapsed
        self.table.setVisible(not self._collapsed)
        self.toggle_btn.setText('Show' if self._collapsed else 'Hide')

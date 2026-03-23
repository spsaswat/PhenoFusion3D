from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


class LogPanel(QWidget):

    def __init__(self):
        super().__init__()
        self._collapsed = False
        self._build_ui()

    def _build_ui(self):
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # Header row with toggle
        header = QWidget()
        header.setStyleSheet('background:#e2e8f0;')
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(8, 4, 8, 4)
        lbl = QLabel('Frame Log')
        lbl.setStyleSheet('font-weight:bold; font-size:12px;')
        self.toggle_btn = QPushButton('Hide')
        self.toggle_btn.setFixedWidth(50)
        self.toggle_btn.setStyleSheet('font-size:11px; padding:1px 4px;')
        self.toggle_btn.clicked.connect(self._toggle)
        h_row.addWidget(lbl)
        h_row.addStretch()
        h_row.addWidget(self.toggle_btn)
        self._outer.addWidget(header)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Frame', 'Status', 'Fitness', 'RMSE', 'Note'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(180)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
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
                item.setForeground(QColor('#dc2626'))
            self.table.setItem(row, col, item)

        self.table.scrollToBottom()

    def _toggle(self):
        self._collapsed = not self._collapsed
        self.table.setVisible(not self._collapsed)
        self.toggle_btn.setText('Show' if self._collapsed else 'Hide')
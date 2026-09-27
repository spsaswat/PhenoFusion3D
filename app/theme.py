"""
app/theme.py
------------
Blue-and-white visual theme for the PhenoFusion3D desktop UI.

This module is presentation only.  It defines the colour roles and the
application-wide Qt style sheet used by the main window, the panels and
the offline dialogs.  Nothing here affects capture, reconstruction,
quality or analysis behaviour -- panels keep their own widgets, signals
and slots and simply ask this module how things should look.

Colour policy
    * Chrome (backgrounds, inputs, buttons, tabs, tables) is blue/white.
    * Result semantics keep their conventional colours so a reading is
      never ambiguous: PASS/READY green is replaced by theme blue, while
      WARN amber and FAIL/emergency-stop red stay as they were.
"""

from __future__ import annotations

# --------------------------------------------------------------- palette

WINDOW        = '#eaf1fb'   # application background, very light blue
SURFACE       = '#ffffff'   # cards, inputs, tables
SURFACE_ALT   = '#f4f8ff'   # table stripes and read-only fields
BORDER        = '#cddff5'
BORDER_STRONG = '#a7c6ea'

PRIMARY       = '#1d63d1'
PRIMARY_HOVER = '#1a57b8'
PRIMARY_PRESS = '#164a9e'
PRIMARY_DEEP  = '#123a7d'   # headings
PRIMARY_TINT  = '#e7f0fd'   # tiles, selected rows, hovered buttons

TEXT          = '#122949'
TEXT_MUTED    = '#5a7292'
TEXT_INVERTED = '#ffffff'

DISABLED_BG   = '#dbe5f2'
DISABLED_FG   = '#93a9c4'

# Result semantics -- deliberately not blue.
SUCCESS       = '#15803d'
WARNING       = '#b45309'
DANGER        = '#c62828'
DANGER_HOVER  = '#b02020'
DANGER_PRESS  = '#991b1b'

# Shared geometry so every panel lines up.
RADIUS        = 10
GAP           = 10
MARGIN        = 12


# ----------------------------------------------------------- style sheet

STYLESHEET = f"""
QMainWindow, QDialog {{
    background: {WINDOW};
}}

/* ---- panel cards -------------------------------------------------- */
CapturePanel, GantryPanel, DataPanel, QualityPanel, PostProcessPanel,
MetricsPanel, LogPanel, QWidget#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}

/* ---- typography --------------------------------------------------- */
QLabel {{
    color: {TEXT};
    font-size: 12px;
    background: transparent;
    border: none;
}}
QLabel[role="appTitle"] {{
    color: {PRIMARY_DEEP};
    font-size: 19px;
    font-weight: 600;
}}
QLabel[role="appSubtitle"] {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel[role="title"] {{
    color: {PRIMARY_DEEP};
    font-size: 14px;
    font-weight: 600;
}}
QLabel[role="section"] {{
    color: {PRIMARY};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel[role="hint"] {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QLabel[role="error"] {{
    color: {DANGER};
    font-size: 11px;
    font-weight: 600;
}}
QLabel[role="tile"] {{
    background: {PRIMARY_TINT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
QLabel[role="readout"] {{
    background: {PRIMARY_TINT};
    color: {PRIMARY_DEEP};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 10px;
    font-family: monospace;
    font-size: 14px;
    font-weight: 600;
}}
QLabel[role="badge"] {{
    background: {PRIMARY};
    color: {TEXT_INVERTED};
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel[role="badgeOffline"] {{
    background: {DISABLED_FG};
    color: {TEXT_INVERTED};
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel[role="banner"] {{
    background: {SURFACE_ALT};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px;
    font-weight: 600;
}}
QLabel[role="viewer"] {{
    background: {SURFACE_ALT};
    color: {TEXT_MUTED};
    border: 1px dashed {BORDER_STRONG};
    border-radius: {RADIUS}px;
    font-size: 13px;
}}

/* ---- separators --------------------------------------------------- */
QFrame[role="separator"] {{
    background: {BORDER};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ---- inputs ------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 18px;
    font-size: 12px;
    selection-background-color: {PRIMARY};
    selection-color: {TEXT_INVERTED};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus {{
    border: 1px solid {PRIMARY};
}}
QLineEdit:read-only {{
    background: {SURFACE_ALT};
    color: {TEXT_MUTED};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_FG};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {PRIMARY_TINT};
    selection-color: {PRIMARY_DEEP};
    outline: none;
}}
QSpinBox, QDoubleSpinBox {{
    padding-right: 22px;
}}
QComboBox {{
    padding-right: 22px;
}}
QCheckBox {{
    color: {TEXT};
    font-size: 12px;
    spacing: 6px;
}}

/* ---- buttons ------------------------------------------------------ */
QPushButton {{
    background: {SURFACE};
    color: {PRIMARY};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {PRIMARY_TINT};
    border-color: {PRIMARY};
}}
QPushButton:pressed {{
    background: {BORDER};
}}
QPushButton:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_FG};
    border-color: {DISABLED_BG};
}}
QPushButton[variant="primary"] {{
    background: {PRIMARY};
    color: {TEXT_INVERTED};
    border: 1px solid {PRIMARY};
    padding: 7px 14px;
}}
QPushButton[variant="primary"]:hover {{
    background: {PRIMARY_HOVER};
    border-color: {PRIMARY_HOVER};
}}
QPushButton[variant="primary"]:pressed {{
    background: {PRIMARY_PRESS};
}}
QPushButton[variant="danger"] {{
    background: {DANGER};
    color: {TEXT_INVERTED};
    border: 1px solid {DANGER};
    padding: 7px 14px;
}}
QPushButton[variant="danger"]:hover {{
    background: {DANGER_HOVER};
    border-color: {DANGER_HOVER};
}}
QPushButton[variant="danger"]:pressed {{
    background: {DANGER_PRESS};
}}
QPushButton[variant="primary"]:disabled, QPushButton[variant="danger"]:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_FG};
    border-color: {DISABLED_BG};
}}
QPushButton[variant="quiet"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {PRIMARY};
    padding: 2px 8px;
    font-size: 11px;
}}
QPushButton[variant="quiet"]:hover {{
    background: {SURFACE};
    border-color: {BORDER};
}}

/* ---- progress ----------------------------------------------------- */
QProgressBar {{
    background: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    min-height: 16px;
    max-height: 16px;
    text-align: center;
    font-size: 11px;
}}
QProgressBar::chunk {{
    background: {PRIMARY};
    border-radius: 5px;
    margin: 1px;
}}

/* ---- tables ------------------------------------------------------- */
QTableWidget {{
    background: {SURFACE};
    alternate-background-color: {SURFACE_ALT};
    color: {TEXT};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 2px;
}}
QTableWidget::item:selected {{
    background: {PRIMARY_TINT};
    color: {PRIMARY_DEEP};
}}
QHeaderView {{
    background: transparent;
}}
QHeaderView::section {{
    background: {PRIMARY_TINT};
    color: {PRIMARY_DEEP};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 5px 2px;
    font-size: 10px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: {PRIMARY_TINT};
    border: none;
    border-bottom: 1px solid {BORDER};
}}

/* ---- tabs --------------------------------------------------------- */
QTabWidget::pane {{
    /* Transparent so the white panel cards inside stay visually
       separate instead of merging into one slab. */
    background: {WINDOW};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    top: -1px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 14px;
    margin-right: 2px;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {PRIMARY};
    border: 1px solid {BORDER};
    border-bottom-color: {SURFACE};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {PRIMARY};
    background: {PRIMARY_TINT};
}}

/* ---- menus, status bar, splitter, scrollbars ---------------------- */
QMenuBar {{
    background: {SURFACE};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 10px;
}}
QMenuBar::item:selected {{
    background: {PRIMARY_TINT};
    color: {PRIMARY_DEEP};
    border-radius: 4px;
}}
QMenu {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 14px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {PRIMARY_TINT};
    color: {PRIMARY_DEEP};
}}
QMenu::item:disabled {{
    color: {DISABLED_FG};
}}
QMenu::separator {{
    background: {BORDER};
    height: 1px;
    margin: 4px 6px;
}}
QStatusBar {{
    background: {SURFACE};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
}}
QStatusBar::item {{
    border: none;
}}
QSplitter::handle:horizontal {{
    background: transparent;
    width: {GAP}px;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
/* The viewport and the scrolled content must both be transparent, or
   they paint a white slab over the tab pane and the panel cards lose
   their separation. */
QScrollArea > QWidget {{
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {PRIMARY};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {PRIMARY};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QToolTip {{
    background: {PRIMARY_DEEP};
    color: {TEXT_INVERTED};
    border: none;
    padding: 5px 7px;
    font-size: 11px;
}}
"""


# --------------------------------------------------------------- helpers

_APPLIED_PROPERTY = '_phenofusion3d_theme'

_ARROW_CACHE: dict = {}


def _arrow_path(direction: str, colour: str, size: int = 9) -> str:
    """Render a small triangle to a cached PNG and return its path.

    Qt draws the native (square, grey) spin/combo sub-controls whenever a
    style sheet reshapes the field around them, which clashes with the
    rounded blue inputs.  Style sheets can only replace those arrows with
    an image, so the theme paints its own instead of shipping assets.
    """
    import os
    import tempfile

    from PyQt5.QtCore import QPoint, QStandardPaths, Qt
    from PyQt5.QtGui import QColor, QPainter, QPixmap, QPolygon

    key = (direction, colour, size)
    if key in _ARROW_CACHE:
        return _ARROW_CACHE[key]

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(colour))
    inset = 1
    if direction == 'down':
        points = [QPoint(inset, inset + 1),
                  QPoint(size - inset, inset + 1),
                  QPoint(size // 2, size - inset)]
    else:
        points = [QPoint(inset, size - inset - 1),
                  QPoint(size - inset, size - inset - 1),
                  QPoint(size // 2, inset)]
    painter.drawPolygon(QPolygon(points))
    painter.end()

    directory = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
    directory = os.path.join(directory or tempfile.gettempdir(),
                             'phenofusion3d-theme')
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(
        directory, f'arrow_{direction}_{colour.lstrip("#")}_{size}.png'
    )
    pixmap.save(path, 'PNG')
    path = path.replace(os.sep, '/')
    _ARROW_CACHE[key] = path
    return path


def _sub_control_stylesheet() -> str:
    """Spin-box and combo-box sub-controls, which need painted arrows."""
    down = _arrow_path('down', PRIMARY)
    up = _arrow_path('up', PRIMARY)
    down_off = _arrow_path('down', DISABLED_FG)
    up_off = _arrow_path('up', DISABLED_FG)
    return f"""
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 20px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: url({down});
    width: 9px;
    height: 9px;
}}
QComboBox::down-arrow:disabled {{
    image: url({down_off});
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    height: 12px;
    margin: 2px 3px 0 0;
    border: none;
    border-radius: 3px;
    background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right;
    margin: 0 3px 2px 0;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {PRIMARY_TINT};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({up});
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({down});
    width: 9px;
    height: 9px;
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled,
QSpinBox::up-arrow:off, QDoubleSpinBox::up-arrow:off {{
    image: url({up_off});
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled,
QSpinBox::down-arrow:off, QDoubleSpinBox::down-arrow:off {{
    image: url({down_off});
}}
"""


def apply(app) -> None:
    """Apply the blue-and-white theme to a QApplication.

    The palette is set explicitly so the UI reads the same way under a
    dark desktop theme, where inherited text colours would otherwise
    fight the light style sheet.
    """
    from PyQt5.QtGui import QColor, QPalette

    # The sub-control geometry below is calibrated for Fusion, so the
    # style is set here rather than left to each entry point.
    app.setStyle('Fusion')

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(WINDOW))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(SURFACE_ALT))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(PRIMARY))
    palette.setColor(QPalette.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.HighlightedText, QColor(TEXT_INVERTED))
    palette.setColor(QPalette.ToolTipBase, QColor(PRIMARY_DEEP))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT_INVERTED))
    palette.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(DISABLED_FG))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(DISABLED_FG))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(DISABLED_FG))
    app.setPalette(palette)
    try:
        sub_controls = _sub_control_stylesheet()
    except Exception:
        # A read-only cache directory must never stop the lab GUI from
        # starting; without the painted arrows Qt falls back to its own.
        sub_controls = ''
    app.setStyleSheet(STYLESHEET + sub_controls)
    app.setProperty(_APPLIED_PROPERTY, True)


def is_applied(app) -> bool:
    """Whether this theme -- not merely some style sheet -- is installed."""
    return bool(app is not None and app.property(_APPLIED_PROPERTY))


def card(widget):
    """Let a plain QWidget subclass paint its style-sheet card background.

    Qt only honours ``background`` / ``border`` on a QWidget subclass when
    WA_StyledBackground is set, so every panel opts in through here.
    """
    from PyQt5.QtCore import Qt

    widget.setAttribute(Qt.WA_StyledBackground, True)
    return widget


def tint(colour: str, alpha: float) -> str:
    """``rgba(...)`` string for a hex colour -- Qt has no #RRGGBBAA."""
    colour = colour.lstrip('#')
    r, g, b = (int(colour[i:i + 2], 16) for i in (0, 2, 4))
    return f'rgba({r}, {g}, {b}, {alpha:.2f})'


def role(widget, name: str):
    """Tag a widget with a style role (see ``QLabel[role=...]`` rules)."""
    widget.setProperty('role', name)
    _repolish(widget)
    return widget


def variant(widget, name: str):
    """Tag a button with a style variant: primary / danger / quiet."""
    widget.setProperty('variant', name)
    _repolish(widget)
    return widget


def _repolish(widget) -> None:
    """Re-evaluate style sheet rules after a dynamic property changed."""
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


def separator():
    """A thin horizontal rule that matches the card borders."""
    from PyQt5.QtWidgets import QFrame

    line = QFrame()
    line.setFrameShape(QFrame.NoFrame)
    return role(line, 'separator')


def tile(text: str):
    """A small blue-tinted metric tile."""
    from PyQt5.QtWidgets import QLabel

    return role(QLabel(text), 'tile')


def title(text: str):
    """A panel heading."""
    from PyQt5.QtWidgets import QLabel

    return role(QLabel(text), 'title')


def hint(text: str):
    """Small muted helper text."""
    from PyQt5.QtWidgets import QLabel

    label = QLabel(text)
    label.setWordWrap(True)
    return role(label, 'hint')

"""Isolated in-software HTML viewer; optional WebEngine never enters lab startup."""
from pathlib import Path
import sys


def main():
    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices
    from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
    # Import before constructing this viewer's QApplication. The lab GUI keeps
    # its existing Qt startup and graphics configuration completely unchanged.
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        QWebEngineView = None
    report = Path(sys.argv[1]).resolve()
    if not report.is_file() or report.suffix.lower() not in ('.html', '.htm'):
        raise ValueError('Select an existing HTML result report.')
    application = QApplication(sys.argv)
    window = QWidget(); window.setWindowTitle('PhenoFusion3D — experimental hyperspectral results'); window.resize(1200, 850)
    layout = QVBoxLayout(window)
    banner = QLabel('EXPERIMENTAL · Historical 28 August 2026 dataset only. New datasets and physical fusion accuracy are unvalidated.')
    banner.setWordWrap(True); banner.setStyleSheet('padding:10px;background:#fff0c2;color:#382800'); layout.addWidget(banner)
    row = QHBoxLayout(); layout.addLayout(row)
    browser = QPushButton('Open in browser'); browser.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(report)))); row.addWidget(browser)
    home = QPushButton('Report home'); row.addWidget(home)
    if QWebEngineView is not None:
        view = QWebEngineView(); view.load(QUrl.fromLocalFile(str(report)))
        home.clicked.connect(lambda: view.load(QUrl.fromLocalFile(str(report))))
        # Keep downloadable scientific files usable from the embedded report.
        def download(item):
            from PyQt5.QtWidgets import QFileDialog
            target, _ = QFileDialog.getSaveFileName(window, 'Save result', item.downloadFileName())
            if target:
                item.setDownloadDirectory(str(Path(target).parent)); item.setDownloadFileName(Path(target).name); item.accept()
        view.page().profile().downloadRequested.connect(download)
    else:
        note = QLabel('Static report view: the optional PyQtWebEngine package is missing. Open in browser for interactive 3D and point spectra, or install the hyperspectral-viewer extra.')
        note.setWordWrap(True); layout.addWidget(note)
        view = QTextBrowser(); view.setOpenExternalLinks(True); view.setSource(QUrl.fromLocalFile(str(report)))
        home.clicked.connect(lambda: view.setSource(QUrl.fromLocalFile(str(report))))
    layout.addWidget(view, 1); window.show()
    sys.exit(application.exec_())


if __name__ == '__main__':
    main()

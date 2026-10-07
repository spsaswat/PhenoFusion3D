"""Isolated research report window; optional WebEngine stays outside lab startup."""
from pathlib import Path
import re
import sys


def static_report_html(path):
    """Readable QTextBrowser fallback without changing the saved web report."""
    text=Path(path).read_text(encoding='utf-8-sig')
    text=re.sub(r'<(style|script)\b[^>]*>.*?</\1\s*>','',text,flags=re.I|re.S)
    text=re.sub(r'\sstyle\s*=\s*("[^"]*"|\x27[^\x27]*\x27)','',text,flags=re.I)
    # QTextBrowser does not lay out HTML5 sectioning elements like a browser.
    text=re.sub(r'<(/?)(?:main|aside|article|section|header|footer)\b[^>]*>',r'<\1div>',text,flags=re.I)
    return text


def main():
    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices
    from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        QWebEngineView = None
    report = Path(sys.argv[1]).resolve()
    if not report.is_file() or report.suffix.lower() not in ('.html', '.htm'):
        raise ValueError('Select an existing HTML research report.')
    application = QApplication(sys.argv)
    window = QWidget(); window.setWindowTitle('PhenoFusion3D — research workspace'); window.resize(1200, 850)
    layout = QVBoxLayout(window)
    banner = QLabel('RESEARCH REVIEW · Measurements remain provisional. See the report for calibration gaps, source evidence and dataset-specific limitations.')
    banner.setWordWrap(True); banner.setStyleSheet('padding:10px;background:#fff0c2;color:#382800'); layout.addWidget(banner)
    row = QHBoxLayout(); layout.addLayout(row)
    browser = QPushButton('Open in browser'); browser.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(report)))); row.addWidget(browser)
    home = QPushButton('Report home'); row.addWidget(home)
    if QWebEngineView is not None:
        view = QWebEngineView(); view.load(QUrl.fromLocalFile(str(report)))
        home.clicked.connect(lambda: view.load(QUrl.fromLocalFile(str(report))))
        def download(item):
            from PyQt5.QtWidgets import QFileDialog
            target, _ = QFileDialog.getSaveFileName(window, 'Save research result', item.downloadFileName())
            if target:
                item.setDownloadDirectory(str(Path(target).parent)); item.setDownloadFileName(Path(target).name); item.accept()
        view.page().profile().downloadRequested.connect(download)
    else:
        note = QLabel('Static report view: optional PyQtWebEngine is missing. Open in browser for interactive point selection and 3D inspection, or use the hyperspectral-viewer extra in your offline environment.')
        note.setWordWrap(True); layout.addWidget(note)
        view = QTextBrowser(); view.setOpenLinks(False)
        view.document().setDefaultStyleSheet('body,p,small,td{color:#182434;} h1{font-size:26px;} h2{font-size:21px;} a{color:#075493;} td,th{padding:6px;}')
        def load_static(path):
            view.document().setBaseUrl(QUrl.fromLocalFile(str(path)))
            view.setHtml(static_report_html(path))
        def follow(url):
            target=view.document().baseUrl().resolved(url)
            path=Path(target.toLocalFile()) if target.isLocalFile() else None
            if path and path.is_file() and path.suffix.lower() in ('.html','.htm'):
                load_static(path)
            else:
                QDesktopServices.openUrl(target)
        view.anchorClicked.connect(follow)
        load_static(report)
        home.clicked.connect(lambda: load_static(report))
    layout.addWidget(view, 1); window.show()
    sys.exit(application.exec_())


if __name__ == '__main__':
    main()

import sys
from PyQt5.QtWidgets import QApplication


def create_application(argv=None):
    """Create Qt before importing modules that load OpenCV's bundled Qt."""

    app = QApplication(sys.argv if argv is None else argv)

    # Several processing/capture modules import cv2.  On Linux, the
    # opencv-python wheel points QT_QPA_PLATFORM_PLUGIN_PATH at its own Qt
    # plugins as a side effect of that import.  If it happens before
    # QApplication exists, PyQt5 may try to load OpenCV's incompatible xcb
    # plugin and abort the process.  Initialising QApplication first makes
    # PyQt5 select its matching platform plugin before any cv2 import.
    from app.main_window import MainWindow

    app.setApplicationName('PhenoFusion3D')
    app.setStyle('Fusion')
    return app, MainWindow()


def main():
    app, window = create_application()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

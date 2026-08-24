import sys

from PyQt5.QtWidgets import QApplication

from logging_setup import LOG_PATH, setup_logging  # noqa: F401


def main():
    setup_logging()
    from app.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName('PhenoFusion3D')
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

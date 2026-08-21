import logging
import logging.handlers
import os
import platform
import sys

from PyQt5.QtWidgets import QApplication

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'phenofusion3d.log')


def setup_logging() -> None:
    """Console at INFO, rotating file at DEBUG (phenofusion3d.log next
    to main.py). The file is the one to read when the app misbehaves on
    the lab rig -- it records the full ROS init sequence."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        '%(asctime)s %(levelname)-7s [%(name)s] %(message)s'
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        file_h = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding='utf-8'
        )
        file_h.setLevel(logging.DEBUG)
        file_h.setFormatter(fmt)
        root.addHandler(file_h)
    except OSError as e:
        root.warning('Could not open log file %s: %s', LOG_PATH, e)

    root.info('PhenoFusion3D starting | python=%s | %s | ROS_MASTER_URI=%s',
              platform.python_version(), platform.platform(),
              os.environ.get('ROS_MASTER_URI', '<unset>'))


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

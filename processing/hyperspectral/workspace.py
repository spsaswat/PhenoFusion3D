"""Launch the original manual spectral GUI in the analysis child process."""
import json
from pathlib import Path
import runpy
import sys
from . import STATUS
from .workflow import LEGACY, check_dependencies, fresh_output


def open_workspace(output):
    check_dependencies()
    output = fresh_output(output, [])
    status_file = output / 'run_status.json'
    status_file.write_text(json.dumps({'status': 'running', 'mode': 'manual_experimental_workspace'}))
    try:
        sys.path.insert(0, str(LEGACY / 'app'))
        namespace = runpy.run_path(str(LEGACY / 'app/main.py'), run_name='legacy_hyperspectral_app')
        from PyQt5.QtWidgets import QApplication, QLabel
        application = QApplication.instance() or QApplication(sys.argv)
        window = namespace['CalibApp']()
        window.setWindowTitle('Experimental manual hyperspectral workspace — new datasets unvalidated')
        label = QLabel(STATUS + '\nOther ENVI inputs can be explored manually. Check calibration regions and every output; this does not enable automatic fusion for new datasets.')
        label.setWordWrap(True); label.setStyleSheet('background:#fff0c2;color:#382800;padding:12px')
        window.layout().insertWidget(0, label)
        window.show()
        application.exec_()
    except BaseException as error:
        status_file.write_text(json.dumps({'status': 'failed', 'error': str(error)}))
        raise
    status_file.write_text(json.dumps({'status': 'workspace_closed', 'note': 'Manual outputs are saved only to operator-selected destinations; no automatic fusion was run.'}))

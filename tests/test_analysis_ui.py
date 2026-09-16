"""Exercise the real desktop entrypoint and child-process lifecycle offscreen."""
import os
import json
from pathlib import Path
import time

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QApplication,QMessageBox
import pytest


@pytest.fixture
def window():
    app=QApplication.instance() or QApplication([])
    from app.main_window import MainWindow
    w=MainWindow();w._open_analysis()
    yield app,w
    w.analysis_dialog.close();w.close();app.processEvents()


def test_new_dialog_preserves_main_capture_and_gantry_controls(window):
    app,w=window
    assert w.analysis_dialog.tabs.count()==5
    assert w.capture_panel is not None and w.gantry_panel is not None
    assert any(a.text()=='File' for a in w.menuBar().actions())
    assert any(a.text()=='Analysis' for a in w.menuBar().actions())
    assert w.controller.capture_worker is None


def test_capture_takes_priority_and_cancels_child(window,tmp_path):
    app,w=window;dialog=w.analysis_dialog
    # A harmless local process stands in for a lengthy reconstruction.
    dialog.output_path=tmp_path/'cancelled';dialog.output_path.mkdir()
    dialog.process.start(__import__('sys').executable,['-c','import time; time.sleep(30)'])
    assert dialog.process.waitForStarted(3000)
    w.controller.capture_started.emit()
    assert dialog.process.waitForFinished(3000)
    app.processEvents()
    assert dialog.cancelled
    assert json.loads((dialog.output_path/'run_status.json').read_text())['status']=='cancelled'


def test_close_terminates_offline_child(window,tmp_path):
    app,w=window;d=w.analysis_dialog;d.output_path=tmp_path/'close';d.output_path.mkdir()
    d.process.start(__import__('sys').executable,['-c','import time; time.sleep(30)'])
    assert d.process.waitForStarted(3000)
    d.close();app.processEvents()
    assert d.process.state()==QProcess.NotRunning


def test_launch_refuses_concurrent_capture(window,tmp_path,monkeypatch):
    app,w=window
    class Busy:
        def isRunning(self):return True
    w.controller.capture_worker=Busy()
    monkeypatch.setattr(QMessageBox,'information',lambda *args:None)
    w.analysis_dialog.launch('processing.rgb_recovery',['missing'],tmp_path/'out')
    assert w.analysis_dialog.process.state()==QProcess.NotRunning
    w.controller.capture_worker=None


def test_invalid_recording_fails_without_crashing_gui(window,tmp_path):
    app,w=window;d=w.analysis_dialog;out=tmp_path/'bad'
    d.launch('processing.rgb_recovery',[str(tmp_path/'missing'),'--output',str(out)],out)
    assert d.process.waitForStarted(3000)
    limit=time.monotonic()+15
    while d.process.state()!=QProcess.NotRunning and time.monotonic()<limit:
        app.processEvents();time.sleep(.01)
    assert d.process.state()==QProcess.NotRunning
    app.processEvents()
    assert not d.open_result.isEnabled()
    assert 'failed' in d.log.toPlainText().lower()


def test_hyperspectral_options_are_separate_and_explicitly_experimental(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    assert 'experimental' in d.tabs.tabText(4).lower()
    assert [d.hsi_mode.itemData(i) for i in range(d.hsi_mode.count())]==['spectral','fusion','all']
    d.hsi_mode.setCurrentIndex(2);d.hsi_output.setText(str(tmp_path))
    calls=[];monkeypatch.setattr(d,'launch',lambda *args:calls.append(args))
    d.hyperspectral(True)
    assert calls[0][0]=='processing.hyperspectral'
    assert calls[0][1][0]=='all' and '--inspect-only' in calls[0][1]


def test_capture_also_closes_optional_report_process(window):
    app,w=window;d=w.analysis_dialog
    d.report_process.start(__import__('sys').executable,['-c','import time; time.sleep(30)'])
    assert d.report_process.waitForStarted(3000)
    w.controller.capture_started.emit()
    assert d.report_process.waitForFinished(3000)
    assert d.report_process.state()==QProcess.NotRunning


def test_report_viewer_refuses_active_capture(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    class Busy:
        def isRunning(self):return True
    report=tmp_path/'index.html';report.write_text('<html>report</html>')
    w.controller.capture_worker=Busy()
    messages=[]
    monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(args))
    d.show_hyperspectral_report(report)
    assert d.report_process.state()==QProcess.NotRunning
    assert messages and 'Processing busy' in messages[0]
    w.controller.capture_worker=None

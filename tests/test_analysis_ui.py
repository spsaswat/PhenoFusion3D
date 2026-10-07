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
    assert w.analysis_dialog.tabs.count()==7
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


def test_research_template_and_build_use_isolated_workspace_module(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    assert d.tabs.tabText(5)=='Research workspace'
    d.research_output.setText(str(tmp_path))
    calls=[];monkeypatch.setattr(d,'launch',lambda *args:calls.append(args))
    d.research_template()
    module,args,output=calls.pop()
    assert module=='processing.research_workspace'
    assert args==['template','--output',output] and output.parent==tmp_path
    manifest=tmp_path/'setup.json';annotations=tmp_path/'reviewed_landmarks.json'
    d.research_manifest.setText(str(manifest));d.research_annotations.setText(str(annotations))
    d.build_research_workspace()
    module,args,output=calls.pop()
    assert module=='processing.research_workspace'
    assert args==['build','--manifest',str(manifest),'--output',output,'--annotations',str(annotations)]
    d.research_annotations.clear();d.build_research_workspace()
    assert '--annotations' not in calls.pop()[1]


def test_research_workspace_requires_setup_and_output_selection(window):
    app,w=window;d=w.analysis_dialog
    d.research_manifest.clear()
    with pytest.raises(ValueError,match='setup JSON'):d.build_research_workspace()
    d.research_output.clear()
    with pytest.raises(ValueError,match='results parent'):d.research_template()
    assert d.process.state()==QProcess.NotRunning


def test_spectral_extraction_uses_explicit_setup_and_isolated_process(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    d.spectral_config.clear()
    with pytest.raises(ValueError,match='spectral extraction setup'):d.extract_research_spectra()
    config=tmp_path/'regions.json';d.spectral_config.setText(str(config));d.research_output.setText(str(tmp_path))
    calls=[];monkeypatch.setattr(d,'launch',lambda *args:calls.append(args))
    d.extract_research_spectra()
    module,args,out=calls[0]
    assert module=='processing.research_workspace.spectral_extract'
    assert args==['--config',str(config),'--output',out] and out.parent==tmp_path


def test_research_build_refuses_active_capture(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    class Busy:
        def isRunning(self):return True
    w.controller.capture_worker=Busy()
    d.research_manifest.setText(str(tmp_path/'setup.json'));d.research_output.setText(str(tmp_path))
    messages=[];monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(args))
    d.build_research_workspace()
    assert d.process.state()==QProcess.NotRunning
    assert not list(tmp_path.iterdir())
    assert messages and 'Processing busy' in messages[0]
    w.controller.capture_worker=None


def test_workspace_report_precedes_json_and_opens_in_guarded_viewer(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    (tmp_path/'result').mkdir();report=tmp_path/'result/index.html';report.write_text('<html>Conditional research report</html>')
    template=tmp_path/'workspace_template.json';template.write_text('{}')
    (tmp_path/'preflight.json').write_text('{}')
    d.output_path=tmp_path;d.active_module='processing.research_workspace'
    d.finished(0,QProcess.NormalExit)
    assert d.result_path==report and d.open_result.isEnabled()
    assert d.research_manifest.text()==str(template)
    assert not d.research_annotations.text()
    assert d.research_report.text()==str(report)
    calls=[];monkeypatch.setattr(d,'show_hyperspectral_report',lambda path,**kw:calls.append((path,kw)))
    d.open_latest()
    assert calls==[(report,{'research':True})]
    d.result_module='processing.research_workspace.spectral_extract';d.open_latest()
    assert calls[-1]==(report,{'research':True})
    # Existing historical reports keep their original specialized route.
    historical=tmp_path/'20260828_showcase/index.html'
    d.result_path=historical;d.result_module='processing.hyperspectral';d.open_latest()
    assert calls[-1]==(historical,{}) and d.hsi_report.text()==str(historical)


def test_capture_cancels_workspace_and_does_not_offer_partial_report(window,tmp_path):
    app,w=window;d=w.analysis_dialog
    d.output_path=tmp_path;d.active_module='processing.research_workspace'
    (tmp_path/'result').mkdir();(tmp_path/'result/index.html').write_text('<html>Partial</html>')
    d.process.start(__import__('sys').executable,['-c','import time; time.sleep(30)'])
    assert d.process.waitForStarted(3000)
    w.controller.capture_started.emit()
    assert d.process.waitForFinished(3000)
    app.processEvents()
    assert d.cancelled and d.result_path is None
    assert not d.open_result.isEnabled()
    assert json.loads((tmp_path/'run_status.json').read_text())['status']=='cancelled'


def test_spectral_review_accepts_explicit_sensor_results_and_rejects_empty_selection(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    assert d.tabs.tabText(6)=='Spectral review / 3D fusion'
    d.fusion_fx10.clear();d.fusion_fx17.clear();d.fusion_output.setText(str(tmp_path))
    with pytest.raises(ValueError,match='at least one extracted-result'):d.build_spectral_review()
    calls=[];monkeypatch.setattr(d,'launch',lambda *args:calls.append(args))
    fx10=tmp_path/'FX10 result';fx17=tmp_path/'FX17 result'
    d.fusion_fx10.setText(str(fx10));d.build_spectral_review()
    module,args,out=calls.pop()
    assert module=='processing.research_workspace.spectral_viewer'
    assert args==['--sensor',f'fx10={fx10}','--output',out]
    assert out.parent==tmp_path
    d.fusion_fx17.setText(str(fx17));d.build_spectral_review()
    module,args,other_out=calls.pop()
    assert args==['--sensor',f'fx10={fx10}','--sensor',f'fx17={fx17}','--output',other_out]
    assert other_out!=out
    d.fusion_output.clear()
    with pytest.raises(ValueError,match='results parent'):d.build_spectral_review()


def test_sparse_fusion_template_and_build_require_reviewed_setup(window,tmp_path,monkeypatch):
    app,w=window;d=w.analysis_dialog
    d.fusion_output.setText(str(tmp_path));d.fusion_config.clear()
    with pytest.raises(ValueError,match='reviewed 3D fusion setup'):d.build_spectral_fusion()
    calls=[];monkeypatch.setattr(d,'launch',lambda *args:calls.append(args))
    d.fusion_template()
    module,args,out=calls.pop()
    assert module=='processing.research_workspace.spectral_fusion'
    assert args==['template','--output',out] and out.parent==tmp_path
    config=tmp_path/'reviewed source matches.json';d.fusion_config.setText(str(config))
    d.build_spectral_fusion()
    module,args,out=calls.pop()
    assert module=='processing.research_workspace.spectral_fusion'
    assert args==['build','--config',str(config),'--output',out]
    d.fusion_output.clear()
    with pytest.raises(ValueError,match='results parent'):d.fusion_template()


@pytest.mark.parametrize('action', ['build_spectral_review','fusion_template','build_spectral_fusion'])
def test_spectral_actions_refuse_active_capture_without_writing(window,tmp_path,monkeypatch,action):
    app,w=window;d=w.analysis_dialog
    class Busy:
        def isRunning(self):return True
    w.controller.capture_worker=Busy()
    d.fusion_fx10.setText(str(tmp_path/'FX10'));d.fusion_config.setText(str(tmp_path/'setup.json'))
    d.fusion_output.setText(str(tmp_path))
    messages=[];monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(args))
    try:
        getattr(d,action)()
        assert d.process.state()==QProcess.NotRunning
        assert not list(tmp_path.iterdir())
        assert messages and 'Processing busy' in messages[0]
    finally:w.controller.capture_worker=None


@pytest.mark.parametrize('module', ['processing.research_workspace.spectral_viewer','processing.research_workspace.spectral_fusion'])
def test_spectral_direct_reports_use_guarded_research_viewer(window,tmp_path,monkeypatch,module):
    app,w=window;d=w.analysis_dialog
    report=tmp_path/'index.html';report.write_text('<html>Provisional sparse measurements</html>')
    (tmp_path/'preflight.json').write_text('{}')
    template=tmp_path/'spectral_fusion_template.json';template.write_text('{}')
    d.output_path=tmp_path;d.active_module=module
    d.finished(0,QProcess.NormalExit)
    assert d.result_path==report and d.open_result.isEnabled()
    assert d.fusion_report.text()==str(report)
    if module.endswith('.spectral_fusion'):assert d.fusion_config.text()==str(template)
    calls=[];monkeypatch.setattr(d,'show_hyperspectral_report',lambda path,**kw:calls.append((path,kw)))
    d.open_latest()
    assert calls==[(report,{'research':True})]


def test_capture_cancels_sparse_fusion_and_does_not_offer_partial_report(window,tmp_path):
    app,w=window;d=w.analysis_dialog
    d.output_path=tmp_path;d.active_module='processing.research_workspace.spectral_fusion'
    (tmp_path/'index.html').write_text('<html>Partial sparse fusion</html>')
    d.process.start(__import__('sys').executable,['-c','import time; time.sleep(30)'])
    assert d.process.waitForStarted(3000)
    w.controller.capture_started.emit()
    assert d.process.waitForFinished(3000)
    app.processEvents()
    assert d.cancelled and d.result_path is None
    assert not d.open_result.isEnabled()
    assert json.loads((tmp_path/'run_status.json').read_text())['status']=='cancelled'

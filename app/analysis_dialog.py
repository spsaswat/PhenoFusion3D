"""Offline analysis UI; scientific code runs only in a cancellable child process."""
from datetime import datetime
import json
from pathlib import Path
import sys

from PyQt5.QtCore import QProcess, QProcessEnvironment, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,
    QPushButton,QLabel,QComboBox,QDoubleSpinBox,QSpinBox,QPlainTextEdit,
    QFileDialog,QMessageBox,QTabWidget,QWidget,QCheckBox)


class AnalysisDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller=controller
        self.setWindowTitle('Offline reconstruction, traits and experimental hyperspectral fusion')
        self.resize(850,760)
        self.process=QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.report_process=QProcess(self)
        self.report_process.setProcessChannelMode(QProcess.MergedChannels)
        self.report_process.readyReadStandardOutput.connect(self.read_report_output)
        self.report_process.errorOccurred.connect(self.report_error)
        self.result_path=None;self.cancelled=False;self.log_handle=None
        layout=QVBoxLayout(self)
        intro=QLabel('Process saved recordings locally. No internet or AI service is required.\nResults remain candidates until coverage, specimen identity and physical dimensions are checked.')
        intro.setWordWrap(True);layout.addWidget(intro)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.buttons=[]
        self.reconstruction_tab();self.traits_tab();self.comparison_tab();self.leaf_tab();self.hyperspectral_tab()
        row=QHBoxLayout()
        self.stop=QPushButton('Cancel processing');self.stop.setEnabled(False);self.stop.clicked.connect(self.cancel)
        self.open_result=QPushButton('Open latest result');self.open_result.setEnabled(False);self.open_result.clicked.connect(self.open_latest)
        row.addWidget(self.stop);row.addWidget(self.open_result);layout.addLayout(row)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(2000);layout.addWidget(self.log)

    def page(self,title):
        widget=QWidget();form=QFormLayout(widget);self.tabs.addTab(widget,title);return form

    def path(self,form,label,directory=True):
        row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
        edit=QLineEdit();button=QPushButton('Browse…')
        def browse():
            value=QFileDialog.getExistingDirectory(self,label) if directory else QFileDialog.getOpenFileName(self,label)[0]
            if value:edit.setText(value)
        button.clicked.connect(browse);layout.addWidget(edit);layout.addWidget(button);form.addRow(label,row);return edit

    def number(self,form,label,default=0,maximum=100000,decimals=4):
        field=QDoubleSpinBox();field.setDecimals(decimals);field.setRange(0,maximum);field.setValue(default);form.addRow(label,field);return field

    def button(self,form,label,callback):
        def safely():
            try:callback()
            except Exception as error:QMessageBox.warning(self,'Analysis input error',str(error))
        button=QPushButton(label);button.clicked.connect(safely);form.addRow(button);self.buttons.append(button)

    def reconstruction_tab(self):
        form=self.page('Reconstruct')
        self.dataset=self.path(form,'Recording folder')
        self.output=self.path(form,'Results parent folder (optional)')
        self.scale=self.number(form,'Raw depth units / metre (0 = metadata)')
        self.near=self.number(form,'Nearest depth, m (0 = estimate)',maximum=20)
        self.far=self.number(form,'Farthest depth, m (0 = estimate)',maximum=20)
        self.frames=QSpinBox();self.frames.setRange(8,64);self.frames.setValue(44);form.addRow('Camera views',self.frames)
        self.axis=QComboBox();self.axis.addItems(['auto','x','-x']);form.addRow('Camera motion direction',self.axis)
        self.foreground=QComboBox();self.foreground.addItems(['auto','depth','colour']);form.addRow('Foreground selection',self.foreground)
        self.poses=self.path(form,'Saved camera poses (optional)',False)
        self.method=QComboBox();self.method.addItems(['auto','rgb','sensor']);form.addRow('Reconstruction method',self.method)
        note=QLabel('Automatic mode targets overlapping overhead gantry recordings. It estimates motion direction and separates surfaces above the support. For other geometry use calibrated camera poses. Depth mode retains all surfaces in the chosen interval; colour mode is optional for saturated foliage.')
        note.setWordWrap(True);form.addRow(note)
        self.button(form,'Check recording and explain settings',lambda:self.reconstruct(True))
        self.button(form,'Reconstruct from photographs + coloured ICP',lambda:self.reconstruct(False))

    def traits_tab(self):
        form=self.page('Model traits / RGB-D references')
        self.ply=self.path(form,'Reviewed plant-only PLY',False)
        self.trait_axis=QComboBox();self.trait_axis.addItems(['z','y','x']);form.addRow('Plant height axis',self.trait_axis)
        self.reviewed=QCheckBox('I reviewed the model orientation and excluded the pot/background.');form.addRow(self.reviewed)
        self.button(form,'Extract 3D model traits',self.extract_traits)
        self.ref_dataset=self.path(form,'Recording for image-derived references')
        self.ref_scale=self.number(form,'Raw depth units / metre')
        self.plants=QSpinBox();self.plants.setRange(1,100);form.addRow('Expected plant count',self.plants)
        note=QLabel('Image references are diagnostic and colour-based. Review selected-frame masks; visible projected areas are not full leaf surface areas.');note.setWordWrap(True);form.addRow(note)
        self.button(form,'Extract image-derived reference traits',self.references)

    def comparison_tab(self):
        form=self.page('Validate traits')
        self.trait_folder=self.path(form,'3D traits folder (plant_N subfolders)')
        self.reference=self.path(form,'Image reference JSON (optional)',False)
        self.manual=self.path(form,'Physical measurement CSV (optional)',False)
        self.matches=QLineEdit();self.matches.setPlaceholderText('Reference:model, e.g. 1:2 2:1');form.addRow('Confirmed specimen pairs',self.matches)
        note=QLabel('Compare matching quantities only. Physical CSV uses plant_id and physical_plant_height_m, physical_canopy_major_span_m, physical_canopy_minor_span_m, physical_projected_canopy_area_m2 and physical_projected_convex_hull_area_m2. Leave unmeasured values blank.');note.setWordWrap(True);form.addRow(note)
        self.button(form,'Create comparison report',self.compare)

    def leaf_tab(self):
        form=self.page('Matched leaves')
        self.leaf_dataset=self.path(form,'Recording folder for marked leaves')
        self.leaf_scale=self.number(form,'Raw depth units / metre')
        self.leaf_config=self.path(form,'Leaf annotations JSON',False)
        note=QLabel('Mark the same leaf measured physically: tip, base, then both width edges. The report shows separate length and width rows in millimetres. These are image-derived leaf measurements, not automatic 3D leaf segmentation.');note.setWordWrap(True);form.addRow(note)
        self.button(form,'Mark leaves on a source photograph',self.annotate)
        self.button(form,'Measure marked leaves and compare',self.leaves)

    def output_dir(self,source,kind):
        parent=Path(self.output.text()) if self.output.text() else (Path(source) if Path(source).is_dir() else Path(source).parent)
        return parent/'analysis_results'/f'{kind}_{datetime.now():%Y%m%d_%H%M%S_%f}'

    def hyperspectral_tab(self):
        form=self.page('Hyperspectral / fusion · experimental')
        warning=QLabel('EXPERIMENTAL — the automatic recipe works only with the reviewed 28 August 2026 dataset. This integration is unvalidated on new datasets. It uses fixed calibration regions, specimen/frame matches and legacy ICP placement estimates.')
        warning.setWordWrap(True);warning.setStyleSheet('padding:10px;background:#fff0c2;color:#382800');form.addRow(warning)
        self.hsi_data=self.path(form,'Paired FX10 / FX17 recording folder')
        self.hsi_rgbd=self.path(form,'Matching RGB-D recording + reviewed ICP results')
        self.hsi_spectral=self.path(form,'Existing spectral results (for fusion only)')
        self.hsi_output=self.path(form,'New results parent folder')
        self.hsi_mode=QComboBox();self.hsi_mode.addItem('Spectral analysis only','spectral');self.hsi_mode.addItem('Fusion from existing spectral results','fusion');self.hsi_mode.addItem('Spectral analysis → RGB-D / ICP fusion','all');form.addRow('Workflow',self.hsi_mode)
        self.button(form,'Check historical inputs',lambda:self.hyperspectral(True))
        self.button(form,'Run selected experimental workflow',lambda:self.hyperspectral(False))
        self.button(form,'Open manual spectral workspace (other inputs unvalidated)',self.manual_hyperspectral)
        self.hsi_report=self.path(form,'Saved showcase / result index.html',False)
        self.button(form,'Display saved report in software',lambda:self.show_hyperspectral_report(self.hsi_report.text()))
        # Convenience only: execution accepts operator-selected locations and
        # contains no dependency on the original repository's source code.
        project=Path(__file__).resolve().parents[1]
        historical=project.parent/'3d_hyperspec_ai'
        defaults=[(self.hsi_data,historical/'data/20260828'),(self.hsi_spectral,historical/'results/20260828_showcase'),
                  (self.hsi_rgbd,project/'data/main/test_plant_20260828120800_best_lighting'),
                  (self.hsi_report,historical/'results/20260828_showcase/index.html')]
        for field,path in defaults:
            if path.exists():field.setText(str(path))
        self.hsi_output.setText(str(project/'generated/hyperspectral'))

    def hyperspectral_output(self):
        if not self.hsi_output.text().strip():raise ValueError('Choose a results parent folder outside the input recordings.')
        return Path(self.hsi_output.text())/f'run_{datetime.now():%Y%m%d_%H%M%S_%f}'

    def hyperspectral(self,inspect):
        out=self.hyperspectral_output()
        args=[self.hsi_mode.currentData(),'--output',out]
        for flag,field in (('--hsi',self.hsi_data),('--rgbd',self.hsi_rgbd),('--spectral-results',self.hsi_spectral)):
            if field.text().strip():args.extend([flag,field.text().strip()])
        if inspect:args.append('--inspect-only')
        self.launch('processing.hyperspectral',args,out)

    def manual_hyperspectral(self):
        out=self.hyperspectral_output()
        self.launch('processing.hyperspectral',['workspace','--output',out],out)

    def show_hyperspectral_report(self,path):
        for name in ('capture_worker','worker','quality_worker','postprocess_worker'):
            worker=getattr(self.controller,name,None)
            if worker is not None and worker.isRunning():
                QMessageBox.information(self,'Processing busy','Finish the current capture or processing job before opening the results viewer.');return
        path=Path(path)
        if not path.is_file() or path.suffix.lower() not in ('.html','.htm'):
            QMessageBox.information(self,'Select a report','Select an existing index.html or HTML report.');return
        if self.report_process.state()!=QProcess.NotRunning:
            self.report_process.kill();self.report_process.waitForFinished(2000)
        self.report_process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.report_process.start(sys.executable,['-m','app.hyperspectral_report',str(path.resolve())])

    def read_report_output(self):
        text=bytes(self.report_process.readAllStandardOutput()).decode('utf-8',errors='replace')
        self.log.insertPlainText(text)

    def report_error(self,error):
        if error==QProcess.FailedToStart:
            self.log.appendPlainText('Results viewer could not start: '+self.report_process.errorString())
        elif error==QProcess.Crashed:
            self.log.appendPlainText('Results viewer closed unexpectedly or was stopped. The saved report is still available in its output folder.')

    def launch(self,module,args,output):
        if self.process.state()!=QProcess.NotRunning:return
        for name in ('capture_worker','worker','quality_worker','postprocess_worker'):
            worker=getattr(self.controller,name,None)
            if worker is not None and worker.isRunning():
                QMessageBox.information(self,'Processing busy','Finish the current capture or processing job before starting offline analysis.');return
        self.result_path=None;self.cancelled=False;self.output_path=Path(output)
        # Sibling log is outside the new run directory, which must remain empty.
        self.output_path.parent.mkdir(parents=True,exist_ok=True)
        self.log_handle=self.output_path.with_suffix('.log').open('w',encoding='utf-8')
        env=QProcessEnvironment.systemEnvironment()
        env.insert('OMP_NUM_THREADS','4');env.insert('OPENBLAS_NUM_THREADS','4');env.insert('PYTHONUNBUFFERED','1')
        env.insert('PYTHONIOENCODING','utf-8')
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.log.clear();self.open_result.setEnabled(False);self.stop.setEnabled(True)
        for button in self.buttons:button.setEnabled(False)
        self.process.start(sys.executable,['-u','-m',module,*map(str,args)])

    def reconstruct(self,inspect):
        root=self.dataset.text().strip()
        if not root:return
        out=self.output_dir(root,'check' if inspect else 'recovery')
        args=[root,'--output',out,'--depth-scale',self.scale.value(),'--near',self.near.value(),'--far',self.far.value(),'--max-frames',self.frames.value(),'--camera-axis',self.axis.currentText(),'--foreground',self.foreground.currentText()]
        args+=['--method',self.method.currentText()]
        if self.poses.text():args+=['--initial-poses',self.poses.text()]
        if inspect:args+=['--inspect-only']
        self.launch('processing.rgb_recovery',args,out)

    def extract_traits(self):
        if not self.ply.text():return
        if not self.reviewed.isChecked():
            QMessageBox.information(self,'Review required','Confirm the selected PLY contains the intended plant and the height axis is correct.');return
        out=self.output_dir(self.ply.text(),'traits')
        self.launch('processing.analysis_workflow',['traits','--input',self.ply.text(),'--output',out,'--axis',self.trait_axis.currentText()],out)

    def references(self):
        if not self.ref_dataset.text():return
        out=self.output_dir(self.ref_dataset.text(),'references')
        self.launch('processing.analysis_workflow',['references','--input',self.ref_dataset.text(),'--output',out,'--depth-scale',self.ref_scale.value(),'--plants',self.plants.value()],out)

    def compare(self):
        if not self.trait_folder.text():return
        out=self.output_dir(self.trait_folder.text(),'comparison')
        self.launch('processing.analysis_workflow',['compare','--input',self.trait_folder.text(),'--output',out,'--reference',self.reference.text(),'--manual',self.manual.text(),'--mapping',self.matches.text()],out)

    def annotate(self):
        if not self.leaf_dataset.text():return
        from app.leaf_annotations import LeafAnnotations
        dialog=LeafAnnotations(self.leaf_dataset.text(),self.leaf_scale.value(),self)
        if dialog.exec_() and dialog.saved_path:self.leaf_config.setText(str(dialog.saved_path))

    def leaves(self):
        if not self.leaf_dataset.text() or not self.leaf_config.text():return
        out=self.output_dir(self.leaf_dataset.text(),'matched_leaves')
        self.launch('processing.analysis_workflow',['leaves','--input',self.leaf_dataset.text(),'--config',self.leaf_config.text(),'--output',out],out)

    def read_output(self):
        text=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        self.log.insertPlainText(text)
        if self.log_handle:self.log_handle.write(text);self.log_handle.flush()

    def finished(self,code,status):
        self.read_output()
        if self.log_handle:self.log_handle.close();self.log_handle=None
        self.stop.setEnabled(False)
        for button in self.buttons:button.setEnabled(True)
        if self.cancelled:
            if self.output_path.is_dir():
                (self.output_path/'run_status.json').write_text(json.dumps({'status':'cancelled','note':'Partial outputs must not be treated as completed results.'},indent=2))
            self.log.appendPlainText('Cancelled. Partial output is not a completed result.');return
        if code!=0:
            self.log.appendPlainText('Processing failed. See the explanation above; existing results were preserved.');return
        for name in ('results/20260828_showcase/index.html','result/index.html','manual_report.html','validation_report.html','plant_1/traits.json','reference_traits.json','profile.json','preflight.json'):
            path=self.output_path/name
            if path.is_file():self.result_path=path;break
        self.open_result.setEnabled(self.result_path is not None)
        self.log.appendPlainText('Finished. Review the result and its measurement limitations.')

    def process_error(self,error):
        if error==QProcess.FailedToStart:
            self.log.appendPlainText(self.process.errorString());self.finished(-1,QProcess.CrashExit)

    def cancel(self):
        if self.process.state()!=QProcess.NotRunning:
            self.cancelled=True;self.process.kill()
        if self.report_process.state()!=QProcess.NotRunning:self.report_process.kill()

    def open_latest(self):
        if self.result_path and self.result_path.parent.name=='20260828_showcase':
            self.hsi_report.setText(str(self.result_path));self.show_hyperspectral_report(self.result_path)
        elif self.result_path:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_path)))

    def closeEvent(self,event):
        self.cancel();self.process.waitForFinished(2000)
        if self.report_process.state()!=QProcess.NotRunning:
            self.report_process.kill();self.report_process.waitForFinished(2000)
        event.accept()

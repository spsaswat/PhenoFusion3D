"""Mark physical leaf correspondences on source images without code editing."""
import json
from pathlib import Path
import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap,QPainter,QPen,QColor
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLabel,QComboBox,
    QSpinBox,QDoubleSpinBox,QPushButton,QFileDialog,QMessageBox)

from app import theme


class ImagePoints(QLabel):
    def __init__(self):
        super().__init__();self.setMinimumSize(640,360);self.points=[];self.source=QPixmap()
    def load(self,path):
        self.source=QPixmap(str(path));self.points=[];self.update()
    def image_rect(self):
        if self.source.isNull():return 0,0,0,0,1
        scale=min(self.width()/self.source.width(),self.height()/self.source.height())
        w,h=int(self.source.width()*scale),int(self.source.height()*scale)
        return (self.width()-w)//2,(self.height()-h)//2,w,h,scale
    def mousePressEvent(self,event):
        x,y,w,h,scale=self.image_rect()
        if len(self.points)<4 and x<=event.x()<x+w and y<=event.y()<y+h:
            self.points.append([int((event.x()-x)/scale),int((event.y()-y)/scale)]);self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor(theme.SURFACE_ALT))
        x,y,w,h,scale=self.image_rect()
        if self.source.isNull():return
        p.drawPixmap(x,y,w,h,self.source)
        p.setPen(QPen(QColor(theme.DANGER),3))
        for i,(u,v) in enumerate(self.points):
            px,py=int(x+u*scale),int(y+v*scale);p.drawEllipse(px-5,py-5,10,10);p.drawText(px+8,py,str(i+1))


class LeafAnnotations(QDialog):
    def __init__(self,dataset,scale,parent=None):
        super().__init__(parent);self.dataset=Path(dataset);self.scale=scale;self.leaves=[];self.saved_path=None
        self.setWindowTitle('Mark the same physical leaf');self.resize(900,760)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        folder=self.dataset/'rgb' if (self.dataset/'rgb').is_dir() else self.dataset
        self.frames={}
        for path in folder.glob('*.png'):
            match=re.fullmatch(r'(?:rgb_)?(\d+)\.png',path.name,re.I)
            if match:self.frames[int(match.group(1))]=path
        self.frame=QComboBox()
        for key in sorted(self.frames):self.frame.addItem(str(key),key)
        form.addRow('Source frame',self.frame)
        self.plant=QSpinBox();self.plant.setRange(1,1000);form.addRow('Plant ID',self.plant)
        self.leaf=QSpinBox();self.leaf.setRange(1,10000);form.addRow('Leaf ID',self.leaf)
        self.length=QDoubleSpinBox();self.length.setRange(.01,10000);form.addRow('Physical leaf length, mm',self.length)
        self.width=QDoubleSpinBox();self.width.setRange(.01,10000);form.addRow('Physical leaf width, mm',self.width)
        layout.addWidget(QLabel('Click 1: tip, 2: base, 3: left width edge, 4: right width edge. Select the same leaf you measured.'))
        self.image=ImagePoints();layout.addWidget(self.image,1)
        self.status=QLabel('No leaves recorded.');layout.addWidget(self.status)
        reset=QPushButton('Clear points on current image');reset.clicked.connect(self.reset_points);layout.addWidget(reset)
        add=QPushButton('Add this matched leaf');add.clicked.connect(self.add);layout.addWidget(add)
        save=QPushButton('Save annotations');theme.variant(save,'primary');save.clicked.connect(self.save);layout.addWidget(save)
        self.frame.currentIndexChanged.connect(self.load_frame)
        if self.frame.count():self.frame.setCurrentIndex(self.frame.count()//2);self.load_frame()

    def load_frame(self):
        key=self.frame.currentData()
        if key in self.frames:self.image.load(self.frames[key])
    def reset_points(self):
        self.image.points=[];self.image.update()
    def add(self):
        if len(self.image.points)!=4:
            QMessageBox.information(self,'Four endpoints needed','Mark all four points on the same visible leaf.');return
        pid,lid=self.plant.value(),self.leaf.value()
        if any(r['plant_id']==pid and r['leaf_id']==lid for r in self.leaves):
            QMessageBox.information(self,'Duplicate leaf','Choose a new leaf ID for this plant.');return
        self.leaves.append(dict(plant_id=pid,leaf_id=lid,frame=self.frame.currentData(),points=list(self.image.points),manual_length_mm=self.length.value(),manual_width_mm=self.width.value()))
        self.status.setText(f'{len(self.leaves)} matched leaves recorded.');self.leaf.setValue(lid+1);self.reset_points()
    def save(self):
        if not self.leaves or self.scale<=0:
            QMessageBox.information(self,'Missing measurements','Add a matched leaf and enter the camera depth units per metre in the analysis window.');return
        path,_=QFileDialog.getSaveFileName(self,'Save reviewed leaf annotations',str(self.dataset/'leaf_annotations.json'),'JSON (*.json)')
        if path:
            Path(path).write_text(json.dumps(dict(depth_scale_units_per_m=self.scale,leaves=self.leaves),indent=2));self.saved_path=Path(path);self.accept()

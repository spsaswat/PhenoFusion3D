"""Bounded extraction of measured spectra from explicitly reviewed ENVI regions.

This new-data path is independent of the hash-gated historical hyperspectral
recipe. It supports unsigned-16-bit BIL recordings with recorded nanometre
wavelengths. It does not segment plants, combine cameras, calibrate reflectance,
infer physiological traits, or assign spectra to 3D surfaces.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import html
import json
import math
import numbers
from pathlib import Path
import re
from typing import Callable

import numpy as np

WARNING = ('Measured camera-space DN; any Q/Q0 is provisional reference-relative signal. '
           'No calibrated reflectance, physiological interpretation, or 3D fusion.')
BAND_FLAGS = dict(outside_reviewed_reference_support=1, sample_suspected_clipping=2,
                  reference_suspected_clipping=4, weak_white_minus_dark=8,
                  raw_zero=16, low_signal_above_dark_advisory=32)
MAX_SCENE_PIXELS = 25_000_000
MAX_OUTPUT_VALUES = 20_000_000
MAX_REFERENCE_VALUES = 4_000_000
INDEX_SPECS = {
    'NDVI_800_680': dict(bands=[800,680],formula='(Q800-Q680)/(Q800+Q680)',operation='nd'),
    'NDRE_790_720': dict(bands=[790,720],formula='(Q790-Q720)/(Q790+Q720)',operation='nd'),
    'GNDVI_800_550': dict(bands=[800,550],formula='(Q800-Q550)/(Q800+Q550)',operation='nd'),
    'PRI_531_570': dict(bands=[531,570],formula='(Q531-Q570)/(Q531+Q570)',operation='nd'),
    'PSRI_678_500_750': dict(bands=[678,500,750],formula='(Q678-Q500)/Q750',operation='psri'),
    'SIPI_800_445_680': dict(bands=[800,445,680],formula='(Q800-Q445)/(Q800-Q680)',operation='sipi'),
}
INDEX_FLAGS = dict(invalid_required_band=1,low_signal_required_band=2,
                   weak_or_wrong_sign_denominator=4,reference_scan_line=8,nonfinite_index=16)


class ExtractionError(ValueError):
    """Inputs need explicit review or use unsupported storage."""


def _positive_int(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Integral) or value <= 0:
        raise ExtractionError(f'{name} must be a positive integer.')
    return int(value)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f'{name} must explicitly describe the reviewed input or assumption.')
    return value


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def _save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def _path(base, value, name):
    p = Path(_text(value, name)).expanduser()
    return (base/p).resolve() if not p.is_absolute() else p.resolve()


@dataclass(frozen=True)
class EnviSource:
    header: Path
    data: Path
    shape: tuple[int, int, int]  # line, band, column (native BIL storage)
    dtype: np.dtype
    offset: int
    wavelength_nm: np.ndarray
    fields: dict

    def read_lines(self, first, stop, bands):
        """Map only the requested contiguous line window, then unmap."""
        lines, count, columns = self.shape
        if not (0 <= first < stop <= lines):
            raise ExtractionError('Source line window is outside the recording.')
        if (stop-first)*count*columns > MAX_REFERENCE_VALUES:
            raise ExtractionError('Full BIL line window exceeds the bounded read budget.')
        band_ids = np.asarray(bands)
        if band_ids.ndim != 1 or not np.issubdtype(band_ids.dtype, np.integer) or np.any(band_ids < 0) or np.any(band_ids >= count):
            raise ExtractionError('Source band index is outside the recording.')
        mm = np.memmap(self.data, mode='r', dtype=self.dtype,
                       offset=self.offset+first*count*columns*2,
                       shape=(stop-first, count, columns))
        block = np.array(mm[:, band_ids, :], dtype=np.uint16, copy=True)
        del mm
        return block


def read_envi_source(header, data=None):
    """Read validated ENVI uint16 BIL metadata without guessing storage/units."""
    header = Path(header).resolve()
    data = Path(data).resolve() if data is not None else header.with_suffix('.bil')
    text = header.read_text(encoding='utf-8-sig')
    if not text.splitlines() or text.splitlines()[0].strip().upper() != 'ENVI':
        raise ExtractionError('Header must start with ENVI.')
    fields = {}
    for key,value in re.findall(r'(?m)^([^=\r\n]+)\s*=\s*(\{[^}]*\}|[^\r\n]*)', text):
        key=key.strip().lower()
        if key in fields:
            raise ExtractionError(f'Duplicate ENVI header key {key}; ambiguous metadata is unsupported.')
        fields[key]=value.strip()
    required = ('lines', 'bands', 'samples', 'data type', 'byte order', 'interleave', 'header offset', 'wavelength', 'wavelength units')
    if any(key not in fields for key in required):
        raise ExtractionError('Header lacks required storage, offset, wavelength or unit fields.')
    if fields['interleave'].lower() != 'bil' or fields['data type'] != '12' or fields['byte order'] not in ('0', '1'):
        raise ExtractionError('Only ENVI uint16 (type 12), BIL, declared little/big-endian data are supported.')
    try:
        shape = tuple(int(fields[key]) for key in ('lines', 'bands', 'samples'))
        offset = int(fields['header offset'])
        wavelengths = np.array([float(x.strip()) for x in fields['wavelength'].strip('{}').split(',')])
    except (ValueError, TypeError) as exc:
        raise ExtractionError('Malformed numeric ENVI storage or wavelength metadata.') from exc
    if min(shape) <= 0 or offset < 0:
        raise ExtractionError('ENVI dimensions must be positive and offset nonnegative.')
    if fields['wavelength units'].strip('{}').strip().lower() not in ('nm', 'nanometers', 'nanometres', 'nanometer', 'nanometre'):
        raise ExtractionError('Only explicitly recorded nanometre wavelengths are supported; no unit conversion is guessed.')
    if len(wavelengths) != shape[1] or not np.isfinite(wavelengths).all() or np.any(wavelengths <= 0) or not np.all(np.diff(wavelengths) > 0):
        raise ExtractionError('Wavelength count must equal bands and be finite, positive and strictly increasing.')
    expected = offset+math.prod(shape)*2
    if data.stat().st_size != expected:
        raise ExtractionError(f'BIL byte length differs from header: expected {expected}.')
    if shape[0]*shape[2] > MAX_SCENE_PIXELS:
        raise ExtractionError('Scene exceeds bounded mask workspace; crop/review a smaller recording first.')
    if shape[1]*shape[2] > MAX_REFERENCE_VALUES:
        raise ExtractionError('A full BIL line exceeds the bounded read budget; this storage layout is unsupported for bounded extraction.')
    return EnviSource(header, data, shape, np.dtype('<u2' if fields['byte order']=='0' else '>u2'), offset, wavelengths, fields)


def _roi(value, shape, name):
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(x,bool) or not isinstance(x,int) for x in value):
        raise ExtractionError(f'{name} must be integer [line_start,line_stop,column_start,column_stop], exclusive stop.')
    y0,y1,x0,x1 = value
    if not (0 <= y0 < y1 <= shape[0] and 0 <= x0 < x1 <= shape[2]):
        raise ExtractionError(f'{name} falls outside the recording.')
    return y0,y1,x0,x1


def _selection(config, source, base):
    selection = config.get('selection', {})
    if selection.get('review_status') not in ('assistant_reviewed', 'operator_reviewed'):
        raise ExtractionError('selection.review_status must declare assistant_reviewed or operator_reviewed regions.')
    _text(selection.get('provenance'), 'selection.provenance')
    polygons, mask_file = selection.get('polygons'), selection.get('label_mask_npy')
    if bool(polygons) == bool(mask_file):
        raise ExtractionError('Supply exactly one nonempty polygon list or integer label_mask_npy.')
    shape = (source.shape[0], source.shape[2])
    records = {}
    mask_path = None
    if mask_file:
        mask_path = _path(base, mask_file, 'label_mask_npy')
        if mask_path.suffix.lower() != '.npy':
            raise ExtractionError('label_mask_npy must be a standalone .npy integer array.')
        a = np.load(mask_path, mmap_mode='r', allow_pickle=False)
        if a.shape != shape or not np.issubdtype(a.dtype, np.integer) or np.any(a < 0) or np.any(a > 65535):
            raise ExtractionError('Label mask must match line/column shape with integer labels 0..65535.')
        labels = np.array(a, dtype=np.uint16, copy=True)
        names = selection.get('label_names', {})
        for label in np.unique(labels):
            if label:
                records[int(label)] = dict(patch_id=int(label), name=str(names.get(str(label), f'patch_{label}')))
    else:
        import cv2
        labels = np.zeros(shape, np.uint16)
        for patch in polygons:
            label = _positive_int(patch.get('patch_id'), 'patch_id')
            if label > 65535 or label in records:
                raise ExtractionError('Polygon patch IDs must be unique integers 1..65535.')
            name = _text(patch.get('name'), 'patch name')
            points = np.asarray(patch.get('column_line'), dtype=float)
            if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
                raise ExtractionError('Polygons require at least three finite (column,line) vertices.')
            if np.any(points < 0) or np.any(points[:,0] > shape[1]-1) or np.any(points[:,1] > shape[0]-1):
                raise ExtractionError('Reviewed polygon exits the recorded image; no silent clipping.')
            mask = np.zeros(shape, np.uint8)
            cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], 1)
            if np.any(mask.astype(bool) & (labels != 0)):
                raise ExtractionError('Reviewed polygons overlap; resolve ownership explicitly.')
            labels[mask != 0] = label
            records[label] = dict(patch_id=label, name=name, region_id=patch.get('region_id'), column_line=points.tolist())
    if not records:
        raise ExtractionError('Reviewed mask contains no selected pixels.')
    return labels, records, mask_path


def _reference_block(source, roi, bands):
    y0,y1,x0,x1 = roi
    line_batch=min(16,MAX_REFERENCE_VALUES//(source.shape[1]*source.shape[2]))
    pieces = [source.read_lines(y,min(y+line_batch,y1),bands)[:,:,x0:x1].copy()
              for y in range(y0,y1,line_batch)]
    return np.concatenate(pieces).astype(np.float32)


def _references(source, norm, ceiling, progress):
    _text(norm.get('white_identity'), 'normalization.white_identity')
    _text(norm.get('settings_assumption'), 'normalization.settings_assumption')
    if norm.get('dark_status') not in ('assumed_tail', 'confirmed_dark'):
        raise ExtractionError('dark_status must explicitly be assumed_tail or confirmed_dark.')
    _text(norm.get('dark_provenance'), 'normalization.dark_provenance')
    white = _roi(norm.get('white_roi'), source.shape, 'white_roi')
    dark = _roi(norm.get('dark_roi'), source.shape, 'dark_roi')
    if max(white[0],dark[0]) < min(white[1],dark[1]) and max(white[2],dark[2]) < min(white[3],dark[3]):
        raise ExtractionError('White and dark reference regions overlap.')
    per_band_values = (white[1]-white[0])*(white[3]-white[2])+(dark[1]-dark[0])*(dark[3]-dark[2])
    batch = min(16, MAX_REFERENCE_VALUES//per_band_values)
    if batch < 1:
        raise ExtractionError('Reference ROIs exceed bounded workspace; review smaller reference regions.')
    bands,cols=source.shape[1:]
    W=np.full((bands,cols),np.nan,np.float32);D=W.copy();SW=W.copy();SD=W.copy()
    coverage=np.zeros((bands,cols),bool)
    coverage[:,max(white[2],dark[2]):min(white[3],dark[3])]=True
    clipped=np.zeros((bands,cols),bool)
    for first in range(0,bands,batch):
        stop=min(first+batch,bands);selected=list(range(first,stop))
        w=_reference_block(source,white,selected);d=_reference_block(source,dark,selected)
        wm=np.median(w,axis=0);dm=np.median(d,axis=0)
        W[first:stop,white[2]:white[3]]=wm;D[first:stop,dark[2]:dark[3]]=dm
        SW[first:stop,white[2]:white[3]]=1.4826*np.median(np.abs(w-wm[None]),axis=0)
        SD[first:stop,dark[2]:dark[3]]=1.4826*np.median(np.abs(d-dm[None]),axis=0)
        if ceiling is not None:
            clipped[first:stop,white[2]:white[3]] |= np.any(w>=ceiling,axis=0)
            clipped[first:stop,dark[2]:dark[3]] |= np.any(d>=ceiling,axis=0)
        progress(f'Reference bands {stop}/{bands}')
    threshold=np.maximum(64.,5*np.sqrt(SW**2+SD**2)).astype(np.float32)
    weak=coverage & (~np.isfinite(W-D) | ((W-D)<=threshold))
    return dict(W_board=W,D_dark=D,white_MAD_sigma=SW,dark_MAD_sigma=SD,
                denominator_guard_DN=threshold,coverage_columns=coverage,
                reference_clipping=clipped,weak_reference=weak)


def _median(values):
    values=values[np.isfinite(values)]
    return float(np.median(values)) if len(values) else None


def _indices(arrays,source,config,normalization):
    requested=config.get('indices',[])
    if not isinstance(requested,list) or len(set(requested))!=len(requested) or any(name not in INDEX_SPECS for name in requested):
        raise ExtractionError('indices must be a unique list of supported explicit descriptor names.')
    if not requested:return {},{}
    tolerance=config.get('max_band_error_nm')
    if isinstance(tolerance,bool) or not isinstance(tolerance,numbers.Real) or not np.isfinite(tolerance) or tolerance<=0:
        raise ExtractionError('Requested descriptors require an explicit finite positive max_band_error_nm.')
    if normalization is None:
        raise ExtractionError('Q-based descriptors require explicit white and dark-reference assumptions.')
    applied={};unavailable={}
    for name in requested:
        spec=INDEX_SPECS[name]
        bands=[int(np.argmin(abs(source.wavelength_nm-t))) for t in spec['bands']]
        if len(set(bands))!=len(bands):
            unavailable[name]='Distinct required wavelengths select the same recorded band; descriptor omitted.'
            continue
        if any(abs(source.wavelength_nm[b]-t)>tolerance for b,t in zip(bands,spec['bands'])):
            unavailable[name]='Required wavelength is outside the configured nearest-band tolerance; no substitute or cross-camera band used.'
            continue
        applied[name]=dict(**spec,source_bands_zero_based=bands,actual_wavelengths_nm=source.wavelength_nm[bands].tolist())
    if not applied:return applied,unavailable
    reference_rows=np.zeros(len(arrays['scan_line']),bool)
    for key in ('white_roi','dark_roi'):
        y0,y1,_,_=normalization[key]
        reference_rows|=(arrays['scan_line']>=y0)&(arrays['scan_line']<y1)
    for array_name,output_name in [('Q_assumed_or_confirmed_dark','dark'),('Q_zero_offset','zero')]:
        values=np.full((len(reference_rows),len(applied)),np.nan,np.float32)
        flags=np.zeros(values.shape,np.uint8)
        for j,spec in enumerate(applied.values()):
            b=spec['source_bands_zero_based'];parts=[arrays[array_name][:,i] for i in b]
            numerator=parts[0]-parts[1]
            if spec['operation']=='nd':denominator=parts[0]+parts[1];stable=denominator>.01
            elif spec['operation']=='psri':denominator=parts[2];stable=denominator>.01
            else:denominator=parts[0]-parts[2];stable=np.abs(denominator)>.01
            np.divide(numerator,denominator,out=values[:,j],where=stable)
            bf=arrays['band_quality_flags'][:,b]
            for bit,bad in [(1,np.any((bf&31)!=0,axis=1)),(2,np.any((bf&32)!=0,axis=1)),(4,~stable),(8,reference_rows),(16,~np.isfinite(values[:,j]))]:
                flags[:,j]|=np.where(bad,bit,0).astype(np.uint8)
        values[flags!=0]=np.nan
        arrays[f'indices_{output_name}']=values;arrays[f'index_flags_{output_name}']=flags
    arrays['index_names']=np.array(list(applied))
    return applied,unavailable


def extract_reviewed_spectra(config_path, output_dir, *, progress: Callable[[str], None] | None = None):
    """Extract measured DN and optionally provisional Q/Q0 into a fresh run.

    Paths inside the JSON resolve relative to that configuration file. References
    are same-recording ROIs. Normalization is optional, but if requested both a
    reviewed white ROI and an explicitly assumed/confirmed dark ROI are required.
    Q0 retains the same conservative eligibility as Q so offset comparison does
    not silently change its spatial or clipping support. No outputs overwrite
    inputs or an existing run. Returns the JSON-compatible output summary.
    """
    progress=progress or (lambda _: None)
    config_path=Path(config_path).resolve();base=config_path.parent
    config_sha_initial=_sha(config_path)
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if config.get('schema_version') != 1:
        raise ExtractionError('Expected extraction configuration schema_version 1.')
    header=_path(base,config.get('header'),'header')
    header_sha_initial=_sha(header)
    data=_path(base,config['data'],'data') if config.get('data') else None
    source=read_envi_source(header,data)
    source_stat_initial=source.data.stat()
    source_identity=(source_stat_initial.st_size,source_stat_initial.st_mtime_ns,source_stat_initial.st_ino)
    configured_mask=config.get('selection',{}).get('label_mask_npy')
    mask_sha_initial=_sha(_path(base,configured_mask,'label_mask_npy')) if configured_mask else None
    labels,records,mask_path=_selection(config,source,base)
    sampling=config.get('sampling',{})
    line_step=_positive_int(sampling.get('line_step',2),'line_step')
    column_step=_positive_int(sampling.get('column_step',2),'column_step')
    yy,xx=np.nonzero(labels[::line_step,::column_step]);yy*=line_step;xx*=column_step
    if len(yy)==0 or len(yy)*source.shape[1] > MAX_OUTPUT_VALUES:
        raise ExtractionError('Selection is empty or exceeds bounded sample output; increase the explicit sampling steps.')
    ceiling=config.get('suspected_clipping_dn')
    if ceiling is not None and (isinstance(ceiling,bool) or not isinstance(ceiling,numbers.Real) or not np.isfinite(ceiling) or not 0<ceiling<=65535):
        raise ExtractionError('suspected_clipping_dn must be null or a finite number in (0,65535].')
    normalization=config.get('normalization')
    if normalization is not None and not isinstance(normalization,dict):
        raise ExtractionError('normalization must be null or an explicit reference object.')
    output=Path(output_dir).resolve()
    if output==source.data.parent or source.data.parent in output.parents:
        raise ExtractionError('Choose a separate output directory outside the source recording folder.')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ExtractionError('Output must be a fresh or empty directory; existing results are preserved.')
    output.mkdir(parents=True,exist_ok=True)
    result=output/'result';result.mkdir()
    _save_json(output/'run_status.json',dict(status='running',complete=False,physical_fusion=None))
    try:
        raw=np.empty((len(yy),source.shape[1]),np.uint16)
        for i,line in enumerate(np.unique(yy)):
            use=np.flatnonzero(yy==line)
            block=source.read_lines(int(line),int(line)+1,np.arange(source.shape[1]))
            raw[use]=block[0,:,xx[use]]
            if i%100==0:progress(f'Measured source lines: {i+1}/{len(np.unique(yy))}')
        flags=np.zeros(raw.shape,np.uint8)
        if ceiling is not None:flags|=np.where(raw>=ceiling,2,0).astype(np.uint8)
        flags|=np.where(raw==0,16,0).astype(np.uint8)
        arrays=dict(raw_DN=raw,band_quality_flags=flags,scan_line=yy.astype(np.int32),detector_column=xx.astype(np.int32),patch_id=labels[yy,xx],source_band_zero_based=np.arange(source.shape[1],dtype=np.int32),wavelength_nm=source.wavelength_nm)
        refs=None
        if normalization is not None:
            refs=_references(source,normalization,ceiling,progress)
            W=refs['W_board'][:,xx].T;D=refs['D_dark'][:,xx].T;SD=refs['dark_MAD_sigma'][:,xx].T
            for bit,test in [(1,~refs['coverage_columns'][:,xx].T),(4,refs['reference_clipping'][:,xx].T),(8,refs['weak_reference'][:,xx].T),(32,(raw.astype(np.float32)-D)<=np.maximum(32.,3*SD))]:
                flags|=np.where(test,bit,0).astype(np.uint8)
            valid=(flags&31)==0
            q=np.full(raw.shape,np.nan,np.float32);q0=np.full_like(q,np.nan)
            np.divide(raw.astype(np.float32)-D,W-D,out=q,where=valid)
            np.divide(raw.astype(np.float32),W,out=q0,where=valid)
            arrays.update(Q_assumed_or_confirmed_dark=q,Q_zero_offset=q0)
            np.savez_compressed(result/'reference_profiles.npz',WARNING=np.array(WARNING),wavelength_nm=source.wavelength_nm,**refs)
        else:
            flags|=np.uint8(1)
        applied_indices,unavailable_indices=_indices(arrays,source,config,normalization)
        np.savez_compressed(result/'measured_spectra.npz',WARNING=np.array(WARNING),**arrays)
        np.savez_compressed(result/'reviewed_patch_mask.npz',WARNING=np.array('Reviewed region candidates, not automatic or whole-plant segmentation.'),patch_id=labels)
        patch_rows=[]
        with (result/'patch_spectral_summary.csv').open('w',newline='',encoding='utf-8') as handle:
            writer=csv.writer(handle)
            writer.writerow(['patch_id','patch_name','source_band_zero_based','wavelength_nm','sample_pixels','raw_DN_mean','raw_DN_median','Q_valid_n','Q_median','Q0_median','suspected_clipped_n','low_signal_n'])
            for label,record in sorted(records.items()):
                use=arrays['patch_id']==label
                patch_rows.append(dict(**record,mask_pixels=int(np.count_nonzero(labels==label)),sample_pixels=int(use.sum()),sampling_status='measured' if use.any() else 'no_pixels_on_requested_sampling_grid',samples_with_any_suspected_clipping=int(np.any(flags[use]&2,axis=1).sum()),samples_without_reference_support=int(np.any(flags[use]&1,axis=1).sum()),samples_all_bands_Q_valid=int(np.all((flags[use]&31)==0,axis=1).sum()) if refs is not None else None))
                for b,wavelength in enumerate(source.wavelength_nm):
                    a=arrays['Q_assumed_or_confirmed_dark'][use,b] if refs is not None else np.array([])
                    z=arrays['Q_zero_offset'][use,b] if refs is not None else np.array([])
                    writer.writerow([label,record['name'],b,wavelength,int(use.sum()),float(raw[use,b].mean()) if use.any() else None,_median(raw[use,b]),int(np.isfinite(a).sum()),_median(a),_median(z),int(np.count_nonzero(flags[use,b]&2)),int(np.count_nonzero(flags[use,b]&32))])
        summary=dict(schema_version=1,status='complete_measured_camera_space_extraction',warning=WARNING,physical_fusion=None,calibrated_reflectance=False,physiological_claims=False,automatic_segmentation=False,cross_camera_concatenation=False,
                     source_header=str(header),source_data=str(source.data),source_config=str(config_path),header_sha256=header_sha_initial,config_sha256=config_sha_initial,source_data_size_bytes=source_identity[0],source_data_mtime_ns=source_identity[1],source_data_identity_check='size, mtime_ns and inode before/after; weaker than full-content hashing',full_source_data_sha256=None,raw_source_shape_line_band_column=list(source.shape),source_dtype=source.dtype.str,header_offset=source.offset,
                     sample_count=len(raw),band_count=source.shape[1],source_sample_sha256_uint16_little_endian_sample_band=hashlib.sha256(raw.astype('<u2',copy=False).tobytes()).hexdigest(),selection=config['selection'],sampling=dict(line_step=line_step,column_step=column_step,origin_line_column=[0,0]),patches=patch_rows,normalization=normalization,normalization_produced=refs is not None,
                     suspected_clipping_dn=ceiling,clipping_evaluated=ceiling is not None,band_flags=BAND_FLAGS,Q_invalid_bit_mask=31,low_signal_bit_32_policy='Advisory for Q; any downstream index must independently exclude required low-signal bands.',reference_formula='Q=(DN-D)/(W-D); Q0=DN/W, same conservative support' if refs is not None else None,reference_support_policy='Intersection of reviewed white/dark columns; no extrapolation',reference_contrast_guard='W-D > max(64 DN,5*sqrt(white_MAD_sigma^2+dark_MAD_sigma^2))',signal_guard='DN-D > max(32 DN,3*dark_MAD_sigma)',guard_limit='Exploratory guards inherited from reviewed workflow, not calibrated noise confidence bounds.',
                     array_axes='Spectral arrays: sample,source_band; index arrays: sample,index_names. Coordinates: zero-based source scan_line and detector_column.',invalid_floating_values='NaN, never zero filled',summary_limit='Medians omit invalid Q separately per band; valid pixel sets may change with wavelength. Patch samples are spatially correlated and not whole-plant traits.',products=dict(spectra='measured_spectra.npz',csv='patch_spectral_summary.csv',mask='reviewed_patch_mask.npz',reference_profiles='reference_profiles.npz' if refs is not None else None),software_sha256=_sha(Path(__file__)))
        if mask_path:summary['label_mask_sha256']=mask_sha_initial
        summary.update(index_specs_applied=applied_indices,indices_unavailable=unavailable_indices,index_quality_flags=INDEX_FLAGS,index_denominator_floor_Q_units=.01)
        if applied_indices:
            with (result/'patch_index_summary.csv').open('w',newline='',encoding='utf-8') as handle:
                writer=csv.writer(handle);writer.writerow(['patch_id','patch_name','descriptor','valid_dark_n','dark_median','valid_zero_n','zero_median','joint_valid_n','mean_absolute_offset_effect'])
                for label,record in sorted(records.items()):
                    use=arrays['patch_id']==label
                    for j,name in enumerate(applied_indices):
                        a=arrays['indices_dark'][use,j];z=arrays['indices_zero'][use,j];delta=a-z;finite=np.isfinite(delta)
                        writer.writerow([label,record['name'],name,int(np.isfinite(a).sum()),_median(a),int(np.isfinite(z).sum()),_median(z),int(finite.sum()),float(np.mean(abs(delta[finite]))) if finite.any() else None])
            summary['products']['indices_csv']='patch_index_summary.csv'
        final_stat=source.data.stat()
        if source_identity!=(final_stat.st_size,final_stat.st_mtime_ns,final_stat.st_ino) or _sha(header)!=header_sha_initial or _sha(config_path)!=config_sha_initial or (mask_path and _sha(mask_path)!=mask_sha_initial):
            raise ExtractionError('A source recording, header, configuration or reviewed mask changed during extraction; this run is not accepted.')
        summary['source_fingerprints_stable_before_after']=True
        _save_json(result/'summary.json',summary)
        replay=json.loads(json.dumps(config));replay['header']=str(header);replay['data']=str(source.data)
        if mask_path:replay['selection']['label_mask_npy']=str(mask_path)
        replay['source_config_provenance']=dict(path=str(config_path),sha256=config_sha_initial)
        _save_json(result/'input_config.json',replay)
        _save_json(result/'measured_spectra.metadata.json',dict(warning=WARNING,summary='summary.json',arrays={k:dict(shape=list(v.shape),dtype=str(v.dtype)) for k,v in arrays.items()},sha256=_sha(result/'measured_spectra.npz')))
        _write_html(result,summary)
        _save_json(output/'run_status.json',dict(status='complete',complete=True,result='result/index.html',physical_fusion=None))
        progress(f'Complete: {len(raw)} measured spectra x {source.shape[1]} bands')
        return summary
    except Exception as exc:
        _save_json(output/'run_status.json',dict(status='failed',complete=False,error=str(exc),physical_fusion=None))
        raise


def _write_html(result,summary):
    rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(p[k]))}</td>' for k in ('patch_id','name','sample_pixels','samples_with_any_suspected_clipping','samples_without_reference_support','samples_all_bands_Q_valid'))+'</tr>' for p in summary['patches'])
    assumption=html.escape(json.dumps(summary['normalization'],indent=2)) if summary['normalization'] else 'Raw DN only; no white/dark normalization requested.'
    reference='<li><a href="reference_profiles.npz">Measured reference profiles and validity</a></li>' if summary['normalization_produced'] else ''
    if summary['index_specs_applied']:
        reference+='<li><a href="patch_index_summary.csv">Exploratory index-shaped descriptors and offset sensitivity</a></li>'
    (result/'index.html').write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Measured spectral extraction</title><style>body{{font:16px/1.6 system-ui;max-width:1150px;margin:35px auto;padding:20px;color:#182434}}.note{{background:#fff1ce;padding:18px;border-left:5px solid #af7200}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:8px;border-bottom:1px solid #ccd5df;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3f7;padding:18px}}a{{color:#075493}}</style><h1>Measured spectral extraction</h1><p><strong>{summary['sample_count']:,} source-pixel spectra × {summary['band_count']} recorded bands</strong></p><p class="note">{html.escape(WARNING)} Selection is supplied by the reviewer; whole-plant identity, physiological state and physical calibration remain unverified. Clipped and unsupported raw DN is retained; invalid normalized data is NaN.</p><h2>Reviewed regions</h2><table><thead><tr><th>Patch</th><th>Name</th><th>Samples</th><th>Any-band clipping</th><th>No reference support</th><th>All bands Q-valid</th></tr></thead><tbody>{rows}</tbody></table><p>Clipping is {'evaluated using the explicitly configured ceiling' if summary['clipping_evaluated'] else 'not evaluated: no ceiling was configured'}. Q-valid counts include normalization support and clipping guards. Low-signal flags remain separately available.</p><h2>Saved measurements</h2><ul><li><a href="measured_spectra.npz">Full measured DN, Q/Q0 where requested, source coordinates and quality flags</a></li><li><a href="patch_spectral_summary.csv">Per-patch, per-band CSV summary</a></li><li><a href="reviewed_patch_mask.npz">Reviewed region label mask</a></li>{reference}<li><a href="summary.json">Method, source provenance and exact limits</a></li><li><a href="measured_spectra.metadata.json">Array shapes and checksum</a></li><li><a href="input_config.json">Input configuration snapshot</a></li></ul><h2>Explicit reference assumptions</h2><pre>{assumption}</pre><p>Unknown white-board spectral response prevents a reflectance claim even when a dark capture is confirmed. An assumed tail is a sensitivity scenario. No reference columns are extrapolated. Q/Q0 retain finite negative and above-one values. Medians may use different valid samples at different wavelengths. No camera alignment or 3D mapping is performed.</p></html>''',encoding='utf-8')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        summary=extract_reviewed_spectra(args.config,args.output,progress=lambda message:print(message,flush=True))
    except (ExtractionError,OSError,KeyError,TypeError,ValueError) as exc:
        parser.exit(2,f'Extraction could not complete: {exc}\n')
    print(json.dumps(dict(status=summary['status'],report=str((args.output/'result/index.html').resolve()))))
    return 0


if __name__=='__main__':
    raise SystemExit(main())

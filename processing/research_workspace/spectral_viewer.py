"""Offline inspection and lossless exports of already measured spectral samples.

The viewer preserves camera-space observations and sample IDs. It does not infer
spatial registration, new wavelengths, reflectance, or plant identity. No device,
web service or raw cube is opened.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
from collections.abc import Mapping

import numpy as np


WARNING = ('Measured camera-space spectra. Q/Q0 and spectral descriptors are '
           'provisional reference-relative signals, not calibrated reflectance '
           'or plant-health measurements. Camera regions are not verified 3D plant identities.')
MAX_VALUES = 20_000_000
REQUIRED = ('raw_DN', 'band_quality_flags', 'scan_line', 'detector_column',
            'patch_id', 'source_band_zero_based', 'wavelength_nm')
OPTIONAL = ('Q_assumed_or_confirmed_dark', 'Q_zero_offset', 'indices_dark',
            'index_flags_dark', 'indices_zero', 'index_flags_zero')


class SpectralReviewError(ValueError):
    """Saved observations are incomplete, inconsistent or unsafe to overwrite."""


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def _within(path, directory):
    return path == directory or directory in path.parents


def _load(directory):
    directory = Path(directory).resolve()
    paths = [directory / name for name in
             ('summary.json', 'measured_spectra.npz', 'measured_spectra.metadata.json')]
    if not all(p.is_file() for p in paths):
        raise SpectralReviewError(f'Missing extraction summary, measured spectra or metadata in {directory}')
    hashes = {p.name: _sha(p) for p in paths}
    summary = json.loads(paths[0].read_text(encoding='utf-8'))
    metadata = json.loads(paths[2].read_text(encoding='utf-8'))
    if summary.get('status') != 'complete_measured_camera_space_extraction':
        raise SpectralReviewError('Only completed measured spectral extractions are supported.')
    if metadata.get('sha256') != hashes['measured_spectra.npz']:
        raise SpectralReviewError('Measured NPZ checksum does not match its metadata.')
    # Bound decompression before materializing arrays, even for an untrusted NPZ.
    import zipfile
    with zipfile.ZipFile(paths[1]) as zipped:
        if sum(item.file_size for item in zipped.infolist()) > MAX_VALUES * 32:
            raise SpectralReviewError('Measured NPZ exceeds the bounded review allocation.')
    with np.load(paths[1], allow_pickle=False) as saved:
        if any(key not in saved for key in REQUIRED):
            raise SpectralReviewError('Measured NPZ lacks required source coordinates or spectral arrays.')
        arrays = {key: saved[key] for key in REQUIRED + OPTIONAL if key in saved}
        names = saved['index_names'].tolist() if 'index_names' in saved else []
    raw = arrays['raw_DN']
    if raw.ndim != 2 or raw.dtype != np.dtype('uint16') or not raw.shape[0] or not raw.shape[1] or raw.size > MAX_VALUES:
        raise SpectralReviewError('raw_DN must be a bounded, nonempty uint16 sample-by-band array.')
    count, bands = raw.shape
    if summary.get('sample_count') != count or summary.get('band_count') != bands:
        raise SpectralReviewError('Summary sample/band counts do not match measured data.')
    canonical = hashlib.sha256(raw.astype('<u2', copy=False).tobytes()).hexdigest()
    if summary.get('source_sample_sha256_uint16_little_endian_sample_band') != canonical:
        raise SpectralReviewError('Canonical measured DN checksum does not match extraction provenance.')
    for key in ('scan_line', 'detector_column', 'patch_id'):
        a = arrays[key]
        if a.shape != (count,) or a.dtype.kind not in 'iu' or np.any(a < (1 if key == 'patch_id' else 0)):
            raise SpectralReviewError(f'{key} must preserve nonnegative source coordinates and positive patch IDs.')
    shape = summary.get('raw_source_shape_line_band_column')
    if not isinstance(shape, list) or len(shape) != 3 or any(type(x) is not int or x <= 0 for x in shape) or shape[1] != bands:
        raise SpectralReviewError('An explicit positive source line-band-column shape is required.')
    if np.any(arrays['scan_line'] >= shape[0]) or np.any(arrays['detector_column'] >= shape[2]):
        raise SpectralReviewError('A measured source pixel lies outside its recording.')
    if len(np.unique(np.column_stack([arrays['scan_line'], arrays['detector_column']]), axis=0)) != count:
        raise SpectralReviewError('Duplicate source pixels make exact sample selection ambiguous.')
    wavelengths = arrays['wavelength_nm']
    if wavelengths.shape != (bands,) or not np.isfinite(wavelengths).all() or np.any(np.diff(wavelengths) <= 0):
        raise SpectralReviewError('Recorded wavelengths must be finite and strictly increasing.')
    if not np.array_equal(arrays['source_band_zero_based'], np.arange(bands)):
        raise SpectralReviewError('Source bands must retain the complete recorded band order.')
    flags = arrays['band_quality_flags']
    if flags.shape != raw.shape or flags.dtype != np.dtype('uint8') or np.any(flags > 63):
        raise SpectralReviewError('Band quality flags must match the supported uint8 flag schema.')
    q_names = ('Q_assumed_or_confirmed_dark', 'Q_zero_offset')
    if any(k in arrays for k in q_names) != all(k in arrays for k in q_names):
        raise SpectralReviewError('Q and Q0 must be present together.')
    for key in q_names:
        if key in arrays:
            a = arrays[key]
            if a.shape != raw.shape or a.dtype.kind != 'f' or np.isinf(a).any():
                raise SpectralReviewError('Q/Q0 must preserve finite values or explicit NaN gaps.')
            if not np.isnan(a[(flags & 31) != 0]).all():
                raise SpectralReviewError('Invalid Q/Q0 bands must remain NaN, never filled.')
    index_keys = ('indices_dark', 'index_flags_dark', 'indices_zero', 'index_flags_zero')
    if any(k in arrays for k in index_keys) != all(k in arrays for k in index_keys):
        raise SpectralReviewError('Index values and quality flags must be supplied together.')
    if not isinstance(names, list) or any(not isinstance(x, str) for x in names) or len(set(names)) != len(names):
        raise SpectralReviewError('Index names must be distinct text labels.')
    if bool(names) != all(k in arrays for k in index_keys):
        raise SpectralReviewError('Index names and value arrays disagree.')
    if set(names) != set(summary.get('index_specs_applied', {})):
        raise SpectralReviewError('Index names do not match the recorded descriptor definitions.')
    for mode in ('dark', 'zero'):
        if names:
            a, f = arrays['indices_' + mode], arrays['index_flags_' + mode]
            if a.shape != (count, len(names)) or a.dtype.kind != 'f' or np.isinf(a).any() or f.shape != a.shape or f.dtype != np.dtype('uint8') or np.any(f > 31):
                raise SpectralReviewError('Index arrays have inconsistent shapes, values or flags.')
            if not np.isnan(a[f != 0]).all():
                raise SpectralReviewError('Invalid descriptors must remain NaN.')
    patches = summary.get('patches', [])
    labels = [p.get('patch_id') for p in patches]
    if len(set(labels)) != len(labels) or not set(np.unique(arrays['patch_id'])).issubset(set(labels)):
        raise SpectralReviewError('Patch metadata must identify every measured patch exactly once.')
    for name in ('input_config.json', 'patch_spectral_summary.csv', 'patch_index_summary.csv',
                 'reference_profiles.npz', 'reviewed_patch_mask.npz'):
        p = directory / name
        if p.is_file():
            hashes[name] = _sha(p)
    return directory, summary, arrays, names, hashes


def _payload(array):
    """Little-endian bytes; float NaNs remain NaNs instead of JSON null coercion."""
    dtype = array.dtype.newbyteorder('<')
    if dtype.kind not in 'iuf' or dtype.itemsize not in (1, 2, 4, 8) or (dtype.kind == 'f' and dtype.itemsize not in (4, 8)):
        raise SpectralReviewError(f'Unsupported browser array dtype {dtype}')
    if dtype.kind in 'iu' and dtype.itemsize == 8:
        if np.any(np.abs(array.astype(float)) > 2 ** 53 - 1):
            raise SpectralReviewError('An integer exceeds the exact browser number range.')
    return dict(dtype=dtype.str, shape=list(array.shape),
                base64=base64.b64encode(array.astype(dtype, copy=False).tobytes()).decode('ascii'))


def load_spectral_result(path):
    """Return ``(arrays, summary)`` after source-hash, shape and quality checks.

    Array row numbers are the persistent zero-based measured sample IDs. This
    reader validates saved camera-space observations; it does not certify any
    separate geometric correspondence or physical calibration.
    """
    _, summary, arrays, names, _ = _load(path)
    if names:
        arrays['index_names'] = np.asarray(names)
    return arrays, summary


def _csv_value(value):
    return '' if not np.isfinite(value) else repr(float(value))


def _exports(directory, sensor, summary, arrays, names):
    raw = arrays['raw_DN']; n, bands = raw.shape
    patch_names = {p['patch_id']: p['name'] for p in summary['patches']}
    with gzip.open(directory / 'sample_bands.csv.gz', 'wt', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['sensor', 'sample_id_zero_based', 'scan_line', 'detector_column',
                         'patch_id', 'patch_name', 'source_band_zero_based', 'wavelength_nm',
                         'raw_DN', 'Q_assumed_or_confirmed_dark', 'Q_zero_offset', 'band_quality_flags'])
        q, q0 = arrays.get('Q_assumed_or_confirmed_dark'), arrays.get('Q_zero_offset')
        for i in range(n):
            prefix = [sensor, i, int(arrays['scan_line'][i]), int(arrays['detector_column'][i]),
                      int(arrays['patch_id'][i]), patch_names[int(arrays['patch_id'][i])]]
            for b in range(bands):
                writer.writerow(prefix + [b, repr(float(arrays['wavelength_nm'][b])), int(raw[i, b]),
                    _csv_value(q[i, b]) if q is not None else '',
                    _csv_value(q0[i, b]) if q0 is not None else '', int(arrays['band_quality_flags'][i, b])])
    if names:
        with gzip.open(directory / 'sample_indices.csv.gz', 'wt', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['sensor', 'sample_id_zero_based', 'scan_line', 'detector_column',
                'patch_id', 'descriptor', 'value_Q', 'value_Q0', 'flags_Q', 'flags_Q0'])
            for i in range(n):
                for j, name in enumerate(names):
                    writer.writerow([sensor, i, int(arrays['scan_line'][i]), int(arrays['detector_column'][i]),
                        int(arrays['patch_id'][i]), name, _csv_value(arrays['indices_dark'][i, j]),
                        _csv_value(arrays['indices_zero'][i, j]), int(arrays['index_flags_dark'][i, j]),
                        int(arrays['index_flags_zero'][i, j])])


def build_spectral_review(result_dirs, output, *, export_csv=True, progress=None):
    """Create an offline report from completed extraction result directories.

    ``result_dirs`` maps unique sensor labels to folders containing summary.json
    and measured_spectra.npz, or is a sequence of folders labelled sensor_1 etc.
    ``output`` must be absent and outside every input folder. All source sample
    IDs are zero-based NPZ row indices, also accepted by the report query string
    ``?sensor=fx10&sample=123``. CSV blank floats represent NaN/unavailable, never
    zero; untouched NPZ archives remain the authoritative lossless data format.
    """
    progress = progress or (lambda _: None)
    if isinstance(result_dirs, Mapping):
        entries = list(result_dirs.items())
    else:
        entries = [(f'sensor_{i + 1}', p) for i, p in enumerate(result_dirs)]
    if not entries or len(entries) > 8:
        raise SpectralReviewError('Supply between one and eight measured sensor results.')
    if any(not isinstance(k, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', k) for k, _ in entries):
        raise SpectralReviewError('Sensor IDs must use 1â€“64 ASCII letters, numbers, underscores or hyphens.')
    if len({k for k, _ in entries}) != len(entries):
        raise SpectralReviewError('Sensor IDs must be unique.')
    output = Path(output).resolve()
    if output.exists():
        raise SpectralReviewError('Choose a fresh output directory; existing results are preserved.')
    for _, p in entries:
        source = Path(p).resolve()
        if _within(output, source) or _within(source, output):
            raise SpectralReviewError('The output must be outside and must not contain source result folders.')
    loaded = [(sensor, _load(path)) for sensor, path in entries]
    if sum(item[1][2]['raw_DN'].size for item in loaded) > MAX_VALUES:
        raise SpectralReviewError('Combined measured spectra exceed the bounded review allocation.')
    output.mkdir(parents=True)
    _json(output / 'run_status.json', dict(status='running', complete=False, physical_fusion=None))
    try:
        sensors = []
        for sensor, (source, summary, arrays, names, hashes) in loaded:
            progress(f'Preserving and exporting measured samples: {sensor}')
            destination = output / 'sensors' / sensor
            destination.mkdir(parents=True)
            for name in hashes:
                shutil.copyfile(source / name, destination / name)
                if _sha(destination / name) != hashes[name]:
                    raise SpectralReviewError('A copied result does not match the source checksum.')
            data = dict(sensor=sensor, summary=summary, index_names=names,
                        arrays={k: _payload(v) for k, v in arrays.items()})
            # External local JS permits file:// use without fetch/CORS or a CDN.
            (destination / 'browser_data.js').write_text(
                'window.spectralDataReady(' + json.dumps(data, allow_nan=False).replace('</', '<\\/') + ');', encoding='utf-8')
            if export_csv:
                _exports(destination, sensor, summary, arrays, names)
            sensors.append(dict(id=sensor, source_directory=str(source),
                sample_count=summary['sample_count'], band_count=summary['band_count'],
                wavelengths_nm=[float(arrays['wavelength_nm'][0]), float(arrays['wavelength_nm'][-1])],
                source_hashes=hashes, descriptors=names, data_script=f'sensors/{sensor}/browser_data.js',
                exports=[f'sensors/{sensor}/{name}' for name in hashes] +
                    ([f'sensors/{sensor}/sample_bands.csv.gz'] if export_csv else []) +
                    ([f'sensors/{sensor}/sample_indices.csv.gz'] if export_csv and names else [])))
        for _, (source, _, _, _, hashes) in loaded:
            if any(_sha(source / name) != digest for name, digest in hashes.items()):
                raise SpectralReviewError('A saved source changed during report creation.')
        manifest = dict(schema_version=1, status='complete_measured_spectral_inspection',
            warning=WARNING, sensors=sensors, source_inputs_unchanged=True,
            physical_fusion=None, calibrated_reflectance=False, physiological_claims=False,
            cross_camera_concatenation=False, sample_id_convention='zero-based row of sensor measured_spectra.npz',
            csv_missing_values='Blank numeric cells mean NaN or unavailable; never zero filled.',
            viewer_sampling='Every saved measured sample; no added or interpolated sample.',
            software_sha256=_sha(Path(__file__)))
        _json(output / 'manifest.json', manifest)
        (output / 'index.html').write_text(_HTML.replace('__MANIFEST__',
            json.dumps(manifest, allow_nan=False).replace('</', '<\\/')), encoding='utf-8')
        products = {str(p.relative_to(output)).replace('\\', '/'): _sha(p)
                    for p in output.rglob('*') if p.is_file() and p.name != 'run_status.json'}
        _json(output / 'checksums.json', products)
        _json(output / 'run_status.json', dict(status='complete', complete=True,
              result='index.html', physical_fusion=None))
        progress('Complete: measured spectral inspection and exact exports')
        return manifest
    except Exception as exc:
        _json(output / 'run_status.json', dict(status='failed', complete=False,
              error=str(exc), physical_fusion=None))
        raise


_HTML = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Measured spectra explorer</title>
<style>body{font:16px/1.5 system-ui;background:#eef3f6;color:#172b39;margin:0}main{max-width:1450px;margin:auto;padding:25px}h1{margin-bottom:8px}.note{padding:15px;border-left:5px solid #b27700;background:#fff0cf}.controls,section{background:white;border-radius:9px;padding:18px;margin:18px 0}.controls{display:flex;gap:16px;flex-wrap:wrap;align-items:center}label{display:flex;gap:7px;align-items:center}select,input,button{font:inherit;max-width:100%;padding:5px}input[type=range]{width:210px}input[type=number]{width:90px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}canvas{width:100%;height:auto;background:#f4f7fa;border:1px solid #cbd7df;touch-action:manipulation}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #d5dfe6;text-align:left;padding:7px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 monospace}.small{font-size:13px;color:#435d6e}a{color:#075d87}#value,#selected{font-weight:600}#message{color:#9a2a15}@media(max-width:850px){.grid{display:block}main{padding:12px}}</style>
<main><h1>Measured spectra explorer</h1><p>Source pixels, recorded bands, reference assumptions and quality flags.</p>
<p class="note">Q/Q0 and the listed descriptors are <strong>provisional reference-relative signals</strong>. The white-board spectrum is unverified and any assumed dark tail is a sensitivity scenario. These are not calibrated reflectance or health measurements. Sensors remain separate; scan-region labels do not establish a 3D plant identity.</p>
<div class="controls"><label>Sensor <select id="sensor" aria-label="Sensor"></select></label><label>Display <select id="mode" aria-label="Display"></select></label><label>Band <input id="band" type="range" min="0" value="0"><span id="bandLabel"></span></label><label>Sample ID <input id="sample" type="number" min="0" value="0"></label><button id="selectSample">Inspect sample</button></div>
<p id="message" role="status">Loading measured spectra…</p><div class="grid"><section><h2>Recorded source pixels</h2><p class="small">Detector column horizontally; scan line vertically. Click a measured dot. Blank areas were not sampled; grey points have unavailable/invalid displayed values. Display colour uses the finite minimum and maximum, without changing saved values.</p><canvas id="map" width="700" height="620" aria-label="Measured source pixel map"></canvas><p id="scale" class="small"></p></section>
<section><h2>Selected measured sample</h2><p id="selected"></p><p id="value"></p><p id="quality"></p><canvas id="curve" width="700" height="360" aria-label="Recorded spectral curve"></canvas><p class="small">Each vertex is one recorded band. Line segments only connect adjacent finite bands for display; invalid bands are explicit gaps. No interpolation is exported.</p><button id="downloadSample">Download this sample CSV</button><div id="indices"></div></section></div>
<section><h2>Downloads and provenance</h2><p class="small">The NPZ is copied byte-for-byte. Compressed CSVs retain sample IDs, source coordinates and quality flags; blank floating values mean NaN or unavailable, never zero. Source paths describe the original saved extraction and are not required to use this report.</p><div id="downloads"></div><details><summary>Recorded method and reference assumptions</summary><pre id="provenance"></pre></details><p><a href="manifest.json">Review manifest</a> · <a href="checksums.json">File checksums</a></p></section></main>
<script>const M=__MANIFEST__;
const el=id=>document.getElementById(id), esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const params=new URLSearchParams(location.search);let data=null,A=null,current=0,band=0,mode='raw_DN',extent=null,loadId=0;
const bandFlags={1:'outside reviewed reference support',2:'sample suspected clipping',4:'reference suspected clipping',8:'weak white-minus-dark',16:'raw zero',32:'low signal (advisory for Q)'},indexFlags={1:'invalid required band',2:'low-signal required band',4:'weak/wrong-sign denominator',8:'reference scan line',16:'nonfinite descriptor'};
const flagText=(f,defs)=>Object.entries(defs).filter(([n])=>f&Number(n)).map(([,s])=>s).join('; ')||'none';
function decode(p){const bin=atob(p.base64),buffer=new ArrayBuffer(bin.length),bytes=new Uint8Array(buffer);for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);const v=new DataView(buffer),t=p.dtype.slice(1),size=Number(t.slice(1)),get={u1:'getUint8',u2:'getUint16',u4:'getUint32',i1:'getInt8',i2:'getInt16',i4:'getInt32',f4:'getFloat32',f8:'getFloat64',u8:'getBigUint64',i8:'getBigInt64'}[t];if(!get)throw Error('Unsupported stored dtype '+p.dtype);const out=new Float64Array(bin.length/size);for(let i=0;i<out.length;i++)out[i]=Number(v[get](i*size,true));return out}
for(const s of M.sensors){const o=document.createElement('option');o.value=s.id;o.textContent=s.id.toUpperCase()+' · '+s.sample_count.toLocaleString()+' measured samples';el('sensor').appendChild(o)}
function sensorLoad(id){const generation=++loadId;data=null;A=null;el('message').textContent='Loading '+id+'…';window.spectralDataReady=d=>{if(generation!==loadId||d.sensor!==id)return;try{data=d;A=Object.fromEntries(Object.entries(d.arrays).map(([k,v])=>[k,decode(v)]));current=0;band=0;mode='raw_DN';el('band').max=d.summary.band_count-1;el('band').value=0;el('sample').max=d.summary.sample_count-1;el('mode').innerHTML='';const modes=[['raw_DN','Raw DN'],['Q_assumed_or_confirmed_dark','Q · assumed/confirmed dark'],['Q_zero_offset','Q0 · zero-offset sensitivity'],['band_quality_flags','Band quality flag bits']];if(d.index_names.length)for(let j=0;j<d.index_names.length;j++){modes.push(['index_dark_'+j,d.index_names[j]+' · Q'],['index_zero_'+j,d.index_names[j]+' · Q0'])}for(const [key,label] of modes){if(key.startsWith('index_')||A[key]){const o=document.createElement('option');o.value=key;o.textContent=label;el('mode').appendChild(o)}}const wanted=Number(params.get('sample'));if(params.get('sensor')===id&&Number.isInteger(wanted)&&wanted>=0&&wanted<d.summary.sample_count)current=wanted;const b=Number(params.get('band'));if(params.get('sensor')===id&&Number.isInteger(b)&&b>=0&&b<d.summary.band_count)band=b;el('band').value=band;downloads();draw();el('message').textContent='Ready. Every displayed dot is a saved measured sample; no 3D mapping is asserted.'}catch(e){el('message').textContent='Unable to inspect saved arrays: '+e.message}};const script=document.createElement('script');script.src=M.sensors.find(s=>s.id===id).data_script;script.onerror=()=>el('message').textContent='Could not load the local data file. Keep the report folders together.';document.body.appendChild(script)}
function values(){if(mode.startsWith('index_')){const [,offset,j]=mode.split('_'),v=A['indices_'+offset],k=Number(j),n=data.index_names.length;return Array.from({length:data.summary.sample_count},(_,i)=>v[i*n+k])}const n=data.summary.band_count;return Array.from({length:data.summary.sample_count},(_,i)=>A[mode][i*n+band])}
function finiteRange(vals){let lo=Infinity,hi=-Infinity;for(const v of vals)if(Number.isFinite(v)){lo=Math.min(lo,v);hi=Math.max(hi,v)}return [lo,hi]}
function color(v,lo,hi){if(!Number.isFinite(v))return '#aebac4';const t=hi===lo?.5:Math.max(0,Math.min(1,(v-lo)/(hi-lo)));return `hsl(${240-240*t},70%,43%)`}
function point(i){const [xmin,xmax,ymin,ymax]=extent;return [45+(A.detector_column[i]-xmin)/(xmax-xmin||1)*620,25+(A.scan_line[i]-ymin)/(ymax-ymin||1)*550]}
function drawMap(){const c=el('map').getContext('2d'),v=values(),[lo,hi]=finiteRange(v);c.clearRect(0,0,700,620);const x=finiteRange(A.detector_column),y=finiteRange(A.scan_line);extent=[...x,...y];c.strokeStyle='#c1cdd6';c.strokeRect(45,25,620,550);for(let i=0;i<v.length;i++){const [px,py]=point(i);c.fillStyle=color(v[i],lo,hi);c.fillRect(px-1.7,py-1.7,3.4,3.4)}const [sx,sy]=point(current);c.strokeStyle='#111';c.lineWidth=2;c.beginPath();c.arc(sx,sy,7,0,2*Math.PI);c.stroke();c.fillStyle='#263e4e';c.font='13px system-ui';c.fillText('Column '+x[0],45,602);c.fillText(String(x[1]),630,602);c.fillText(String(y[0]),3,30);c.fillText(String(y[1]),3,576);el('scale').textContent=Number.isFinite(lo)?'Display range '+format(lo)+' to '+format(hi)+' · '+v.filter(Number.isFinite).length+' finite samples.':'No finite values for this display. Raw DN and quality flags remain available.'}
function format(v){return Number.isFinite(v)?Number(v).toPrecision(7):'Unavailable (NaN)'}
function spectrumMode(){return mode==='Q_assumed_or_confirmed_dark'||mode.startsWith('index_dark')?'Q_assumed_or_confirmed_dark':mode==='Q_zero_offset'||mode.startsWith('index_zero')?'Q_zero_offset':mode==='band_quality_flags'?'band_quality_flags':'raw_DN'}
function drawCurve(){const c=el('curve').getContext('2d'),key=spectrumMode(),n=data.summary.band_count,ys=A[key].slice(current*n,(current+1)*n),xs=A.wavelength_nm,[lo0,hi0]=finiteRange(ys),lo=Number.isFinite(lo0)?lo0:0,hi=hi0===lo?lo+1:(Number.isFinite(hi0)?hi0:1);c.clearRect(0,0,700,360);const px=b=>60+(xs[b]-xs[0])/(xs[n-1]-xs[0]||1)*610,py=v=>305-(v-lo)/(hi-lo)*265;c.strokeStyle='#b9c8d1';c.strokeRect(60,40,610,265);c.strokeStyle='#076e92';c.lineWidth=1.5;c.beginPath();let connected=false;for(let b=0;b<n;b++){if(!Number.isFinite(ys[b])){connected=false;continue}if(connected)c.lineTo(px(b),py(ys[b]));else c.moveTo(px(b),py(ys[b]));connected=true}c.stroke();c.fillStyle='#076e92';for(let b=0;b<n;b++)if(Number.isFinite(ys[b])){c.beginPath();c.arc(px(b),py(ys[b]),2.2,0,2*Math.PI);c.fill()}c.strokeStyle='#b46a00';c.beginPath();c.moveTo(px(band),40);c.lineTo(px(band),305);c.stroke();c.fillStyle='#263e4e';c.font='13px system-ui';c.fillText(key,60,21);c.fillText(format(hi),2,42);c.fillText(format(lo),2,308);c.fillText(xs[0]+' nm',60,336);c.fillText(xs[n-1]+' nm',584,336)}
function selected(){const n=data.summary.band_count,i=current,b=band,patch=data.summary.patches.find(p=>p.patch_id===A.patch_id[i]),flags=A.band_quality_flags[i*n+b];el('sample').value=i;el('selected').textContent=data.sensor.toUpperCase()+' · sample '+i+' · scan line '+A.scan_line[i]+' · detector column '+A.detector_column[i]+' · patch '+A.patch_id[i]+' ('+(patch?.name||'')+')'+(patch?.region_id?' · '+patch.region_id:'');const isIndex=mode.startsWith('index_');el('band').disabled=isIndex;if(isIndex){const [,offset,j]=mode.split('_'),idx=Number(j),f=A['index_flags_'+offset][i*data.index_names.length+idx];el('value').textContent=data.index_names[idx]+' · '+(offset==='dark'?'Q':'Q0')+': '+format(values()[i]);el('quality').textContent='Descriptor flags '+f+': '+flagText(f,indexFlags)}else{el('value').textContent='Band '+b+' ('+A.wavelength_nm[b]+' nm): '+format(values()[i]);el('quality').textContent='Band flags '+flags+': '+flagText(flags,bandFlags)}el('bandLabel').textContent=b+' · '+A.wavelength_nm[b]+' nm';let body='';for(let j=0;j<data.index_names.length;j++){const k=i*data.index_names.length+j;body+='<tr><td>'+esc(data.index_names[j])+'</td><td>'+format(A.indices_dark[k])+'</td><td>'+format(A.indices_zero[k])+'</td><td>'+esc(flagText(A.index_flags_dark[k],indexFlags))+' / '+esc(flagText(A.index_flags_zero[k],indexFlags))+'</td></tr>'}el('indices').innerHTML=body?'<h3>Exploratory descriptors</h3><table><tr><th>Descriptor</th><th>Q</th><th>Q0</th><th>Quality Q / Q0</th></tr>'+body+'</table>':'<p>No supported saved descriptor for this sensor. Missing wavelengths are not borrowed from another camera.</p>';if(history.replaceState){const q=new URLSearchParams({sensor:data.sensor,sample:String(i),band:String(b)});try{history.replaceState(null,'','?'+q)}catch(e){}}}
function draw(){if(!data)return;selected();drawMap();drawCurve()}
function downloads(){const s=M.sensors.find(s=>s.id===data.sensor);el('downloads').innerHTML='<ul>'+s.exports.map(p=>'<li><a href="'+p+'">'+esc(p.split('/').at(-1))+'</a></li>').join('')+'</ul>';el('provenance').textContent=JSON.stringify({source_directory:s.source_directory,source_hashes:s.source_hashes,method:data.summary},null,2)}
el('map').onclick=e=>{if(!data)return;const r=el('map').getBoundingClientRect(),x=(e.clientX-r.left)*700/r.width,y=(e.clientY-r.top)*620/r.height;let closest=-1,dist=144;for(let i=0;i<data.summary.sample_count;i++){const [px,py]=point(i),d=(px-x)**2+(py-y)**2;if(d<dist){closest=i;dist=d}}if(closest<0){el('message').textContent='No measured sample at this position. Choose a measured dot or its sample ID.';return}current=closest;el('message').textContent='Selected an exact saved measured sample.';draw()};
el('sensor').onchange=()=>sensorLoad(el('sensor').value);el('mode').onchange=()=>{mode=el('mode').value;draw()};el('band').oninput=()=>{band=Number(el('band').value);draw()};el('selectSample').onclick=()=>{const i=Number(el('sample').value);if(!data||!Number.isInteger(i)||i<0||i>=data.summary.sample_count){el('message').textContent='Enter an existing zero-based measured sample ID.';return}current=i;draw()};
function download(text,name){const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
el('downloadSample').onclick=()=>{if(!data)return;const n=data.summary.band_count,i=current,rows=[['sensor','sample_id_zero_based','scan_line','detector_column','patch_id','source_band_zero_based','wavelength_nm','raw_DN','Q_assumed_or_confirmed_dark','Q_zero_offset','band_quality_flags'].join(',')];for(let b=0;b<n;b++){const k=i*n+b,cell=v=>Number.isFinite(v)?String(v):'';rows.push([data.sensor,i,A.scan_line[i],A.detector_column[i],A.patch_id[i],b,A.wavelength_nm[b],A.raw_DN[k],cell(A.Q_assumed_or_confirmed_dark?.[k]),cell(A.Q_zero_offset?.[k]),A.band_quality_flags[k]].join(','))}download(rows.join('\r\n')+'\r\n',data.sensor+'_sample_'+i+'.csv')};
const initial=M.sensors.some(s=>s.id===params.get('sensor'))?params.get('sensor'):M.sensors[0].id;el('sensor').value=initial;sensorLoad(initial);
</script></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sensor', action='append', required=True, metavar='ID=RESULT_DIRECTORY')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--no-csv', action='store_true')
    args = parser.parse_args(argv)
    try:
        entries = [item.split('=', 1) for item in args.sensor]
        if any(len(item) != 2 for item in entries) or len({x[0] for x in entries}) != len(entries):
            raise SpectralReviewError('Each --sensor needs a unique ID=RESULT_DIRECTORY.')
        result = build_spectral_review(dict(entries), args.output, export_csv=not args.no_csv,
                                      progress=lambda message: print(message, flush=True))
    except (SpectralReviewError, OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'Spectral review could not complete: {exc}\n')
    print(json.dumps(dict(status=result['status'], report=str((args.output / 'index.html').resolve()))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Sparse, explicit measured-spectrum associations to existing 3D vertices.

This is a correspondence-based research result, not a camera calibration or a
dense surface texture. A reviewed match remains provisional: this module never
upgrades it to physically validated fusion, reflectance, or a plant health score.
It imports no acquisition, ROS, or camera SDK module.
"""
from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path
import shutil

import numpy as np

from .workflow import cloud_record, fresh_output, local_path, read_json, rotation, save_json, sha

WARNING = ('Sparse provisional measured-spectrum associations. Unassigned geometry has no spectral value. '
           'No independently validated surface registration, calibrated reflectance, or physiological claim.')


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be explicit nonempty text.')
    return value


def _index(value, count, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < count:
        raise ValueError(f'{name} must identify an exact original source row.')
    return value


def _fingerprinted(entry, key, base):
    path = local_path(entry[key], base)
    expected = _text(entry.get('sha256'), key + ' sha256')
    if not path.is_file() or sha(path) != expected:
        raise ValueError(f'Missing or changed source: {path}')
    return path


def load_spectra(folder, expected):
    """Validate and copy arrays without interpolation or changing invalid values."""
    path = folder / 'measured_spectra.npz'
    if sha(path) != expected:
        raise ValueError('Measured spectral archive changed since correspondence review.')
    from .spectral_viewer import load_spectral_result
    arrays, _summary = load_spectral_result(folder)
    return arrays


def validate_associations(items, records, spectra, evidence, unit):
    if not isinstance(items, list) or not items:
        raise ValueError('No reviewed correspondences supplied. Use spectral review without claiming 3D fusion.')
    rows = []
    identities, pixels, vertices = set(), set(), set()
    for item in items:
        identity = _text(item.get('id'), 'Correspondence id')
        sensor, cloud_id = item.get('sensor_id'), item.get('cloud_id')
        if identity in identities or sensor not in spectra or cloud_id not in records:
            raise ValueError('Duplicate correspondence ID or unknown sensor/cloud.')
        if item.get('status') != 'provisional_reviewed_correspondence':
            raise ValueError('Only explicitly provisional reviewed correspondences are supported.')
        for key in ('reviewer', 'review_method', 'feature_description'):
            _text(item.get(key), key)
        refs = item.get('evidence_ids')
        if not isinstance(refs, list) or not refs or any(x not in evidence for x in refs):
            raise ValueError('Every correspondence needs fingerprinted source evidence.')
        data, record = spectra[sensor], records[cloud_id]
        sample = _index(item.get('sample_index'), len(data['raw_DN']), 'sample_index')
        point = _index(item.get('point_index'), record['source_count'], 'point_index')
        if (sensor, sample) in pixels or (sensor, cloud_id, point) in vertices:
            raise ValueError('Do not reuse a sensor pixel or assign multiple spectra to one sensor/cloud vertex.')
        raw_xyz = np.asarray(item.get('localized_reference_xyz'), dtype=float)
        threshold = item.get('maximum_vertex_distance')
        if (raw_xyz.shape != (3,) or not np.isfinite(raw_xyz).all() or isinstance(threshold, bool)
                or not isinstance(threshold, (int, float)) or not np.isfinite(threshold) or threshold <= 0):
            raise ValueError('Finite source-localized XYZ and a positive explicit vertex-distance limit are required.')
        distance = float(np.linalg.norm(record['reference_points'][point] - raw_xyz))
        if distance > threshold:
            raise ValueError(f'{identity}: localized observation is too far from its named source vertex.')
        votes = item.get('supporting_rgb_pairs')
        if isinstance(votes, bool) or not isinstance(votes, int) or votes < 2:
            raise ValueError('This sparse recovered-depth workflow requires at least two supporting RGB pairs.')
        row = dict(item, sensor_id=sensor, cloud_id=cloud_id, sample_index=sample, point_index=point,
                   source_scan_line=int(data['scan_line'][sample]), source_detector_column=int(data['detector_column'][sample]),
                   source_patch_id=int(data['patch_id'][sample]), source_cloud_sha256=record['sha256'],
                   xyz_reference=record['reference_points'][point].tolist(), xyz_upright=record['points'][point].tolist(),
                   vertex_distance=distance, coordinate_unit=unit, physical_registration_validated=False,
                   surface_visibility_validated=False, calibrated_reflectance=False)
        rows.append(row)
        identities.add(identity); pixels.add((sensor, sample)); vertices.add((sensor, cloud_id, point))
    return rows


def build(config_path, output_dir, *, progress=None):
    progress = progress or (lambda _: None)
    config_path = Path(config_path).resolve()
    config_hash = sha(config_path)
    config = read_json(config_path); base = config_path.parent
    if config.get('schema_version') != 1:
        raise ValueError('Expected sparse fusion schema_version 1.')
    frame = _text(config.get('frame_id'), 'frame_id')
    unit = _text(config.get('coordinate_unit'), 'coordinate_unit')
    R = rotation(config.get('upright_R'))
    inputs = {config_path: config_hash}; records = {}; sensors = {}; source_dirs = {}
    for entry in config.get('clouds', []):
        identity = _text(entry.get('id'), 'cloud id')
        if identity in records:
            raise ValueError('Duplicate cloud ID.')
        path = _fingerprinted(entry, 'cloud', base); inputs[path] = entry['sha256']
        record = cloud_record(entry, base, np.eye(3))
        record['reference_points'] = record['points'].copy()
        record['points'] = record['points'] @ R.T
        records[identity] = record
    if not records:
        raise ValueError('Supply existing observed PLY geometry.')
    for entry in config.get('sensors', []):
        identity = _text(entry.get('id'), 'sensor id')
        if identity in sensors or not identity.replace('_', '').replace('-', '').isalnum():
            raise ValueError('Sensor IDs must be unique safe directory names.')
        folder = local_path(entry['result_dir'], base)
        expected = _text(entry.get('spectra_sha256'), 'spectra_sha256')
        for name in ('measured_spectra.npz', 'measured_spectra.metadata.json', 'summary.json'):
            path = folder / name; inputs[path] = sha(path)
        sensors[identity] = load_spectra(folder, expected)
        for name in ('measured_spectra.npz', 'measured_spectra.metadata.json', 'summary.json'):
            path = folder / name
            if sha(path) != inputs[path]:
                raise ValueError('Source changed during spectral loading: '+str(path))
        source_dirs[identity] = folder
    evidence = {}
    for entry in config.get('evidence', []):
        identity = _text(entry.get('id'), 'evidence id')
        if identity in evidence:
            raise ValueError('Duplicate evidence ID.')
        path = _fingerprinted(entry, 'path', base)
        evidence[identity] = dict(entry, path=str(path)); inputs[path] = entry['sha256']
    rows = validate_associations(config.get('associations'), records, sensors, evidence, unit)
    out = fresh_output(output_dir, inputs, protected_roots=source_dirs.values())
    save_json(out/'run_status.json', dict(status='running', complete=False))
    try:
        progress('Copying measured spectra and preparing offline band inspection')
        from .spectral_viewer import build_spectral_review
        build_spectral_review(source_dirs, out/'spectra', progress=progress)
        (out/'clouds').mkdir(); (out/'evidence').mkdir()
        for number, record in enumerate(records.values()):
            dest = out/'clouds'/f'cloud_{number}.ply'
            shutil.copyfile(record['path'], dest)
            record['packaged_cloud'] = dest.relative_to(out).as_posix()
        for number, entry in enumerate(evidence.values()):
            path = Path(entry['path']); dest = out/'evidence'/f'{number:03d}_{path.name}'
            shutil.copyfile(path, dest); entry['packaged_path'] = dest.relative_to(out).as_posix()
        row_fields = ['id','sensor_id','sample_index','cloud_id','point_index','source_scan_line','source_detector_column',
                      'source_patch_id','vertex_distance','maximum_vertex_distance','coordinate_unit','supporting_rgb_pairs',
                      'status','feature_description']
        with (out/'associations.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, row_fields, extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
        save_json(out/'associations.json', dict(warning=WARNING, frame_id=frame, coordinate_unit=unit, associations=rows))
        sensor_products = {}
        band_keys = {'source_band_zero_based','wavelength_nm','index_names'}
        for sensor, data in sensors.items():
            selected = [r for r in rows if r['sensor_id'] == sensor]
            if not selected:
                continue
            ids = np.array([r['sample_index'] for r in selected], dtype=int)
            result = {k: (v if k in band_keys else v[ids]) for k, v in data.items()}
            result.update(source_sample_index=ids, association_id=np.array([r['id'] for r in selected]),
                          cloud_id=np.array([r['cloud_id'] for r in selected]),
                          source_point_index=np.array([r['point_index'] for r in selected], dtype=np.int64),
                          xyz_reference=np.array([r['xyz_reference'] for r in selected]),
                          xyz_upright=np.array([r['xyz_upright'] for r in selected]), WARNING=np.array(WARNING))
            filename=f'assigned_spectra_{sensor}.npz'
            np.savez_compressed(out/filename, **result); sensor_products[sensor] = filename
        with (out/'assigned_points_reference.ply').open('w', encoding='ascii', newline='\n') as handle:
            handle.write(f'ply\nformat ascii 1.0\ncomment Sparse provisional associations; see associations.json\nelement vertex {len(rows)}\nproperty double x\nproperty double y\nproperty double z\nend_header\n')
            for row in rows:
                handle.write(' '.join(format(x,'.17g') for x in row['xyz_reference'])+'\n')
        summary = dict(schema_version=1, status='complete_sparse_provisional_correspondence_fusion', warning=WARNING,
                       title=config.get('title','Sparse measured spectral fusion'), associations=len(rows),
                       sensor_counts={s:sum(r['sensor_id']==s for r in rows) for s in sensors},
                       cloud_counts={c:sum(r['cloud_id']==c for r in rows) for c in records},
                       geometry_source_points=sum(r['source_count'] for r in records.values()),
                       unassigned_geometry_policy='No spectral values, no interpolation, no nearest-neighbour colour propagation.',
                       frame_id=frame, coordinate_unit=unit, upright_R=R.tolist(), absolute_metric_scale_verified=False,
                       physical_fusion=None, physical_registration_validated=False, surface_visibility_validated=False,
                       dense_surface_fusion=False, calibrated_reflectance=False, cross_sensor_spectrum_concatenation=False,
                       sensor_products=sensor_products, evidence=list(evidence.values()),
                       source_config=str(config_path), config_sha256=config_hash,
                       inputs=[dict(path=str(p),sha256=h) for p,h in inputs.items()],
                       software_sha256=sha(Path(__file__)))
        from .spectral_fusion_viewer import write_viewer
        write_viewer(out, records, rows, sensors, summary)
        save_json(out/'summary.json', summary)
        for path, expected in inputs.items():
            if sha(path) != expected:
                raise ValueError('Source changed during fusion build: '+str(path))
        save_json(out/'run_status.json', dict(status=summary['status'], complete=True, physical_fusion=None))
        progress(f'Saved {len(rows)} sparse provisional associations; no dense or physically validated fusion claimed.')
        return summary
    except Exception as exc:
        save_json(out/'run_status.json', dict(status='failed', complete=False, error=str(exc), physical_fusion=None))
        raise


def create_template(output):
    out = fresh_output(output)
    setup = dict(schema_version=1, title='Sparse measured spectral fusion', frame_id='REPLACE_shared_ICP_frame',
                 coordinate_unit='unknown', upright_R=np.eye(3).tolist(),
                 clouds=[dict(id='P1',label='Observed plant geometry',cloud='REPLACE_existing_cloud.ply',sha256='REPLACE_sha256')],
                 sensors=[dict(id='fx10',result_dir='REPLACE_measured_extraction_result',spectra_sha256='REPLACE_sha256')],
                 evidence=[dict(id='review',path='REPLACE_correspondence_evidence.json',sha256='REPLACE_sha256')],
                 associations=[])
    save_json(out/'spectral_fusion_template.json', setup)
    example = dict(id='feature_01',sensor_id='fx10',sample_index=0,cloud_id='P1',point_index=0,
                   status='provisional_reviewed_correspondence',reviewer='REPLACE',review_method='REPLACE actual cross-modal correspondence review',
                   feature_description='REPLACE exact persistent material feature',evidence_ids=['review'],
                   localized_reference_xyz=[0,0,0],maximum_vertex_distance=None,supporting_rgb_pairs=None)
    save_json(out/'association_format_example.json',example)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Sparse fusion setup</title>'
        '<h1>Sparse measured fusion setup</h1><p>'+html.escape(WARNING)+'</p>'
        '<p>Supply explicit reviewed source spectral pixels and exact existing cloud vertices in one shared frame. '
        'Do not populate this file with arbitrary leaf centres, planar warps, or guessed depth. '
        'The example is a format guide, not a measured observation. Record a justified vertex-distance bound in the same coordinate units.</p>'
        '<p><a href="spectral_fusion_template.json">Setup template</a> Â· '
        '<a href="association_format_example.json">Correspondence record format</a></p>',encoding='utf-8')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_subparsers(dest='mode',required=True)
    template=modes.add_parser('template');template.add_argument('--output',required=True)
    run=modes.add_parser('build');run.add_argument('--config',required=True);run.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    if args.mode=='template':create_template(args.output)
    else:build(args.config,args.output,progress=lambda text:print(text,flush=True))


if __name__=='__main__':
    main()

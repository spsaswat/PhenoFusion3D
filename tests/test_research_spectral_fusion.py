"""Sparse fusion preserves observed rows and cannot manufacture dense evidence."""
import hashlib
import json

import numpy as np
import pytest

from processing.research_workspace.spectral_fusion import build, create_template, load_spectra
from processing.research_workspace.workflow import sha


def _json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')


def _save_spectra(case):
    folder = case['spectral']
    np.savez_compressed(folder/'measured_spectra.npz', **case['arrays'])
    _json(folder/'summary.json', case['spectral_summary'])
    digest = sha(folder/'measured_spectra.npz')
    _json(folder/'measured_spectra.metadata.json', dict(sha256=digest))
    case['config']['sensors'][0]['spectra_sha256'] = digest
    _json(case['config_path'], case['config'])


@pytest.fixture
def case(tmp_path):
    source = tmp_path/'inputs'; source.mkdir()
    spectral = source/'measured'; spectral.mkdir()
    points = np.array([[0., 0., 0.], [1., 0., 2.], [0., 2., 3.], [.5, 2., 3.]])
    cloud = source/'observed.ply'
    cloud.write_text('ply\nformat ascii 1.0\nelement vertex 4\nproperty double x\n'
        'property double y\nproperty double z\nend_header\n' +
        '\n'.join(' '.join(map(str, row)) for row in points)+'\n', encoding='ascii')
    evidence = source/'review.json'
    _json(evidence, dict(note='Synthetic software test evidence, not physical measurements.'))
    raw = np.array([[100, 110, 120], [200, 210, 220], [300, 310, 320]], dtype=np.uint16)
    arrays = dict(raw_DN=raw, band_quality_flags=np.array([[0, 0, 0], [0, 2, 32], [0, 0, 0]], dtype=np.uint8),
        scan_line=np.array([1, 3, 4], dtype=np.int32), detector_column=np.array([2, 1, 3], dtype=np.int32),
        patch_id=np.array([1, 2, 2], dtype=np.uint16), source_band_zero_based=np.arange(3, dtype=np.int32),
        wavelength_nm=np.array([500., 680., 800.], dtype=np.float64),
        Q_assumed_or_confirmed_dark=np.array([[.1, .3, .6], [-.2, np.nan, 1.2], [.3, .4, .7]], dtype=np.float32),
        Q_zero_offset=np.array([[.2, .4, .5], [.1, np.nan, 1.1], [.4, .5, .8]], dtype=np.float32),
        indices_dark=np.array([[1/3], [np.nan], [.3/1.1]], dtype=np.float32),
        indices_zero=np.array([[.1/.9], [np.nan], [.3/1.3]], dtype=np.float32),
        index_flags_dark=np.array([[0], [1], [0]], dtype=np.uint8),
        index_flags_zero=np.array([[0], [1], [0]], dtype=np.uint8),
        index_names=np.array(['NDVI_800_680']))
    spectral_summary = dict(status='complete_measured_camera_space_extraction', sample_count=3, band_count=3,
        raw_source_shape_line_band_column=[5, 3, 4],
        source_sample_sha256_uint16_little_endian_sample_band=hashlib.sha256(raw.astype('<u2').tobytes()).hexdigest(),
        patches=[dict(patch_id=1, name='candidate leaf A'), dict(patch_id=2, name='candidate leaf B')],
        normalization=dict(dark_status='assumed_tail', white_identity='Unknown board'),
        index_specs_applied={'NDVI_800_680': dict(formula='(Q800-Q680)/(Q800+Q680)')})
    R = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    associations = [dict(id=f'synthetic_{i}', sensor_id='fx10', sample_index=sample, cloud_id='P1', point_index=point,
        status='provisional_reviewed_correspondence', reviewer='Software fixture', review_method='Synthetic pairing',
        feature_description='Synthetic fixture vertex', evidence_ids=['review'],
        localized_reference_xyz=points[point].tolist(), maximum_vertex_distance=.001, supporting_rgb_pairs=2)
        for i, (sample, point) in enumerate([(2, 3), (1, 1)])]
    config = dict(schema_version=1, title='Synthetic sparse fusion <not physical validation>', frame_id='fixture',
        coordinate_unit='conditional_m', upright_R=R.tolist(),
        clouds=[dict(id='P1', cloud='observed.ply', sha256=sha(cloud))],
        sensors=[dict(id='fx10', result_dir='measured', spectra_sha256='populated below')],
        evidence=[dict(id='review', path='review.json', sha256=sha(evidence))], associations=associations)
    result = dict(source=source, spectral=spectral, cloud=cloud, evidence=evidence, arrays=arrays,
        spectral_summary=spectral_summary, config=config, config_path=source/'fusion.json', points=points,
        R=R, output=tmp_path/'fusion')
    _save_spectra(result)
    return result


def _snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def test_end_to_end_fusion_preserves_exact_subset_without_filling_unassigned_geometry(case):
    original = _snapshot(case['source'])
    summary = build(case['config_path'], case['output'])
    assert _snapshot(case['source']) == original
    assert summary['associations'] == 2 and summary['geometry_source_points'] == 4
    assert summary['physical_fusion'] is None
    for key in ('absolute_metric_scale_verified', 'physical_registration_validated', 'surface_visibility_validated',
                'dense_surface_fusion', 'calibrated_reflectance', 'cross_sensor_spectrum_concatenation'):
        assert summary[key] is False
    ids = np.array([2, 1]); points = np.array([3, 1])
    band_keys = {'wavelength_nm', 'source_band_zero_based', 'index_names'}
    with np.load(case['output']/'assigned_spectra_fx10.npz', allow_pickle=False) as assigned:
        for key, original_array in case['arrays'].items():
            expected = original_array if key in band_keys else original_array[ids]
            assert assigned[key].dtype == expected.dtype
            np.testing.assert_array_equal(assigned[key], expected)
        np.testing.assert_array_equal(assigned['source_sample_index'], ids)
        np.testing.assert_array_equal(assigned['source_point_index'], points)
        np.testing.assert_array_equal(assigned['xyz_reference'], case['points'][points])
        np.testing.assert_array_equal(assigned['xyz_upright'], case['points'][points] @ case['R'].T)
        assert assigned['raw_DN'].shape == (2, 3)
    rows = json.loads((case['output']/'associations.json').read_text())['associations']
    assert [r['source_scan_line'] for r in rows] == [4, 3]
    assert [r['source_detector_column'] for r in rows] == [3, 1]
    assert all(r['physical_registration_validated'] is False for r in rows)
    assert (case['output']/'clouds/cloud_0.ply').read_bytes() == case['cloud'].read_bytes()
    assert (case['output']/'spectra/sensors/fx10/measured_spectra.npz').read_bytes() == original['measured/measured_spectra.npz']
    assert (case['output']/'index.html').is_file()
    assert (case['output']/'spectra/index.html').is_file()
    assert json.loads((case['output']/'run_status.json').read_text())['complete'] is True


@pytest.mark.parametrize('kind', ['identity', 'pixel', 'cloud_vertex'])
def test_repeated_correspondence_or_reused_source_row_rejected(case, kind):
    first, second = case['config']['associations']
    if kind == 'identity':second['id'] = first['id']
    elif kind == 'pixel':second['sample_index'] = first['sample_index']
    else:second['point_index'] = first['point_index']
    _json(case['config_path'], case['config'])
    with pytest.raises(ValueError, match='Duplicate|reuse'):
        build(case['config_path'], case['output'])
    assert not case['output'].exists()


@pytest.mark.parametrize('field', ['sample_index', 'point_index'])
@pytest.mark.parametrize('value', [True, -1, .5, '1', 10000])
def test_only_exact_in_range_original_indices_are_accepted(case, field, value):
    case['config']['associations'][0][field] = value
    _json(case['config_path'], case['config'])
    with pytest.raises(ValueError, match='exact original source row'):
        build(case['config_path'], case['output'])
    assert not case['output'].exists()


@pytest.mark.parametrize('field,value,message', [
    ('localized_reference_xyz', [20, 20, 20], 'too far'),
    ('maximum_vertex_distance', 0, 'positive explicit'),
    ('maximum_vertex_distance', True, 'positive explicit'),
    ('supporting_rgb_pairs', 1, 'at least two'),
    ('supporting_rgb_pairs', True, 'at least two'),
    ('supporting_rgb_pairs', 2.1, 'at least two'),
    ('status', 'physically_validated', 'provisional'),
    ('evidence_ids', [], 'fingerprinted'),
    ('reviewer', '', 'nonempty'),
])
def test_unsupported_or_overclaimed_correspondences_rejected(case, field, value, message):
    case['config']['associations'][0][field] = value
    _json(case['config_path'], case['config'])
    with pytest.raises(ValueError, match=message):build(case['config_path'], case['output'])
    assert not case['output'].exists()


@pytest.mark.parametrize('source', ['cloud', 'evidence', 'spectra'])
def test_sources_changed_since_review_are_rejected(case, source):
    path = case['spectral']/'measured_spectra.npz' if source == 'spectra' else case[source]
    with path.open('ab') as handle:handle.write(b'changed')
    before = _snapshot(case['source'])
    with pytest.raises(ValueError, match='changed|Changed'):
        build(case['config_path'], case['output'])
    assert _snapshot(case['source']) == before
    assert not case['output'].exists()


@pytest.mark.parametrize('issue', ['summary_counts', 'source_shape', 'metadata_hash', 'incomplete', 'raw_hash',
                                  'duplicate_source_pixel', 'wrong_band_order', 'partial_q', 'filled_invalid', 'indices_shape'])
def test_fusion_rejects_inconsistent_extraction_metadata_and_arrays_before_writing(case, issue):
    arrays, summary = case['arrays'], case['spectral_summary']
    if issue == 'summary_counts':summary['sample_count'] = 99
    elif issue == 'source_shape':summary['raw_source_shape_line_band_column'] = [2, 3, 4]
    elif issue == 'incomplete':summary['status'] = 'running'
    elif issue == 'raw_hash':summary['source_sample_sha256_uint16_little_endian_sample_band'] = 'bad'
    elif issue == 'duplicate_source_pixel':
        arrays['scan_line'][1] = arrays['scan_line'][0]
        arrays['detector_column'][1] = arrays['detector_column'][0]
    elif issue == 'wrong_band_order':arrays['source_band_zero_based'][:] = [2, 1, 0]
    elif issue == 'partial_q':arrays.pop('Q_zero_offset')
    elif issue == 'filled_invalid':arrays['Q_zero_offset'][1, 1] = 0
    elif issue == 'indices_shape':arrays['indices_dark'] = arrays['indices_dark'][:1]
    _save_spectra(case)
    if issue == 'metadata_hash':_json(case['spectral']/'measured_spectra.metadata.json', dict(sha256='bad'))
    with pytest.raises(ValueError):build(case['config_path'], case['output'])
    assert not case['output'].exists()


def test_unknown_npz_scalar_is_not_treated_as_a_measured_spectrum(case):
    case['arrays']['unexpected_scalar'] = np.array('not a sample field')
    _save_spectra(case)
    loaded = load_spectra(case['spectral'], case['config']['sensors'][0]['spectra_sha256'])
    assert 'unexpected_scalar' not in loaded
    np.testing.assert_array_equal(loaded['raw_DN'], case['arrays']['raw_DN'])


@pytest.mark.parametrize('source', ['spectra', 'metadata', 'summary'])
def test_measurements_changed_while_loading_cannot_rebase_the_reviewed_fingerprint(case, monkeypatch, source):
    from processing.research_workspace import spectral_fusion
    original_loader = spectral_fusion.load_spectra
    def change_after_loading(folder, expected):
        arrays = original_loader(folder, expected)
        if source == 'spectra':
            case['arrays']['raw_DN'][0, 0] += 1
            np.savez_compressed(folder/'measured_spectra.npz', **case['arrays'])
            _json(folder/'measured_spectra.metadata.json', dict(sha256=sha(folder/'measured_spectra.npz')))
            case['spectral_summary']['source_sample_sha256_uint16_little_endian_sample_band'] = hashlib.sha256(
                case['arrays']['raw_DN'].astype('<u2').tobytes()).hexdigest()
            _json(folder/'summary.json', case['spectral_summary'])
        elif source == 'metadata':
            _json(folder/'measured_spectra.metadata.json', dict(sha256=sha(folder/'measured_spectra.npz'), changed=True))
        else:
            case['spectral_summary']['patches'][0]['name'] = 'Changed after loading'
            _json(folder/'summary.json', case['spectral_summary'])
        return arrays
    monkeypatch.setattr(spectral_fusion, 'load_spectra', change_after_loading)
    with pytest.raises(ValueError, match='changed|Changed'):
        build(case['config_path'], case['output'])
    assert not case['output'].exists()


def test_no_correspondences_cannot_produce_fake_completed_fusion(case):
    case['config']['associations'] = []
    _json(case['config_path'], case['config'])
    with pytest.raises(ValueError, match='No reviewed correspondences'):
        build(case['config_path'], case['output'])
    assert not case['output'].exists()


def test_previous_outputs_and_input_directories_are_preserved(case):
    old = case['output']; old.mkdir(); (old/'keep.txt').write_text('Preserve completed work.')
    before = _snapshot(case['source'])
    for target in (old, case['spectral'], case['spectral']/'new', case['source']):
        with pytest.raises(ValueError):build(case['config_path'], target)
    assert (old/'keep.txt').read_text() == 'Preserve completed work.'
    assert _snapshot(case['source']) == before


def test_source_mutation_during_build_cannot_be_reported_complete(case):
    def changed(_):
        case['evidence'].write_text('Changed after loading input.', encoding='utf-8')
    with pytest.raises(ValueError, match='Source changed during fusion'):
        build(case['config_path'], case['output'], progress=changed)
    status = json.loads((case['output']/'run_status.json').read_text())
    assert status['complete'] is False and status['status'] == 'failed'
    assert status['physical_fusion'] is None


def test_template_contains_no_claimed_correspondences_or_calibration(tmp_path):
    output = tmp_path/'template'
    create_template(output)
    config = json.loads((output/'spectral_fusion_template.json').read_text())
    example = json.loads((output/'association_format_example.json').read_text())
    assert config['associations'] == [] and config['coordinate_unit'] == 'unknown'
    assert example['maximum_vertex_distance'] is None and example['supporting_rgb_pairs'] is None
    assert 'not a measured observation' in (output/'index.html').read_text(encoding='utf-8')
    before = _snapshot(output)
    with pytest.raises(ValueError):create_template(output)
    assert _snapshot(output) == before

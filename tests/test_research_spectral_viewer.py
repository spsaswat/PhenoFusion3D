import base64
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from processing.research_workspace.spectral_viewer import (
    SpectralReviewError, build_spectral_review, load_spectral_result, _payload,
)


def fixture_result(path, *, normalized=True, indices=True):
    path.mkdir()
    arrays = dict(raw_DN=np.array([[10, 20, 30], [40, 50, 60]], dtype=np.uint16),
        band_quality_flags=np.array([[0, 2, 32], [0, 0, 0]], dtype=np.uint8),
        scan_line=np.array([7, 9], dtype=np.int32),
        detector_column=np.array([3, 5], dtype=np.int32),
        patch_id=np.array([1, 2], dtype=np.uint16),
        source_band_zero_based=np.arange(3, dtype=np.int32),
        wavelength_nm=np.array([500., 680., 800.], dtype=np.float64))
    if normalized:
        arrays.update(Q_assumed_or_confirmed_dark=np.array([[-.25, np.nan, .7], [1.2, .4, .8]], dtype=np.float32),
                      Q_zero_offset=np.array([[.1, np.nan, .5], [1.1, .5, .7]], dtype=np.float32))
    else:
        arrays['band_quality_flags'][:] = 1
    if indices and normalized:
        arrays.update(indices_dark=np.array([[np.nan], [1 / 3]], dtype=np.float32),
            indices_zero=np.array([[np.nan], [1 / 6]], dtype=np.float32),
            index_flags_dark=np.array([[1], [0]], dtype=np.uint8),
            index_flags_zero=np.array([[1], [0]], dtype=np.uint8),
            index_names=np.array(['NDVI_800_680']))
    summary = dict(status='complete_measured_camera_space_extraction', sample_count=2,
        band_count=3, raw_source_shape_line_band_column=[11, 3, 7],
        patches=[dict(patch_id=1, name='red, leaf', region_id='R1'), dict(patch_id=2, name='green')],
        index_specs_applied={'NDVI_800_680': dict(formula='(Q800-Q680)/(Q800+Q680)')} if indices and normalized else {},
        source_sample_sha256_uint16_little_endian_sample_band=hashlib.sha256(arrays['raw_DN'].astype('<u2').tobytes()).hexdigest(),
        normalization=dict(dark_status='assumed_tail', white_identity='Unknown board') if normalized else None)
    save(path, arrays, summary)
    return arrays, summary


def save(path, arrays, summary):
    np.savez_compressed(path / 'measured_spectra.npz', **arrays)
    (path / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    (path / 'measured_spectra.metadata.json').write_text(json.dumps(dict(
        sha256=hashlib.sha256((path / 'measured_spectra.npz').read_bytes()).hexdigest())), encoding='utf-8')


def test_full_export_keeps_source_identity_floats_and_missing_values(tmp_path):
    source = tmp_path / 'input'
    arrays, _ = fixture_result(source)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    output = tmp_path / 'review'
    result = build_spectral_review({'fx10': source}, output)
    assert result['physical_fusion'] is None
    assert result['source_inputs_unchanged'] and not result['calibrated_reflectance']
    assert not result['cross_camera_concatenation']
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    copied = output / 'sensors/fx10/measured_spectra.npz'
    assert copied.read_bytes() == before['measured_spectra.npz']
    with gzip.open(output / 'sensors/fx10/sample_bands.csv.gz', 'rt', encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    for i, row in enumerate(rows):
        sample, band = divmod(i, 3)
        assert int(row['sample_id_zero_based']) == sample
        assert int(row['source_band_zero_based']) == band
        assert int(row['raw_DN']) == arrays['raw_DN'][sample, band]
        assert int(row['scan_line']) == arrays['scan_line'][sample]
        assert int(row['detector_column']) == arrays['detector_column'][sample]
        assert int(row['band_quality_flags']) == arrays['band_quality_flags'][sample, band]
    assert rows[0]['patch_name'] == 'red, leaf'
    assert float(rows[0]['Q_assumed_or_confirmed_dark']) == -.25
    assert rows[1]['Q_assumed_or_confirmed_dark'] == ''
    assert float(rows[3]['Q_assumed_or_confirmed_dark']) == float(arrays['Q_assumed_or_confirmed_dark'][1, 0])
    with gzip.open(output / 'sensors/fx10/sample_indices.csv.gz', 'rt', encoding='utf-8') as handle:
        indices = list(csv.DictReader(handle))
    assert indices[0]['value_Q'] == '' and indices[0]['flags_Q'] == '1'
    assert float(indices[1]['value_Q']) == float(arrays['indices_dark'][1, 0])
    for path, digest in json.loads((output / 'checksums.json').read_text()).items():
        assert hashlib.sha256((output / path).read_bytes()).hexdigest() == digest


def test_browser_payload_preserves_numeric_values_and_nan_gaps(tmp_path):
    source = tmp_path / 'input'
    original, _ = fixture_result(source)
    build_spectral_review({'fx10': source}, tmp_path / 'out', export_csv=False)
    script = (tmp_path / 'out/sensors/fx10/browser_data.js').read_text()
    data = json.loads(script[len('window.spectralDataReady('):-2])
    for name, payload in data['arrays'].items():
        restored = np.frombuffer(base64.b64decode(payload['base64']), dtype=payload['dtype']).reshape(payload['shape'])
        np.testing.assert_array_equal(restored, original[name])
    assert not (tmp_path / 'out/sensors/fx10/sample_bands.csv.gz').exists()
    text = (tmp_path / 'out/index.html').read_text()
    assert 'new URLSearchParams(location.search)' in text
    assert "params.get('sample')" in text and "params.get('sensor')" in text
    assert "if(!Number.isFinite(ys[b])){connected=false;continue}" in text
    assert 'https://' not in text and 'fetch(' not in text
    assert '3D plant identity' in text and 'calibrated reflectance' in text
    big = np.array([2 ** 53], dtype=np.uint64)
    with pytest.raises(SpectralReviewError, match='exact browser'):
        _payload(big)


def test_raw_only_separate_sensor_has_no_invented_q_or_indices(tmp_path):
    first = tmp_path / 'first'; second = tmp_path / 'second'
    fixture_result(first)
    original, summary = fixture_result(second, normalized=False)
    loaded, _ = load_spectral_result(second)
    assert 'Q_zero_offset' not in loaded and 'index_names' not in loaded
    result = build_spectral_review({'fx10': first, 'fx17': second}, tmp_path / 'out')
    assert result['sensors'][1]['descriptors'] == []
    assert result['sensors'][1]['sample_count'] == 2
    with gzip.open(tmp_path / 'out/sensors/fx17/sample_bands.csv.gz', 'rt') as handle:
        rows = list(csv.DictReader(handle))
    assert all(r['Q_assumed_or_confirmed_dark'] == '' and r['Q_zero_offset'] == '' for r in rows)
    assert not (tmp_path / 'out/sensors/fx17/sample_indices.csv.gz').exists()


def test_output_never_reuses_or_nests_source(tmp_path):
    source = tmp_path / 'input'
    fixture_result(source)
    for target in [source, source / 'review', tmp_path]:
        with pytest.raises(SpectralReviewError, match='fresh|outside'):
            build_spectral_review({'fx10': source}, target)
    existing = tmp_path / 'already'; existing.mkdir()
    sentinel = existing / 'keep.txt'; sentinel.write_text('preserve')
    with pytest.raises(SpectralReviewError, match='fresh'):
        build_spectral_review({'fx10': source}, existing)
    assert sentinel.read_text() == 'preserve'
    with pytest.raises(SpectralReviewError, match='Sensor IDs'):
        build_spectral_review({'../escape': source}, tmp_path / 'other')


@pytest.mark.parametrize('case', ['hash', 'raw_hash', 'counts', 'pixel', 'duplicate', 'band_order',
                                  'wavelength', 'flags', 'filled_q', 'partial_q', 'filled_index', 'partial_index'])
def test_corrupt_or_ambiguous_saved_measurements_rejected_before_writing(tmp_path, case):
    source = tmp_path / 'input'
    arrays, summary = fixture_result(source)
    if case == 'raw_hash': summary['source_sample_sha256_uint16_little_endian_sample_band'] = 'bad'
    elif case == 'counts': summary['band_count'] = 4
    elif case == 'pixel': arrays['scan_line'][0] = 1000
    elif case == 'duplicate':
        arrays['scan_line'][1] = arrays['scan_line'][0]
        arrays['detector_column'][1] = arrays['detector_column'][0]
    elif case == 'band_order': arrays['source_band_zero_based'][:] = [2, 1, 0]
    elif case == 'wavelength': arrays['wavelength_nm'][1] = np.nan
    elif case == 'flags': arrays['band_quality_flags'][0, 0] = 128
    elif case == 'filled_q': arrays['Q_assumed_or_confirmed_dark'][0, 1] = 0
    elif case == 'partial_q': arrays.pop('Q_zero_offset')
    elif case == 'filled_index': arrays['indices_dark'][0, 0] = 0
    elif case == 'partial_index': arrays.pop('index_flags_dark')
    save(source, arrays, summary)
    if case == 'hash':
        (source / 'measured_spectra.metadata.json').write_text('{"sha256":"bad"}')
    with pytest.raises(SpectralReviewError):
        build_spectral_review({'fx10': source}, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_source_mutation_during_build_is_not_reported_complete(tmp_path):
    source = tmp_path / 'input'
    fixture_result(source)
    def mutate(_):
        (source / 'summary.json').write_text('{}')
    with pytest.raises(SpectralReviewError, match='copied|changed'):
        build_spectral_review({'fx10': source}, tmp_path / 'out', progress=mutate)
    status = json.loads((tmp_path / 'out/run_status.json').read_text())
    assert status['status'] == 'failed' and not status['complete']

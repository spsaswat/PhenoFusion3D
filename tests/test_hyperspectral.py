"""Integration guards, provenance and packaging; not new-dataset validation."""
import hashlib
import json
from pathlib import Path

import pytest

from processing.hyperspectral.workflow import (LEGACY, check_inputs, fresh_output,
                                               profile, spectral_inputs, verify_files)
from processing.hyperspectral.reports import prepare_reports, validate_bundle


def test_preserved_source_matches_manifest():
    manifest=json.loads((LEGACY/'SOURCE_MANIFEST.json').read_text())
    assert len(manifest['files'])==33
    for record in manifest['files']:
        content=(LEGACY/record['destination']).read_bytes()
        assert len(content)==record['bytes']
        assert hashlib.sha256(content).hexdigest()==record['sha256']


def test_profile_records_original_dataset_inputs_not_just_folder_name():
    recipe=profile()
    assert recipe['stride']==4 and recipe['depth_scale']==10000
    assert len(recipe['inputs']['hsi'])==4
    assert 'rgb/330.png' in recipe['inputs']['rgbd']
    assert 'merge_simple_full_step10/diagnostics/scene_preview_sampled.ply' in recipe['inputs']['rgbd']


def test_changed_input_rejected_even_if_name_and_size_match(tmp_path):
    file=tmp_path/'001-specim-fx10.hdr';file.write_bytes(b'abcd')
    record={file.name:dict(bytes=4,sha256=hashlib.sha256(b'abcd').hexdigest())}
    assert verify_files(tmp_path,record)==record
    file.write_bytes(b'wxyz')
    with pytest.raises(ValueError,match='differs from the reviewed'):verify_files(tmp_path,record)


def test_unrecognized_recording_cannot_silently_use_historical_rois(tmp_path):
    with pytest.raises(ValueError,match='Required historical input'):check_inputs('spectral',hsi=tmp_path)


def test_missing_fusion_prerequisites_explained():
    with pytest.raises(ValueError,match='completed historical spectral'):check_inputs('fusion')


def test_output_preserves_recordings_and_previous_runs(tmp_path):
    source=tmp_path/'recording';source.mkdir()
    for output in (source,source/'results',tmp_path):
        with pytest.raises(ValueError):fresh_output(output,[source])
    output=tmp_path/'new';fresh_output(output,[source]);(output/'precious.txt').write_text('retain')
    with pytest.raises(ValueError,match='not empty'):fresh_output(output,[source])
    assert (output/'precious.txt').read_text()=='retain'


def test_partial_spectral_manifest_rejected(tmp_path):
    (tmp_path/'integration_manifest.json').write_text(json.dumps(dict(profile='20260828',hsi_inputs=profile()['inputs']['hsi'],spectral_files={'missing':{}})))
    with pytest.raises(ValueError,match='incomplete'):spectral_inputs(tmp_path)


def test_report_is_portable_labelled_and_does_not_claim_unrun_fusion(tmp_path):
    (tmp_path/'index.html').write_text('''<html><body><a href="../../../old/merge_pcd_cam0.ply">Full PLY</a>
<section id="fusion-roadmap"><p>Historical fusion completed</p></section>
<script src="fusion/viewer_models.js"></script><script src="fusion/viewer.js"></script></body></html>''')
    prepare_reports(tmp_path,'spectral')
    source=(tmp_path/'index.html').read_text()
    assert 'EXPERIMENTAL' in source and 'not validated on new datasets' in source
    assert 'Historical fusion completed' not in source
    assert '<script' not in source
    assert 'href="full_resolution_note.html"' in source
    result=validate_bundle(tmp_path)
    assert result['html_pages']==2


def test_escaping_report_link_is_rejected_even_if_target_exists(tmp_path):
    root=tmp_path/'bundle';root.mkdir()
    (tmp_path/'outside.txt').write_text('outside')
    (root/'index.html').write_text('<a href="../outside.txt">Outside</a>')
    with pytest.raises(ValueError,match='outside the output'):validate_bundle(root)


def test_incomplete_interactive_assets_fail_link_validation(tmp_path):
    (tmp_path/'index.html').write_text('<script src="fusion/viewer.js"></script>')
    with pytest.raises(AssertionError,match='Missing report references'):validate_bundle(tmp_path)

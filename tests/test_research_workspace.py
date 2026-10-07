"""Research output must not turn cloud crops or missing evidence into truth."""
import json
from pathlib import Path
import numpy as np
import pytest

from processing.research_workspace.workflow import (
    TRAITS, build, create_template, descriptors, fresh_output, measure_annotations, rotation,
)


def record(name='P1',context=False):
    return dict(id=name,label=name,sha256='abc',points=np.array([[0.,0.,4.],[0.,0.,4.5],[.1,.2,4.2]]),
        source_count=3,context=context)


def annotation(**extra):
    item=dict(specimen_id='P1',trait='height',definition=TRAITS['height'],
        points=[dict(cloud_id='P1',source_sha256='abc',point_index=i) for i in [0,1]],
        landmarks_reviewed=False,organ_match_confirmed=False,reference_id=None)
    item.update(extra)
    return dict(schema_version=1,measurements=[item])


def test_observed_crop_span_does_not_become_height():
    result=descriptors(record(),'conditional_m')
    assert result['observed_extent_xyz'][2]==.5
    assert result['anatomical_height'] is None
    assert result['whole_leaf_area'] is None


def test_empty_reference_set_has_no_error_score():
    rows,scores=measure_annotations(annotation(),{'P1':record()},{'P1'},'conditional_m')
    assert rows[0]['value']==.5
    assert not rows[0]['physical_accuracy_validated']
    assert scores['height']==dict(n=0,mean_signed_error=None,mae=None,rmse=None,status='no_eligible_pairs',physical_accuracy_validated=False)


def test_matching_definition_and_reference_are_required():
    ref=dict(id='h1',specimen_id='P1',definition='height_from_pot_bottom',unit='m',value=.6,evidence_status='operator_reported',source='original note')
    data=annotation(landmarks_reviewed=True,organ_match_confirmed=True,reference_id='h1')
    rows,scores=measure_annotations(data,{'P1':record()},{'P1'},'conditional_m',[ref])
    assert rows[0]['comparison_status']=='incompatible_measurement_definition'
    assert scores['height']['n']==0
    ref['definition']=TRAITS['height']
    rows,scores=measure_annotations(data,{'P1':record()},{'P1'},'conditional_m',[ref])
    assert scores['height']['n']==1
    assert scores['height']['mae']==pytest.approx(.1)
    assert not scores['height']['physical_accuracy_validated']


@pytest.mark.parametrize('mutation', ['stale_hash','float_index','negative_height','duplicate_endpoint'])
def test_invalid_source_endpoints_fail(mutation):
    data=annotation();marks=data['measurements'][0]['points']
    if mutation=='stale_hash':marks[0]['source_sha256']='changed'
    elif mutation=='float_index':marks[0]['point_index']=0.5
    elif mutation=='negative_height':marks.reverse()
    else:marks[1]=dict(marks[0])
    with pytest.raises(ValueError):measure_annotations(data,{'P1':record()},{'P1'},'conditional_m')


def test_context_cloud_can_supply_actual_base():
    data=annotation();data['measurements'][0]['points'][0]['cloud_id']='original_scene'
    rows,_=measure_annotations(data,{'P1':record(),'original_scene':record('original_scene',True)},{'P1'},'conditional_m')
    assert rows[0]['value']==.5


def test_partial_observed_distance_cannot_become_validation_score():
    data=annotation(trait='observed_chord',definition=TRAITS['observed_chord'],
        landmarks_reviewed=True,organ_match_confirmed=True,reference_id='partial')
    ref=dict(id='partial',specimen_id='P1',definition=TRAITS['observed_chord'],
        unit='m',value=.5,evidence_status='independent_measured',source='ruler')
    rows,scores=measure_annotations(data,{'P1':record()},{'P1'},'conditional_m',[ref])
    assert rows[0]['value']==.5
    assert rows[0]['comparison_status']=='observed_extent_is_not_a_validation_trait'
    assert scores['observed_chord']['n']==0 and scores['observed_chord']['mae'] is None


def test_no_rescaling_or_reflection_hidden_in_upright_rotation():
    for R in [np.eye(3)*2,np.diag([1,1,-1]),np.full((3,3),np.nan)]:
        with pytest.raises(ValueError):rotation(R)


def test_fresh_results_and_input_protection(tmp_path):
    protected=tmp_path/'recording';protected.mkdir()
    with pytest.raises(ValueError):fresh_output(protected/'results',protected_roots=[protected])
    existing=tmp_path/'completed';existing.mkdir();(existing/'keep.txt').write_text('preserve')
    with pytest.raises(ValueError):fresh_output(existing)
    assert (existing/'keep.txt').read_text()=='preserve'


def test_end_to_end_workspace_preserves_source_and_exports_offline_picker(tmp_path):
    source=tmp_path/'plant.ply'
    source.write_text('ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 4\n0 0 4.5\n.1 .2 4.2\n')
    before=source.read_bytes()
    manifest=tmp_path/'setup.json'
    manifest.write_text(json.dumps(dict(schema_version=1,title='<Research>',coordinate_unit='conditional_m',
        scale_status='unverified',specimens=[dict(id='P1',cloud='plant.ply')],
        gaps=[dict(id='scale',title='Board size unknown',status='unresolved')],artifacts=[])))
    out=tmp_path/'result-run';summary=build(manifest,out)
    assert source.read_bytes()==before
    assert not summary['physical_accuracy_validated']
    assert not summary['calibrated_3d_spectral_fusion_achieved']
    assert summary['error_summaries']['height']['mae'] is None
    assert (out/'result/research_cloud_0.js').exists()
    page=(out/'result/point_review.html').read_text(encoding='utf-8')
    assert 'source_indices' in page and 'point_index' in page
    assert '__PHOTO__' not in page and 'source\').onclick' not in page
    assert '&lt;Research&gt;' in (out/'result/index.html').read_text(encoding='utf-8')
    assert json.loads((out/'run_status.json').read_text())['status']=='complete_candidate_workspace'
    # A copied snapshot must retain the original input base, not accidentally
    # resolve plant.ply relative to the new report directory.
    replay=build(out/'workspace_manifest_snapshot.json',tmp_path/'replay-run')
    assert replay['source_clouds'][0]['sha256']==summary['source_clouds'][0]['sha256']
    assert replay['observed_descriptors']==summary['observed_descriptors']
    with pytest.raises(ValueError):build(manifest,out)


def test_template_has_no_invented_specimens_or_calibration(tmp_path):
    create_template(tmp_path/'setup')
    data=json.loads((tmp_path/'setup/workspace_template.json').read_text())
    assert data['specimens']==[] and data['scale_status']=='unverified'
    assert (tmp_path/'setup/result/index.html').is_file()

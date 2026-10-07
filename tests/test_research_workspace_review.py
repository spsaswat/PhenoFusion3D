"""Independent evidence-boundary regressions for research workspaces."""
import base64
from html.parser import HTMLParser
import json

import numpy as np
import pytest

from processing.research_workspace import workflow


def _record(identity, context=False):
    return dict(id=identity,sha256=identity*32,source_count=2,
                points=np.array([[0.,0.,0.],[0.,0.,.5]]),context=context)


def _annotation(cloud, reviewed=True):
    return dict(schema_version=1,measurements=[dict(
        specimen_id='P1',trait='height',definition=workflow.TRAITS['height'],
        landmarks_reviewed=reviewed,organ_match_confirmed=True,reference_id='physical_P1',
        points=[dict(cloud_id=cloud['id'],source_sha256=cloud['sha256'],point_index=i)
                for i in (0,1)])])


def _reference():
    return dict(id='physical_P1',specimen_id='P1',definition=workflow.TRAITS['height'],
                unit='m',value=.5,evidence_status='operator_reported',source='recorded measurement')


def test_unrelated_specimen_endpoints_cannot_validate_selected_specimen():
    p1,p2=_record('P1'),_record('P2')
    with pytest.raises(ValueError,match='specimen|cloud'):
        workflow.measure_annotations(_annotation(p2),{'P1':p1,'P2':p2},{'P1','P2'},'conditional_m',[_reference()])


def test_context_cloud_is_available_for_explicit_omitted_base_review():
    p1,scene=_record('P1'),_record('scene',context=True)
    rows,metrics=workflow.measure_annotations(_annotation(scene),{'P1':p1,'scene':scene},{'P1'},'conditional_m',[_reference()])
    assert rows[0]['source_points'][0]['cloud_id']=='scene'
    assert rows[0]['value']==pytest.approx(.5)
    assert rows[0]['comparison_status']=='provisional_matched_comparison'
    assert rows[0]['physical_accuracy_validated'] is False
    assert metrics['height']['physical_accuracy_validated'] is False


def test_unreviewed_endpoints_keep_all_empty_accuracy_scores_null():
    p1=_record('P1')
    rows,metrics=workflow.measure_annotations(_annotation(p1,reviewed=False),{'P1':p1},{'P1'},'conditional_m',[_reference()])
    assert rows[0]['comparison_status']=='endpoints_not_reviewed'
    assert rows[0]['signed_difference'] is None
    for result in metrics.values():
        assert result['n']==0
        assert result['mae'] is None and result['rmse'] is None and result['mean_signed_error'] is None
        assert result['physical_accuracy_validated'] is False


def test_changed_cloud_during_load_cannot_produce_inconsistent_provenance(tmp_path_factory,monkeypatch):
    import open3d as o3d
    # Open3D's Windows file reader still rejects some paths beyond MAX_PATH.
    tmp_path=tmp_path_factory.mktemp('cloud')
    cloud=tmp_path/'plant.ply'
    cloud.write_text('ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n1 0 0\n0 0 1\n')
    manifest=tmp_path/'setup.json'
    manifest.write_text(json.dumps(dict(schema_version=1,coordinate_unit='conditional_m',specimens=[dict(id='P1',cloud=str(cloud))])))
    original=o3d.io.read_point_cloud
    def read_then_change(path):
        result=original(path)
        with cloud.open('a') as stream:stream.write('\n')
        return result
    monkeypatch.setattr(o3d.io,'read_point_cloud',read_then_change)
    # The guard must be independent of optional HTML/viewer rendering.
    monkeypatch.setattr(workflow,'report',lambda *args:None)
    with pytest.raises(ValueError,match='changed|provenance'):
        workflow.build(manifest,tmp_path/'new_run')


def test_manifest_changed_after_parse_cannot_receive_new_hash_for_old_settings(tmp_path,monkeypatch):
    cloud=tmp_path/'plant.ply';cloud.write_bytes(b'original cloud content')
    manifest=tmp_path/'setup.json'
    setup=dict(schema_version=1,title='Original reviewed settings',coordinate_unit='conditional_m',
               specimens=[dict(id='P1',cloud=str(cloud))])
    manifest.write_text(json.dumps(setup))
    record=_record('P1')
    record.update(label='P1',path=cloud,sha256=workflow.sha(cloud),colours=np.full((2,3),.5))
    def load_and_change_setup(*args,**kwargs):
        setup['title']='Changed after the workspace already parsed its configuration'
        manifest.write_text(json.dumps(setup))
        return record
    monkeypatch.setattr(workflow,'cloud_record',load_and_change_setup)
    monkeypatch.setattr(workflow,'report',lambda *args:None)
    with pytest.raises(ValueError,match='changed|provenance|manifest'):
        workflow.build(manifest,tmp_path/'new_run')


def test_sampled_viewer_keeps_original_indices_and_local_script_assets(tmp_path):
    from processing.research_workspace.viewer import write_viewer
    count=600001
    points=np.column_stack([np.arange(count,dtype=float)/1000000,np.zeros(count),np.linspace(0,.5,count)])
    source=tmp_path/'source.ply'
    record=dict(id='P1',label='Plant <one>',context=False,sha256='a'*64,
                path=source,points=points,colours=np.full(points.shape,.5),source_count=count)
    write_viewer(tmp_path,{'P1':record},['P1'],{'coordinate_unit':'conditional_m'})
    javascript=(tmp_path/'research_cloud_0.js').read_text(encoding='utf-8')
    payload=json.loads(javascript[len('DATA.push('):-3])
    indices=np.frombuffer(base64.b64decode(payload['source_indices']),dtype='<u4')
    preview=np.frombuffer(base64.b64decode(payload['xyz']),dtype='<f4').reshape(-1,3)
    assert payload['display_stride']==2 and payload['original_count']==count
    np.testing.assert_array_equal(indices,np.arange(0,count,2))
    recovered=preview.astype(float)*payload['scale']+payload['centre']
    np.testing.assert_allclose(recovered,points[indices],atol=1e-7)
    assert payload['sha256']==record['sha256']
    class Sources(HTMLParser):
        def __init__(self):super().__init__();self.sources=[]
        def handle_starttag(self,tag,attrs):
            if tag=='script':
                values=dict(attrs)
                if values.get('src'):self.sources.append(values['src'])
    parser=Sources();page=(tmp_path/'point_review.html').read_text(encoding='utf-8');parser.feed(page)
    assert parser.sources==['research_cloud_0.js']
    assert all((tmp_path/p).is_file() for p in parser.sources)
    assert 'Plant &lt;one&gt;' in page and '__PHOTO__' not in page
    assert not any('://' in p for p in parser.sources)

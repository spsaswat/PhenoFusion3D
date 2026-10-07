import json
from pathlib import Path

import numpy as np
import pytest

from processing.research_workspace.spectral_extract import (
    ExtractionError, extract_reviewed_spectra, read_envi_source,
)


WL=[444.89,471.26,500.37,532.25,550.91,569.61,661.10,677.36,680.07,720.87,750.93,789.33,800.34]


def setup(tmp_path, *, byte_order=0, normalization=True):
    recording=tmp_path/'recording';recording.mkdir()
    cube=np.full((6,len(WL),7),500,np.uint16)
    cube[:2]=1000;cube[4:]=200
    cube[2,12,2]=65520;cube[2,0,3]=100;cube[2,1,4]=1600
    cube[:2,2,5]=65520;cube[:2,3,4]=205
    cube[3,3,3]=0
    hdr=recording/'cube.hdr';bil=recording/'cube.bil'
    hdr.write_text('ENVI\n'+f'lines = 6\nbands = {len(WL)}\nsamples = 7\ninterleave = bil\ndata type = 12\nbyte order = {byte_order}\nheader offset = 32\nwavelength units = Nanometers\nwavelength = {{'+','.join(map(str,WL))+'}\n')
    with bil.open('wb') as f:f.write(b'X'*32);cube.astype('<u2' if byte_order==0 else '>u2').tofile(f)
    mask=np.zeros((6,7),np.uint16);mask[2]=1;mask[3]=2
    np.save(tmp_path/'mask.npy',mask)
    config=dict(schema_version=1,header='recording/cube.hdr',data='recording/cube.bil',suspected_clipping_dn=65520,sampling=dict(line_step=1,column_step=1),selection=dict(review_status='operator_reviewed',provenance='Synthetic test regions, not physical evidence',label_mask_npy='mask.npy',label_names={'1':'a','2':'b'}),normalization=dict(white_roi=[0,2,1,6],dark_roi=[4,6,0,7],white_identity='Synthetic board',settings_assumption='Synthetic fixed exposure',dark_status='assumed_tail',dark_provenance='Synthetic candidate dark') if normalization else None,indices=['NDVI_800_680','SIPI_800_445_680'] if normalization else [],max_band_error_nm=3)
    path=tmp_path/'config.json';path.write_text(json.dumps(config))
    return path,cube,config


def test_offset_endianness_and_full_source_band_identity(tmp_path):
    path,cube,_=setup(tmp_path,byte_order=1)
    source=read_envi_source(tmp_path/'recording/cube.hdr')
    np.testing.assert_array_equal(source.read_lines(2,4,np.arange(len(WL))),cube[2:4])
    result=extract_reviewed_spectra(path,tmp_path/'out')
    assert result['source_fingerprints_stable_before_after']
    with np.load(tmp_path/'out/result/measured_spectra.npz') as data:
        np.testing.assert_array_equal(data['raw_DN'],cube[data['scan_line'],:,data['detector_column']])
        np.testing.assert_array_equal(data['source_band_zero_based'],np.arange(len(WL)))
    snapshot=json.loads((tmp_path/'out/result/input_config.json').read_text())
    assert Path(snapshot['header']).is_absolute()
    assert Path(snapshot['selection']['label_mask_npy']).is_absolute()


def test_masks_negative_above_one_clipping_weak_reference_and_indices(tmp_path):
    path,cube,_=setup(tmp_path)
    extract_reviewed_spectra(path,tmp_path/'out')
    with np.load(tmp_path/'out/result/measured_spectra.npz') as data:
        flags=data['band_quality_flags'];q=data['Q_assumed_or_confirmed_dark']
        def index(y,x):return int(np.flatnonzero((data['scan_line']==y)&(data['detector_column']==x))[0])
        assert np.isnan(q[index(2,0)]).all()
        assert flags[index(2,2),12]&2 and np.isnan(q[index(2,2),12])
        assert flags[index(2,5),2]&4 and np.isnan(q[index(2,5),2])
        assert flags[index(2,4),3]&8 and np.isnan(q[index(2,4),3])
        assert flags[index(3,3),3]&16
        assert q[index(2,3),0]<0 and flags[index(2,3),0]&32
        assert q[index(2,4),1]>1
        assert np.isnan(data['indices_dark'][index(2,2),0])
        assert np.isnan(data['indices_dark'][index(2,3),1])
        assert np.isnan(data['indices_dark'][data['index_flags_dark']!=0]).all()
        assert np.array_equal(np.isnan(q),np.isnan(data['Q_zero_offset']))


def test_raw_only_retains_samples_without_inventing_references(tmp_path):
    path,_,_=setup(tmp_path,normalization=False)
    result=extract_reviewed_spectra(path,tmp_path/'out')
    assert not result['normalization_produced'] and result['physical_fusion'] is None
    with np.load(tmp_path/'out/result/measured_spectra.npz') as data:
        assert 'Q_zero_offset' not in data and np.all(data['band_quality_flags']&1)
    with pytest.raises(ExtractionError,match='fresh'):extract_reviewed_spectra(path,tmp_path/'out')


@pytest.mark.parametrize('old,new',[('interleave = bil','interleave = bsq'),('data type = 12','data type = 4'),('wavelength units = Nanometers','wavelength units = Micrometers'),('header offset = 32','header offset = 31')])
def test_unsupported_or_inconsistent_storage_rejected(tmp_path,old,new):
    setup(tmp_path)
    header=tmp_path/'recording/cube.hdr';header.write_text(header.read_text().replace(old,new))
    with pytest.raises(ExtractionError):read_envi_source(header)


def test_unavailable_wavelengths_omit_indices(tmp_path):
    path,_,config=setup(tmp_path)
    config['max_band_error_nm']=.001;path.write_text(json.dumps(config))
    summary=extract_reviewed_spectra(path,tmp_path/'out')
    assert not summary['index_specs_applied'] and len(summary['indices_unavailable'])==2
    with np.load(tmp_path/'out/result/measured_spectra.npz') as data:assert 'indices_dark' not in data


def test_ambiguous_header_and_same_band_descriptor_rejected(tmp_path):
    path,_,config=setup(tmp_path)
    header=tmp_path/'recording/cube.hdr';text=header.read_text();header.write_text(text+'byte order = 1\n')
    with pytest.raises(ExtractionError,match='Duplicate'):read_envi_source(header)
    header.write_text(text.replace(','.join(map(str,WL)),','.join(str(680+i*.01) for i in range(len(WL)))))
    config['max_band_error_nm']=200;config['indices']=['PRI_531_570'];path.write_text(json.dumps(config))
    summary=extract_reviewed_spectra(path,tmp_path/'out')
    assert 'same recorded band' in summary['indices_unavailable']['PRI_531_570']


def test_changed_config_detected_and_run_not_complete(tmp_path):
    path,_,_=setup(tmp_path)
    changed=False
    def mutate(message):
        nonlocal changed
        if not changed:path.write_text(path.read_text()+' ');changed=True
    with pytest.raises(ExtractionError,match='changed'):extract_reviewed_spectra(path,tmp_path/'out',progress=mutate)
    assert json.loads((tmp_path/'out/run_status.json').read_text())['complete'] is False


def test_full_line_allocation_budget_and_zero_sample_patch(tmp_path,monkeypatch):
    path,_,config=setup(tmp_path)
    source=read_envi_source(tmp_path/'recording/cube.hdr')
    monkeypatch.setattr('processing.research_workspace.spectral_extract.MAX_REFERENCE_VALUES',100)
    with pytest.raises(ExtractionError,match='bounded'):source.read_lines(0,2,np.arange(len(WL)))
    monkeypatch.setattr('processing.research_workspace.spectral_extract.MAX_REFERENCE_VALUES',4_000_000)
    config['sampling']['line_step']=2;path.write_text(json.dumps(config))
    summary=extract_reviewed_spectra(path,tmp_path/'out')
    patch=next(p for p in summary['patches'] if p['patch_id']==2)
    assert patch['sample_pixels']==0 and patch['sampling_status']=='no_pixels_on_requested_sampling_grid'


def test_reviewed_polygon_path_and_overlap_rejection(tmp_path):
    path,_,config=setup(tmp_path)
    config['selection'].pop('label_mask_npy')
    patch=dict(patch_id=1,name='reviewed scene',column_line=[[1,2],[5,2],[5,3],[1,3]])
    config['selection']['polygons']=[patch];path.write_text(json.dumps(config))
    summary=extract_reviewed_spectra(path,tmp_path/'out')
    assert summary['sample_count']==10
    config['selection']['polygons'].append(dict(patch,patch_id=2));path.write_text(json.dumps(config))
    with pytest.raises(ExtractionError,match='overlap'):extract_reviewed_spectra(path,tmp_path/'different')


def test_current_recording_subset_matches_reviewed_saved_spectra(tmp_path):
    root=Path(__file__).resolve().parents[1]
    source=root/'data/main/test_plant_10-7/20260928/003-specim-fx10.bil'
    expected=root/'generated/research_followthrough_20261007/spectral/fx10_measured_full_spectra.npz'
    if not source.is_file() or not expected.is_file():
        pytest.skip('Real recording and reviewed generated spectra are optional local parity fixtures, not packaged data.')
    config=json.loads((root/'docs/examples/research_spectral_20260928_fx10.json').read_text())
    config['header']=str(source.with_suffix('.hdr'));config['data']=str(source)
    config['selection']['polygons']=[p for p in config['selection']['polygons'] if p['patch_id']==2]
    path=tmp_path/'real_config.json';path.write_text(json.dumps(config))
    summary=extract_reviewed_spectra(path,tmp_path/'out')
    assert summary['sample_count']==106
    with np.load(expected) as old,np.load(tmp_path/'out/result/measured_spectra.npz') as new:
        use=old['patch_id']==2
        for a,b in [('raw_DN','raw_DN'),('band_quality_flags','band_quality_flags'),('Q_assumed_or_confirmed_dark','Q_assumed_tail'),('Q_zero_offset','Q_zero_offset'),('scan_line','scan_line'),('detector_column','detector_column')]:
            np.testing.assert_allclose(new[a],old[b][use],rtol=0,atol=0,equal_nan=True)
        with np.load(expected.parent/'fx10_patch_indices.npz') as previous:
            selected=previous['patch_id']==2
            np.testing.assert_allclose(new['indices_dark'],previous['indices_assumed_tail'][selected],rtol=0,atol=0,equal_nan=True)
            np.testing.assert_allclose(new['indices_zero'],previous['indices_zero_offset'][selected],rtol=0,atol=0,equal_nan=True)

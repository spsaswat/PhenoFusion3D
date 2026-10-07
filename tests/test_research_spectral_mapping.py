import numpy as np
import pytest

from processing.research_workspace.spectral_mapping import (
    CalibrationError, PixelThresholds, fit_pushbroom_controls, mapping_readiness,
    project_control_model, project_physical_pushbroom,
)


def observe(x):
    return np.column_stack([400+200*x[:,0]/(3-x[:,2]),300+120*x[:,1]+15*x[:,2]])


def controls():
    rng=np.random.default_rng(9307)
    train=rng.uniform([-1,-1,0],[1,1,1],(80,3))
    hold=rng.uniform([-.7,-.7,.2],[.7,.7,.8],(25,3))
    return train,hold


def fit(train=None,hold=None,**overrides):
    a,b=controls();train=a if train is None else train;hold=b if hold is None else hold
    kw=dict(training_ids=[f'train_{i}' for i in range(len(train))],validation_ids=[f'hold_{i}' for i in range(len(hold))],frame_id='rig',length_unit='shared_board_square',image_shape=(1000,1000),thresholds=PixelThresholds(.01,.02,.03),height_axis=[0,0,1],reference_plane_offset=0,min_off_plane_distance=.1)
    kw.update(overrides)
    return fit_pushbroom_controls(train,observe(train),hold,observe(hold),**kw)


def test_nonplanar_fit_and_unseen_projection_in_shared_arbitrary_units():
    model=fit()
    assert model['held_out_error_px']['maximum']<1e-9
    assert model['absolute_metric_scale_verified'] is False
    p=np.array([[0,0,.5],[.2,.1,.4]])
    result=project_control_model(p,model,frame_id='rig',length_unit='shared_board_square')
    np.testing.assert_allclose(result['column_line'],observe(p),atol=1e-9)
    assert result['projection_valid'].all()
    assert not result['surface_mapping_eligible'].any()
    assert result['physical_fusion'] is None


def test_planar_and_nearly_planar_controls_are_rejected():
    train,hold=controls();train[:,2]=0
    with pytest.raises(CalibrationError,match='coplanar'):fit(train,hold)
    train[:,2]=np.linspace(0,1e-10,len(train))
    with pytest.raises(CalibrationError,match='coplanar'):fit(train,hold)


def test_holdout_must_be_independent_and_off_plane():
    train,hold=controls()
    with pytest.raises(CalibrationError,match='repeated IDs'):fit(validation_ids=[f'train_{i}' for i in range(len(hold))])
    hold[0]=train[0]
    with pytest.raises(CalibrationError,match='recycles'):fit(train,hold)
    hold[:,2]=0
    with pytest.raises(CalibrationError,match='off-plane'):fit(train,hold)


def test_boolean_is_not_numeric_validation():
    with pytest.raises(CalibrationError):PixelThresholds(True,1,1)
    with pytest.raises(CalibrationError):fit(thresholds=True)
    with pytest.raises(CalibrationError):fit(min_off_plane_distance=True)


def test_duplicate_holdout_points_cannot_masquerade_as_independent_controls():
    train, hold = controls()
    hold[:] = hold[0]
    with pytest.raises(CalibrationError, match='duplicate'):fit(train, hold)


def test_malformed_serialized_model_cannot_disable_support_volume():
    model = fit()
    model['training_hull_equations'] = []
    with pytest.raises(CalibrationError, match='training_hull'):project_control_model([[0,0,.5]],model,frame_id='rig',length_unit='shared_board_square')
    model = fit()
    model['xyz_scale'] = -1
    with pytest.raises(CalibrationError, match='xyz_scale'):project_control_model([[0,0,.5]],model,frame_id='rig',length_unit='shared_board_square')


def test_bad_holdout_cannot_be_used_to_refit_model():
    train,hold=controls()
    with pytest.raises(CalibrationError,match='exceed'):
        fit_pushbroom_controls(train,observe(train),hold,observe(hold)+np.array([4,0]),training_ids=[f't{i}' for i in range(len(train))],validation_ids=[f'v{i}' for i in range(len(hold))],frame_id='rig',length_unit='m',image_shape=(1000,1000),thresholds=PixelThresholds(1,1,1),height_axis=[0,0,1],reference_plane_offset=0,min_off_plane_distance=.1)


def test_volume_frame_and_detector_guards():
    model=fit()
    result=project_control_model([[8,0,.5],[0,0,4]],model,frame_id='rig',length_unit='shared_board_square')
    assert not result['projection_valid'].any()
    assert np.isnan(result['column_line']).all()
    assert not result['positive_projective_depth'][1]
    with pytest.raises(CalibrationError,match='frame'):project_control_model([[0,0,.5]],model,frame_id='other',length_unit='m')


def test_physical_projection_rejects_negative_depth_and_unknown_visibility():
    model=dict(frame_id='rig',length_unit='m',image_shape=(1000,1000),world_to_camera_rotation=np.eye(3),camera_centre_line0=[0,0,0],motion_per_line=[0,.01,0],focal_length_pixels=400,principal_column=500)
    r=project_physical_pushbroom([[.1,1,1],[0,1,-1],[4,1,1]],frame_id='rig',length_unit='m',model=model)
    np.testing.assert_allclose(r['column_line'][0],[540,100])
    assert r['projection_valid'].tolist()==[True,False,False]
    assert not r['surface_mapping_eligible'].any()
    assert not r['calibration_validated']
    model['motion_per_line']=[.01,0,0]
    with pytest.raises(CalibrationError,match='slit'):project_physical_pushbroom([[0,1,1]],frame_id='rig',length_unit='m',model=model)


def test_current_dataset_readiness_keeps_physical_fusion_null():
    r=mapping_readiness(shared_frame=None,shared_units='board_squares_unverified',noncoplanar_controls=None,held_out_validation=True,physical_ray_calibration=None,visibility_surface=None,scan_transfer_evidence=None)
    assert r['status']=='blocked_missing_calibration'
    assert 'held_out_validation' in r['missing']
    assert r['physical_fusion'] is None
    assert r['achieved_3d_mapping'] is False

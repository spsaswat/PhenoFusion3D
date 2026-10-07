"""Offline pushbroom control fitting and projection, separate from legacy replay.

An empirical fit predicts detector column and scan line in a declared shared 3D
frame. It is not an optical-ray calibration and never certifies surface visibility.
Physical projection supports only an explicitly supplied straight-motion model.
Neither API maps spectra onto plant surfaces or creates calibrated reflectance.
"""
from __future__ import annotations

from dataclasses import dataclass
import numbers
import numpy as np


class CalibrationError(ValueError):
    """Controls, acquisition metadata, or numerical validation are insufficient."""


@dataclass(frozen=True)
class PixelThresholds:
    rms: float
    p95: float
    maximum: float

    def __post_init__(self):
        for name in ('rms', 'p95', 'maximum'):
            value = getattr(self, name)
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real) or not np.isfinite(value) or value <= 0:
                raise CalibrationError(f'{name} threshold must be an explicit finite positive pixel number, not a boolean.')


def _points(value, columns, name, minimum=1):
    result = np.asarray(value, dtype=float)
    if result.ndim != 2 or result.shape[1] != columns or len(result) < minimum or not np.isfinite(result).all():
        raise CalibrationError(f'{name} must contain at least {minimum} finite {columns}-coordinate rows.')
    return result


def _positive(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real) or not np.isfinite(value) or value <= 0:
        raise CalibrationError(f'{name} must be a finite positive number.')
    return float(value)


def _context(frame_id, length_unit, image_shape):
    if not isinstance(frame_id, str) or not frame_id.strip() or not isinstance(length_unit, str) or not length_unit.strip():
        raise CalibrationError('A shared coordinate frame and declared length unit are required; an arbitrary shared unit is allowed.')
    if len(image_shape) != 2 or any(isinstance(x, (bool, np.bool_)) or not isinstance(x, numbers.Integral) or x <= 0 for x in image_shape):
        raise CalibrationError('image_shape must be (scan lines, detector columns), both positive integers.')


def _ids(ids, count, name):
    if len(ids) != count or any(not isinstance(x, str) or not x.strip() for x in ids) or len(set(ids)) != count:
        raise CalibrationError(f'{name} requires one unique physical-control ID per row.')
    return set(ids)


def _pixel_domain(uv, image_shape):
    lines, cols = image_shape
    return np.isfinite(uv).all(axis=1) & (uv[:, 0] >= 0) & (uv[:, 0] <= cols-1) & (uv[:, 1] >= 0) & (uv[:, 1] <= lines-1)


def _predict(xyz, centre, scale, line_coefficients, column_numerator, column_denominator):
    h = np.column_stack([(xyz-centre)/scale, np.ones(len(xyz))])
    depth = h @ column_denominator
    positive = depth > 1e-10
    uv = np.full((len(xyz), 2), np.nan)
    uv[positive, 0] = (h[positive] @ column_numerator) / depth[positive]
    uv[positive, 1] = h[positive] @ line_coefficients
    return uv, depth


def fit_pushbroom_controls(training_xyz, training_column_line, validation_xyz,
                           validation_column_line, *, training_ids, validation_ids,
                           frame_id, length_unit, image_shape, thresholds,
                           height_axis, reference_plane_offset,
                           min_off_plane_distance, max_condition=1e6):
    """Fit a linear-pushbroom candidate using independently withheld 3D controls.

    Controls must share `frame_id` and `length_unit`; absolute millimetres are not
    needed for pixel validation. All points use XYZ; HSI coordinates are zero-based
    (column, scan line). Holdout labels must identify independently measured controls
    and at least four must be away from the stated reference plane. Numeric gates
    establish fit consistency only, not capture independence or physical accuracy.

    Returns a JSON-compatible model with held-out residuals and a training-control
    convex hull. Raises CalibrationError for missing, coplanar, ill-conditioned,
    recycled, out-of-detector, or numerically failed controls. No robust outlier
    selection is performed on validation observations.
    """
    from scipy.spatial import ConvexHull, distance

    _context(frame_id, length_unit, image_shape)
    if not isinstance(thresholds, PixelThresholds):
        raise CalibrationError('Supply PixelThresholds with numeric RMS, P95 and maximum limits; a pass boolean is insufficient.')
    max_condition = _positive(max_condition, 'max_condition')
    min_off_plane_distance = _positive(min_off_plane_distance, 'min_off_plane_distance')
    if isinstance(reference_plane_offset, (bool, np.bool_)) or not np.isscalar(reference_plane_offset) or not np.isfinite(reference_plane_offset):
        raise CalibrationError('reference_plane_offset must be a finite coordinate value.')
    axis = np.array(height_axis, dtype=float, copy=True)
    if axis.shape != (3,) or not np.isfinite(axis).all() or np.linalg.norm(axis) < 1e-12:
        raise CalibrationError('height_axis must explicitly identify the reference-plane normal.')
    axis /= np.linalg.norm(axis)
    train = _points(training_xyz, 3, 'training_xyz', 12)
    target = _points(training_column_line, 2, 'training_column_line', 12)
    test = _points(validation_xyz, 3, 'validation_xyz', 4)
    observed = _points(validation_column_line, 2, 'validation_column_line', 4)
    if len(train) != len(target) or len(test) != len(observed):
        raise CalibrationError('3D and HSI control counts differ.')
    if not _pixel_domain(target, image_shape).all() or not _pixel_domain(observed, image_shape).all():
        raise CalibrationError('All supplied controls must lie within the recorded detector/line extent.')
    ids = _ids(training_ids, len(train), 'training_ids')
    test_ids = _ids(validation_ids, len(test), 'validation_ids')
    if ids & test_ids:
        raise CalibrationError('Training and holdout must use independent physical controls, not repeated IDs.')
    scale = float(np.sqrt(np.mean(np.sum((train-train.mean(axis=0))**2, axis=1))))
    if scale <= 0:
        raise CalibrationError('3D controls have no spatial extent.')
    for coordinates, name in [(train, 'Training'), (test, 'Holdout')]:
        if np.min(distance.pdist(coordinates)) <= scale*1e-8:
            raise CalibrationError(f'{name} contains duplicate or indistinguishable 3D controls; distinct IDs are insufficient.')
    if np.min(distance.cdist(train, test)) <= scale*1e-8:
        raise CalibrationError('Holdout recycles a training 3D coordinate; independent observations are required.')
    off_plane = np.abs(test @ axis - float(reference_plane_offset)) >= min_off_plane_distance
    if np.count_nonzero(off_plane) < 4:
        raise CalibrationError('At least four withheld controls must independently test off-plane geometry.')
    centre = train.mean(axis=0)
    h = np.column_stack([(train-centre)/scale, np.ones(len(train))])
    spatial_s = np.linalg.svd(h, compute_uv=False)
    if spatial_s[-1] <= spatial_s[0]/max_condition:
        raise CalibrationError('Training controls are coplanar, rank deficient, or too ill-conditioned to determine height-dependent mapping.')
    # Normalize detector columns for a scale-stable homogeneous rational fit.
    u_centre = float(target[:, 0].mean())
    u_scale = float(target[:, 0].std())
    if u_scale <= 1e-9:
        raise CalibrationError('Controls do not span detector columns.')
    u = (target[:, 0]-u_centre)/u_scale
    design = np.column_stack([h, -u[:, None]*h])
    _, singular, vh = np.linalg.svd(design, full_matrices=False)
    # Seven independent combinations are needed; the last value is the fitted
    # homogeneous residual (zero for exact synthetic controls).
    if singular[-2] <= singular[0]/max_condition:
        raise CalibrationError('Column projection is rank deficient or ill-conditioned.')
    solution = vh[-1]
    denominator = solution[4:]
    numerator = u_scale*solution[:4] + u_centre*denominator
    sign = 1 if np.median(h @ denominator) > 0 else -1
    norm = np.linalg.norm(denominator)
    denominator = denominator*sign/norm
    numerator = numerator*sign/norm
    line_coef = np.linalg.lstsq(h, target[:, 1], rcond=None)[0]
    train_pred, train_depth = _predict(train, centre, scale, line_coef, numerator, denominator)
    pred, test_depth = _predict(test, centre, scale, line_coef, numerator, denominator)
    if np.any(train_depth <= 1e-10) or np.any(test_depth <= 1e-10):
        raise CalibrationError('Controls cross the fitted positive projective-depth domain.')
    if not _pixel_domain(pred, image_shape).all():
        raise CalibrationError('Holdout prediction exits the recorded image domain.')
    errors = np.linalg.norm(pred-observed, axis=1)
    metrics = dict(rms=float(np.sqrt(np.mean(errors**2))), p95=float(np.quantile(errors, .95)), maximum=float(errors.max()))
    if any(metrics[k] > getattr(thresholds, k) for k in metrics):
        raise CalibrationError(f'Independent held-out pixel residuals exceed supplied limits: {metrics}')
    hull = ConvexHull((train-centre)/scale)
    return dict(schema_version=1, status='held_out_pixel_validated_empirical_projection_only', model_type='linear_pushbroom_control_fit', frame_id=frame_id, length_unit=length_unit, absolute_metric_scale_verified=False,
                image_shape=list(image_shape), xyz_centre=centre.tolist(), xyz_scale=scale, line_coefficients=line_coef.tolist(), column_numerator=numerator.tolist(), column_denominator=denominator.tolist(), training_hull_equations=hull.equations.tolist(),
                training_ids=list(training_ids), validation_ids=list(validation_ids), training_control_count=len(train), validation_control_count=len(test), withheld_off_plane_count=int(off_plane.sum()), height_axis=axis.tolist(), reference_plane_offset=float(reference_plane_offset), min_off_plane_distance=min_off_plane_distance,
                spatial_condition=float(spatial_s[0]/spatial_s[-1]), column_identifiability_condition=float(singular[0]/singular[-2]), thresholds_px=dict(rms=thresholds.rms,p95=thresholds.p95,maximum=thresholds.maximum), held_out_error_px=metrics, held_out_residual_column_line=(pred-observed).tolist(), training_rms_px=float(np.sqrt(np.mean(np.sum((train_pred-target)**2,axis=1)))),
                physical_ray_model=False, surface_visibility_verified=False, physical_fusion=None,
                limitations=['Empirical projection is not a calibrated physical ray model.', 'Training and holdout independence must also be established by acquisition provenance.', 'Only points inside the training control convex hull are supported.', 'No point-cloud occlusion or measured spectral surface mapping is performed.', 'No calibrated reflectance or physiological interpretation.'])


def project_control_model(xyz, model, *, frame_id, length_unit):
    """Project within the calibrated control volume; never certify surface fusion."""
    points = _points(xyz, 3, 'xyz')
    if model.get('model_type') != 'linear_pushbroom_control_fit' or model.get('status') != 'held_out_pixel_validated_empirical_projection_only':
        raise CalibrationError('A numerically validated control model is required.')
    if frame_id != model['frame_id'] or length_unit != model['length_unit']:
        raise CalibrationError('Point frame and length units must match the calibrated controls.')
    _context(frame_id, length_unit, model['image_shape'])
    scale = _positive(model['xyz_scale'], 'xyz_scale')
    centre = np.asarray(model['xyz_centre'], dtype=float)
    coefficients = [np.asarray(model[key], dtype=float) for key in ('line_coefficients', 'column_numerator', 'column_denominator')]
    if centre.shape != (3,) or not np.isfinite(centre).all() or any(c.shape != (4,) or not np.isfinite(c).all() for c in coefficients):
        raise CalibrationError('Serialized control model has invalid finite coefficient dimensions.')
    planes = _points(model['training_hull_equations'], 4, 'training_hull_equations', 4)
    if np.any(np.linalg.norm(planes[:, :3], axis=1) < 1e-10):
        raise CalibrationError('Serialized control hull contains a degenerate plane.')
    uv, depth = _predict(points, centre, scale, *coefficients)
    normalized = (points-centre)/scale
    support = np.all(normalized @ planes[:, :3].T + planes[:, 3] <= 1e-9, axis=1)
    positive = depth > 1e-10
    detector = _pixel_domain(uv, model['image_shape'])
    valid = positive & detector & support
    uv[~valid] = np.nan
    return dict(column_line=uv, projection_valid=valid, positive_projective_depth=positive, in_detector=detector, in_control_volume=support, projective_depth=depth, surface_visibility_verified=False, surface_mapping_eligible=np.zeros(len(points),bool), physical_fusion=None)


def project_physical_pushbroom(xyz, *, frame_id, length_unit, model):
    """Project an explicitly supplied straight, constant-attitude slit-camera model.

    model requires world_to_camera_rotation, camera_centre_line0, motion_per_line,
    focal_length_pixels, principal_column, image_shape, frame_id and length_unit.
    This computes q_y=0 interception and positive optical depth. Supplied parameters
    are not automatically considered calibrated: independent held-out validation
    and visibility/ray-surface intersections remain separate requirements.
    """
    points = _points(xyz, 3, 'xyz')
    _context(frame_id,length_unit,model['image_shape'])
    if frame_id != model.get('frame_id') or length_unit != model.get('length_unit'):
        raise CalibrationError('Point frame and units must match the supplied physical model.')
    R=np.asarray(model['world_to_camera_rotation'],float)
    C=np.asarray(model['camera_centre_line0'],float)
    v=np.asarray(model['motion_per_line'],float)
    if R.shape!=(3,3) or C.shape!=(3,) or v.shape!=(3,) or not all(np.isfinite(a).all() for a in (R,C,v)) or not np.allclose(R@R.T,np.eye(3),atol=1e-7) or not np.isclose(np.linalg.det(R),1,atol=1e-7):
        raise CalibrationError('Finite rigid camera rotation, centre and motion are required.')
    f=_positive(model['focal_length_pixels'],'focal_length_pixels')
    c=model['principal_column']
    if isinstance(c,(bool,np.bool_)) or not isinstance(c,numbers.Real) or not np.isfinite(c):raise CalibrationError('principal_column must be finite.')
    denominator=float(R[1]@v)
    if abs(denominator)<=1e-10*max(np.linalg.norm(v),1e-12):raise CalibrationError('Motion does not cross the slit plane; scan line cannot be determined.')
    line=((points-C)@R[1])/denominator
    q=(points-C-line[:,None]*v)@R.T
    positive=q[:,2]>0
    uv=np.column_stack([np.full(len(points),np.nan),line])
    uv[positive,0]=c+f*q[positive,0]/q[positive,2]
    detector=_pixel_domain(uv,model['image_shape']);valid=positive&detector
    uv[~valid]=np.nan
    return dict(column_line=uv,optical_depth=q[:,2],projection_valid=valid,positive_optical_depth=positive,in_detector=detector,calibration_validated=False,surface_visibility_verified=False,surface_mapping_eligible=np.zeros(len(points),bool),physical_fusion=None)


def mapping_readiness(*, shared_frame, shared_units, noncoplanar_controls,
                      held_out_validation, physical_ray_calibration,
                      visibility_surface, scan_transfer_evidence):
    """Describe missing inputs without treating supplied booleans as calibration."""
    records=dict(shared_frame=shared_frame,shared_units=shared_units,noncoplanar_controls=noncoplanar_controls,held_out_validation=held_out_validation,physical_ray_calibration=physical_ray_calibration,visibility_surface=visibility_surface,scan_transfer_evidence=scan_transfer_evidence)
    missing=[name for name,value in records.items() if value is None or isinstance(value,(bool,np.bool_)) or (isinstance(value,str) and not value.strip())]
    return dict(status='blocked_missing_calibration' if missing else 'inputs_supplied_require_numeric_validation',missing=missing,physical_fusion=None,achieved_3d_mapping=False,absolute_metric_scale_separate=True,explanation='Planar board agreement cannot determine raised-leaf projection. Shared arbitrary units may support pixel validation, while millimetre traits still require verified physical scale.')

"""Traceable research review and conditional traits; never controls acquisition.

Cloud extents are descriptors, not anatomical height. Point-picked landmarks
retain their original source index and hash. Physical truth is not established
by an operator checkbox or by numerical consistency alone.
"""
from __future__ import annotations

import csv
import copy
import hashlib
import html
import json
import math
import os
from pathlib import Path
from urllib.parse import quote

import numpy as np

TRAITS = {
    'observed_chord': 'straight_distance_between_observed_points',
    'height': 'vertical_stem_base_to_highest_tip',
    'leaf_chord_length': 'straight_blade_base_to_tip_chord',
    'leaf_section_width': 'straight_width_at_identified_section',
}


def read_json(path):
    def reject(value): raise ValueError('Nonfinite JSON number: '+value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=reject)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(4*1024*1024), b''): h.update(data)
    return h.hexdigest()


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def local_path(value, base):
    if not isinstance(value,str) or not value.strip(): raise ValueError('A local file path is required')
    if '://' in value: raise ValueError('Use local saved files, not network URLs')
    p = Path(value)
    return (p if p.is_absolute() else base/p).resolve()


def fresh_output(output, inputs=(), protected_roots=()):
    out = Path(output).resolve()
    for raw in inputs:
        p = Path(raw).resolve()
        if out == p or p.is_relative_to(out):
            raise ValueError('Output would contain/replace an input: '+str(p))
    for raw in protected_roots:
        p = Path(raw).resolve()
        if out == p or out.is_relative_to(p) or p.is_relative_to(out):
            raise ValueError('Output overlaps a protected recording directory')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError('Choose a new, empty output folder; existing results are preserved')
    out.mkdir(parents=True, exist_ok=True)
    return out


def rotation(value):
    R = np.asarray(value if value is not None else np.eye(3), dtype=float)
    if R.shape != (3,3) or not np.isfinite(R).all() or not np.allclose(R.T@R,np.eye(3),atol=1e-7) or not np.isclose(np.linalg.det(R),1,atol=1e-7):
        raise ValueError('upright_R must be a finite proper rotation, not a rescaling/reflection')
    return R


def cloud_record(entry, base, R, context=False):
    import open3d as o3d  # Optional at module import; never import camera/ROS code.
    path = local_path(entry['cloud'],base)
    if path.suffix.lower() != '.ply' or not path.is_file(): raise ValueError('Expected an existing PLY: '+str(path))
    fingerprint=sha(path)
    if entry.get('sha256') and entry['sha256'] != fingerprint: raise ValueError('Cloud changed since review: '+str(path))
    cloud=o3d.io.read_point_cloud(str(path)); points=np.asarray(cloud.points).copy()
    if not len(points) or not np.isfinite(points).all(): raise ValueError('Cloud is empty or contains nonfinite coordinates')
    colours=np.asarray(cloud.colors).copy() if cloud.has_colors() else np.full(points.shape,.65)
    points=points@R.T
    return dict(id=str(entry['id']),label=str(entry.get('label',entry['id'])),path=path,sha256=fingerprint,
                points=points,colours=colours,context=context,source_count=len(points))


def descriptors(record, unit):
    p=record['points'];lo=p.min(0);hi=p.max(0);qlo,qhi=np.percentile(p,[.5,99.5],axis=0)
    return dict(specimen_id=record['id'],source_sha256=record['sha256'],points=len(p),
        coordinate_unit=unit,observed_extent_xyz=(hi-lo).tolist(),observed_p99_extent_xyz=(qhi-qlo).tolist(),
        minimum_xyz=lo.tolist(),maximum_xyz=hi.tolist(),anatomical_height=None,
        whole_leaf_area=None,whole_plant_volume=None,
        status='observed_cloud_distribution_only',
        limitation='Retained point range is not stem-base height, complete canopy extent, tissue surface area or volume.')


def measure_annotations(document, records, specimen_ids, unit, references=()):
    if document.get('schema_version') != 1: raise ValueError('Unsupported landmark schema')
    refs={str(r['id']):r for r in references}
    if len(refs) != len(references): raise ValueError('Duplicate manual reference IDs')
    rows=[];used_refs=set()
    for item in document.get('measurements',[]):
        specimen=str(item.get('specimen_id',''));trait=item.get('trait')
        if specimen not in specimen_ids or trait not in TRAITS: raise ValueError('Unknown specimen or measurement type')
        if item.get('definition') != TRAITS[trait]: raise ValueError('Measurement definition does not match its type')
        marks=item.get('points',[])
        if len(marks)!=2: raise ValueError('Exactly two recorded endpoints are required')
        points=[];identities=[]
        for mark in marks:
            cloud=records.get(str(mark.get('cloud_id','')))
            if cloud is None or mark.get('source_sha256') != cloud['sha256']:
                raise ValueError('Landmark cloud is missing or its recorded hash is stale')
            if cloud['id'] != specimen and not cloud['context']:
                raise ValueError('Endpoint belongs to a different specimen cloud')
            i=mark.get('point_index')
            if isinstance(i,bool) or not isinstance(i,int) or not 0<=i<cloud['source_count']:
                raise ValueError('Landmark index must identify an original source point')
            points.append(cloud['points'][i]);identities.append((cloud['id'],i))
        if identities[0]==identities[1]: raise ValueError('Both endpoints identify the same point')
        d=points[1]-points[0]
        value=float(d[2] if trait=='height' else np.linalg.norm(d))
        if value<=0: raise ValueError('Measurement must be positive; height needs base first and tip second')
        reviewed=item.get('landmarks_reviewed') is True
        row=dict(specimen_id=specimen,trait=trait,definition=TRAITS[trait],value=value,
            coordinate_unit=unit,status='reviewed_candidate' if reviewed else 'unreviewed_endpoint_candidate',
            source_points=marks,endpoint_upright_xyz=[x.tolist() for x in points],
            physical_accuracy_validated=False,comparison_status='no_eligible_reference',reference_id=None,
            signed_difference=None,absolute_difference=None)
        row['label']=str(item.get('label',''))
        row['scope']=str(item.get('scope',''))
        ref_id=item.get('reference_id');ref=refs.get(str(ref_id)) if ref_id is not None else None
        if ref_id is not None and ref is None: raise ValueError('Unknown manual reference ID')
        if ref is not None:
            if str(ref_id) in used_refs: raise ValueError('A manual reference cannot be reused as an independent pair')
            used_refs.add(str(ref_id));row['reference_id']=str(ref_id)
            reason=None
            if trait=='observed_chord':reason='observed_extent_is_not_a_validation_trait'
            elif not reviewed: reason='endpoints_not_reviewed'
            elif item.get('organ_match_confirmed') is not True:reason='physical_organ_match_unconfirmed'
            elif str(ref.get('specimen_id')) != specimen:reason='specimen_mismatch'
            elif ref.get('definition') != TRAITS[trait]:reason='incompatible_measurement_definition'
            elif ref.get('unit')!='m' or unit not in ('m','conditional_m'):reason='units_not_comparable'
            elif ref.get('evidence_status') not in ('operator_reported','photo_interval','independent_measured'):reason='reference_evidence_unspecified'
            elif not ref.get('source'):reason='reference_source_missing'
            ref_value=ref.get('value')
            if isinstance(ref_value,bool) or not isinstance(ref_value,(float,int)) or not math.isfinite(ref_value) or ref_value<=0:
                reason=reason or 'reference_value_missing_or_invalid'
            if reason:row['comparison_status']=reason
            else:
                row.update(comparison_status='provisional_matched_comparison',reference_value=ref_value,
                    reference_evidence_status=ref['evidence_status'],reference_source=ref['source'],
                    signed_difference=value-ref_value,absolute_difference=abs(value-ref_value))
                # Matching and arithmetic do not independently verify metric scale.
        rows.append(row)
    groups={}
    for trait in TRAITS:
        selected=[r for r in rows if r['trait']==trait and r['comparison_status']=='provisional_matched_comparison']
        errors=np.asarray([r['signed_difference'] for r in selected],float)
        groups[trait]=dict(n=len(errors),mean_signed_error=float(errors.mean()) if len(errors) else None,
            mae=float(np.abs(errors).mean()) if len(errors) else None,
            rmse=float(np.sqrt((errors**2).mean())) if len(errors) else None,
            status='provisional_matched_comparisons' if len(errors) else 'no_eligible_pairs',
            physical_accuracy_validated=False)
    return rows,groups


def link(path, root):
    try:return quote(Path(os.path.relpath(path,root)).as_posix(),safe='/')
    except ValueError:return Path(path).as_uri()


def report(out, manifest, records, observed, measurements, metrics, gaps, artifacts):
    escape=lambda x:html.escape(str(x),quote=True)
    readable=lambda x:escape(str(x).replace('_',' '))
    root=out/'result';root.mkdir(exist_ok=True)
    cards=''.join(f'<article><h3>{escape(a["title"])}</h3><p>{escape(a.get("description",""))}</p><a href="{escape(link(a["path"],root))}">Open saved result</a></article>' for a in artifacts)
    rows=''.join(f'<tr><td>{escape(d["specimen_id"])}</td><td>{d["points"]:,}</td><td>{d["observed_extent_xyz"][0]:.4f}</td><td>{d["observed_extent_xyz"][1]:.4f}</td><td>{d["observed_extent_xyz"][2]:.4f}</td><td>Not inferred from lowest point</td></tr>' for d in observed)
    gap_rows=''.join(f'<tr><td>{escape(g.get("title",g.get("id","")))}</td><td>{readable(g.get("status","unresolved"))}</td><td>{escape(g.get("resolution",""))}</td></tr>' for g in gaps)
    measurement_rows=''.join(f'<tr><td>{escape(r["specimen_id"])}</td><td>{readable(r["trait"])}<br><small>{escape(r.get("label",""))} {escape(r.get("scope",""))}</small></td><td>{r["value"]:.5f}</td><td>{readable(r["status"])}</td><td>{readable(r["comparison_status"])}</td></tr>' for r in measurements)
    if not measurement_rows:measurement_rows='<tr><td colspan="5">No endpoint measurements imported. Use the point reviewer; missing measurements remain blank.</td></tr>'
    page=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(manifest.get('title','Research workspace'))}</title>
<style>body{{margin:0;background:#081b26;color:#e9f3f5;font:16px/1.65 system-ui}}main{{max-width:1120px;margin:auto;padding:40px 28px}}h1{{font-size:36px;line-height:1.2}}h2{{margin-top:36px}}p,small{{color:#b1c9d3}}a{{color:#8cdbcc}}aside{{border-left:4px solid #e8b866;background:#22333b;padding:16px 22px}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #355160}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}}article{{background:#102c3b;padding:20px;border-radius:10px}}.button{{display:inline-block;padding:10px 16px;border-radius:6px;background:#80d5c4;color:#082333;text-decoration:none;font-weight:600}}</style>
<main><small>PHENOFUSION3D · LOCAL RESEARCH WORKSPACE</small><h1>{escape(manifest.get('title','Research workspace'))}</h1>
<aside><strong>Conditional measurements · calibration gaps retained</strong><p>Coordinate units: {escape(manifest.get('coordinate_unit','unknown'))}. Physical scale status: {escape(manifest.get('scale_status','unverified'))}. This report does not certify physical accuracy, complete plant coverage or calibrated 3D spectral fusion.</p></aside>
<p>Saved cloud dimensions and reviewed landmark measurements are kept separate. No geometry is fitted to manual validation values. Existing cloud files and lab acquisition settings are preserved.</p>
<p><a class="button" href="point_review.html">Inspect clouds and mark measurement endpoints</a> <a href="../workspace_summary.json">Summary and provenance</a></p>
<h2>Saved research stages</h2><div class="cards">{cards or '<p>No linked stage results supplied.</p>'}</div>
<h2>Observed cloud distribution</h2><p>These X/Y/Z ranges describe the supplied selection in its upright frame. They are affected by missing tissue, fragments and prior cleanup. Z range is not automatically plant height; no whole-leaf area or volume is inferred.</p><div style="overflow:auto"><table><tr><th>Specimen</th><th>Points</th><th>X range</th><th>Y range</th><th>Z range</th><th>Anatomical height</th></tr>{rows}</table></div>
<h2>Explicit endpoint measurements</h2><p>Point picks are source-linked candidates. Physical organ matching and measurement definitions must be reviewed before comparisons. Provisional error calculations retain scale and reference limitations; an empty comparison has no accuracy score.</p><table><tr><th>Specimen</th><th>Quantity</th><th>Value</th><th>Review</th><th>Comparison</th></tr>{measurement_rows}</table>
<p><a href="../measurements.csv">Measurement CSV</a> · <a href="../measurements.json">Endpoints and comparison details</a></p>
<h2>Open evidence gaps</h2><table><tr><th>Gap</th><th>Status</th><th>Evidence needed</th></tr>{gap_rows}</table>
<p>Reuse this workspace with local PLYs and a setup file; optional endpoint JSON is hash-checked on rebuild. The point reviewer runs offline. Source-reviewed masks and specimen labels remain inputs, not proof of general automatic segmentation. New-dataset and lab-hardware validation are separate.</p></main></html>'''
    (root/'index.html').write_text(page,encoding='utf-8')
    from .viewer import write_viewer
    write_viewer(root, records, [r['id'] for r in records.values() if not r['context']], manifest)


def create_template(output):
    out=fresh_output(output)
    setup=dict(schema_version=1,title='New research workspace',coordinate_unit='unknown',scale_status='unverified',
        upright_R=np.eye(3).tolist(),specimens=[],context_clouds=[],artifacts=[],manual_references=[],
        protected_input_roots=[],gaps=[dict(id='physical_scale',title='Physical scale needs independent evidence',status='unresolved',resolution='Provide measured reference and acquisition units')],
        instructions='Add specimens with unique id and cloud local PLY path (relative to this JSON or absolute). upright_R maps all clouds into the same Z-up frame. Use context_clouds for original scene points, including stem bases omitted by cleanup. Artifacts have title,path,description. Manual references use stable id,specimen_id,definition,value,unit=m,evidence_status,source. Never set scale from plant traits reserved for validation.')
    save_json(out/'workspace_template.json',setup)
    (out/'result').mkdir()
    (out/'result/index.html').write_text('<!doctype html><meta charset="utf-8"><title>Research setup created</title><h1>Research setup created</h1><p>Add your reviewed specimen PLY paths and known evidence to <a href="../workspace_template.json">workspace_template.json</a>, then build a new workspace. Unknown calibration remains a recorded gap.</p>',encoding='utf-8')
    save_json(out/'run_status.json',dict(status='template_created',report='result/index.html'))
    print(str(out/'workspace_template.json'),flush=True)


def build(manifest_path, output, annotations_path=None):
    source=Path(manifest_path).resolve();source_hash=sha(source)
    manifest=read_json(source);base=source.parent
    if manifest.get('schema_version')!=1:raise ValueError('Unsupported workspace schema')
    entries=manifest.get('specimens',[]);contexts=manifest.get('context_clouds',[])
    if not entries:raise ValueError('Add at least one reviewed specimen PLY before building')
    ids=[str(e['id']) for e in entries+contexts]
    if len(set(ids))!=len(ids) or any(not i.strip() for i in ids):raise ValueError('Every specimen/context needs a unique nonempty ID')
    R=rotation(manifest.get('upright_R'));unit=manifest.get('coordinate_unit','unknown')
    if unit not in ('m','conditional_m','unknown'):raise ValueError('Use m, conditional_m or unknown coordinate units; do not silently rescale')
    records={}
    for entry in entries+contexts:
        record=cloud_record(entry,base,R,context=entry in contexts);records[record['id']]=record
        print('Loaded',record['id'],record['source_count'],'points',flush=True)
    artifacts=[]
    for entry in manifest.get('artifacts',[]):
        path=local_path(entry['path'],base)
        if not path.is_file():raise ValueError('Linked stage output is missing: '+str(path))
        artifacts.append(dict(entry,path=path))
    annotations_file=Path(annotations_path).resolve() if annotations_path else None
    annotations_hash=sha(annotations_file) if annotations_file else None
    annotations=read_json(annotations_file) if annotations_file else dict(schema_version=1,measurements=[])
    rows,metrics=measure_annotations(annotations,records,{str(e['id']) for e in entries},unit,manifest.get('manual_references',[]))
    gaps=manifest.get('gaps',[])
    input_files=[source,*[r['path'] for r in records.values()],*[a['path'] for a in artifacts]]
    if annotations_file:input_files.append(annotations_file)
    out=fresh_output(output,input_files,[local_path(v,base) for v in manifest.get('protected_input_roots',[])])
    save_json(out/'run_status.json',dict(status='running',mode='research_workspace'))
    try:
        observed=[descriptors(r,unit) for r in records.values() if not r['context']]
        # Resolve input paths before saving elsewhere so this snapshot can be
        # rebuilt locally without interpreting paths against the output folder.
        snapshot=copy.deepcopy(manifest)
        snapshot['source_manifest']=str(source)
        for entry in snapshot.get('specimens',[])+snapshot.get('context_clouds',[]):
            record=records[str(entry['id'])]
            entry.update(cloud=str(record['path']),sha256=record['sha256'])
        for entry,artifact in zip(snapshot.get('artifacts',[]),artifacts):
            entry['path']=str(artifact['path'])
        snapshot['protected_input_roots']=[str(local_path(v,base)) for v in manifest.get('protected_input_roots',[])]
        save_json(out/'workspace_manifest_snapshot.json',snapshot)
        save_json(out/'observed_descriptors.json',observed)
        save_json(out/'measurements.json',dict(measurements=rows,error_summaries=metrics,physical_accuracy_validated=False))
        with (out/'measurements.csv').open('w',newline='',encoding='utf-8') as f:
            fields=['specimen_id','trait','label','scope','definition','value','coordinate_unit','status','comparison_status','reference_id','signed_difference','absolute_difference']
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
        input_hashes={str(p):sha(p) for p in input_files}
        if input_hashes[str(source)] != source_hash:
            raise ValueError('Workspace setup changed while loading')
        if annotations_file and input_hashes[str(annotations_file)] != annotations_hash:
            raise ValueError('Endpoint annotations changed while loading')
        for record in records.values():
            if input_hashes[str(record['path'])] != record['sha256']:
                raise ValueError('Source cloud changed while loading')
        summary=dict(status='research_review_ready_with_recorded_gaps',schema_version=1,
            coordinate_unit=unit,scale_status=manifest.get('scale_status','unverified'),
            physical_accuracy_validated=False,calibrated_3d_spectral_fusion_achieved=False,
            gaps=gaps,input_hashes=input_hashes,observed_descriptors=observed,
            measurement_count=len(rows),error_summaries=metrics,
            source_clouds=[{k:v for k,v in r.items() if k not in ('points','colours','path')}|{'path':str(r['path'])} for r in records.values()],
            upright_R=R.tolist(),notes=['Display point sampling never changes source files.','No acquisition/camera/gantry module is imported.','Geometry and scale are never fitted to physical validation traits.'])
        save_json(out/'workspace_summary.json',summary)
        report(out,manifest,records,observed,rows,metrics,gaps,artifacts)
        for p in input_files:
            if sha(p)!=input_hashes[str(p)]:raise ValueError('Input changed during workspace build')
        save_json(out/'run_status.json',dict(status='complete_candidate_workspace',report='result/index.html',physical_accuracy_validated=False))
    except BaseException as error:
        save_json(out/'run_status.json',dict(status='failed',error=str(error)));raise
    print('Research workspace:',out/'result/index.html',flush=True)
    return summary

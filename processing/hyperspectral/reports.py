"""Label historical outputs honestly and retain portable report assets."""
import html
import hashlib
import json
from pathlib import Path
import re
import runpy
from urllib.parse import unquote, urlsplit

from . import STATUS
from .workflow import LEGACY


def write_viewer(root):
    """Adapt display paths and picking only; preserve the source snapshot."""
    source=(LEGACY/'assets/viewer.js').read_text(encoding='utf-8')
    source=source.replace('`../global_placement/global_scene_', '`global_placement/global_scene_')
    source=source.replace('`${plantKey}/${plantKey}_', '`fusion/${plantKey}/${plantKey}_')
    start=source.index('    for (let point = 0; point < projected.x.length; point += 1) {',source.index('  function selectNearest('))
    end=source.index('    if (nearest >= 0) inspectPoint(nearest);',start)
    source=source[:start]+'''    // Measured points are drawn over grey context. Prefer a nearby measured
    // sample when their screen positions overlap; never invent a spectrum.
    const specimenCount = decodedModels[plantKey].meta.displaySpecimenVertices;
    for (const [first, last] of [[specimenCount, projected.x.length], [0, specimenCount]]) {
      for (let point = first; point < last; point += 1) {
        const dx = projected.x[point] - targetX;
        const dy = projected.y[point] - targetY;
        const distance = dx * dx + dy * dy;
        if (distance <= nearestDistance) { nearestDistance = distance; nearest = point; }
      }
      if (nearest >= 0) break;
    }
'''+source[end:]
    (Path(root)/'fusion/viewer.js').write_text(source,encoding='utf-8')


def prepare_reports(root, mode):
    root = Path(root)
    note = root / 'full_resolution_note.html'
    scene_note = ('Use the included sampled scene for interactive inspection.' if mode != 'spectral'
                  else 'This spectral-only run does not include an RGB-D scene.')
    note.write_text('<!doctype html><html><body><h1>Original full-resolution ICP scene</h1>'
                    '<p>The 1.2 GB historical scene remains in the selected RGB-D recording under '
                    '<code>merge_simple_full_step10/merge_pcd_cam0.ply</code>. '
                    'It is not duplicated in this result bundle. ' + scene_note + '</p><p>' +
                    html.escape(STATUS) + '</p></body></html>', encoding='utf-8')
    point_count = None
    fusion = root / 'fusion/fusion_summary.json'
    if fusion.is_file():
        write_viewer(root)
        point_count = sum(p['coverage']['points_within_20mm_of_specimen_surface']
                          for p in json.loads(fusion.read_text())['plants'])
    for page in root.rglob('*.html'):
        content = page.read_text(encoding='utf-8-sig')
        if page == root / 'index.html' and point_count is not None:
            revision=hashlib.sha256((root/'fusion/viewer.js').read_bytes()).hexdigest()[:12]
            content=re.sub(r'src="fusion/viewer\.js(?:\?[^"]*)?"',f'src="fusion/viewer.js?v={revision}"',content)
            content = content.replace('10,485', f'{point_count:,}')
            content = content.replace('Registration is measured and validated, but still an approximation affected by parallax and the five-minute capture gap.',
                                      'Registration has internal numerical checks only; physical cross-sensor accuracy remains unvalidated and can be affected by parallax and the five-minute capture gap.')
            content = content.replace('Held-out surface checks gave median errors below five millimetres, with at least 97.2 percent of points within twenty millimetres.',
                                      'The tables report the current held-out surface distances; these are internal consistency checks, not physical ground truth.')
        if mode == 'spectral' and page == root / 'index.html':
            # The historical template includes the finished fusion roadmap even
            # when only spectral data was processed. Do not claim those stages ran.
            content = re.sub(r'<section id="fusion-roadmap">.*?</section>', '', content, flags=re.S)
            content = re.sub(r'<script src="fusion/[^"]+"></script>', '', content)
            for section in ('rgbd-results', 'fusion-results', 'interactive-3d', 'global-placement'):
                content = re.sub(rf'<a href="#{section}">.*?</a>', '', content)
            content = content.replace('A guided, presentation-ready walkthrough of hyperspectral calibration, RGB-D reconstruction and traits, cross-modal fusion, interactive 3D models and recovered placement in the legacy ICP scene.',
                                      'Spectral analysis completed for the historical recording. RGB-D fusion and global placement have not been run in this bundle.')
        # Replace non-portable full-resolution scene links with a truthful note.
        relative_note = Path(__import__('os').path.relpath(note, page.parent)).as_posix()
        content = re.sub(r'''href=(["'])[^"']*merge_pcd_cam0\.ply\1''',
                         lambda m: f'href="{relative_note}"', content)
        if 'id="experimental-status"' not in content:
            banner = ('<aside id="experimental-status" role="note" style="padding:18px 24px;background:#fff0c2;'
                      'color:#382800;border-bottom:3px solid #a96800;font:16px/1.5 system-ui">'
                      '<strong>' + html.escape(STATUS) + '</strong><br>'
                      'This report preserves the previous dataset recipe. Software checks do not validate '
                      'new plants, new captures, biological interpretations or physical cross-sensor calibration.</aside>')
            content = re.sub(r'<body[^>]*>', lambda m: m.group(0) + banner, content, count=1, flags=re.I)
        page.write_text(content, encoding='utf-8')


def validate_bundle(root, fusion=False):
    import numpy as np
    root = Path(root).resolve()
    links = runpy.run_path(str(LEGACY / 'scripts/validate_report_links.py'))
    pages, references = links['check_report_links'](root)
    # Every relative link must also stay inside the portable output bundle.
    for page in root.rglob('*.html'):
        parser = links['References'](); parser.feed(page.read_text(encoding='utf-8'))
        for raw in parser.urls:
            url = urlsplit(raw)
            if not url.scheme and not url.netloc and url.path:
                target = (page.parent / unquote(url.path)).resolve()
                if not target.is_relative_to(root):
                    raise ValueError(f'Report depends on a file outside the output bundle: {raw}')
    checked = {'html_pages': pages, 'local_references': references, 'fusion_checked': fusion,
               'scope': 'File integrity and internal numerical checks only. New datasets and physical accuracy remain unvalidated.'}
    if fusion:
        reader = runpy.run_path(str(LEGACY / 'scripts/build_interactive_viewer_assets.py'))['read_binary_ply']
        summary = json.loads((root / 'fusion/fusion_summary.json').read_text())
        global_summary = json.loads((root / 'global_placement/global_placement_summary.json').read_text())
        expected_plants = {'coleus', 'fuzzy_kalanchoe', 'succulent_jade'}
        if {p['plant'] for p in summary['plants']} != expected_plants:
            raise ValueError('Historical fusion must contain all three reviewed specimens.')
        if {p['plant'] for p in global_summary['plants']} != expected_plants:
            raise ValueError('Historical global placement is incomplete.')
        measured_total = 0
        for plant in summary['plants']:
            key = plant['plant']; count = plant['coverage']['points_within_20mm_of_specimen_surface']; measured_total += count
            with np.load(root / 'fusion' / key / f'{key}_spectral_points.npz', allow_pickle=False) as arrays:
                if (count < 100 or arrays['xyz_m'].shape != (count, 3) or arrays['spectra'].shape != (count, 427)
                        or arrays['wavelengths_nm'].shape != (427,) or not np.isfinite(arrays['xyz_m']).all()
                        or not np.isfinite(arrays['spectra']).all()):
                    raise ValueError(f'Invalid spectral point arrays: {key}')
            xyz, _ = reader(root / 'fusion' / key / f'{key}_ndvi_on_specimen.ply')
            if len(xyz) != count + plant['specimen_surface_validation']['specimen_points']:
                raise ValueError(f'Point counts disagree: {key}')
        for plant in global_summary['plants']:
            transform = np.asarray(plant['transform_camera_to_global'], dtype=float)
            if (transform.shape != (4, 4) or not np.isfinite(transform).all()
                    or not np.allclose(transform[3], [0, 0, 0, 1])
                    or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3), atol=1e-5)
                    or not np.isclose(np.linalg.det(transform[:3, :3]), 1, atol=1e-5)):
                raise ValueError('Global placement is not a finite rigid transform.')
            v = plant['held_out_validation']
            if not (v['nearest_scene_distance_median_mm'] < 10 and v['nearest_scene_distance_p90_mm'] < 20
                    and v['within_20mm_fraction'] > .95):
                raise ValueError(f"Historical scene consistency gates failed: {plant['plant']}")
        viewer = root / 'fusion/viewer_models.js'
        if not viewer.is_file() or not (root / 'fusion/viewer.js').is_file():
            raise ValueError('Interactive viewer assets are missing.')
        checked['measured_spectral_points'] = measured_total
    (root / 'integration_checks.json').write_text(json.dumps(checked, indent=2), encoding='utf-8')
    print(f'OUTPUT_CHECKS_OK: {pages} HTML pages; {references} local references.', flush=True)
    return checked

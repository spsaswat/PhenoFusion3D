"""Run the preserved historical recipe without touching capture or reconstruction."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import sys

from . import STATUS

PACKAGE = Path(__file__).resolve().parent
LEGACY = PACKAGE / 'legacy'
PLANTS = {'plant_1': 'succulent_jade', 'plant_2': 'coleus', 'plant_3': 'fuzzy_kalanchoe'}


def profile():
    return json.loads((PACKAGE / 'profile_20260828.json').read_text(encoding='utf-8'))


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def verify_files(root, expected):
    root = Path(root).resolve()
    checked = {}
    for relative, record in expected.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Input manifest contains a path outside its selected folder.')
        if not path.is_file():
            raise ValueError(f'Required historical input is missing: {path}')
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError(
                f'Input differs from the reviewed 28 August recipe: {relative}. '
                'Automatic fusion is unsupported for this dataset. Use the manual '
                'spectral workspace for exploration; new calibration regions, specimen '
                'matches and camera poses must be reviewed before extending fusion.'
            )
        checked[relative] = record
    return checked


def spectral_inputs(folder):
    folder = Path(folder)
    manifest = folder / 'integration_manifest.json'
    recipe = profile()
    if manifest.is_file():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        if (saved.get('profile') != recipe['id'] or
                saved.get('hsi_inputs') != recipe['inputs']['hsi'] or
                not saved.get('spectral_files')):
            raise ValueError('Spectral bundle lacks verified historical input provenance.')
        # Require every original spectral product, not a partial manifest.
        if set(saved['spectral_files']) != set(recipe['spectral_bundle']):
            raise ValueError('Spectral bundle is incomplete.')
        verify_files(folder, saved['spectral_files'])
    else:
        verify_files(folder, recipe['spectral_bundle'])
    return recipe['inputs']['hsi']


def check_inputs(mode, hsi=None, rgbd=None, spectral=None):
    recipe = profile()
    result = {'profile': recipe['id'], 'status': STATUS, 'mode': mode}
    if mode in ('spectral', 'all'):
        if not hsi:
            raise ValueError('Select the original paired FX10/FX17 recording folder.')
        result['hsi_inputs'] = verify_files(hsi, recipe['inputs']['hsi'])
    if mode == 'fusion':
        if not spectral:
            raise ValueError('Select a completed historical spectral-results folder.')
        result['hsi_inputs'] = spectral_inputs(spectral)
    if mode in ('fusion', 'all'):
        if not rgbd:
            raise ValueError('Select the matching 28 August RGB-D recording with reviewed specimen clouds and ICP scene.')
        result['rgbd_inputs'] = verify_files(rgbd, recipe['inputs']['rgbd'])
        # These historical reports remain prerequisites, not newly recomputed traits.
        required = ['merge_simple_full_step10/diagnostics/scene_geometry_diagnostics.json',
                    'merge_simple_full_step10/diagnostics/scene_top_side_preview.png',
                    'validation/software_traits/software_traits.json',
                    'validation/software_traits/software_traits.csv',
                    'validation/report/validation_report.html',
                    'validation/report/validation_results.json']
        for relative in required:
            if not (Path(rgbd) / relative).is_file():
                raise ValueError(f'Missing reviewed RGB-D evidence: {relative}')
    return result


def check_dependencies():
    missing = [name for name in ('numpy', 'cv2', 'matplotlib', 'spectral', 'scipy', 'sklearn', 'skimage')
               if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError('Missing optional hyperspectral dependencies: ' + ', '.join(missing) +
                           '. Install the project hyperspectral extra in the analysis environment; see HYPERSPECTRAL_WORKFLOW.md.')


def fresh_output(output, inputs):
    output = Path(output).resolve()
    for source in inputs:
        if source:
            source = Path(source).resolve()
            if output == source or output in source.parents or source in output.parents:
                raise ValueError('Choose a separate output folder outside the selected inputs. Existing recordings and results are preserved.')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output folder is not empty. Choose a new run folder.')
    output.mkdir(parents=True, exist_ok=True)
    return output


@contextmanager
def legacy_context(directory):
    previous_argv, previous_path, previous_cwd = sys.argv[:], sys.path[:], Path.cwd()
    sys.path.insert(0, str(LEGACY / 'scripts'))
    os.chdir(directory)
    try:
        yield
    finally:
        sys.argv, sys.path = previous_argv, previous_path
        os.chdir(previous_cwd)


def invoke(script, arguments):
    print(f'Stage: {script}', flush=True)
    sys.argv = [script, *map(str, arguments)]
    try:
        runpy.run_path(str(LEGACY / 'scripts' / script), run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise RuntimeError(f'{script} failed with exit status {exc.code}') from exc


def stage_rgbd(dataset, showcase):
    """Portable equivalent of the original two PowerShell staging scripts."""
    dataset, destination = Path(dataset), Path(showcase) / 'rgbd_icp'
    def copy(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    reconstruction = dataset / 'merge_simple_full_step10'
    copy(reconstruction / 'reconstruction_summary.json', destination / 'reconstruction_summary.json')
    for name in ('scene_geometry_diagnostics.json', 'scene_top_side_preview.png', 'scene_preview_sampled.ply'):
        copy(reconstruction / 'diagnostics' / name, destination / name)
    validation = dataset / 'validation'
    for ext in ('json', 'csv'):
        copy(validation / 'software_traits' / f'software_traits.{ext}', destination / f'software_traits.{ext}')
    for file in (validation / 'report').iterdir():
        if file.is_file(): copy(file, destination / 'validation' / file.name)
    for folder in ('guided_leaf_measurements', 'manual_photos'):
        images = list((validation / folder).glob('*.png'))
        if not images: raise ValueError(f'Missing reviewed validation images: {folder}')
        for file in images: copy(file, destination / folder / file.name)
    for plant, key in PLANTS.items():
        for name in ('plant_overlay.png', 'leaf_segments.png', 'plant_mask.png', 'traits.json', 'visible_leaves.json', 'specimen_pointcloud.ply'):
            copy(validation / 'software_traits' / plant / name, destination / 'plants' / key / name)
        for name in ('plant_overlay.png', 'leaf_segments.png'):
            copy(validation / 'software_traits' / plant / name, destination / 'software_traits' / plant / name)
    report = destination / 'validation/validation_report.html'
    content = report.read_text(encoding='utf-8-sig')
    for name in ('scene_preview_sampled.ply', 'scene_top_side_preview.png'):
        content = content.replace(f'../../merge_simple_full_step10/diagnostics/{name}', f'../{name}')
    report.write_text(content, encoding='utf-8')


def fingerprint_spectral(showcase):
    return {name: {'bytes': (showcase / name).stat().st_size, 'sha256': digest(showcase / name)}
            for name in profile()['spectral_bundle']}


def run(mode, output, hsi=None, rgbd=None, spectral=None, inspect_only=False):
    print(STATUS, flush=True)
    evidence = check_inputs(mode, hsi, rgbd, spectral)
    output = fresh_output(output, [hsi, rgbd, spectral])
    evidence['source_snapshot_sha256'] = digest(LEGACY / 'SOURCE_MANIFEST.json')
    evidence['started_utc'] = datetime.now(timezone.utc).isoformat()
    (output / 'preflight.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    if inspect_only:
        print(f'RESULT: {output / "preflight.json"}', flush=True)
        return output / 'preflight.json'
    state = {'status': 'running', 'experimental': True, 'completed_stages': []}
    showcase = output / 'results/20260828_showcase'
    showcase.mkdir(parents=True)
    def stage(name, action):
        state['current_stage'] = name
        (output / 'run_status.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        action()
        state['completed_stages'].append(name)
    try:
        check_dependencies()
        os.environ.setdefault('MPLBACKEND', 'Agg')
        with legacy_context(output):
            if mode == 'fusion':
                for folder in ('cubes', 'indices', 'tables', 'figures'):
                    shutil.copytree(Path(spectral) / folder, showcase / folder)
                shutil.copy2(Path(spectral) / 'quality_metrics.json', showcase / 'quality_metrics.json')
                state['completed_stages'].append('verified_existing_spectral_results')
            else:
                stage('spectral_analysis', lambda: invoke('generate_showcase.py', ['--data-dir', hsi, '--output-dir', showcase, '--stride', 4]))
            if mode in ('fusion', 'all'):
                stage('stage_reviewed_rgbd_evidence', lambda: stage_rgbd(rgbd, showcase))
                stage('map_measured_spectra', lambda: invoke('fuse_rgbd_hyperspectral.py', ['--showcase-dir', showcase, '--rgbd-dir', rgbd, '--depth-scale', 10000]))
                stage('recover_legacy_global_placement', lambda: invoke('recover_global_placement.py', ['--dataset', rgbd, '--fusion-dir', showcase / 'fusion', '--output-dir', showcase / 'global_placement']))
                stage('build_interactive_viewer', lambda: invoke('build_interactive_viewer_assets.py', ['--fusion-dir', showcase / 'fusion', '--output', showcase / 'fusion/viewer_models.js']))
                shutil.copy2(LEGACY / 'assets/viewer.js', showcase / 'fusion/viewer.js')
                stage('assemble_report', lambda: invoke('generate_showcase.py', ['--output-dir', showcase, '--report-only']))
            from .reports import prepare_reports, validate_bundle
            stage('experimental_labels_and_portable_links', lambda: prepare_reports(showcase, mode))
            stage('verify_outputs', lambda: validate_bundle(showcase, fusion=mode != 'spectral'))
        evidence['spectral_files'] = fingerprint_spectral(showcase)
        evidence['validation'] = 'Software/output checks only; no new-dataset or physical validation.'
        (showcase / 'integration_manifest.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        state['status'] = 'complete_experimental'
        print(f'RESULT: {showcase / "index.html"}', flush=True)
        return showcase / 'index.html'
    except BaseException as exc:
        state.update(status='failed', error=str(exc))
        raise
    finally:
        (output / 'run_status.json').write_text(json.dumps(state, indent=2), encoding='utf-8')

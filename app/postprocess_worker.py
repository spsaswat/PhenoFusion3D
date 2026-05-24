import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtCore import QThread, pyqtSignal


class PostProcessWorker(QThread):
    done = pyqtSignal(str, object)
    error = pyqtSignal(str)

    def __init__(self, mode: str, input_ply: str, output_dir: str, expected_plants: int = 1):
        super().__init__()
        self.mode = mode
        self.input_ply = input_ply
        self.output_dir = output_dir
        self.expected_plants = expected_plants

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _run_script(self, script_name: str, *args: str) -> str:
        cmd = [sys.executable, str(self._repo_root() / 'scripts' / script_name), *map(str, args)]
        proc = subprocess.run(
            cmd,
            cwd=str(self._repo_root()),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f'{script_name} failed').strip())
        return proc.stdout

    def _load_json(self, path: str | os.PathLike) -> SimpleNamespace:
        with open(path, 'r', encoding='utf-8') as f:
            return SimpleNamespace(**json.load(f))

    def _clean(self) -> SimpleNamespace:
        self._run_script(
            'clean_pointcloud.py',
            self.input_ply,
            '--output-dir',
            self.output_dir,
            '--green-only',
            '--voxel-size',
            '0.005',
        )
        return self._load_json(Path(self.output_dir) / 'cleanup_summary.json')

    def _segment(self) -> SimpleNamespace:
        self._run_script(
            'segment_plants.py',
            self.input_ply,
            '--output-dir',
            self.output_dir,
            '--expected-plants',
            str(self.expected_plants),
        )
        return self._load_json(Path(self.output_dir) / 'segmentation_summary.json')

    def _traits(self, input_ply: str | None = None, output_dir: str | None = None) -> SimpleNamespace:
        input_ply = input_ply or self.input_ply
        output_dir = output_dir or self.output_dir
        self._run_script(
            'extract_traits.py',
            input_ply,
            '--output-dir',
            output_dir,
            '--height-axis',
            'z',
        )
        return self._load_json(Path(output_dir) / 'traits.json')

    def _pipeline(self) -> SimpleNamespace:
        dataset_dir = Path(self.output_dir)
        cleanup_dir = dataset_dir / 'post_cleanup'
        plants_dir = dataset_dir / 'plants'
        traits_dir = dataset_dir / 'traits'

        clean_result = PostProcessWorker('clean', self.input_ply, str(cleanup_dir))._clean()
        segment_result = PostProcessWorker(
            'segment',
            clean_result.output_ply,
            str(plants_dir),
            self.expected_plants,
        )._segment()

        trait_results = []
        for plant in segment_result.plants:
            plant_id = plant['plant_id']
            plant_ply = plant['output_ply']
            trait_result = PostProcessWorker(
                'traits',
                plant_ply,
                str(traits_dir / f'plant_{plant_id}'),
            )._traits()
            trait_results.append(vars(trait_result))

        return SimpleNamespace(
            cleanup=vars(clean_result),
            segmentation=vars(segment_result),
            traits=trait_results,
            output_dir=str(dataset_dir),
        )

    def run(self):
        try:
            if self.mode == 'clean':
                result = self._clean()
            elif self.mode == 'segment':
                result = self._segment()
            elif self.mode == 'traits':
                result = self._traits()
            elif self.mode == 'pipeline':
                result = self._pipeline()
            else:
                raise ValueError(f'Unknown postprocess mode: {self.mode}')
            self.done.emit(self.mode, result)
        except Exception as e:
            self.error.emit(str(e))

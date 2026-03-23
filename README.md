# PhenoFusion3D

Python tools for **RGB-D–based 3D reconstruction**: turn paired colour and depth images into coloured point clouds, align successive frames with ICP, and merge them into a single model. The project targets phenotyping / plant-imaging workflows (ANU COMP8715 Technical Team Project).

## Prerequisites

- **Python 3.10+** (3.12 is used in development; match your team’s version).
- A C++ runtime compatible with **Open3D** wheels on your OS (on Windows, the [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) is usually required).

## Getting started

From the repository root:

```bash
python -m venv venv
```

Activate the virtual environment:

- **Windows (PowerShell):** `.\venv\Scripts\Activate.ps1`
- **Windows (cmd):** `.\venv\Scripts\activate.bat`
- **macOS / Linux:** `source venv/bin/activate`

Install dependencies:

```bash
pip install -r requirements.txt
```

Do not commit large datasets or generated point clouds; see `.gitignore` (`data/`, `*.ply`, `*.pcd`, etc.).

## Project layout

| Path | Role |
|------|------|
| `file_io/loader.py` | **`load_image_pairs`** — pairs RGB/depth PNGs from two folders (stakeholder `rgb_*.png` / `depth_*.png`, or ICL-NUIM-style `0.png`, `1.png`, …); optional **`step`** subsamples pairs. **`load_intrinsics`** / **`get_default_intrinsics`** for camera JSON |
| `file_io/exporter.py` | **`save_ply`** — write a point cloud to PLY; **`save_metrics_csv`** — per-frame metrics (e.g. fitness / RMSE) to CSV |
| `processing/rgbd.py` | **`rgbd2pcd`** — RGB + depth → Open3D coloured point cloud |
| `processing/icp.py` | Colour ICP with point-to-plane fallback |
| `processing/utils.py` | Downsampling, outlier removal, normals, optional GPU/CuPy check |
| `processing/reconstructor.py` | **`Reconstructor`** — sequential merge via ICP; optional **`save_path`** writes **`merge_pcd_live.ply`** after each successful frame (live merge snapshot) |
| `tests/` | Unit tests (`test_loader`, `test_rgbd`, `test_icp`) |
| `tests/smoke_reconstructor.py` | End-to-end smoke script (synthetic frames → merged cloud) |
| `stakeholder_reference/` | Reference scripts from stakeholders (e.g. `3D_recons.py`); may expect extra deps such as PyTorch |
| `data/` | Local RGB-D sequences (gitignored; keep datasets here, e.g. `data/icl_nuim/`) |
| `app/`, `main.py`, `visualiser/` | Reserved for a future PyQt-style UI; entry points may still be empty stubs |

## Data conventions

- **Two filename layouts** (see `load_image_pairs` in `file_io/loader.py`):
  - **Stakeholder:** `rgb_*.png` and `depth_*.png` in separate directories.
  - **ICL-NUIM / numbered:** `0.png`, `1.png`, … in `rgb/` and `depth/` (same count; paired by natural sort order).
- **Subsampling:** Pass **`step=n`** to use every *n*-th pair (e.g. faster experiments).
- **Intrinsics:** JSON in the style of `kdc_intrinsics.txt` with keys such as `K` (3×3), `dist`, `width`, `height`. If the file is missing or invalid, use **`get_default_intrinsics()`** (optionally pass image size to match your frames).
- **Depth units:** Defaults in **`Reconstructor`** assume depth in **millimetres** and **`depth_scale=1000.0`**. For **ICL-NUIM** Freiburg PNG releases, **`depth_scale=1.0`** is typical (depth in metres); tune **`depth_scale`**, **`depth_trunc`**, and **`voxel_size`** if colours or alignment look wrong (e.g. when slicing a subset of frames).

## Sample dataset (ICL-NUIM)

A convenient public RGB-D sequence in PNG form is **ICL-NUIM — living room trajectory 1 (Freiburg PNG)**:

- Download: [http://www.doc.ic.ac.uk/~ahanda/living_room_traj1_frei_png.tar.gz](http://www.doc.ic.ac.uk/~ahanda/living_room_traj1_frei_png.tar.gz)

After extracting under `data/` (e.g. `data/icl_nuim/`), you typically get **`rgb/`** and **`depth/`** folders of matching numbered PNGs, plus metadata such as a ground-truth trajectory (**`livingRoom1.gt.freiburg`**) for evaluation—the loader does not read that file; it only needs paired RGB/depth paths and intrinsics.

Point `load_image_pairs` at your **`rgb`** and **`depth`** directories, supply **`kdc_intrinsics.txt`** (or project-specific intrinsics JSON), and set **`depth_scale`** (often **`1.0`** for this dataset) when constructing **`Reconstructor`**.

## Running tests

From the repository root (with the venv activated):

```bash
python -m pytest tests -q
```

Tests prepend the project root to `sys.path` so imports like `from processing.rgbd import ...` resolve without installing the repo as a package.

## Trying the reconstruction pipeline

The **`Reconstructor`** class in `processing/reconstructor.py` takes a list of `(rgb_path, depth_path)` tuples, intrinsics **`K`**, optional distortion **`dist`**, and runs the sequential ICP merge.

- If **`save_path`** is set, **`merge_pcd_live.ply`** is updated in that folder after each successful frame (final file = full merged cloud at end of run). Use **`file_io.exporter.save_ply`** for one-off or custom export paths; **`save_metrics_csv`** if you record per-frame metrics in a list of dicts.

For a quick check without real data:

```bash
python tests/smoke_reconstructor.py
```

Typical real-data usage: **`pairs = load_image_pairs(rgb_dir, depth_dir, step=1)`**, **`load_intrinsics(path)`** or defaults, then **`Reconstructor(pairs=..., K=..., dist=..., depth_scale=..., save_path=...).run()`**. You can slice **`pairs`** (e.g. Python list slicing) to run on a subset of frames.

## Dependencies (summary)

Declared in `requirements.txt`: Open3D, OpenCV, NumPy, natsort, tqdm, PyQt5, pyqtgraph, matplotlib, pytest. Optional acceleration paths (e.g. CuPy) are referenced in `processing/utils.py` but are not required for the core tests.

## Contributing tips

- Keep new logic alongside existing modules (`file_io`, `processing`) so tests stay easy to run from the repo root.
- When adding scripts, assume the working directory is the project root or insert the root onto `sys.path` like the tests do.
- Large assets stay out of git per `.gitignore`; use **`data/`** locally and the sample URL above for a standard benchmark sequence.

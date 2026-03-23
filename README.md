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
| `file_io/loader.py` | Discover `rgb_*.png` / `depth_*.png` pairs; load `kdc_intrinsics.txt` (JSON) or build default intrinsics |
| `processing/rgbd.py` | `rgbd2pcd` — RGB + depth → Open3D coloured point cloud |
| `processing/icp.py` | Colour ICP with point-to-plane fallback |
| `processing/utils.py` | Downsampling, outlier removal, normals, optional GPU/CuPy check |
| `processing/reconstructor.py` | **`Reconstructor`** — sequential merge of frames via ICP (main batch pipeline) |
| `tests/` | Unit tests for loader, RGB-D, and ICP |
| `tests/smoke_reconstructor.py` | End-to-end smoke script (synthetic frames → merged cloud) |
| `stakeholder_reference/` | Reference scripts from stakeholders (e.g. `3D_recons.py`); may expect extra deps such as PyTorch |
| `data/` | Place local RGB-D sequences here (gitignored except placeholders) |
| `app/`, `main.py`, `visualiser/` | Reserved for a future PyQt-style UI; many files are currently empty stubs |

## Data conventions

- **RGB and depth:** PNG files named `rgb_*.png` and `depth_*.png`, with matching counts and natural sort order (see `load_image_pairs` in `file_io/loader.py`). If those patterns are missing, the loader falls back to any `*.png` per folder.
- **Intrinsics:** JSON in the style of `kdc_intrinsics.txt` with keys such as `K` (3×3), `dist`, `width`, `height`. If the file is missing or invalid, the code can use `get_default_intrinsics()`.
- **Depth units:** Defaults assume depth in **millimetres** and use `depth_scale=1000.0` to convert to metres (adjust for your sensor, e.g. ICL-NUIM may use `depth_scale=1.0`).

## Running tests

From the repository root (with the venv activated):

```bash
python -m pytest tests -q
```

Tests prepend the project root to `sys.path` so imports like `from processing.rgbd import ...` resolve without installing the repo as a package.

## Trying the reconstruction pipeline

The **`Reconstructor`** class in `processing/reconstructor.py` takes a list of `(rgb_path, depth_path)` tuples, intrinsics `K`, optional distortion `dist`, and runs the sequential ICP merge.

For a quick check without real data, run the smoke script (writes temporary PNGs and exercises the full loop):

```bash
python tests/smoke_reconstructor.py
```

You can also follow the same pattern in your own script: build pairs with `file_io.loader.load_image_pairs`, load intrinsics with `load_intrinsics` or `get_default_intrinsics`, then call `Reconstructor(...).run()`.

## Dependencies (summary)

Declared in `requirements.txt`: Open3D, OpenCV, NumPy, natsort, tqdm, PyQt5, pyqtgraph, matplotlib, pytest. Optional acceleration paths (e.g. CuPy) are referenced in `processing/utils.py` but are not required for the core tests.

## Contributing tips

- Keep new logic alongside existing modules (`file_io`, `processing`) so tests stay easy to run from the repo root.
- When adding scripts, assume the working directory is the project root or insert the root onto `sys.path` like the tests do.
- Large assets and secrets stay out of git per `.gitignore`; use `data/` locally or document download steps separately.

# PhenoFusion3D — RGB-D Capture and 3D Point-Cloud Reconstruction for Plant Phenotyping

Reconstructs a single coloured 3D point cloud of a plant from a gantry-mounted
RGB-D camera. The software captures paired colour and depth frames along a
linear gantry pass, converts each pair into a coloured point cloud, aligns
successive clouds with Iterative Closest Point (ICP) registration, and merges
them into one model. It also scores the captured sequence so an operator can
tell, before reconstructing, whether the data is good enough to use.

Developed by the ANU COMP8715 TechLauncher team for plant-phenotyping and
controlled-environment plant-imaging workflows.

## Keywords

`3D Reconstruction` · `RGB-D Imaging` · `Point Cloud Processing` ·
`Plant Phenotyping` · `High-Throughput Phenotyping` · `ICP Registration` ·
`Open3D` · `Computer Vision` · `Machine Learning` · `Digital Agriculture`

## Licence

Released under the **Mozilla Public License 2.0** — see [LICENSE](LICENSE) for
the full text. SPDX identifier: `MPL-2.0`.

## Authors and contributors

**Project team:** TechLauncher PhenoFusion3D Team (ANU COMP8715 Technical
Team Project).

| Contributor | Email |
|---|---|
| Adithya Rama | Adithya.Rama@anu.edu.au |
| Tanisha Sharma | Tanisha.Sharma@anu.edu.au |
| Howard Zhang | u7877905@anu.edu.au |
| Flynn Nyhof | u7650207@anu.edu.au |
| Tianyu Xu | Tianyu.Xu@anu.edu.au |

## Contact

For questions, follow-up, or access requests, contact
**Saswat Panda — Saswat.Panda@anu.edu.au**.

---

## Prerequisites

- **Python 3.10–3.12** with the `venv` module already available.
- The lab's existing ROS distribution and gantry catkin workspace.
- The lab's existing RealSense system/USB configuration.

## Installation and setup

On the Linux lab rig, run:

```bash
./setup.sh
source .venv-linux/bin/activate
python main.py
```

`setup.sh` creates and populates only the project venv. It never installs or
changes system packages, ROS, RealSense drivers/SDKs, apt repositories, kernel
modules, or shell startup files. See [install/README.md](install/README.md) for
the full safety boundary and for Windows instructions.

Do not commit large datasets or generated point clouds; see `.gitignore`
(`data/`, `*.ply`, `*.pcd`, etc.).

---

## Inputs

### Format

| Input | Format |
|---|---|
| Colour frames | PNG, 8-bit RGB, one file per frame |
| Depth frames | PNG, 16-bit single-channel (`z16`), one file per frame |
| Colour intrinsics | `kdc_intrinsics.txt` — JSON with `K` (3×3), `dist`, `width`, `height` |
| Depth intrinsics | `kd_intrinsics.txt` — same schema, depth stream |
| Session metadata | `session.json` — backend, resolution, fps, velocity, `frame_index → gantry position` (optional) |

Two on-disk layouts are accepted by `load_image_pairs`
(`file_io/loader.py`):

- **Numbered / ICL-NUIM:** `rgb/0.png`, `rgb/1.png`, … and `depth/0.png`,
  `depth/1.png`, … — this is what the in-app capture writes.
- **Stakeholder flat:** `rgb_*.png` and `depth_*.png` in separate directories.

### Objects represented

- Individual potted plants and plant canopies.
- Controlled-environment imaging scenes on the linear gantry rig.
- Any static scene imaged by a translating RGB-D camera (the ICL-NUIM indoor
  benchmark is used as the reference test sequence).

### Constraints

- **Paired frames required.** RGB and depth directories must contain the same
  number of files; pairing is by natural sort order, so numbering must be
  consistent across the two folders.
- **Supported sensors:** Intel RealSense RGB-D cameras exposing both a colour
  and a depth stream — validated on **L515, D435, and D405**. Device selection
  is dynamic and profile-negotiated, so replacement units are not tied to any
  hard-coded serial.
- **Capture resolution:** requested `1280×720 @ 30 fps` by default. If the
  attached device does not offer that profile, the closest supported
  colour/depth profile is negotiated automatically.
- **Multiple cameras:** if more than one RealSense is connected, one must be
  chosen by serial via `PHENOFUSION_CAMERA_SERIAL` before launch.
- **Image format:** PNG only. Depth must be an integer PNG; lossy formats are
  not supported.
- **Depth range:** depth beyond `depth_trunc` is discarded — **3.0 m** in
  `Reconstructor`, **4.0 m** in the quality checker.
- **Gantry motion:** ROS backend requires a driver publishing `/joint_states`
  and accepting `/cmd_vel`. Capture aborts rather than commanding motion if no
  gantry position is received.

### Associated parameters

| Parameter | Default | Meaning |
|---|---|---|
| `width` × `height` | `1280 × 720` | Requested capture resolution |
| `fps` | `30` | Requested frame rate |
| `duration_s` | `10.0` | RealSense-only capture length (`-1` = manual stop) |
| `max_buffer_gib` | `6.0` | Absolute ceiling before RAM/disk safety limits are applied |
| Capture velocity | `38 mm/s` | Gantry linear velocity (`velocity_mps=0.038` internally) |
| Capture endpoint | `1640 mm` | Gantry position at which the pass stops (`end_position_m=1.64` internally) |
| Camera warm-up | `4` frames | Frames discarded before acquisition |
| Home position | `5 mm` | Gantry go-home target |
| Home velocity | `200 mm/s` | Gantry go-home velocity |
| `gantry_axis` | `0` | `0` = X, `1` = Y in the camera frame |
| `depth_scale` | `1000.0` | Depth units per metre (use `1.0` for ICL-NUIM) |
| `depth_trunc` | `3.0` (recon) / `4.0` (quality) | Maximum retained depth (m) |
| `voxel_size` | `0.005` | Downsample voxel edge length (m) |
| `max_iter` | `50` | ICP iteration cap |
| `K`, `dist` | from intrinsics file | Camera matrix and distortion coefficients |
| `min_fitness` / `max_rmse` | `0.3` / `0.015` | Frame-rejection bars during merge |

---

## Outputs

### Format

| Output | Format | Written by |
|---|---|---|
| `merge_pcd_live.ply` | PLY point cloud, updated after each accepted frame | `Reconstructor` (when `save_path` is set) |
| Merged point cloud | PLY | `file_io.exporter.save_ply` |
| `quality_report.csv` | CSV, one row per consecutive frame pair | Data Quality panel — Full Report |
| `quality_report.txt` | Plain-text summary with PASS/WARN/FAIL verdict | Data Quality panel — Full Report |
| Per-frame metrics | CSV | `file_io.exporter.save_metrics_csv` |
| Captured sequence | `rgb/N.png`, `depth/N.png`, intrinsics, `session.json` | Data Capture panel |

### Objects represented

- Reconstructed 3D coloured point clouds of individual plants and canopies.
- Per-capture session records linking each frame index to its gantry position.

### Variables represented

Per consecutive frame pair (`PairMetrics` in `processing/quality.py`):

| Variable | Unit | Meaning |
|---|---|---|
| `depth_validity` | fraction | Share of pixels with usable depth |
| `median_depth_m` | metres | Median scene depth |
| `n_points` | count | Points in the generated cloud |
| `icp_fitness` | 0–1 | ICP overlap ratio between the pair |
| `icp_rmse` | metres | ICP inlier root-mean-square error |
| `rotation_deg` | degrees | Per-pair rotation magnitude |

Aggregated across the sequence, each variable is reported as mean, median, p25
and p75, together with an overall `verdict` (`PASS` / `WARN` / `FAIL`) and the
list of `failing_metrics`.

---

## Capture (in-app)

The **Data Capture** panel drives an RGB-D capture without leaving the app.

- **Backend = Auto** picks ROS+gantry when ROS is installed, otherwise camera-only.
- **ROS + Gantry** uses the working `/cmd_vel` and `/joint_states` gantry protocol through the lab's existing ROS interpreter while capturing RGB-D frames.
- **RealSense Only** captures from the camera without starting or requiring the gantry.
- The separate **Gantry Control** panel moves the gantry without opening the camera.

Both camera backends copy the aligned RGB/depth frames into memory during
acquisition. After the camera (and gantry, when used) has stopped, the complete
batch is saved as PNG files, followed by the intrinsics and `session.json`.
This keeps image compression and disk I/O out of the time-critical capture loop.
At the default 1280x720, 30 FPS settings, a 10-second raw buffer uses roughly
1.3 GiB of RAM before Python/driver overhead; longer captures scale linearly.
The required `0.005 m` to `1.64 m` ROS pass uses approximately 5.54 GiB of
raw frame storage and is covered by the 6 GiB configured ceiling.
Before acquisition, the app checks the estimated raw buffer against available
RAM and output-disk space. Manual captures are stopped and saved at the runtime
safety ceiling rather than allowing the process to exhaust memory. ROS passes
also stop if gantry position does not advance for five seconds.

Camera selection happens when capture starts. One connected RGB-D RealSense is
selected automatically. If several are connected, select one by serial before
launching the app:

```bash
export PHENOFUSION_CAMERA_SERIAL=<serial>
python main.py
```

PowerShell equivalent:

```powershell
$env:PHENOFUSION_CAMERA_SERIAL = "<serial>"
python main.py
```

The setup check prints every detected model and serial. Capture probes the
selected device's supported colour/depth profiles, so L515, D435, D405, and
replacement units are not tied to the historical serials in the stakeholder
script.

Output layout (consumed directly by the loader):

```
data/captures/<YYYYMMDDhhmmss>/
    rgb/0.png, 1.png, ...
    depth/0.png, 1.png, ...
    kdc_intrinsics.txt        # color stream
    kd_intrinsics.txt         # depth stream
    session.json              # backend, velocity, frame_index -> gantry position
```

After a successful capture the **Data Loading** fields are auto-populated so you can immediately run the quality check or reconstruction.
After ROS acquisition stops, the go-home command returns the gantry to `5 mm`
at `200 mm/s` before buffered frames are saved; the session records whether that
return was confirmed. Automatic failures after motion begins also attempt Home,
while an operator-requested Stop does not initiate new motion. Closing the app
during capture requests a stop and waits for the buffered batch to finish saving
before the window exits. The gantry panel continues to show live position during
combined capture and its automatic return Home.

## Quality Check (in-app)

The **Data Quality** panel runs depth + ICP diagnostics on the loaded sequence:

- **Quick Check** -- ~15 random consecutive pairs, ~10–30 s.
- **Full Report** -- every consecutive pair; writes `quality_report.csv` and `quality_report.txt` next to the dataset.

Per-pair metrics: depth validity %, median depth (m), point count, ICP fitness, ICP inlier RMSE (m), per-pair rotation magnitude (deg).

Verdict bands (default thresholds):

| Metric | PASS | WARN | FAIL |
|---|---|---|---|
| ICP fitness (mean) | ≥ 0.50 | 0.30–0.50 | < 0.30 |
| ICP inlier RMSE (mean) | ≤ 0.005 m | 0.005–0.015 m | > 0.015 m |
| Depth validity per frame | ≥ 30 % | 10–30 % | < 10 % |
| Per-frame rotation (gantry) | < 1° | 1–5° | > 5° |

The same `min_fitness` / `max_rmse` thresholds are now enforced inside the reconstructor: frames whose ICP result misses either bar are marked **REJECTED** and don't pollute the merged cloud.

---

## Sample and test data

A convenient public RGB-D sequence in PNG form is **ICL-NUIM — living room
trajectory 1 (Freiburg PNG)**, used as this project's reference sequence for
verifying the pipeline still works after system changes:

- Download: [http://www.doc.ic.ac.uk/~ahanda/living_room_traj1_frei_png.tar.gz](http://www.doc.ic.ac.uk/~ahanda/living_room_traj1_frei_png.tar.gz)

After extracting under `data/` (e.g. `data/icl_nuim/`), you typically get **`rgb/`** and **`depth/`** folders of matching numbered PNGs, plus metadata such as a ground-truth trajectory (**`livingRoom1.gt.freiburg`**) for evaluation—the loader does not read that file; it only needs paired RGB/depth paths and intrinsics.

Point `load_image_pairs` at your **`rgb`** and **`depth`** directories, supply **`kdc_intrinsics.txt`** (or project-specific intrinsics JSON), and set **`depth_scale`** (often **`1.0`** for this dataset) when constructing **`Reconstructor`**.

For a synthetic end-to-end check that needs no download:

```bash
python tests/smoke_reconstructor.py
```

## Validation and quality evidence

**Reference-sequence run (ICL-NUIM living room trajectory 1):**

| Measure | Result |
|---|---|
| Frames successfully registered | 50 / 50 |
| Mean ICP fitness | 1.0 |
| Points in merged cloud | ~740,000 |

This is the regression baseline the pipeline is re-checked against after
changes; it was recorded on the ICL-NUIM sequence, whose ground-truth
trajectory (`livingRoom1.gt.freiburg`) ships with the dataset.

Continuous verification is provided by the unit and offline test suites
(`python -m pytest tests -q`), which cover the loader, RGB-D conversion, ICP,
the ROS and RealSense runtimes, and offline gantry behaviour.

**Outstanding validation work.** The following have not yet been measured and
should not be assumed:

- Reconstruction accuracy against a surveyed ground-truth plant specimen.
- Registration RMSE against a published benchmark, reported as a distribution
  rather than a single sequence.
- Point-cloud completeness / coverage metrics.
- Trait-level agreement (e.g. plant height, canopy area) against manual
  measurement.
- Any peer-reviewed validation study arising from the project.

---

## Technical documentation

### Project layout

| Path | Role |
|------|------|
| `file_io/loader.py` | **`load_image_pairs`** — pairs RGB/depth PNGs from two folders (stakeholder `rgb_*.png` / `depth_*.png`, or ICL-NUIM-style `0.png`, `1.png`, …); optional **`step`** subsamples pairs. **`load_intrinsics`** / **`get_default_intrinsics`** for camera JSON |
| `file_io/exporter.py` | **`save_ply`** — write a point cloud to PLY; **`save_metrics_csv`** — per-frame metrics (e.g. fitness / RMSE) to CSV |
| `processing/rgbd.py` | **`rgbd2pcd`** — RGB + depth → Open3D coloured point cloud |
| `processing/icp.py` | Colour ICP with point-to-plane fallback |
| `processing/quality.py` | Depth + ICP diagnostics, thresholds, PASS/WARN/FAIL verdicts |
| `processing/utils.py` | Downsampling, outlier removal, normals, optional GPU/CuPy check |
| `processing/reconstructor.py` | **`Reconstructor`** — sequential merge via ICP; optional **`save_path`** writes **`merge_pcd_live.ply`** after each successful frame (live merge snapshot) |
| `processing/pointcloud_post.py` | Post-merge cleanup of the reconstructed cloud |
| `capture/base.py` | `CaptureBackend` / `CaptureParams` / `CaptureSession` — the backend contract |
| `capture/realsense_capture.py` | Camera-only backend: device selection, profile negotiation, intrinsics export |
| `capture/ros_capture.py` | ROS + gantry backend (synchronised motion and frame capture) |
| `capture/ros_runtime.py`, `capture/ros_client.py`, `capture/ros_agent.py` | Bridge to the lab's system ROS interpreter without pip-installing `rospy` into the venv |
| `capture/gantry.py` | `GantryController` — `/cmd_vel` + `/joint_states` motion control |
| `app/`, `main.py` | PyQt5 UI: capture, gantry, data loading, quality, reconstruction panels |
| `visualiser/` | Live Open3D viewer |
| `scripts/reorganize_to_icl_layout.py` | CLI: convert stakeholder flat `rgb_*`/`depth_*` layout → `rgb/N.png`, `depth/N.png` + `kdc_intrinsics.txt` |
| `scripts/reorganize_data_main.py` | Wrapper: batch that for each subfolder of `data/main` |
| `scripts/segment_plants.py`, `scripts/extract_traits.py`, `scripts/clean_pointcloud.py` | Downstream segmentation, trait extraction, and cloud cleanup |
| `tests/` | Unit and offline tests (loader, RGB-D, ICP, ROS runtime, RealSense runtime, gantry) |
| `tests/smoke_reconstructor.py` | End-to-end smoke script (synthetic frames → merged cloud) |
| `stakeholder_reference/` | Reference scripts from stakeholders (e.g. `3D_recons.py`); may expect extra deps such as PyTorch |
| `docs/` | Hardware setup (`L515_SETUP.md`) and canopy reconstruction notes |
| `install/` | Platform install notes and compatibility entry points |
| `data/` | Local RGB-D sequences (gitignored; keep datasets here, e.g. `data/icl_nuim/`, `data/main/`) |

### Data conventions

- **Two filename layouts** (see `load_image_pairs` in `file_io/loader.py`):
  - **Stakeholder:** `rgb_*.png` and `depth_*.png` in separate directories.
  - **ICL-NUIM / numbered:** `0.png`, `1.png`, … in `rgb/` and `depth/` (same count; paired by natural sort order).
- **Subsampling:** Pass **`step=n`** to use every *n*-th pair (e.g. faster experiments).
- **Intrinsics:** JSON in the style of `kdc_intrinsics.txt` with keys such as `K` (3×3), `dist`, `width`, `height`. If the file is missing or invalid, use **`get_default_intrinsics()`** (optionally pass image size to match your frames).
- **Depth units:** Defaults in **`Reconstructor`** assume depth in **millimetres** and **`depth_scale=1000.0`**. For **ICL-NUIM** Freiburg PNG releases, **`depth_scale=1.0`** is typical (depth in metres); tune **`depth_scale`**, **`depth_trunc`**, and **`voxel_size`** if colours or alignment look wrong (e.g. when slicing a subset of frames).

### Organizing `data/main` (ICL-style layout)

Team RGB-D drops often use **`rgb_*.png`** and **`depth_*.png`** in a single folder per capture (e.g. `data/main/<sequence>/`). To mirror **`data/icl_nuim/`** (`rgb/0.png`, `depth/0.png`, and **`kdc_intrinsics.txt`** at the sequence root), activate the venv (see above) and run from the repo root:

```bash
python scripts/reorganize_data_main.py --dry-run
python scripts/reorganize_data_main.py
```

Use **`--move`** instead of copy if you want to remove the flat `rgb_*` / `depth_*` files after moving them into `rgb/` and `depth/`. For one sequence, separate RGB/depth folders, or **`camera_N`** layouts, see **`python scripts/reorganize_to_icl_layout.py --help`**.

### Running tests

From the repository root (with the venv activated):

```bash
python -m pytest tests -q
```

Tests prepend the project root to `sys.path` so imports like `from processing.rgbd import ...` resolve without installing the repo as a package.

### Using the reconstruction pipeline directly

The **`Reconstructor`** class in `processing/reconstructor.py` takes a list of `(rgb_path, depth_path)` tuples, intrinsics **`K`**, optional distortion **`dist`**, and runs the sequential ICP merge.

- If **`save_path`** is set, **`merge_pcd_live.ply`** is updated in that folder after each successful frame (final file = full merged cloud at end of run). Use **`file_io.exporter.save_ply`** for one-off or custom export paths; **`save_metrics_csv`** if you record per-frame metrics in a list of dicts.

Typical real-data usage: **`pairs = load_image_pairs(rgb_dir, depth_dir, step=1)`**, **`load_intrinsics(path)`** or defaults, then **`Reconstructor(pairs=..., K=..., dist=..., depth_scale=..., save_path=...).run()`**. You can slice **`pairs`** (e.g. Python list slicing) to run on a subset of frames.

### Dependencies

Declared in `requirements.txt`: Open3D, OpenCV, NumPy, natsort, tqdm, PyQt5, pyqtgraph, matplotlib, pyrealsense2 (camera capture). Developer extras (`pytest`, `ruff`) are in `pyproject.toml` under `[project.optional-dependencies] dev`. Optional acceleration paths (e.g. CuPy) are referenced in `processing/utils.py` but are not required for the core tests.

---

## Version history

Current version: **0.2.0** (see `pyproject.toml`). Releases are not yet git-tagged;
the milestones below are drawn from the commit history.

| Version | Date | Changes |
|---|---|---|
| 0.2.0 | 2026-08 | Gantry driven through the lab's existing ROS runtime instead of a venv `rospy`; RealSense setup and Qt startup stabilised; offline gantry, ROS-runtime and RealSense-runtime test suites added |
| 0.1.3 | 2026-05 | Point-cloud post-processing and trait-extraction tooling; RealSense capture initialisation and error handling reworked |
| 0.1.2 | 2026-04 | In-app Data Capture and Data Quality panels; gantry control panel and motion backend; configurable reconstruction parameters and registration agent |
| 0.1.1 | 2026-04 | Layout-conversion scripts (flat `rgb_*`/`depth_*` → ICL layout); RGB-D pipeline improvements |
| 0.1.0 | 2026-03 | Initial pipeline: loader, RGB-D conversion, ICP, reconstructor, exporter; PyQt scaffold and live Open3D viewer; validated on ICL-NUIM (50/50 frames) |

## References

**Algorithms**

- Besl, P.J. and McKay, N.D. (1992). *A Method for Registration of 3-D Shapes.*
  IEEE Transactions on Pattern Analysis and Machine Intelligence, 14(2), 239–256.
  — the ICP algorithm underlying registration.
- Chen, Y. and Medioni, G. (1992). *Object modelling by registration of multiple
  range images.* Image and Vision Computing, 10(3), 145–155. — point-to-plane
  ICP, used as the fallback metric.
- Park, J., Zhou, Q.-Y. and Koltun, V. (2017). *Colored Point Cloud Registration
  Revisited.* IEEE International Conference on Computer Vision (ICCV), 143–152.
  — the coloured ICP variant used as the primary registration method.

**Software**

- Zhou, Q.-Y., Park, J. and Koltun, V. (2018). *Open3D: A Modern Library for 3D
  Data Processing.* arXiv:1801.09847. — reconstruction, registration, and
  visualisation backend.
- Intel RealSense SDK 2.0 (`pyrealsense2`) —
  [https://github.com/IntelRealSense/librealsense](https://github.com/IntelRealSense/librealsense)

**Datasets**

- Handa, A., Whelan, T., McDonald, J. and Davison, A.J. (2014). *A Benchmark for
  RGB-D Visual Odometry, 3D Reconstruction and SLAM.* IEEE International
  Conference on Robotics and Automation (ICRA). — the ICL-NUIM benchmark used as
  this project's reference sequence.

## Contributing

- Keep new logic alongside existing modules (`file_io`, `processing`, `capture`) so tests stay easy to run from the repo root.
- When adding scripts, assume the working directory is the project root or insert the root onto `sys.path` like the tests do.
- Large assets stay out of git per `.gitignore`; use **`data/`** locally and the sample URL above for a standard benchmark sequence.

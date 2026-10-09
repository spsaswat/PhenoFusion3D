# Experimental hyperspectral analysis and RGB-D / ICP fusion

The desktop software now contains the historical `3d_hyperspec_ai` workflow:
spectral calibration and analysis, mapping measured spectra onto RGB-D specimen
surfaces, estimated placement in the existing ICP scene, and the interactive
showcase report. It runs locally without an AI service or the sibling repo's code.

**EXPERIMENTAL: the automatic recipe is restricted to the reviewed 28 August
2026 recording. This integration is unvalidated on new datasets.** Replaying the
old recording is a software check, not independent validation of physical
cross-sensor calibration, plant physiology, or accuracy on other plants.

The existing reconstruction and trait workflows remain available. Their current
implementation was preserved; none of the older reconstruction code was copied
over them. In particular, the successful Coleus recording ending `109` cannot be
given spectra from the unrelated August recording.

## Open the workflow

Start the software normally with `main.py`. Open **Analysis**, then the offline
analysis window, then **Hyperspectral / fusion · experimental**.

1. Select the paired FX10 / FX17 recording folder. For the historical run this is
   `3d_hyperspec_ai/data/20260828`, containing both cameras' `.hdr` and `.bil` files.
2. For fusion, select the matching RGB-D recording with its reviewed specimen
   clouds and ICP results: `data/main/test_plant_20260828120800_best_lighting`.
3. Choose a new results parent folder outside all input folders. Each GUI run
   receives a separate timestamped directory. Existing runs are never overwritten.
4. Choose a workflow below and use **Check historical inputs** first. This checks
   file content, not just filenames. The check does not run scientific processing
   or establish that optional dependencies are installed.
5. Run the selected workflow. Read the progress log and then **Open latest result**.

| Workflow | Required inputs | Result |
|---|---|---|
| Spectral analysis only | Original paired FX10 / FX17 recording | Calibration, masks, alignment and merge, spectra, 14 index maps, spectral report |
| Fusion from existing spectral results | Completed historical spectral bundle and matching reviewed RGB-D recording | Measured spectral points on the three specimen surfaces, estimated global ICP placement, interactive report |
| Spectral analysis → RGB-D / ICP fusion | Original paired hyperspectral recording and matching reviewed RGB-D recording | Both stages in one run |

For fusion from saved spectra, select the folder containing `quality_metrics.json`,
`cubes/`, `indices/`, `tables/` and `figures/`, such as the original
`results/20260828_showcase`. A new spectral run from this integration is also
accepted through its input and output fingerprint manifest.

The historical RGB-D folder must contain the selected RGB/depth images, camera
intrinsics, `merge_simple_full_step10` reconstruction summary and diagnostics,
and the existing `validation` specimen clouds, trait reports, manual photographs
and guided leaf images. These are reviewed **inputs** to the copied fusion recipe;
this action does not reconstruct the scene or recompute those historical traits.
Missing inputs are reported in the log. Copy the complete reviewed folder when
moving it to another machine. Raw datasets and generated reports are not in Git.

## Optional dependencies and report display

The new tab loads without hyperspectral or WebEngine dependencies. Scientific work
and the report viewer run in separate processes using the application's Python
environment. Capture takes priority: active capture blocks new analysis/viewer
jobs, and starting capture closes these optional processes. Closing the analysis
window also closes them. Cancelled outputs are labelled incomplete.

The optional dependency groups in `pyproject.toml` are `hyperspectral` and
`hyperspectral-viewer`. Install them in a separate analysis environment first:

```sh
python -m pip install -e ".[hyperspectral,hyperspectral-viewer]"
```

Use the same Python environment to start the app. Do not upgrade the working lab
camera/ROS/Qt installation just to preview this feature. The lab dependency pins
and setup scripts are unchanged. A separate analysis environment can process
copies of the lab's saved recordings without any camera attached.

With a compatible PyQtWebEngine installation, **Display saved report in software**
opens an application report window with the interactive 3D viewer and point
spectra. Without it, the window provides a static HTML view and **Open in browser**
for full interaction. The original saved `index.html` can also be opened directly;
the application's warning remains visible. No public web server is required.

In the interactive report, select a specimen or the global ICP scene and an index
colour layer. Drag to rotate, use zoom controls, and click a coloured measured
point for its spectrum and source-pixel information. Grey context points have no
measured spectrum. Downloads include PLY geometry and spectral arrays. Keep the
entire report folder together when copying it; `index.html` alone is insufficient.

## What the mapping means

The preserved recipe calibrates the two measured ENVI cubes using the recorded
white/dark regions, samples spatially at stride four, registers FX17 to FX10 and
combines them into 427 spectral bands. It calculates the original 14 indices:
NDVI, NPCI, PSRI, PRI, SR, SIPI, RENDVI, NPQI, NDRE, CCCI, CRI2, NDWI, MSI and NDNI.
These maps are descriptive outputs, not validated diagnoses of plant health.

For each known specimen, image registration maps hyperspectral pixels to a
selected RGB image. Valid observed depth and camera intrinsics place them in
that camera's metric coordinate system. The recipe selects a foreground layer
and retains points within 20 mm of the reviewed specimen cloud. It keeps measured
spectra with those points; it does not fill all unobserved surfaces with spectra.
The fusion recipe uses a pinhole projection and does not implement a general
lens-distortion or calibrated push-broom sensor model.

The legacy merged scene did not store a complete camera-pose trajectory. The
copied placement stage estimates each specimen's rigid transform into a sampled
ICP scene using dataset-specific starting locations. Its held-out surface
distances are internal consistency checks against related geometry, not an
independent physical accuracy measurement or recovery of every original pose.

The original scientific arrays retain metre coordinates and float32 spectra.
The browser display normalizes geometry for viewing and quantizes spectra to
16-bit values to reduce payload size. Use the exported arrays for analysis, not
measurements taken from screen coordinates or rounded inspector values.

## Outputs

Each run contains `preflight.json`, `run_status.json`, and, after processing:

```text
results/20260828_showcase/
  index.html
  cubes/                     calibrated and merged ENVI products
  indices/                   index products
  figures/ and tables/       plots and numerical summaries
  quality_metrics.json
  rgbd_icp/                  staged historical geometry/trait evidence [fusion]
  fusion/                    specimen PLYs, spectral NPZs, viewer assets [fusion]
  global_placement/          estimated transforms and scene overlays [fusion]
  integration_manifest.json verified input provenance and spectral fingerprints
  integration_checks.json   local-link and numerical consistency checks
```

The GUI writes a sibling `.log` file. `complete_experimental` in the run status
means the software stages and output checks completed; it is not scientific
acceptance. A failed or cancelled run may contain partial products and must not
be presented as a finished result. The original 1.2 GB full-resolution scene is
not duplicated; the report contains a sampled scene and explains where the
original remains.

## Other datasets and the next validation step

**Open manual spectral workspace** exposes the copied interactive calibration,
background removal, spectra, spatial registration, merge/split and index tools.
Other compatible ENVI inputs can be explored there, but this path has not been
validated on new recordings. Review and change the original ROI defaults; never
assume the old white/dark coordinates suit a new scan. Choose new save destinations
in the legacy dialogs. Closing this workspace does not imply a fusion run passed.

Automatic processing rejects input files whose hashes differ from the reviewed
recording. Renaming a new file to an old filename cannot bypass this restriction.
Do not edit the profile hashes merely to make a new recording pass: its fixed
regions, specimen matches, frame IDs, depth scale and placement seeds would still
be wrong. Arbitrary dataset fusion needs additional implementation and testing.

Before extending support, collect matched hyperspectral and RGB-D observations of
the same stationary plants, white/dark references, synchronized timing/gantry
positions, camera intrinsics/distortion and cross-sensor calibration. Save every
accepted RGB-D frame pose and its coordinate convention. Review the correspondence
and visibility of each specimen, including occlusions and plant motion; validate
registration with independent landmarks and geometry/traits with physical
measurements. Test on held-out recordings before enabling a new automatic profile.
Additional views can increase coverage, but measurements cannot be assigned to
unseen surfaces without further observations.

## Command-line equivalents

Paths below are placeholders. Every run output must be new and separate from inputs.

```sh
python -m processing.hyperspectral all --hsi "PATH/20260828" --rgbd "PATH/test_plant_20260828120800_best_lighting" --output "PATH/new-check" --inspect-only
python -m processing.hyperspectral spectral --hsi "PATH/20260828" --output "PATH/new-spectral-run"
python -m processing.hyperspectral fusion --spectral-results "PATH/20260828_showcase" --rgbd "PATH/test_plant_20260828120800_best_lighting" --output "PATH/new-fusion-run"
python -m processing.hyperspectral all --hsi "PATH/20260828" --rgbd "PATH/test_plant_20260828120800_best_lighting" --output "PATH/new-combined-run"
python -m processing.hyperspectral workspace --output "PATH/new-manual-session"
python -m app.hyperspectral_report "PATH/20260828_showcase/index.html"
```

See [HYPERSPECTRAL_INTEGRATION_EVIDENCE.md](HYPERSPECTRAL_INTEGRATION_EVIDENCE.md)
for provenance, implementation boundaries and the checks actually performed.

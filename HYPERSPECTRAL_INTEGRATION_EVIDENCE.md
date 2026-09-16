# Hyperspectral integration evidence — 17 September 2026

## Scope and provenance

The integration adds the previous `3d_hyperspec_ai` spectral analysis and measured
spectra-to-RGB-D / ICP workflow to PhenoFusion3D. It is explicitly experimental
and limited to the reviewed 28 August dataset. No new hyperspectral dataset or
lab hardware was available for validation.

Source repository HEAD was `49521698cd7c1fb903071f9d4a0c435c9bce7b46`. Its working
`scripts/` files were untracked, so that commit alone does not identify the
working pipeline. All 33 imported files have recorded byte counts and SHA-256
hashes in `processing/hyperspectral/legacy/SOURCE_MANIFEST.json`. They were copied
byte-for-byte, including the viewer JavaScript that lived in the saved result
folder. `.gitattributes` disables text conversion for this snapshot. Scientific
changes, if later needed, must be distinguished from this preserved source.

The copy includes app modules, scripts, notebooks, README, requirements and the
source MPL-2.0 licence. It excludes editor scratch files, environments, raw
recordings and generated scientific results. The imported code retains its
[MPL-2.0 licence](processing/hyperspectral/legacy/LICENSE); the root project's
licence does not replace it.

## Source architecture and integration

| Source component | Responsibility | How it is used here |
|---|---|---|
| `app/main.py`, preprocessing modules | Manual calibration, ROI selection, white/dark references, masks | Isolated optional manual workspace with an experimental banner |
| `app/analysis/` | Spectrum inspection, cross-calibration, spatial registration, merge/split and indices | Preserved manual tools; no universal automatic fusion implied |
| `scripts/generate_showcase.py` | Headless paired-cube calibration, spectral analysis and HTML report | Original script invoked with selected paths and the historical stride |
| `scripts/fuse_rgbd_hyperspectral.py` | Image correspondence, observed-depth backprojection and specimen filtering | Original measured-spectrum mapping recipe |
| `scripts/recover_global_placement.py` | Estimate specimen-to-scene rigid transforms | Original dataset-specific recovery into the sampled legacy scene |
| `scripts/build_interactive_viewer_assets.py`, saved `fusion/viewer.js` | Pack geometry, indices and spectra; interactive display | Original payload builder plus separate display-only adaptations |
| Validation scripts and PowerShell launch/staging scripts | Original orchestration and report checking | Retained for provenance; portable Python wrapper stages assets and adds output checks |
| `notebooks/` | Earlier exploration utilities | Preserved reference material, not part of automatic execution |

The wrapper lives outside the snapshot: `workflow.py` checks inputs and executes
stages; `reports.py` labels and verifies report bundles; `workspace.py` launches
the original manual UI. `app/analysis_dialog.py` exposes three run modes and a
manual workspace. `app/hyperspectral_report.py` opens reports in a separate Qt
process, with optional WebEngine and a static fallback.

Original Windows/WSL paths in historical launch scripts are not used by the new
runner. Operator-selected paths are resolved before scripts change their working
directory. The sibling source repo is unnecessary after copying the required
data. All scientific processing is offline; optional packages must already be
installed.

## Historical assumptions retained

The source uses the explicitly selected BIL files as little-endian uint16,
zero-offset BIL data. It does not provide a general ENVI format adapter in the
headless recipe. Both recordings have 224 bands; spatial stride is four and the
merged product contains 427 bands.

Calibration regions are `(row_start, row_end, column_start, column_end)`, with
exclusive end coordinates:

| Camera | White | Dark | Scene |
|---|---|---|---|
| FX10 | `(77,110,165,900)` | `(2091,2100,165,900)` | `(110,2091,165,900)` |
| FX17 | `(28,30,75,545)` | `(2085,2087,100,540)` | `(30,2085,75,545)` |

| Specimen | Reviewed cloud | RGB-D frame | Global x seed (m) |
|---|---|---:|---:|
| Coleus | plant_2 | 330 | 0.62 |
| Fuzzy kalanchoe | plant_3 | 540 | 0.97 |
| Succulent / jade | plant_1 | 750 | 1.18 |

The fusion recipe also retains fixed specimen image regions, foreground selection,
depth scale 10,000 units/metre, depth interval 0.30–1.50 m, and a 20 mm
specimen-surface proximity filter. Image registration combines SIFT, RANSAC and
ECC. This is a planar image-registration prototype followed by pinhole depth
backprojection, not a physically calibrated general push-broom camera model.

The original scene contains 44,430,791 points. Global recovery uses its 300,000
point sample and dataset-specific spatial/colour filters. Alternating voxel
samples provide a fit/held-out split; both originate from related reconstruction
data. Small held-out distances do not establish independent physical accuracy or
full recovery of the 95-frame historical reconstruction trajectory.

`profile_20260828.json` hashes the four raw HSI files, selected RGB-D images and
intrinsics, reviewed specimen clouds and sampled scene. It also fingerprints the
53 historical spectral products needed for fusion. New runs write their own
spectral fingerprints with the original input provenance. These checks prevent
accidental use of this recipe on different recordings; they are not a security
signature or biological validation.

## Packaging changes outside the scientific snapshot

- Each run writes fresh outputs and explicit status/provenance. It rejects
  existing nonempty destinations and destinations overlapping selected inputs.
- The report bundle includes the nested historical validation images. Links to
  the external 1.2 GB scene become a local explanatory page; the sampled scene
  remains included. Relative links are checked for existence and containment.
- Every generated HTML page and the report window clearly display the experimental
  status. Spectral-only reports do not claim fusion or placement was executed.
- The old report's fixed 10,485-point sentence now reports the actual output
  count. A fixed sub-five-millimetre narrative was replaced by a reference to the
  current measured consistency tables.
- Generated viewer download links now resolve relative to `index.html`. Picking
  prefers measured spectral points over overlapping grey context within the
  original click radius. No spectra are inferred for grey points. A content
  version on the viewer script prevents stale browser caching. The preserved
  source JavaScript is unchanged.

## Preservation of the working lab software

The integration base was main `ea17b77`, including the reconstruction and trait
work from `0359583`. Source comparisons leave `main.py`, `capture/`, the controller,
capture/quality/gantry workers, reconstruction/ICP modules, `processing/rgb_recovery/`,
trait modules, setup/launcher scripts and camera pins unchanged. Existing app edits
are confined to the optional analysis dialog and its menu label. The hyperspectral
and viewer dependencies are optional extras, not additions to lab startup.

Existing earlier research remains separately preserved as described in
[ANALYSIS_INTEGRATION_EVIDENCE.md](ANALYSIS_INTEGRATION_EVIDENCE.md). The original
recordings, earlier outputs and sibling source repository were not rewritten.

## Recorded-data replays

All three modes completed on the original recording in fresh local folders:

| Mode | Local evidence under `generated/hyperspectral/` | Output checks |
|---|---|---|
| Spectral analysis | `spectral_verification_20260917/` | 2 HTML pages, 25 local references |
| Fusion from historical saved cubes | `fusion_verification_20260917/` | 3 HTML pages, 90 local references |
| Raw spectral analysis through fusion | `combined_verification_20260917/` | 3 HTML pages, 90 local references |

The combined replay produced **10,719 measured spectral points × 427 bands**:
5,807 Coleus, 2,539 fuzzy kalanchoe, and 2,373 succulent/jade. This differs from
the older saved 10,485-point result. The copied scientific files are byte-identical;
the numerical output is not claimed to be byte-identical across software/runtime
environments. The current result passed finite-array and point-count checks,
rigid-transform checks, and the historical held-out scene-distance gates (median
under 10 mm, P90 under 20 mm, over 95% within 20 mm).

The interactive browser report was inspected with real generated data: the
experimental banner, model rendering, colour changes, zoom, global scene switch,
download targets, and measured-point spectrum inspector. A selected Coleus point
reported processed HSI pixel `(row=182, column=96)` and RGB-D pixel
`(u=692, v=442)`. This confirms the display/inspection path, not physical accuracy
of that correspondence.

For replay, missing optional packages were installed only in an ignored test
folder. The existing lab environment was not upgraded. Generated data, logs and
screenshots are local verification artifacts and are not part of the source commit.

The separate desktop report window loaded the generated HTML and rendered the
Coleus model with its live 5,807-point viewer status using isolated
PyQtWebEngine 5.15.7 / Qt 5.15.2. The initial split-package test setup lacked a
complete Qt resource layout; assembling the complete Qt package in the test
folder resolved that environment issue. A screenshot of the final report window
was inspected. The static QTextBrowser fallback also loaded successfully without
WebEngine. The preserved manual workspace opened with its calibration controls
and experimental warning; this is a startup check, not a new-data manual analysis.

A wheel was built from a separate source staging folder. Every one of the 33
imported files was present with its original hash, together with the input
profile, source manifest and report viewer. This check caught and corrected the
package-data pattern for nested notebooks. The current reconstruction remains the
active implementation; the imported reconstruction notebook is reference material.

## Verification boundaries

The regression run passed **159 tests**, with five known baseline cases
deselected. `tests/test_e2e.py` was excluded from collection because the clean
baseline lacks its `processing.canopy` import. Three deselected TSDF cases expect
configuration fields absent from that baseline; two setup-script cases depend on
Linux behavior under this Windows test host. These same pre-existing exclusions
are documented in the reconstruction integration evidence. No new test failure
was hidden by these exclusions.

After the final report and packaging adjustments, the 18 hyperspectral and
desktop lifecycle tests passed again. The full suite was not used as a claim of
hardware operation or generalization to new recordings.

The source/provenance, input rejection, output preservation, report portability
and desktop lifecycle checks are automated software evidence. Browser interaction
is display evidence. No new hyperspectral recording, independent cross-sensor
ground truth, or connected RealSense/gantry acceptance test was performed.

Follow [HYPERSPECTRAL_WORKFLOW.md](HYPERSPECTRAL_WORKFLOW.md) for operation and the
data/calibration required before extending automatic support. The feature must
remain experimental until those checks are completed on new data.

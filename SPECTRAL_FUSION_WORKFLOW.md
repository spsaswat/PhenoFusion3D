# Measured spectral review and sparse 3D fusion

This offline workflow inspects saved hyperspectral measurements and associates
explicitly reviewed source pixels with existing RGB-D / ICP vertices. It adds a
**Spectral review / 3D fusion** tab to the analysis window. It requires no AI
service at runtime and does not change camera capture, ROS, gantry movement,
`main.py`, the existing reconstruction algorithms or their dependency pins.

The software accepts compatible extraction results and reviewed correspondence
setups through files. This is reusable input support, not validation on arbitrary
new datasets, automatic cross-camera calibration or automatic identification of
every leaf. Empty or unsupported correspondence sets cannot become a completed
fusion result. The older, dataset-restricted August workflow remains documented
separately in [HYPERSPECTRAL_WORKFLOW.md](HYPERSPECTRAL_WORKFLOW.md).

## Current confirmed-board result (8 October 2026)

The final recheck is archived in [docs/results/20260928-confirmed-board](docs/results/20260928-confirmed-board/README.md). It uses the confirmed 25 mm square / 18 mm marker board. The final Plant 5 cloud has 154,648 points, with six provisional spectra from **both FX10 and FX17 at three shared vertices**. The 13,343 camera-space samples are preserved. The website also includes an exploratory FX17 1301.56/1449.68 nm signal ratio, separate from the application's six FX10 descriptors. Unknown white reflectance, unconfirmed dark capture, and failed elevated projection checks prevent claims of calibrated reflectance or dense physical fusion.

The complete website results are saved in unsigned website commit `cd1c30bc315398aaf21b5afd70b2b4bf1528a9e7`; publication requires a separate push. The following section documents the earlier initial September output, preserved for provenance. Its cloud count and unresolved board-scale statement are historical, superseded by the final archive.

## Initial September result and its historical scope

The saved September inspection contains **13,343 previously extracted source-pixel
spectra**: 7,982 FX10 and 5,361 FX17, each with its original 224 recorded bands.
These are reviewed patch samples, not all pixels in the recordings and not
verified whole-plant identities. The two sensors retain separate wavelengths,
sample IDs and products; the workflow does not concatenate their spectra.

The new sparse fusion contains **three provisional FX10 correspondences on two
Plant 5 leaves**, linked to exact vertices in the cleaned 156,185-point Plant 5
cloud. Two features are on the upper red leaf and one on the lower green leaf.
Their full 224-band DN spectra were extracted separately at the selected pixels.
Feature matching, visual review, recovered-depth support and the accepted ICP
poses support these candidate associations. They have not been independently
confirmed by a human or validated with withheld physical control points.

Both red-leaf pixels lie outside the reviewed reference coverage. Their raw DN
remains available, while Q/Q0 and derived descriptors remain missing; one also
has suspected clipping. The green-leaf pixel has supported reference-relative
values. Missing floating values are NaN in NPZ, blank in CSV and shown as missing
in the viewer. They are never replaced with zero or copied from another leaf.

This result is not dense, physically validated spectral fusion. Unassigned plant
geometry has no spectral value. Marker size is a display aid, not the physical
area sampled by the hyperspectral detector. Coordinate units remain conditional;
checkerboard scale, independent metric checks and physical cross-sensor
registration remain unresolved.

The separately saved reports are:

- `generated/research_spectral_fusion_20261007/v1/spectral_review/index.html`
  for both sensors' reviewed patch spectra.
- `generated/research_spectral_fusion_20261007/v1/sparse_fusion/index.html`
  for the three provisional Plant 5 associations.
- `generated/research_spectral_fusion_20261007/inputs/sparse_fusion_config.json`
  for the measured input paths, hashes and reviewed correspondence records.

Generated data is local and excluded from Git. Earlier frozen result archives
and the earlier lab-test kit were not updated to contain this new work. Preserve
those snapshots and copy the complete new result folders when sharing.

## Use the application

Start the existing app normally and open **Analysis â†’ Offline reconstruction,
traits and hyperspectral fusion...**, then **Spectral review / 3D fusion**.

1. Select an FX10 and/or FX17 extracted-result folder containing
   `measured_spectra.npz`, `measured_spectra.metadata.json` and `summary.json`.
   Select the extraction's `result` folder, not the raw ENVI recording folder.
2. Choose a fresh results parent outside the inputs and click **Build interactive
   spectral review**. A separate output is created for each run.
3. To prepare measured associations, use **Create 3D fusion setup template**.
   Fill its JSON with actual reviewed source identities, geometry and evidence.
   The generated example describes the format; it is not a measured observation.
4. Select the completed setup and click **Build sparse measured fusion**.
   **Open latest result** opens the guarded research viewer.

For a new raw recording, first use the sixth **Research workspace** tab's
**Extract measured spectra from reviewed regions** action with an explicit ENVI,
region and reference configuration. See [docs/RESEARCH_WORKSPACE.md](docs/RESEARCH_WORKSPACE.md).
Review new tissue regions and reference assumptions; do not reuse September's
regions merely because the file dimensions match.

All new actions share the existing analysis subprocess lifecycle. An active
capture or processing job blocks their start. Starting capture cancels the
optional analysis/viewer processes; cancelled or failed outputs remain incomplete.
Interactive reports work in the optional WebEngine viewer or a normal browser;
without WebEngine, the app shows a static report with an **Open in browser** action.
Do not change a working lab camera/ROS environment merely to install a viewer.

## Inspect spectra and descriptors

The 2D inspector provides sensor selection, recorded-band selection, exact sample
ID selection, measured-pixel maps and full spectral curves. Selecting an
unmeasured map location does not create a sample. The 3D inspector colours only
the sparse reviewed markers, offers RGB or grey context, and links each marker
back to its exact source spectrum. Rotate and inspect side views; a checkbox
explicitly controls whether annotation markers show through geometry.

Raw DN is the saved unsigned camera signal. Where reference support is available,
`Q = (DN - D) / (W - D)` uses the explicitly assumed/confirmed dark reference;
`Q0 = DN / W` is the zero-offset sensitivity case with the same conservative
support. The white board's spectral reflectance is unknown and the September
dark tail is unconfirmed. These signals are not calibrated reflectance.

The saved FX10 descriptors are NDVI, NDRE, GNDVI, PRI, PSRI and SIPI, using the
recorded bands identified in `summary.json` rather than pretending the nominal
wavelengths were recorded exactly. FX17 retains no supported descriptor from
this six-index selection; missing wavelengths are not borrowed from FX10.
Descriptor values are exploratory, not validated plant-health or physiological
measurements. Review the quality flags and the Q-versus-Q0 sensitivity.

Band flags record missing reference support, suspected sample/reference clipping,
weak reference contrast, raw zero and low signal. Invalid normalized bands remain
missing. Index flags separately reject unsuitable required bands and unstable
denominators. Sparse markers with invalid selected values stay grey. Curves do
not connect across missing bands.

## Required fusion setup

Use `spectral_fusion_template.json` as the schema guide. Relative paths resolve
against the setup file's parent directory, not the output directory. IDs and
indices refer to unchanged source files. Do not reorder/resample the PLY and then
reuse its old indices or replace a hash simply to bypass a changed-input error.

| Setup field | Required meaning |
|---|---|
| `schema_version` | `1` |
| `frame_id`, `coordinate_unit` | Explicit shared source frame and units; use `unknown` or `conditional_m` when appropriate. A units label does not verify physical scale. |
| `upright_R` | A finite proper 3Ã—3 display rotation. Rescaling and reflection are rejected. Source-reference XYZ is preserved separately. |
| `clouds` | Each cloud's unique `id`, local PLY path `cloud` and reviewed `sha256`; optional `label`. |
| `sensors` | Each sensor's unique safe `id`, extraction `result_dir` and reviewed `spectra_sha256` of `measured_spectra.npz`. |
| `evidence` | Unique `id`, local source `path` and `sha256` for each reviewed supporting artifact. |
| `associations` | Nonempty explicit source correspondences, using the record fields below. |

Each association records a unique `id`, `sensor_id`, zero-based `sample_index`,
`cloud_id` and zero-based `point_index`. A sample index is the measured NPZ row;
the software retrieves its original scan line, detector column and patch ID.
A point index is the original PLY vertex. Boolean, fractional, negative,
out-of-range and repeated assignments are rejected. A sensor pixel cannot be
reused, and one sensor cannot assign multiple spectra to the same cloud vertex.

The record also requires `status: "provisional_reviewed_correspondence"`,
`reviewer`, `review_method`, `feature_description` and nonempty `evidence_ids`.
Provide an observed `localized_reference_xyz`, a justified positive
`maximum_vertex_distance` in those coordinate units, and an integer
`supporting_rgb_pairs` of at least two. The latter is declared reviewed support
for this recovered-depth workflow, not independent validation performed by the
fusion builder. Proximity to a vertex does not prove cross-camera identity.

The builder checks completed extraction status, NPZ/metadata hashes, original
array dimensions, source coordinates, band order, quality flags and missing-value
rules. It checks input fingerprints before/after processing. It never upgrades
operator declarations into verified physical calibration or invents associations
when no reviewed correspondence exists.

## Command-line equivalents

Run these from the repository with a suitable existing analysis Python
environment. Replace the paths with your inputs and choose a new output for each
command. Create the setup first, review/edit its placeholders, and only then build
fusion. No camera needs to be attached.

Linux:

```sh
python -m processing.research_workspace.spectral_viewer --sensor "fx10=/data/extraction/fx10/result" --sensor "fx17=/data/extraction/fx17/result" --output "/data/results/new-spectral-review"
python -m processing.research_workspace.spectral_fusion template --output "/data/results/new-fusion-setup"
python -m processing.research_workspace.spectral_fusion build --config "/data/results/new-fusion-setup/spectral_fusion_template.json" --output "/data/results/new-sparse-fusion"
python -m app.research_report "/data/results/new-sparse-fusion/index.html"
```

Windows PowerShell:

```powershell
python -m processing.research_workspace.spectral_viewer --sensor "fx10=C:/data/extraction/fx10/result" --sensor "fx17=C:/data/extraction/fx17/result" --output "C:/data/results/new-spectral-review"
python -m processing.research_workspace.spectral_fusion template --output "C:/data/results/new-fusion-setup"
python -m processing.research_workspace.spectral_fusion build --config "C:/data/results/new-fusion-setup/spectral_fusion_template.json" --output "C:/data/results/new-sparse-fusion"
python -m app.research_report "C:/data/results/new-sparse-fusion/index.html"
```

The review CLI accepts one to eight separately named sensor inputs; the app
offers FX10/FX17 fields. Sensor IDs use 1â€“64 ASCII letters, numbers, underscores
or hyphens, starting with a letter or number. Omit an unavailable sensor. Add
`--no-csv` to the spectral-review command if full CSV exports are unnecessary;
the unchanged NPZ downloads remain available.

## Outputs, preservation and verification

The standalone spectral review contains `index.html`, a manifest and checksums,
plus `sensors/ID/` with copied authoritative NPZ/metadata/summary files, local
viewer assets, `sample_bands.csv.gz` and supported `sample_indices.csv.gz`.
The browser also exports an individual sample spectrum. There is no CDN or
network service dependency.

The fusion output contains `index.html`, `fusion_data.js`, `associations.json`
and `.csv`, per-sensor `assigned_spectra_ID.npz`, `assigned_points_reference.ply`,
unchanged `clouds/`, copied `evidence/`, `summary.json`, `run_status.json` and a
complete nested `spectra/` inspector. NPZ products preserve full measured bands,
raw dtype, Q/Q0 values including NaNs, quality flags, descriptor values, original
source IDs and both reference/upright XYZ. The geometry itself is not altered.
The viewer may subsample context geometry for responsiveness; the downloadable
source PLY remains unchanged.

`complete_sparse_provisional_correspondence_fusion` means the software built the
declared sparse association products. `physical_fusion` remains `null`, and
physical registration, calibrated reflectance and dense fusion remain false.
Check `run_status.json` before using partial outputs. Preserve the full output
folder together; `index.html` alone is insufficient. Hashes establish file
identity, not scientific accuracy.

Focused checks at implementation time passed: 44 sparse-fusion tests, 22 analysis
UI tests and 17 spectral-viewer tests. They cover exact sample/coordinate
preservation, quality/missing-value handling, stale or changing inputs, duplicate
assignments, output preservation and capture-priority process controls. These
are software checks, not physical lab acceptance or new-dataset validation; the
separate final regression evidence records the broader test run.

Dense physical fusion still requires applicable HSI spatial/line-timing and rig
calibration, confirmed scale, reviewed same-surface correspondences, independent
off-plane validation, visibility/occlusion handling and documented white/dark
references. Further plant views are needed for unobserved tissue. This sparse
result does not resolve those missing acquisition/calibration measurements.

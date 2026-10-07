# Local research workspace

The **Research workspace** tab assembles saved point clouds, research reports,
explicit endpoint measurements and an evidence-gap ledger into one local review.
It accepts a setup JSON file for each dataset. Building a workspace reads supplied
clouds and links existing analyses; reconstruction, source-mask creation and
spectral processing remain separate stages.

The workspace preserves uncertainty. Cloud ranges describe the supplied points;
they do not establish anatomical plant height, complete leaf area or plant volume.
Endpoint comparisons remain provisional, and all physical-accuracy and calibrated
3D spectral-fusion outcome flags remain false.

## Use the desktop tab

1. Start the normal application with `python main.py` or the existing lab launcher.
   Open **Analysis → Offline reconstruction, traits and hyperspectral fusion...**,
   then **Research workspace**.
2. Choose a **New results parent folder** outside the recordings and source
   results. Each desktop run creates a fresh timestamped child directory.
3. Select an existing **Workspace setup JSON**, or choose **Create workspace setup
   template**. The template creates `workspace_template.json` and a short HTML
   instruction page. After success, its JSON path fills the setup field. Edit
   that file to supply actual cloud paths and known evidence before building.
4. Choose **Build / check research workspace**. At least one specimen cloud is
   required. The job validates inputs, computes observed ranges, records input
   fingerprints and writes `result/index.html` with the point reviewer.
5. Use **Open latest result** or select an existing `result/index.html` under
   **Saved workspace report**, then choose **Open saved workspace report in
   software**. The report's point-review link opens the endpoint picker.
6. If you export endpoint JSON, select it under **Reviewed landmark JSON
   (optional)** and rebuild into a new output directory. Exported picks start
   unreviewed; the field label does not confer review or calibration status.

The default results parent is `generated/research_workspace/`. If the local
`generated/research_followthrough_20261007/workspace_manifest.json` exists, its
path is offered as a convenience. Neither this file nor the September recordings
are required to use a new setup.

When the corresponding saved endpoint JSON and report are present beside that
setup, the tab offers them too. Creating a new workspace template clears the
old endpoint selection so it cannot silently carry into a different dataset.

The same tab also has **Spectral extraction setup JSON** and **Extract measured
spectra from reviewed regions**. This separate action reads the declared local
ENVI recording, selected regions and reference assumptions; it writes a new
measured-spectra report under the selected results parent. It does not rebuild
geometry or map spectra onto 3D leaves. See the
[spectral extraction guide](RESEARCH_SPECTRAL_EXTRACTION.md) for the input
contract and supported format. The older hyperspectral tab keeps its original
August dataset restriction.

The tab uses the existing isolated analysis process. An active capture,
reconstruction, quality check or post-processing job prevents it from starting.
Starting capture cancels an active offline job; cancelled output is partial and
must not be treated as a completed run. Opening a saved report also respects the
capture/processing busy guard.

Research results use their own report window and provisional-measurement banner.
Interactive point review uses optional PyQtWebEngine or a local WebGL-capable
browser. If WebEngine is unavailable, the window shows a static report; use
**Open in browser** for 3D inspection and endpoint selection. The existing
`hyperspectral-viewer` optional dependency group supplies WebEngine without
changing the historical hyperspectral report window.

## Command-line equivalents

Run from the repository root with the application's Python environment. Every
`--output` must name a fresh, empty directory. These example output names are
arbitrary and must be changed if they already contain a previous run.

```text
python -m processing.research_workspace template --output generated/workspace_setup
python -m processing.research_workspace build --manifest generated/workspace_setup/workspace_template.json --output generated/workspace_run_01
python -m processing.research_workspace build --manifest generated/workspace_setup/workspace_template.json --annotations research_endpoints.json --output generated/workspace_run_02
```

Edit the generated setup before the first build. `--annotations` is optional;
without it, the report contains no endpoint measurements and no comparison score.
The CLI does not invoke capture, a camera, ROS, a gantry or an online service.

## Setup schema

This example shows the structure for one specimen and an original scene. The
filenames are illustrative; replace them with existing local files. Use identity
`upright_R` only when those clouds already share the intended Z-up frame.

```json
{
  "schema_version": 1,
  "title": "Reviewed specimen workspace",
  "coordinate_unit": "unknown",
  "scale_status": "unverified",
  "upright_R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  "specimens": [
    {"id": "P1", "label": "Plant 1 candidate", "cloud": "P1_candidate.ply"}
  ],
  "context_clouds": [
    {"id": "scene", "label": "Original scene", "cloud": "original_scene.ply"}
  ],
  "artifacts": [],
  "manual_references": [],
  "protected_input_roots": [],
  "gaps": [
    {
      "id": "physical_scale",
      "title": "Physical scale needs independent evidence",
      "status": "unresolved",
      "resolution": "Recover acquisition units and an independently measured reference."
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `schema_version` | Must be `1`. |
| `specimens` | Nonempty list of specimen candidates. Each requires a unique nonempty `id` and an existing `cloud` PLY; `label` is optional. |
| `context_clouds` | Optional scene/uncertainty clouds in the same coordinate frame. IDs must be unique across both cloud lists. Context clouds do not receive specimen range descriptors. |
| Cloud `sha256` | Optional expected SHA-256 fingerprint. A mismatch rejects the cloud. The current fingerprint is recorded even when no expected hash is supplied. |
| `coordinate_unit` | Exactly `unknown`, `conditional_m` or `m`. This declaration never rescales the cloud. Use `conditional_m` when coordinates follow a metre convention with unresolved physical scale. |
| `scale_status` | Descriptive evidence status shown in the report. It is not a calibration switch. |
| `upright_R` | One finite proper 3×3 rotation applied to every cloud. It cannot encode translation, reflection or rescaling. All source clouds must already share one frame. |
| `artifacts` | Optional existing local report/data files, each with `title`, `path` and optional `description`. Building links these files; it does not rerun their analyses. |
| `manual_references` | Optional explicit physical-reference records described below. |
| `protected_input_roots` | Recording/source directories to protect. The output cannot equal, contain or lie inside any listed root. Populate this for every recording directory; it is empty in the generic template because no recordings are known yet. |
| `gaps` | Operator-maintained records with `id`, `title`, `status` and `resolution`. The report preserves this ledger; it does not automatically certify that a gap is resolved. |

Paths inside the setup may be absolute or relative to the setup JSON's directory.
Use forward slashes or escaped backslashes in JSON. CLI `--manifest`, `--output`
and `--annotations` paths resolve from the current working directory. HTTP URLs
are not accepted as source-file paths.

Source files are read only. Output preservation checks reject an existing
nonempty output and any output that would contain an input file. Directory-wide
protection is applied to `protected_input_roots`. The setup, annotations and
clouds are fingerprinted before use and checked again during the build.

## Point review and endpoint definitions

Select the measured specimen, the displayed cloud and the quantity. Choose
**Mark first point**, then double-click a visible point; repeat with **Mark second
point**. Choose **Keep endpoint pair**, then **Download endpoint JSON** when the
desired pairs are queued. Changing the measured specimen or quantity clears an
unfinished pair. Rotate, zoom and inspect the source evidence before accepting a
pick, especially at thin leaves, overlaps and cloud boundaries.

The display may sample a large cloud, using a recorded stride. Each exported
endpoint retains its original zero-based source point index, cloud ID and SHA-256
fingerprint. Normalized preview coordinates are for display; rebuilding measures
the original source vertices after the declared upright rotation. No interpolated
point is created. A missing or unsampled anatomical landmark cannot be recovered
by clicking empty space.

For a selected specimen, endpoints may come from that specimen's cloud or a
declared context cloud. This allows a real stem base retained in the original
scene to be paired with a tip in the cleaned specimen. Endpoints from another
specimen cloud are rejected. Context membership does not prove anatomical
ownership: check the plant/leaf identity against source views.

| `trait` | Required `definition` | Calculation and endpoint order |
|---|---|---|
| `observed_chord` | `straight_distance_between_observed_points` | Euclidean distance between two observed points. The visible tissue may be partial; this quantity never enters physical-reference validation scores. |
| `height` | `vertical_stem_base_to_highest_tip` | Upright Z of tip minus Z of actual stem base; base first, tip second. The result must be positive. |
| `leaf_chord_length` | `straight_blade_base_to_tip_chord` | Euclidean distance from blade base to tip. A curved midrib/ruler-path length is a different quantity. |
| `leaf_section_width` | `straight_width_at_identified_section` | Euclidean distance between the two edges of the identified section. It is not automatically the leaf's maximum width. |

Every measurement requires two distinct source vertices. Point hashes and index
bounds are checked on import. If the anatomical base/tip is absent or the organ
identity is unresolved, retain that gap and leave the measurement unmade. The
lowest remaining point of a cleaned cloud is not a substitute stem base.

The picker's default **Observed tissue distance (may be partial)** is appropriate
when a fragment or visible section can be identified but a complete leaf's blade
base and tip cannot. Preserve a useful partial chord without relabelling it as
whole-leaf length. Optional annotation `label` and `scope` strings are retained
in JSON, CSV and the report, so the measured section and missing endpoints can be
described explicitly. Observed chords remain excluded from manual validation even
if both review flags and a reference are supplied.

The exported annotations use `schema_version: 1` and a `measurements` list.
Each entry carries `specimen_id`, `trait`, `definition`, two `points`,
`landmarks_reviewed: false`, `organ_match_confirmed: false` and
`reference_id: null`. Each point contains `cloud_id`, `source_sha256` and
`point_index`. Review and edit these records only after checking the actual
endpoints and matching physical organ. True review flags enable provisional
comparison eligibility; they never establish calibration or physical accuracy.

## Physical references and provisional comparisons

A `manual_references` entry requires a unique stable `id`, matching `specimen_id`,
the exact compatible `definition`, a finite positive `value`, `unit: "m"`, an
`evidence_status`, and a nonempty `source` description. Supported evidence labels
are `operator_reported`, `photo_interval` and `independent_measured`. The source
description should identify the record/photo and the particular plant or leaf
and measurement endpoints. Naming a reference `independent_measured` does not
make its independence software-verified.

Attach a reference by setting the annotation's `reference_id` to its stable ID.
Both review flags must be true; the specimen, quantity and metre units must be
compatible. The workspace permits a comparison with `conditional_m` coordinates
but retains its conditional status. Unknown coordinate units are ineligible.
One reference ID cannot be reused as another independent pair in the same run.

Eligible pairs receive signed and absolute differences. Per quantity, the JSON
summary provides count, mean signed difference, mean absolute error and RMSE.
These arithmetic results remain **provisional matched comparisons** with
`physical_accuracy_validated: false`. They do not independently validate scale,
geometry, reference quality or specimen matching. Empty eligible groups have
`n: 0` and null scores, never zero error.

The current reference schema compares a scalar value. A `photo_interval` label
records its evidence class but does not propagate an interval or confidence bound.
Retain the actual reading range and uncertainty in the source evidence; a selected
scalar must not be described as an exact physical reference. Physical validation
values must not be used to tune cloud scale or choose convenient endpoints.

## Outputs and local dependencies

A successful build writes:

```text
workspace_manifest_snapshot.json
workspace_summary.json
observed_descriptors.json
measurements.json
measurements.csv
run_status.json
result/
  index.html
  point_review.html
  point_review_provenance.json
  research_cloud_0.js
  ...
```

Observed descriptors include each specimen's full X/Y/Z ranges and its 0.5–99.5
percentile ranges. `anatomical_height`, `whole_leaf_area` and `whole_plant_volume`
remain null in these descriptors. Explicit endpoint measurements are stored
separately. `run_status.json` identifies completed candidate workspaces, failures
and cancellations; partially written files do not establish completion.

The saved `workspace_manifest_snapshot.json` resolves cloud, artifact and
protected-directory paths to their original absolute locations and pins the cloud
hashes. It can be passed to a later `build --manifest` on the same machine while
those source files remain available. To reproduce imported endpoint measurements,
also pass the original endpoint JSON again with `--annotations`; the setup
snapshot does not embed that separate document.

The point preview and its JavaScript assets run offline. **The output directory
is not a self-contained portable bundle:** downloads and linked stage reports
refer to original local files, and those reports can have further image/data
dependencies. Keep their directory relationships intact. Rebuilding requires the
setup's source PLYs, linked files and any imported annotation JSON. Moving or
sharing only `result/` or the new run directory can break those links. Fingerprints
cover the directly supplied files, not every transitive asset of a linked report.

## Hyperspectral boundary

The existing **Hyperspectral / fusion · experimental** tab remains the separate,
hash-guarded replay for the reviewed 28 August 2026 inputs. Its supported dataset,
legacy source and scientific limitations are unchanged; see the
[historical workflow guide](../HYPERSPECTRAL_WORKFLOW.md).

The Research workspace can link later spectral QC and calibration diagnostics.
Its `build` command does not fit a pushbroom model or project spectra. Developers
can separately use `processing.research_workspace.spectral_mapping`:

- `fit_pushbroom_controls` fits an empirical detector-column/scan-line model from
  noncoplanar controls and checks independent withheld off-plane observations
  against explicit numeric pixel thresholds. Recycled controls, deficient
  geometry and failed residual gates are rejected.
- `project_control_model` projects within the fitted control volume and detector
  bounds using the declared shared frame and units.
- `project_physical_pushbroom` computes projection for supplied straight-motion,
  fixed-attitude camera parameters. Supplying those parameters does not establish
  that they were calibrated.
- `mapping_readiness` reports missing evidence. Boolean acknowledgements cannot
  substitute for calibration inputs; even supplied inputs still need numerical
  and scientific validation.

These APIs return projection candidates. They leave `physical_fusion` null and
surface-mapping eligibility false. They do not establish surface visibility,
perform spectral ray/surface assignment, calibrate reflectance or validate plant
physiology. Shared arbitrary units can support pixel checks while physical
dimensions remain unresolved. Planar agreement alone cannot validate elevated
leaf projection.

## Current evidence and generalization

The five-plant continuation uses assistant-reviewed, dataset-specific source
masks and conditional geometry. Accepting new setup files makes the workspace
reusable; it does not demonstrate automatic segmentation or reliable anatomical
landmarks for arbitrary plants. Original, uncertain and scene-context geometry
remain valuable evidence alongside cleaned candidates. Additional physical
calibration and held-out recordings are separate requirements.

See [the 28 September gap ledger](RESEARCH_GAPS_20260928.md) for the currently
unresolved dimensions, units, organ definitions, radiometry, pushbroom geometry
and coverage. The workspace adds no changes to `main.py`, acquisition, RealSense,
ROS or gantry implementation. Computational tests and offline review do not
replace the existing lab hardware acceptance procedure.

# Final sprint GitHub issue drafts

One parent and twelve sub-issues for Adithya Rama, Howard Zhang, Tanisha Sharma and Tianyu Xu. Names come from the current repository contributor list. Assignments are proposed review/handover ownership, not attribution of earlier work. GitHub handles, actual issue numbers and sprint dates have not been invented.

The 52 points use a proposed 3/5-point relative scale and are balanced at 13 per person. They are not hours or a reconstruction of previously committed velocity. Agree these estimates with the team. Future follow-ups are excluded. The parent has zero additional points.

All checkboxes start unchecked so that saved evidence is reviewed before the team closes issues. A research spike can finish with a documented partial or negative result while the wider product goal remains open.

Create the parent first, then the children; replace PARENT_URL and FS dependency references with actual issue links. Use the existing project fields and milestone. These drafts have not been posted or assigned on GitHub.

## Allocation

| Owner | Sub-issues | Points |
|---|---|---:|
| Adithya Rama | FS04, FS08, FS12 | 13 |
| Howard Zhang | FS03, FS05, FS11 | 13 |
| Tanisha Sharma | FS01, FS06, FS10 | 13 |
| Tianyu Xu | FS02, FS07, FS09 | 13 |

## Issue summary

| ID | Title | Owner | Reviewer | SP | Evidence status |
|---|---|---|---|---:|---|
| [FS01](issues/FS01.md) | Audit the five-plant recordings and preserve exact source identities | Tanisha Sharma | Howard Zhang | 3 | Evidence ready for peer review |
| [FS02](issues/FS02.md) | Recheck metric calibration using the confirmed ChArUco board | Tianyu Xu | Adithya Rama | 5 | Metric results ready for peer review; physical accuracy remains unverified |
| [FS03](issues/FS03.md) | Reconstruct and review the D405 five-plant observations | Howard Zhang | Adithya Rama | 5 | Saved reconstruction ready for peer review |
| [FS04](issues/FS04.md) | Reconstruct L515 and fuse supported observations with D405 | Adithya Rama | Howard Zhang | 5 | Selected fusion ready for peer review |
| [FS05](issues/FS05.md) | Separate plant tissue candidates and retain reversible cleanup evidence | Howard Zhang | Tanisha Sharma | 5 | Cleanup artifacts ready for peer review |
| [FS06](issues/FS06.md) | Compare manual traits with matched source-supported plant measurements | Tanisha Sharma | Tianyu Xu | 5 | Conditional comparisons ready for review; complete anatomical validation remains open |
| [FS07](issues/FS07.md) | Extract and inspect both hyperspectral cameras with quality flags | Tianyu Xu | Tanisha Sharma | 5 | Measured camera-space outputs ready for peer review |
| [FS08](issues/FS08.md) | Investigate dense spectral registration and preserve the partial surface result | Adithya Rama | Tianyu Xu | 5 | Research investigation and partial candidate ready for review; full fusion unresolved |
| [FS09](issues/FS09.md) | Audit correspondence controls and correct unsupported accuracy claims | Tianyu Xu | Howard Zhang | 3 | Audit ready for peer review |
| [FS10](issues/FS10.md) | Publish an inspectable results journey with downloads and explicit gaps | Tanisha Sharma | Adithya Rama | 5 | Local build and browser evidence available; latest publication not verified |
| [FS11](issues/FS11.md) | Verify offline analysis integration and complete laboratory regression checks | Howard Zhang | Tanisha Sharma | 3 | Blocked for physical acceptance until the lab machine is available |
| [FS12](issues/FS12.md) | Prepare the final sprint narrative demo and research handover | Adithya Rama | Tianyu Xu | 3 | Draft prepared; team review and final handover remain |

## Parent issue body

# Deliver and evaluate the five-plant final sprint workflow

**Planning ID:** FS00

**Proposed assignee:** Adithya Rama, coordinating with all four team members.

**Milestone:** Final Sprint, use the team's existing milestone and dates.

**Labels:** type:epic, sprint:final, priority:P1

**Estimate:** 0 additional points; 52 points roll up from the twelve sub-issues. Do not add the parent total to the child total.

## User story

As a plant-phenotyping researcher and project reviewer, I want a traceable workflow from recorded calibration data to inspectable geometry, trait comparisons and measured spectra so that I can assess the results and understand their limitations.

## Description

Deliver the final sprint research and software handover for the 28 September five-plant recordings. Cover input integrity, confirmed-board calibration, D405 and L515 reconstruction, geometric fusion, reversible cleanup, conditional manual comparisons, both-camera spectral inspection and bounded spectral fusion experiments. Preserve laboratory capture and gantry behaviour and report local, laboratory and deployed verification separately.

The latest result includes 13 conditional same-organ trait comparisons and an exploratory partial spectral surface with 2,338 FX10 and 862 FX17 observations on two upper P5 leaves. Complete physical validation and full five-plant spectral mapping remain unresolved. This epic does not require inventing missing measurements to appear complete.

## Sub-issues

- [ ] FS01 — Audit the five-plant recordings and preserve exact source identities — Tanisha Sharma — 3 SP
- [ ] FS02 — Recheck metric calibration using the confirmed ChArUco board — Tianyu Xu — 5 SP
- [ ] FS03 — Reconstruct and review the D405 five-plant observations — Howard Zhang — 5 SP
- [ ] FS04 — Reconstruct L515 and fuse supported observations with D405 — Adithya Rama — 5 SP
- [ ] FS05 — Separate plant tissue candidates and retain reversible cleanup evidence — Howard Zhang — 5 SP
- [ ] FS06 — Compare manual traits with matched source-supported plant measurements — Tanisha Sharma — 5 SP
- [ ] FS07 — Extract and inspect both hyperspectral cameras with quality flags — Tianyu Xu — 5 SP
- [ ] FS08 — Investigate dense spectral registration and preserve the partial surface result — Adithya Rama — 5 SP
- [ ] FS09 — Audit correspondence controls and correct unsupported accuracy claims — Tianyu Xu — 3 SP
- [ ] FS10 — Publish an inspectable results journey with downloads and explicit gaps — Tanisha Sharma — 5 SP
- [ ] FS11 — Verify offline analysis integration and complete laboratory regression checks — Howard Zhang — 3 SP
- [ ] FS12 — Prepare the final sprint narrative demo and research handover — Adithya Rama — 3 SP

## Acceptance criteria

- [ ] Every sub-issue has an owner, reviewer, evidence and an accurate status.
- [ ] Saved calibration, reconstruction, cleanup, trait and spectral outputs can be inspected and traced to inputs.
- [ ] The report distinguishes observed geometry, conditional traits, provisional spatial mapping and calibrated physical measurements.
- [ ] Earlier outputs and changed interpretations remain available.
- [ ] Latest results are publicly verified after an authorized deployment, or publication is explicitly carried as incomplete.
- [ ] Actual lab regression results are attached, or the epic remains open for physical acceptance.
- [ ] Final presentation, contribution statements and follow-up gaps are reviewed by the team.

## Out of scope for claims of completion

Do not claim gap-free 360-degree coverage, calibrated reflectance, full-plant dense spectral correspondence, arbitrary-dataset generalization or successful physical hardware testing without supporting evidence. FU01-FU05 capture work requiring new observations or independent validation.

## Evidence

- Project report: `docs/final-sprint-20260928/README.md`
- Issue pack: `docs/final-sprint-20260928/ISSUES.md`
- Compact evidence snapshots: `docs/final-sprint-20260928/evidence/manifest.json`
- Latest local study: http://127.0.0.1:8879/results/final-sprint-20260928/

These are drafts, not already-created GitHub issues. FS identifiers are planning references, not repository issue numbers. Replace PARENT_URL and dependencies with the created issue links, and associate the children with the parent in the team's tracker. Localhost links are only usable on the machine serving the files.


## Sub-issue bodies

# Audit the five-plant recordings and preserve exact source identities

**Planning ID:** FS01

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Tanisha Sharma |
| Reviewer | Howard Zhang |
| Story points | 3 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:data, type:task |
| Dependencies | None; replace with real issue links |
| Evidence status | Evidence ready for peer review |

## User story

As a lab operator, I want incomplete and mismatched recordings identified before processing so that reconstructed results use genuine paired observations.

## Description

Inventory D405, L515, FX10 and FX17 calibration and plant inputs. Verify RGB/depth identifiers and decoding, spectral header dimensions and byte counts, and the relationship between calibration and plant recordings. Preserve the original archive and document the replacement export.

## Current evidence

The initial L515 plant archive had 89 exact pairs. The replacement has 1,278 plant pairs and 1,290 calibration pairs. Do not rename adjacent frames into artificial pairs.

## Acceptance criteria

- [ ] Inventory lists each sensor, recording role, exact pairing and missing metadata.
- [ ] Original and replacement L515 audits are distinguishable and the pairing gap is documented as resolved.
- [ ] Raw files remain unchanged and source identifiers remain traceable.
- [ ] Peer reviewer confirms the inventory and records any unresolved timing or unit assumptions.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/input_inventory.md`
- Project file: `docs/final-sprint-20260928/evidence/l515_replacement.md`

## Risk and scope

Folder naming and exact file pairing do not independently prove synchronization or device depth units.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Recheck metric calibration using the confirmed ChArUco board

**Planning ID:** FS02

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Tianyu Xu |
| Reviewer | Adithya Rama |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:calibration, type:task |
| Dependencies | FS01; replace with real issue links |
| Evidence status | Metric results ready for peer review; physical accuracy remains unverified |

## User story

As a researcher, I want geometry expressed using the actual board dimensions so that reported distances have a documented metric basis.

## Description

Record the confirmed 7 by 10 ChArUco layout, 25 mm squares, 18 mm markers and DICT_4X4_50. Recheck D405 scale, L515 motion and depth interpretations, and the shared hyperspectral table reference. Preserve earlier conditional outputs.

## Current evidence

D405 factor 1.0288746669 and L515 RGB travel factor 1.0296675589. The selected L515 depth conversion is empirical, not certified device metadata.

## Acceptance criteria

- [ ] Board dimensions, metre units, dictionary and confirmation source are explicit.
- [ ] Rechecked geometry, poses and derived dimensions retain original identities and earlier results.
- [ ] RGB motion scale is distinguished from raw depth conversion.
- [ ] Report distinguishes table-plane fitting residuals from elevated-leaf or independent physical accuracy.
- [ ] Peer reviewer checks unit conversions and the recalculated outputs.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/board_confirmation.json`
- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_findings.md`

## Risk and scope

Print tolerance and independent device-unit evidence remain open; a good plane fit does not validate plant-height spectral projection.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Reconstruct and review the D405 five-plant observations

**Planning ID:** FS03

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Howard Zhang |
| Reviewer | Adithya Rama |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:reconstruction, type:task |
| Dependencies | FS01, FS02; replace with real issue links |
| Evidence status | Saved reconstruction ready for peer review |

## User story

As a researcher, I want to inspect reconstructed plants from multiple views so that alignment failures and unobserved surfaces are visible.

## Description

Document the RGB multi-view stereo, scene-supported motion and ICP route, chosen outputs and source-supported views. Preserve separate trials. Inspect all five plants, including fine stems and difficult side views.

## Current evidence

The confirmed-board update re-expresses the existing D405 result at the metric scale; it does not rerun stereo or create new surfaces. Plant 5 has more continuous broad-leaf observations than the difficult thin structures.

## Acceptance criteria

- [ ] Saved cloud, accepted camera poses and processing parameters are traceable.
- [ ] P1-P5 can be inspected from front, side and top with unsupported areas visible.
- [ ] Scale-only changes are distinguished from reconstruction changes.
- [ ] No unobserved surface is presented as a measured gap-free reconstruction.
- [ ] Peer reviewer records the selected result and its coverage limitations.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_findings.md`
- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_verification.json`

## Risk and scope

Occlusion and missing thin structures cannot be repaired simply by increasing point size or relaxing alignment filters.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Reconstruct L515 and fuse supported observations with D405

**Planning ID:** FS04

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Adithya Rama |
| Reviewer | Howard Zhang |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:geometry-fusion, type:task |
| Dependencies | FS01, FS02, FS03; replace with real issue links |
| Evidence status | Selected fusion ready for peer review |

## User story

As a researcher, I want complementary camera observations in a common frame so that I can inspect additional measured surfaces and their source.

## Description

Compare the recorded-depth L515 hypotheses, retain separate reconstructions, align L515 into the D405 reference and preserve per-point camera provenance. Document overlap, excluded conflicts and selection checks.

## Current evidence

Selected union: 1,719,001 D405 inspection points plus 21,672 L515 additions, totalling 1,740,673 points. Matched-soil median disagreement changed from 11.160 to 6.289 mm in the comparable metric candidate comparison.

## Acceptance criteria

- [ ] Both L515 hypotheses and the selected rigid alignment are saved.
- [ ] Fusion counts reconcile and retained points preserve camera and source indices.
- [ ] Selection checks and unselected alternatives are reported without treating tuning data as untouched validation.
- [ ] Geometric fusion is explained separately from spectral-to-surface association.
- [ ] Reviewer verifies provenance and the basis for selecting the final candidate.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_findings.md`
- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_verification.json`

## Risk and scope

The selected P90 and maximum disagreement are 10.326 and 26.037 mm; candidate selection used the checking data.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Separate plant tissue candidates and retain reversible cleanup evidence

**Planning ID:** FS05

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Howard Zhang |
| Reviewer | Tanisha Sharma |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:cleanup, type:task |
| Dependencies | FS04; replace with real issue links |
| Evidence status | Cleanup artifacts ready for peer review |

## User story

As a researcher, I want plant candidates separated from pots and background so that I can inspect traits while recovering any questionable exclusions.

## Description

Review source-image tissue masks, extract P1-P5 and retain uncertain and scene-context partitions. Expose pre-cleanup and post-cleanup geometry and preserve original point indices.

## Current evidence

430,060 tissue-candidate points: P1 21,444; P2 72,786; P3 112,943; P4 68,239; P5 154,648.

## Acceptance criteria

- [ ] Counts reconcile across the five saved specimen clouds.
- [ ] Candidate, uncertain and context partitions remain recoverable.
- [ ] Every retained point maps to its original recorded/reconstructed source.
- [ ] Side-view inspections document missing tips, undersides and possible mask losses.
- [ ] Reviewer confirms that cleanup is described as a candidate segmentation rather than complete anatomical truth.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_findings.md`
- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_verification.json`

## Risk and scope

Approximate masks and basal exclusions can remove true tissue; cleaned extent is not automatically stem-base-to-tip height.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Compare manual traits with matched source-supported plant measurements

**Planning ID:** FS06

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Tanisha Sharma |
| Reviewer | Tianyu Xu |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:traits, type:task |
| Dependencies | FS02, FS05; replace with real issue links |
| Evidence status | Conditional comparisons ready for review; complete anatomical validation remains open |

## User story

As a researcher, I want matched measurements and explicit exclusions so that differences from ruler references can be interpreted fairly.

## Description

Account for all 47 manual dimensions, match specimen and organ identity, review endpoint support and compute justified differences. Keep operator annotations distinct from approximate photo readings and natural-pose chords distinct from flattened leaf measurements.

## Current evidence

13 conditional comparisons across eight P3/P5 organs: seven lengths and six widths. Five vertical-span diagnostics are descriptive and are not validated plant-height errors.

## Acceptance criteria

- [ ] The 47-dimension ledger contains a comparison or a specific unresolved reason for each dimension.
- [ ] The 13 comparisons include operator value, 3D value, units, signed difference and source identities.
- [ ] Endpoint choices are justified from images rather than chosen to match manual values.
- [ ] P1 width conflict, P4 organ identity and unresolved base/tip pairs remain explicit.
- [ ] Reviewer confirms eligible dimensions and retains poor agreements without an unsupported aggregate accuracy claim.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/trait_findings.md`
- Project file: `docs/final-sprint-20260928/evidence/conditional_comparisons.csv`
- Project file: `docs/final-sprint-20260928/evidence/dimension_ledger_47.csv`
- Project file: `docs/final-sprint-20260928/evidence/trait_verification.json`

## Risk and scope

Natural-pose chords, flattened ruler lengths and different width sections can measure different quantities.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Extract and inspect both hyperspectral cameras with quality flags

**Planning ID:** FS07

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Tianyu Xu |
| Reviewer | Tanisha Sharma |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:spectra, type:task |
| Dependencies | FS01; replace with real issue links |
| Evidence status | Measured camera-space outputs ready for peer review |

## User story

As a spectral analyst, I want exact measured bands and reference-quality information so that unsupported normalization does not become a scientific claim.

## Description

Verify FX10 and FX17 cubes, preserve native pixel identities, expose measured DN and the Q/Q0 sensitivity alternatives, and calculate only supported descriptors. Retain missing and clipped values with their flags.

## Current evidence

The broader inspector contains 7,982 FX10 and 5,361 FX17 selected samples, each with 224 bands. White reflectance and shutter-closed dark capture remain unconfirmed.

## Acceptance criteria

- [ ] Both cameras retain native column, line, wavelength and sample identities.
- [ ] Raw values are traceable to the original cubes and invalid normalized values remain unavailable.
- [ ] Reference support, clipping and dark assumptions are visible in exports and the viewer.
- [ ] FX10 descriptors and the FX17 SWIR diagnostic are distinguished; no red band is borrowed for FX17 NDVI.
- [ ] Reviewer verifies selected spectra and the wording of radiometric limitations.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_findings.md`
- Project file: `docs/final-sprint-20260928/evidence/fusion_rescue_verification.json`

## Risk and scope

Fixed exposure and an ordinary white board do not independently establish calibrated reflectance or physiological interpretation.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Investigate dense spectral registration and preserve the partial surface result

**Planning ID:** FS08

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Adithya Rama |
| Reviewer | Tianyu Xu |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:spectral-fusion, type:spike |
| Dependencies | FS03, FS05, FS07; replace with real issue links |
| Evidence status | Research investigation and partial candidate ready for review; full fusion unresolved |

## User story

As a researcher, I want spectra associated with supported 3D locations so that spatial patterns can be explored without invented coverage.

## Description

Compare learned image matching, local multimodal warps, physical camera models and cross-sensor tracking. Freeze candidates before scoring proposed check coordinates, preserve failed trials and limit exports to supported geometry domains.

## Current evidence

72 learned configurations on P5, 24 frozen maps and 16 additional P1-P4 runs. The selected two-upper-leaf demonstration has 2,338 FX10 and 862 FX17 native spectra on unchanged P5 geometry. These patches support raw DN only.

## Acceptance criteria

- [ ] Candidate definitions, selection rules and unsuccessful experiments remain available.
- [ ] The partial viewer separates both cameras and traces each assignment to an exact native pixel and existing vertex.
- [ ] No spectra are interpolated onto unobserved surfaces or spliced across cameras.
- [ ] Local versus whole-plant coverage, post-hoc demonstration-region selection and unknown per-point error are explicit.
- [ ] The investigation can close with a documented partial or negative result; complete validated fusion remains a separate unresolved product goal.
- [ ] Peer reviewer signs off the evidence and links follow-up calibration work.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/fusion_rescue_report.md`
- Project file: `docs/final-sprint-20260928/evidence/fusion_rescue_verification.json`

## Risk and scope

Training fit, plausible colour overlap and geometry support do not establish the same physical material point across cameras.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Audit correspondence controls and correct unsupported accuracy claims

**Planning ID:** FS09

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Tianyu Xu |
| Reviewer | Howard Zhang |
| Story points | 3 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:validation, type:task |
| Dependencies | FS02, FS06, FS08; replace with real issue links |
| Evidence status | Audit ready for peer review |

## User story

As a reviewer, I want checking landmarks and coordinate conventions audited so that a result is not accepted or rejected using unreliable truth labels.

## Description

Check orientation, scale, native versus undistorted coordinates and exact source identities. Preserve uncertain landmark attempts and score frozen models without moving labels toward predictions. Record corrections to earlier interpretations.

## Current evidence

23 fresh/adaptive landmark attempts were retained. The old green_lower_4 control was already unaccepted and non-independent, so its discrepancy could not alone establish a definitive physical mapping failure.

## Acceptance criteria

- [ ] Coordinate and point-identity checks are documented.
- [ ] Model-fitting evidence is distinguished from withheld annotations and independently measured truth.
- [ ] Uncertain and unsuccessful checks remain visible, including adaptive second-round selection.
- [ ] The previous rejection wording is corrected while the old result remains preserved.
- [ ] Reviewer checks that residuals are not advertised as per-point error bounds.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/control_reassessment.json`
- Project file: `docs/final-sprint-20260928/evidence/control_verification.json`
- Project file: `docs/final-sprint-20260928/evidence/fusion_rescue_report.md`

## Risk and scope

Subjective landmark radii are not statistical confidence intervals; repetitive veins can have uncertain identity.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Publish an inspectable results journey with downloads and explicit gaps

**Planning ID:** FS10

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Tanisha Sharma |
| Reviewer | Adithya Rama |
| Story points | 5 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:website, type:task |
| Dependencies | FS05, FS06, FS07, FS08, FS09; replace with real issue links |
| Evidence status | Local build and browser evidence available; latest publication not verified |

## User story

As a tutor or collaborator, I want an accessible results page with provenance so that I can inspect outcomes and limitations without running the research pipeline.

## Description

Present calibration, geometry stages, manual comparisons, both-camera spectra, partial surface fusion and the control reassessment. Keep the historical baseline available, link the complete sprint explanation and verify the final deployed route.

## Current evidence

The rescue build and browser checks passed, including both sensor layers and 86 static evidence/download links. Local success is distinct from GitHub Pages publication.

## Acceptance criteria

- [ ] The main page leads to geometry, traits, spectra and the latest partial-fusion report.
- [ ] Sensor switching, wavelength selection, exact-source inspection and unavailable-value display are checked.
- [ ] Download and evidence links resolve in the local build.
- [ ] A teammate checks readable desktop/mobile presentation and historical versus current wording.
- [ ] After the owner-authorized push, verify the public route and record the deployed commit before closing publication.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/fusion_rescue_verification.json`
- Project file: `docs/final-sprint-20260928/evidence/website_link_validation.json`

## Risk and scope

A local build or fork push does not by itself prove the intended public Pages site contains the new results.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Verify offline analysis integration and complete laboratory regression checks

**Planning ID:** FS11

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Howard Zhang |
| Reviewer | Tanisha Sharma |
| Story points | 3 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:lab-regression, type:task |
| Dependencies | FS01, FS03, FS04, FS06, FS07; replace with real issue links |
| Evidence status | Blocked for physical acceptance until the lab machine is available |

## User story

As a lab operator, I want the established camera and gantry workflow preserved while offline analysis is available so that analysis changes do not disrupt recording.

## Description

Review the existing offline integration and protected-source receipts, then run a bounded physical acceptance session for application startup, camera selection, capture, gantry motion, stop/cancel and saved output. New research rescue scripts are not automatically production features.

## Current evidence

The saved archive records 26 protected files unchanged and a historical run of 101 targeted offline tests. This does not establish a new physical lab pass or arbitrary-dataset automation.

## Acceptance criteria

- [ ] Record exact software revision, environment and protected-source comparison.
- [ ] Confirm the lab operator can launch the app and select the intended RealSense device.
- [ ] Check paired capture, intended gantry motion, stop/cancel and recovery on the actual rig.
- [ ] Verify offline analysis cannot trigger unintended acquisition or gantry activity.
- [ ] Attach a dated lab observation log, failures and reviewer sign-off; do not close using source hashes alone.

## Evidence

- Project file: `docs/final-sprint-20260928/evidence/confirmed_board_verification.json`
- Project file: `docs/final-sprint-20260928/evidence/software_archive_notes.md`

## Risk and scope

Requires lab access and the normal operating procedure. Physical execution remains unverified in the saved local work.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


# Prepare the final sprint narrative demo and research handover

**Planning ID:** FS12

**Parent:** replace PARENT_URL after creating the parent issue.

| Field | Proposed value |
|---|---|
| Assignee | Adithya Rama |
| Reviewer | Tianyu Xu |
| Story points | 3 |
| Priority | P1 |
| Milestone | Final Sprint, use the existing team milestone |
| Labels | sprint:final, area:handover, type:task |
| Dependencies | FS09, FS10, FS11; replace with real issue links |
| Evidence status | Draft prepared; team review and final handover remain |

## User story

As a tutor or incoming developer, I want the user journey, decisions and evidence explained together so that I understand both the outcome and the next steps.

## Description

Use the complete sprint report to present the objective, evolving workflow, problems, fixes, findings, limitations and lessons. Update the earlier slide deck to reflect the partial fusion and control correction. Confirm each member's actual contribution before final reflection.

## Current evidence

The complete explanation, end-to-end software user guide, parent/sub-issue drafts and evidence snapshots are now prepared. The earlier presentation predates the rescue interpretation and needs reconciliation.

## Acceptance criteria

- [ ] Walkthrough covers calibration through geometry, traits and both-camera spectral inspection.
- [ ] Stories and journeys link to demonstrated outputs or explicit gaps.
- [ ] Presentation reflects 13 conditional trait comparisons and the new partial surface without claiming full fusion.
- [ ] Each team member confirms their contribution and adds an evidence-based reflection.
- [ ] Record public-site and lab status honestly, and hand unresolved items to the follow-up backlog.
- [ ] Complete peer review and tutor/team handover.

## Evidence

- Project file: `docs/final-sprint-20260928/README.md`
- Project file: `docs/final-sprint-20260928/USER_GUIDE.md`
- Project file: `docs/final-sprint-20260928/evidence/fusion_rescue_report.md`
- Project file: `docs/final-sprint-20260928/evidence/trait_findings.md`

## Risk and scope

FS11 can remain blocked, but the handover must carry that gap explicitly; it cannot assert complete lab acceptance.

## Review note

This is a proposed issue allocation. The saved evidence above is not a claim that the named owner performed all historical work. Check criteria against the artifacts, attach the deployed/source links when available, and have the reviewer confirm closure.


## Follow-up backlog outside the final sprint estimate

These are proposed future issues; do not count their points as delivered in this sprint.

### FU01 Capture elevated cross-camera calibration targets and independent checks

**Proposed owner:** Tianyu Xu · **Estimate:** 8 SP · **Related:** FS02, FS08, FS09

**Acceptance:** Targets span foliage heights and scan positions; lens/rig and line timing are recorded; fitting and independent check targets are distinct; report spatial errors before promoting dense mapping.

### FU02 Record characterized white references and confirmed dark data

**Proposed owner:** Tianyu Xu · **Estimate:** 5 SP · **Related:** FS07, FS08

**Acceptance:** White reference covers relevant detector columns at fixed documented exposure; panel reflectance and shutter-dark procedure are known; normalization quality is re-evaluated without filling unsupported values.

### FU03 Acquire stable overlapping views for missing plant surfaces

**Proposed owner:** Howard Zhang · **Estimate:** 5 SP · **Related:** FS03, FS05

**Acceptance:** Record side, oblique and lower foliage coverage with stable plants; inspect quality during capture; compare newly observed surfaces while preserving original data.

### FU04 Test offline reconstruction and fusion on an independent dataset

**Proposed owner:** Adithya Rama · **Estimate:** 8 SP · **Related:** FS08, FS11

**Acceptance:** Use a fresh capture with preset configuration; record manual interventions, failures, reproducibility and held-out spatial/trait checks; define a supported operating domain rather than universal perfection.

### FU05 Repeat matched manual traits under a consistent anatomical protocol

**Proposed owner:** Tanisha Sharma · **Estimate:** 3 SP · **Related:** FS06

**Acceptance:** Resolve P1 units and P4 organ type, tag individual organs, define stem base/highest tip and lamina/width sections, and record repeated measurements under the chosen pose protocol.


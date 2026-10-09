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

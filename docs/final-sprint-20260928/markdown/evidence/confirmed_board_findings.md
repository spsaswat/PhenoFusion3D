# Confirmed-board recheck of the September five-plant study

This directory preserves a separate recheck using Saswat's supplied 7 x 10
ChArUco target: 25 mm squares, 18 mm markers and DICT_4X4_50. Earlier results
remain in their original directories. No manual plant dimensions were used to
fit the reconstruction scale or camera alignment.

## What changed

- D405 RGB geometry is re-expressed by **1.0288746669** from a metric fit to
  the recorded board observations. This corrects lengths by **+2.8875%** and
  areas of the same selection by **+5.8583%**. Point identities, colours and
  image projections are preserved; it does not add surfaces or rerun stereo.
- The independently obtained L515 RGB motion factor is **1.0296675589**.
  Its raw depth has been reconstructed twice with corrected camera motion:
  native candidate 0.00025 m/count, and empirical board-derived conversion
  0.0002533640571 m/count. This conversion is not certified device metadata.
- The board-corrected depth candidate was selected for new fusion after
  fixed-region and matched-soil checks. Against the newly metric native
  candidate, matched-soil median disagreement decreased **11.160 to 6.289 mm**;
  the selected P90 is **10.326 mm**, with a **26.037 mm** maximum. The same
  checking data informed candidate selection, so this is not an untouched
  final accuracy test. The old 3.411 mm result used different conditional
  geometry and must not be advertised as directly improved by the new value.
- The new union contains **1,740,673** observed points: **1,719,001 D405** and
  **21,672 L515 additions**. Source-mask cleanup retains **430,060** candidate
  tissue points: P1 21,444; P2 72,786; P3 112,943; P4 68,239; P5 154,648.
  Uncertain and scene-context points remain separately recoverable.
- P3.O03's historical selected chord becomes **7.691100957 cm**, compared
  with the 7.5 cm operator annotation. The +0.191100957 cm difference is
  provisional, not validated accuracy. Anatomical/reference ambiguities
  remain despite the resolved board pitch.
- Both FX10 and FX17 now have a shared metric table-plane calibration and
  measured calibration-to-plant scan transfer. The attempted sparse
  height-dependent model fails its held-out leaf predictions and is rejected
  for dense fusion. The accepted output remains **six provisional spectra at
  three P5 points**, plus **13,343 measured camera-space samples**.

## Outputs

- `d405_metric/`: metric cloud, camera poses, exact-coordinate verification.
- `l515_metric_v1/`, `l515_metric_boardgain_v1/`: separate raw-depth replays.
- `cross_camera/`: board seed, bounded rigid fits, fixed-soil comparison and
  selection decision. Region IDs and quality selection were frozen before fit.
- `fusion_v1/`: selected observed-point union and per-point camera provenance.
- `cleanup_v1/`: P1-P5, combined candidates, uncertain points and scene context.
- `traits_metric/`, `website/traits/`: rechecked geometric descriptors and
  manual-reference dispositions, with historical selections identified.
- `hsi_geometry/`: shared plane, scan transfer, RGB bridge and rejected height
  model, including source crops and exact predictions.
- `website/geometry/`: 24 interactive model assets and full-resolution PLY.gz
  downloads, with point indices and round-trip verification.
- `website/spectral/`: both-camera inspectors and quality/index diagnostics.
- `site_src/`: source of the new static website page.

The requested website route is `/results/final-sprint-20260928/` in the WSL
`phenofusion3d.github.io` checkout. `install_website.py` copies the prepared
local page, and `verify_website.py` audits the exported links. Build with the
website's existing `pnpm build`. Publication is a separate user-controlled
push; this work does not push or claim a live deployment.

## Remaining scientific limits

Physical board dimensions are supplied, but print tolerance and independent
physical accuracy remain unmeasured. Session depth metadata is incomplete.
Missing tips/undersides cannot be filled by scale correction. No accepted
stem-base-to-tip height or matched-organ accuracy set exists for all five
plants. Dense spectral mapping fails available elevation checks. Unknown white
reflectance and unconfirmed dark capture limit Q/Q0 and derived indices to
exploratory signals. Independent datasets and physical laboratory checks are
still needed to establish generalisation and hardware operation.

Protected camera, capture and gantry source is checked separately by hash;
that proves source preservation, not a new laboratory hardware test.

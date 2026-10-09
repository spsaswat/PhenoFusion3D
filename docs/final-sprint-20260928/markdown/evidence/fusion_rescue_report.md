# Spectral fusion rescue — saved results, 8 October 2026

## What changed

The new work goes beyond the original three provisional spectral locations. A partial surface candidate now associates native FX10 measurements with **2,338 unchanged Plant 5 vertices** on two upper leaves: 1,050 on the upper green leaf and 1,288 on the upper red leaf. This is an **exploratory overlay**, not measurement-ready dense fusion. Per-point material correspondence error is unknown, and full-leaf/whole-plant coverage is not claimed. The [partial 3D spectral inspector](partial_surface/result/index.html) is now available with separate FX10 and FX17 layers. FX17 adds 862 native measured spectra on the same recorded geometry: 551 upper-green and 311 upper-red vertices. Each sensor retains 224 measured bands. The original 154,648-point P5 context is unchanged.

The reconstruction itself is preserved. No missing geometry or spectra were invented. Earlier geometry, the sparse three-location result, trait comparisons, recorded camera captures and capture/gantry software remain separate and unchanged.

## What was tested

Counts below distinguish configurations, fitted models and retained variants; they must not be added together as independent experiments.

| Branch | Executed work | Main result |
|---|---|---|
| Physical scan-camera model | Eight base configurations: four priors for each of FX10 and FX17. Each has three leave-one-old-feature and three leave-one-board-sheet fits (56 fits including the base fits). | Good table-plane fits do not establish elevated leaf mapping. |
| Capture-run bridge | 12 joint fits: three RGB paper-weight settings × full/three leave-one-old-control cases, using 386 unique paper correspondences. | Bridge adjustment did not resolve disagreement among exposed elevated controls. |
| Additional physical controls | Six frozen FX10 variants: three priors × direct depth lift or nearest existing vertex, using two newly proposed red-leaf training features. | Useful coarse projection; reserved image checks remain several pixels apart. |
| Geometry colour/silhouette search | Three final version-2 starts. Earlier version-1 runs retained as a failed out-of-view-censoring diagnostic. | Broad colour overlap is plausible but not precise material identity. |
| Local multimodal registration | Six lower-green-leaf fields: three single-scale MIND-style variants, one pyramid, mutual-information affine, one foreground-only pyramid. Four principal variants also received fresh withheld checks. | More flexible fields did not consistently improve fresh features. |
| Learned P5 matching | 72 configurations: 36 LoFTR and 36 DISK/LightGlue; 138 fitted affine/projective hypotheses. Six base maps were selected using training fit/spread, then 18 residual smooth variants were retained: 24 frozen maps. | Upper red and green leaves have useful local correspondence evidence; coverage and precision remain limited. |
| Other plants | 16 runs: four plants × two geometry-selected RGB views × two channels; eight small patch affine/projective fits. | 13 source proposals pass the two-view geometry screen, with no independent material-point validation. |
| Landmark audit | 13 initial reserved image landmarks, then 10 adaptive second-round attempts on unchanged maps; 23 total, including uncertain attempts. | Coordinates and metric identities are consistent. The old 3-pixel screen was stronger than the label evidence supports. |

### How the partial surface was produced

The already-frozen base image maps are used only inside their learned inlier convex hull, eroded by one pixel. Heuristic green/red tissue masks must agree in both images. Each exact native FX10 pixel is mapped to native RGB, undistorted for depth lookup, and linked to an unchanged current P5 vertex within 3 mm and 1.5 image pixels. Depth needs at least two stereo votes and support from at least two of three recorded views within 12 mm. Deduplication retains one source observation per selected vertex.

There were 6,781 geometry-supported pixel proposals before deduplication and 2,338 retained vertices. Geometry checks test source support; they do not independently prove that an HSI pixel and the selected leaf material are the same. The two displayed leaves were selected after reviewing validation evidence, so demonstration-region selection is post hoc. Maps were not refitted to improve those checks.

Native spectra are read without filling, averaging or interpolation. The added upper patches fall outside supported reference conditions. **There are zero newly mapped samples with valid normalization across all 224 bands for either sensor.** Invalid normalized values remain NaN. These new layers are raw DN (recorded camera-signal) fusion, not a reflectance or NDVI rescue. Earlier separate spectral regions with valid exploratory normalization remain separate. Exact native raw spectra and normalization outputs were independently reread/recomputed; that verifies stored measurements and invalid-value handling, not spatial correspondence accuracy.

## What the image checks say

All errors below are **disagreements with uncertain image annotations**, not independently established physical accuracy. Most fresh marks have subjective localization radii of 4–5 HSI pixels and 3 RGB pixels; these are not statistical confidence intervals. Repetitive vein forks may have uncertain identity.

| Area | Withheld/adaptive checks inside the learned domain | Interpretation |
|---|---|---|
| Upper green P5 | Three interior checks; 0.67–7.16 native RGB pixels across frozen variants. | Supports approximate local correspondence, not a universal 3-pixel guarantee. |
| Upper red P5 | Four checks; 1.90–5.60 native RGB pixels, including one low-confidence mark. | Local alignment is plausible; the whole leaf remains unvalidated. |
| Lower green P5 | New medium-confidence lower-midvein check: 7.92–8.69 RGB pixels. Other attempted forks are ambiguous. | Mapping uncertainty remains; one dubious old control cannot decide validity alone. |
| Lower red P5 | Initial interior fork: 7.47–8.12 RGB pixels; low-medium confidence. | Needs stronger material landmarks. |
| Variegated P5 | Initial notch: 18.30–19.03 RGB pixels; medium confidence. | Current map and proposed landmark disagree substantially. |
| Central green P5 | Fresh marks outside the learned inlier hull. | No in-domain validation supplied by these marks; extrapolation is not interpolation evidence. |

The first round had five unique in-domain landmarks and eight outside the learned hull. Every frozen variant and ambiguous attempt is retained. Second-round leaf selection followed first-round evidence and is labelled adaptive; model parameters and selected coordinates were unchanged after scoring.

### Correction to the previous failure interpretation

The old `green_lower_4` lateral-vein feature was already recorded as **accepted=false**, **independent_holdout=false** and **recommended_for_sparse_exploratory_join=false**. It repeated in only five grayscale SIFT configurations, whereas `green_lower_0` repeated in 25 configurations across three channels. The exact lateral branch/descriptor centre is not visually unique. Its old nearest-cloud association also had a 2.69 mm displacement and 2.22 px reprojection discrepancy.

Therefore the earlier approximately 7–8 px screen measured disagreement with uncertain selected controls. It was too strong to describe that as a definitive physical mapping failure of that magnitude. This correction does **not** demonstrate that the older map was accurate. No control was moved toward a model prediction.

The audit found exact source-point identities and correct metric scaling. The three original native-RGB reprojection errors are 0.13, 0.71 and 0.94 px; metric re-expression changes their projection by less than 3×10⁻¹³ px. Rotation is exact. Native/undistorted conventions were correctly handled in the reviewed old map path. A historical resize inverse omits up to 0.75 source HSI pixel of half-pixel correction; it is worth fixing in a replay but cannot alone explain the large residuals.

## Physical models: useful coarse positioning, uncertain pixel identity

The gantry-constrained model uses the full measured 3D motion direction. Native sensor column is a ratio of affine functions transverse to motion; scan line is affine in 3D coordinates. Three of nine coefficients are unobservable from a perfectly planar target. The recorded board deviations from a common plane are only about ±0.35 mm, while selected leaves are roughly 350–392 mm above it. Excellent board residuals cannot resolve this height extrapolation by themselves.

The initial joint table fits have approximately 0.633 px RMS for FX10 and 0.337 px for FX17; these are fitting residuals, not held-out leaf accuracy. Smooth capture-run drift and a joint RGB bridge were tested. Neither resolves the approximately 8–9 scan-line disagreement between the two uncertain red controls. This does not identify camera height as the sole cause.

The physical primary gives 4.87, 8.84, 8.83 and 5.94 native HSI-pixel disagreements on the four reserved checks above low identity confidence. The colour-objective primary gives 5.35, 6.52, 8.62 and 19.85 px on the same four. The low-identity basal vein is retained separately and cannot independently veto either model.

The physical and colour-objective primaries disagree by a median 5.52 and 95th percentile 13.47 HSI pixels over 145,459 in-view existing P5 points. That is model sensitivity, not a calibrated uncertainty bound. The silhouette model's 90.85% green and 98.41% red within-colour proximity statistics describe colour-region overlap, not same-material accuracy or visibility.

## Progress on Plants 1–4

| Plant | Unique domain proposals in two views | Repeated source proposals | Pass geometry consistency |
|---|---:|---:|---:|
| P1 | 0 / 0 | 0 | 0 |
| P2 | 8 / 5 | 3 | 2 |
| P3 | 16 / 14 | 9 | 9 |
| P4 | 2 / 2 | 2 | 2 |

Duplicate channel proposals were merged before this screen. Its fixed conditions were at most 10 mm between associated existing vertices and at most 3 RGB pixels forward reprojection. The 13 passing proposals comprise P2:2, P3:9 and P4:2. They are provisional sparse evidence, not validated dense assignments. No new dense P1–P4 product was created. The P2 broad blade has a plausible coarse visual identity; the small learned patch lacks an independent precise anatomical check.

## FX10–FX17 progress

Separate upper-red and upper-green cross-sensor tracking was added; no lower-green warp was reused. The upper green leaf has 11,575 image-consistent tracks and the upper red leaf 8,044 (19,619 total). These are tracked source queries, not unique 3D points or a tissue segmentation. The corresponding rounded unique native FX17 pixel counts before 3D intersection are 7,254 and 5,244.

Tracks must be within the local inlier hull, agree in at least three of four overlap bands, pass forward/backward and local-correlation screens, and satisfy a maximum cross-band radius. Their image consistency is correlated across bands and does not establish physical spectral footprints.

Intersecting tracks with the selected tissue/geometry-supported FX10 surface yields 902 FX17 candidates. Deduplication retains **862** unique native-pixel/vertex pairs (green 551, red 311). FX10 retains 2,338 pairs (green 1,050, red 1,288). Spectra are kept separate by camera; there is no cross-sensor spectrum concatenation. These assignments remain partial and exploratory. Cross-sensor success cannot repair an incorrect HSI-to-RGB material match.

The old red anchors were excluded from cross-sensor fitting; post-fit disagreements were 0.91 and 0.38 native FX17 pixels. Those old, previously inspected anchors are correlated with FX10 and are not fresh physical validation.

[Upper-green overlap evidence](physical_model/cross_sensor_upper/upper_green_registration.png) · [Upper-red overlap evidence](physical_model/cross_sensor_upper/upper_red_registration.png) · [Native spectrum verification](partial_surface/result/numeric_validation.json) · [Package verification](partial_surface/result/verification.json).

## Separate the remaining limits

- **Data limits:** occluded or absent surfaces; changed appearance and possible leaf pose between sensors; unknown dark-reference acquisition and white-panel reflectance; incomplete reference-panel detector coverage. A complete 360-degree plant cannot be inferred from unobserved surfaces without adding assumptions.
- **Method limits:** local maps are valid only over supported regions; learned correspondences can repeat on veins; physical height parameters remain weakly constrained; masks and visible-surface decisions are provisional. These experiments do not exhaust every possible method.
- **Validation limits:** manually proposed cross-modal marks are uncertain and not surveyed physical targets; their residuals are not physical accuracy. Sparse checks do not provide a per-point error map or cross-dataset generalization proof.

Useful next evidence includes measured elevated targets spanning the plant volume, repeatable visible landmarks in all sensor views, exact synchronization/gantry timing, documented panel reflectance and dark frames, and more viewpoints where geometry is absent. Software-only work can still improve matching, uncertainty propagation and reproducible automation, but it should preserve the distinction between a plausible overlay and quantitative spectral measurement.

## Saved deliverables and reproduction evidence

- [Partial surface inspector](partial_surface/result/index.html) — exploratory two-leaf illustration; check its own status before using measurements.
- [Partial-surface provenance](partial_surface/evidence.json) — masks, geometry checks, hashes and deduplication.
- [Coordinate and control audit](control_audit/index.html) — all 23 attempts and frozen-model evaluations.
- [Physical-model report](physical_model/REPORT.txt), [model summary](physical_model/summary.json), [reserved checks](physical_model/reserved_physical_evaluation.json), [silhouette comparison](physical_model/silhouette_projection_comparison_v2.jpg).
- [All LoFTR runs](learned_registration/loftr_outdoor.json), [all LightGlue runs](learned_registration/lightglue_outdoor.json), [24 frozen maps](learned_registration/frozen_candidates.json).
- [Local registration methods and evidence](local_registration/README.md), [input/hash verification](local_registration/artifact_verification.json).
- [Other-plant runs](local_registration/other_plants/learned_other_plants.json), [two-view screen](local_registration/other_plants/cross_view_consistency.json).
- [Existing manual trait comparisons](../research_sprint_review_20261008/traits_audit/index.html) — 13 conditional comparisons across eight organs, with all 47 reference dimensions accounted for.
- [Earlier sparse spectral result](../research_confirmed_board_20261007/spectral_metric_v1/result/index.html) — preserved three-location baseline.

Results are saved locally. Website publication is a separate step. No software hardware-control paths were edited by this rescue work.

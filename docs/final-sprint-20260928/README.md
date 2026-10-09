# PhenoFusion3D final sprint explanation and evidence

Prepared on 8 October 2026 for the four-person final sprint review. This report covers the 28 September five-plant recordings, the subsequent calibration and reconstruction work, manual trait comparisons, both hyperspectral cameras, the spectral fusion investigation, and the software and website handover. The accompanying [GitHub issue pack](ISSUES.md) supplies a parent issue and twelve proposed sub-issues.

The sprint produced traceable observed geometry, conditional manual comparisons and measured spectral inspection. The latest fusion result is a partial exploratory surface on two Plant 5 leaves: 2,338 FX10 spectra and 862 separate FX17 spectra. It is not a complete, physically validated five-plant spectral model. Preserving this distinction is part of the research outcome.

## Team and allocation

The repository lists Adithya Rama, Howard Zhang, Tanisha Sharma and Tianyu Xu as the project team. Saswat Panda is the project contact. Proposed issue owners and reviewers are handover responsibilities, not a retrospective claim about who performed each experiment. Team members should confirm personal contribution statements before submitting the final reflection.

The issue pack proposes 52 story points, balanced at 13 per person. These are relative scope estimates for organising the work, not measured hours, previously agreed estimates or earned sprint velocity. The parent has no additional points. The sprint dates, milestone number and GitHub handles need the team's existing project-board values.

## What the sprint set out to achieve

A plant researcher should be able to open recorded data, reconstruct and inspect each plant, compare suitable traits with ruler measurements, inspect both hyperspectral recordings, and understand which spectral measurements can reasonably be associated with the 3D surface. A lab operator should retain the existing camera capture and gantry behaviour. A tutor or collaborator should be able to follow each displayed result to its inputs, processing choices and limitations.

The intended product journey was:

1. Record or import calibration and plant scans from D405, L515, FX10 and FX17.
2. Verify paired inputs and units before reconstruction.
3. Establish calibration and reconstruct the available views.
4. Align the RGB-D camera results and separate plant tissue candidates from scene context.
5. Match manual measurements to identifiable plants and organs.
6. Extract spectral samples with reference and quality information.
7. Associate supported spectral pixels with existing plant surface points.
8. Inspect, export and present the results with unresolved gaps visible.

The journey is partially implemented and partially supported by reviewed research scripts. It is not yet evidence of unattended processing for arbitrary datasets.

## What happened and what changed

### Input integrity and the replacement L515 recording

The first downloaded L515 plant archive contained only 89 exact RGB/depth pairs. The original ZIP itself was incomplete, so extracting it again would not recover the missing images. Nearby frame numbers were not renamed to create false pairs. D405 could be investigated while a replacement L515 export was obtained.

The replacement contained 1,278 exact plant RGB/depth pairs and 1,290 calibration pairs, with no unmatched images or decoding failures in the replacement audit. This resolved the incomplete-export problem; it did not establish capture timing, depth units or physical sensor accuracy. [Original inventory and replacement update](evidence/input_inventory.md) · [Replacement audit](evidence/l515_replacement.md).

### Physical calibration and the corrected scale

The remembered 127/76 measurements were ambiguous. A generic checkerboard image was also different from the recorded ChArUco pattern. We retained the uncertainty until Saswat supplied the recorded board specification: 7 by 10 squares, 25 mm square pitch, 18 mm markers and DICT_4X4_50. Metre values are 0.025 and 0.018 respectively.

The board-based D405 metric factor was 1.0288746669. This increases lengths by about 2.8875% and areas of the same point selection by about 5.8583%. It preserves point identities and does not add missing surfaces. L515 RGB travel independently supported a similar factor, 1.0296675589. L515 depth was investigated separately rather than treating RGB motion scaling as a sensor-depth calibration.

The selected L515 depth interpretation uses an empirical board-derived conversion of 0.0002533640571 m per count, compared with the native candidate of 0.00025 m per count. It remains an empirical interpretation because session metadata did not independently certify the executed device unit. [Confirmed-board findings](evidence/confirmed_board_findings.md) · [Board statement](evidence/board_confirmation.json).

### Reconstruction and geometric fusion

The D405 route recovered geometry through RGB multi-view stereo, scene-supported motion and ICP alignment. The L515 route integrated recorded sensor depth separately. Different views supply different observed surfaces; ICP aligns supported observations but cannot measure a leaf underside that was never visible.

For camera fusion, a board-referenced rigid alignment placed L515 observations in the D405 reference frame. The selected union contains 1,719,001 D405 inspection points and 21,672 L515 additions, totalling 1,740,673 observed points. This is geometric fusion. It is a different operation from assigning a hyperspectral measurement to a leaf location.

On the fixed matched-soil comparison, the board-corrected L515 depth candidate reduced median disagreement from 11.160 to 6.289 mm against the newly metric native candidate. The selected 90th percentile was 10.326 mm and maximum 26.037 mm. These checks also informed selection; they are not an untouched final accuracy test. The older 3.411 mm result used a different conditional reference and cannot be compared as though it were the same experiment. [Geometry and selection evidence](evidence/confirmed_board_findings.md).

### Cleanup and observed plant geometry

Source-image masks separated candidate tissue, scene context and uncertain observations while retaining source point identities. Cleanup retained 430,060 tissue-candidate points: P1 21,444; P2 72,786; P3 112,943; P4 68,239; P5 154,648. The website exposes the geometry stages and individual plants so exclusions can be inspected.

Cleanup improves inspection but approximate masks can remove real tissue. The clouds are not closed, gap-free surfaces or certified biological segmentations. Sparse tips, stems, occluded leaves and undersides remain significant limitations. A larger rendered point size can make a cloud look fuller without adding evidence.

### Manual traits and conditional comparisons

An earlier report stopped at unresolved correspondence too readily. The follow-through explicitly reviewed organ identity and endpoint support, retained operator measurements as legitimate comparison references, and produced 13 conditional same-organ comparisons across eight organs: seven lengths and six widths. All 47 manual dimensions have a recorded disposition. Five height annotations are also compared descriptively with retained-cloud vertical spans.

| Comparison | Operator measurement | Observed 3D chord | Signed difference |
|---|---:|---:|---:|
| P5 O01 length | 12.00 cm | 11.679 cm | -0.321 cm |
| P5 O01 width | 9.90 cm | 9.758 cm | -0.142 cm |
| P3 O01 width | 5.50 cm | 3.936 cm | -1.564 cm |
| P3 O02 width | 7.60 cm | 9.266 cm | +1.666 cm |

The poor agreements are retained. A leaf measured flat with a ruler is not necessarily the same quantity as a straight chord across its natural pose. Width sections and basal origins can differ. The P1 9 cm width annotation remains in conflict with a roughly 0.8 cm readable ruler estimate; it was not silently changed to millimetres. P4's four narrow objects remain unresolved as leaves versus pod-like organs. The true stem-base-to-highest-tip pairs are not established for all five plants.

No manual measurement was used to tune reconstruction scale or choose a distance that matched the expected answer. No overall anatomical accuracy or plant completeness percentage is claimed. [Trait explanation](evidence/trait_findings.md) · [All 13 comparisons](evidence/conditional_comparisons.csv) · [All 47 dimensions](evidence/dimension_ledger_47.csv) · [Trait verification](evidence/trait_verification.json).

### Both hyperspectral cameras and reference limitations

The actual recording headers identify FX10 and FX17, each with 224 bands. The broader saved camera-space inspection contains 7,982 FX10 samples and 5,361 FX17 samples, or 13,343 selected pixels. These samples are not the same count as 3D assignments and do not imply complete plant coverage.

The white board at the start and fixed exposure were confirmed. The board's spectral reflectance is unknown and the final scan lines were not confirmed as shutter-closed dark measurements. The processing therefore distinguishes raw detector values, a white-board/tail-normalized signal Q, and a zero-offset sensitivity alternative Q0. Quality flags retain clipping, missing reference coverage and invalid normalization.

FX10 supports exploratory visible/NIR descriptors such as NDVI where the required bands and reference support are available. FX17 does not contain the red band needed for NDVI; its SWIR ratio remains a signal diagnostic, not a calibrated estimate of water content. Spectra are not spliced across cameras to manufacture missing wavelengths.

### Why dense spectral fusion was difficult

The original inspector displayed three provisional spatial associations. Changing wavelength coloured those three locations; it did not assign spectra to every grey point. The older August experimental result used a dataset-specific image warp and RGB-depth lifting. Its denser colour coverage demonstrated a projection prototype, not independent proof of spatial accuracy.

A table-plane mapping can fit checkerboard points well while remaining uncertain for foliage tens of centimetres above the table. RGB and hyperspectral images also differ in perspective, appearance and scan geometry. Repeated veins can produce plausible but incorrect matches. Missing calibration information, algorithm limitations and uncertain validation landmarks all contributed; the evidence does not support blaming a single missing number.

The rescue investigation tested 72 learned matching configurations across six P5 regions, physical scan-camera models, six local multimodal registration variants, capture-run alignment adjustments and 16 additional matching runs across P1-P4. It retained 24 frozen learned maps and 23 fresh or adaptive landmark attempts. These counts describe overlapping stages and should not be added as independent experiments. [Full rescue report](evidence/fusion_rescue_report.md).

### What the rescue improved

The partial surface maps exact native FX10 pixels through a frozen local image map to native RGB, checks recorded depth and multiple views, and selects an unchanged existing P5 vertex. Separate FX10-to-FX17 matching in overlapping bands supplies additional native FX17 observations. No missing spectrum is filled or averaged into neighbouring geometry.

The final candidate contains 2,338 FX10 observations and 862 FX17 observations on parts of two upper leaves. The original P5 context contains 154,648 points. These counts describe coverage in a candidate, not a spatial accuracy score. Upper-green checks disagree with uncertain image marks by 0.67-7.16 RGB pixels across frozen variants; upper-red checks by 1.90-5.60 pixels. These ranges are not per-point error bounds.

The new upper patches have no supported normalized Q or Q0 values. Their useful output is raw-DN surface inspection, not calibrated reflectance or a new NDVI map. Other-plant testing produced 13 provisional proposals passing a two-view geometry screen across P2-P4, insufficient for a dense validated surface. P1 produced no proposals surviving the chosen tissue/geometry domain checks. [Final rescue verification](evidence/fusion_rescue_verification.json).

### A correction to our own evaluation

An earlier local warp was rejected using approximately 7-8 pixel discrepancies against two proposed features and a 3-pixel screen. The later audit found that one feature, green_lower_4, was already explicitly marked unaccepted and non-independent. Its precise branch identity was ambiguous.

That disagreement could not independently establish a definitive physical mapping failure of that magnitude. The correction does not prove the old map accurate. We retained the previous output and the revised interpretation, rather than moving the feature to agree with the model. This is a key lesson: validation controls need scrutiny as well as reconstruction algorithms. [Control reassessment](evidence/control_reassessment.json).

## Problems fixes and remaining gaps

| Problem | Action taken | Current result | Remaining need |
|---|---|---|---|
| Incomplete initial L515 export | Audited exact IDs and obtained replacement | Pairing gap resolved | Timing and device metadata still need confirmation |
| Ambiguous board dimensions | Obtained the actual ChArUco specification and rechecked metric scale | Nominal scale improved | Print tolerance and independent target measurements |
| Missing or disconnected surfaces | Tested view recovery, camera fusion and reversible cleanup | Better observed geometry | Additional stable viewpoints and independent coverage checks |
| Manual traits not compared | Matched organs and reviewed endpoints in source views | 13 conditional comparisons and 47-dimension ledger | Consistent anatomical protocol and remaining endpoint identities |
| Three spectral markers mistaken for a dense model | Explained sparse associations and built a separate surface candidate | Two upper leaves with both cameras | Full-plant correspondence and independent elevated controls |
| Flexible warps gave inconsistent results | Compared learned, local and physical approaches against frozen checks | Limited local improvement | Better landmarks and calibrated sensor/scan geometry |
| A questionable control drove rejection | Audited feature identity and historical acceptance flags | Earlier interpretation corrected | Stronger independent controls and explicit uncertainty |
| Unknown spectral references | Preserved DN and flagged unsupported normalized outputs | Traceable exploratory spectra | Characterized full-width white reference and confirmed dark capture |
| Local success confused with publication or lab operation | Kept build, source-preservation and hardware status separate | Local results and test receipts available | Public deployment verification and physical lab regression |

The records show that correspondence and validation required the broadest experimentation. There is no time log supporting a precise ranking of hours spent by task or person.

## User stories and observed journeys

### The plant researcher

**Story:** As a plant researcher, I want a measurement and its supporting source evidence together so I can judge whether it answers my biological question.

**Journey:** Select plant and processing stage; inspect the cloud from several angles; open a manual dimension; inspect organ identity and endpoints; read the conditional difference or the reason it is unavailable; export the comparison. A successful journey can end with a documented unsupported measurement instead of a fabricated value. FS05 and FS06 support this journey.

### The spectral analyst

**Story:** As a spectral analyst, I want to inspect measured bands and spatial associations separately so I can distinguish sensor signal from uncertain registration.

**Journey:** Select FX10 or FX17; inspect a source pixel and its quality flags; change wavelength; view a provisional mapped surface point; follow the exact source pixel; check reference support; export the spectrum. On the new upper patches, switching to Q shows unavailable values because the reference support is missing. FS07-FS10 support this journey.

### The lab operator

**Story:** As a lab operator, I want offline analysis to coexist with the established capture and gantry workflow so I can collect data without introducing regressions.

**Journey:** Launch the application; choose the camera; verify capture readiness; acquire and save paired data; run offline analysis after acquisition; handle errors or cancellation without unintended motion. The preservation checks support code integrity, but the final physical lab journey still requires execution and a signed observation log. FS01 and FS11 support this journey.

### The tutor or collaborator

**Story:** As a reviewer, I want to move from a result to the method, evidence and remaining gap so I can assess progress without mistaking a preview for validated science.

**Journey:** Open the study; inspect calibration and geometry; review trait agreements and disagreements; compare sparse and partial spectral outputs; inspect the control correction; read lessons and follow-up work. Local website checks support the saved demonstration. Latest public deployment must be checked separately. FS09, FS10 and FS12 support this journey.

## Lessons and experience to discuss

1. **Check the input archive before tuning the algorithm.** Missing L515 pairs were an export problem, not an ICP parameter problem. Keeping exact identities prevented a false repair.
2. **Use each calibration result for the quantity it supports.** A confirmed square pitch improves scale. A low plane residual does not certify elevated leaves, complete geometry or radiometric calibration.
3. **Compare legitimate measurements even when they are conditional.** The first trait pass was too restrictive. Explicit organ matching produced useful numerical comparisons without claiming universal anatomical accuracy.
4. **More coloured points are not automatically better evidence.** Dense overlays need material correspondence and quality flags. Raw DN is a measurement; assigning it to a particular leaf location remains a hypothesis until checked.
5. **Review the checking data itself.** A dubious feature should not be treated as exact ground truth. Corrections to our interpretation should remain visible in the research record.
6. **Keep failed and superseded experiments.** Frozen maps, source indices and separate output directories let us explain why a candidate changed without overwriting the evidence.
7. **Separate scientific delivery from deployment and hardware acceptance.** A successful build and unchanged source hashes are useful evidence, but they do not establish a live website or successful physical camera/gantry operation.

For personal reflection, each member should add an actual contribution, an example of a difficult decision, the evidence that changed their mind, and what they would do differently. Do not attribute feelings, effort hours, meetings or decisions to a person solely from the proposed issue allocation. AI-assisted research and implementation should be described accurately under the course's applicable disclosure requirements; human source review and lab validation remain distinct responsibilities.

## A concise explanation for the final review

We assembled a traceable workflow from recorded calibration and camera data through reconstruction, geometric fusion, cleanup, conditional trait comparisons and hyperspectral inspection. Confirmed board dimensions improved the metric scale. We repaired a data-export gap through replacement recordings, preserved observed geometry and source identities, and calculated thirteen matched organ comparisons instead of leaving all validation blank. Spectral fusion progressed from three provisional locations to an exploratory two-leaf surface using both cameras. Broad experiments showed that precise full-plant correspondence is still unresolved, and an audit corrected an overconfident earlier rejection. The deliverable includes useful measured outputs and an explicit account of what additional capture, calibration and validation are needed.

## Evidence and demonstration links

These preview links work on the machine running the local server. They are not publicly shareable GitHub Pages links. The new handover and latest rescue changes require commit, push and deployment verification before their corresponding public URLs can be advertised.

- [Complete study and geometry inspector](http://127.0.0.1:8879/results/final-sprint-20260928/)
- [Trait comparisons and earlier presentation](http://127.0.0.1:8879/results/final-sprint-20260928/review-20261008/index.html)
- [Latest fusion experiments and evidence](http://127.0.0.1:8879/results/final-sprint-20260928/fusion-rescue-20261008/index.html)
- [Partial surface with both spectral cameras](http://127.0.0.1:8879/results/final-sprint-20260928/fusion-rescue-20261008/partial_surface/result/index.html)
- [GitHub issue drafts and allocation](ISSUES.md)
- [Evidence snapshot manifest](evidence/manifest.json)

The earlier presentation predates the rescue correction. Use this report to update its spectral-fusion explanation before presenting it as the final state. The compact evidence snapshots accompany this report; full-resolution clouds, raw recordings and complete experiment arrays remain in their original archives and the results website. No new laboratory test, public deployment or cross-dataset generalization result is claimed here.

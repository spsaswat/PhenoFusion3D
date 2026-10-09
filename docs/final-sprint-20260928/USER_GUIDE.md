# PhenoFusion3D end-to-end user guide

Version: 8 October 2026. This guide follows the current `main.py` desktop application and its offline analysis window. It covers setup, capture, reconstruction, inspection, traits, manual validation, hyperspectral analysis, reviewed spectral association and saving results. Laboratory operation still requires testing on the actual rig; writing this guide is not a hardware acceptance test.

For the results, decisions, evidence and unresolved research questions, read the [complete final sprint explanation](index.html). For proposed team responsibilities, use the [issue pack](issues.html). This guide describes how to operate the software; a separately generated research result is not necessarily a one-click feature in the application.

## 1. Choose your starting point

| Your goal | Start here | What you need |
|---|---|---|
| Acquire new RGB-D recordings | Sections 2–4 | Lab camera, existing drivers, storage; working ROS and gantry for moving scans |
| Reconstruct a saved recording | Sections 5–7 | Matched RGB/depth frames, intrinsics, recorded depth units; motion information for RGB stereo |
| Measure and validate traits | Sections 8–10 | Reviewed plant cloud, specimen identities, matching manual measurements |
| Inspect new hyperspectral data | Sections 11–12 | ENVI header/data pair and reviewed extraction setup |
| Associate spectra with 3D points | Section 13 | Measured spectra, unchanged source cloud and reviewed correspondence evidence |
| Replay the old August experiment | Section 14 | Exact reviewed historical inputs |
| Review or share saved results | Sections 15–17 | Complete output folder and its provenance |

The offline processing tools run locally without Codex or another AI service. They still require appropriate inputs and human review. They cannot guarantee a complete 360-degree plant from unobserved surfaces or automatically establish every cross-camera correspondence.

## 2. Prepare and launch

On the working lab machine, use the existing environment and launcher first. Keep its camera and ROS configuration recorded. Do not upgrade a working hardware environment merely to open a report.

From the repository root on the supported Linux lab setup, check the existing installation without changing it:

```bash
./setup.sh --check
```

For a new installation with the required system prerequisites already available:

```bash
./setup.sh
source .venv-linux/bin/activate
python main.py
```

Setup creates the project environment and a per-user Ubuntu Activities launcher. It does not install system ROS, replace the gantry workspace or install system drivers. Python 3.10–3.12 is the documented lab range. System ROS remains separate from the GUI environment.

If multiple RealSense devices are connected, select the intended serial before launching. Replace the example values with the machine's actual values:

```bash
export PHENOFUSION_CAMERA_SERIAL=YOUR_CAMERA_SERIAL
export PHENOFUSION_ROS_WS=/path/to/gantry_workspace
python main.py
```

Setting these before `setup.sh` also records them in the generated launcher. Check the selected model and serial; D405 and L515 are separate acquisitions, not interchangeable files.

For a separate Windows offline-analysis environment, create and activate an environment from the repository root, then install the analysis extras:

```powershell
py -3.11 -m venv .venv-analysis
.\.venv-analysis\Scripts\Activate.ps1
python -m pip install -e ".[analysis,hyperspectral,hyperspectral-viewer]"
python main.py
```

This is a fresh analysis-environment recipe, not a claim that the lab's ROS gantry runs on Windows. Camera-only Windows support uses the separate `windows` extra and compatible device setup. Follow the repository installation instructions for that hardware configuration. Package installation may need internet; processing installed workflows does not need an AI service. If embedded WebEngine is unavailable, use the saved report in an external browser.

## 3. Organise inputs before recording or processing

Keep raw acquisitions unchanged. Use different folders for calibration and plant scans and for each camera. Preserve original frame identifiers, timestamps, intrinsics, sensor serial, depth units, exposure and motion metadata. Give plants stable specimen IDs and use the same IDs in ruler photographs and measurements.

For this project's confirmed ChArUco target, the board has 7 × 10 squares, 25 mm square edges, 18 mm marker edges and `DICT_4X4_50`. In metric calibration configuration these lengths are 0.025 m and 0.018 m. A plain checkerboard image is not interchangeable with this ChArUco target. The earlier 127/76 values are not physical square dimensions.

Record calibration using the actual cameras and configuration. If a mount, angle or scan geometry changes, review whether the previous calibration still applies. Board dimensions alone do not establish hyperspectral scan timing or an elevated leaf's correspondence to a 3D point. The desktop workflow does not provide a universal automatic calibration wizard; calibration setups and reviewed poses are explicit analysis inputs.

For hyperspectral acquisition, retain the ENVI header and binary data together. Record panel identity/reflectance, exposure, illumination, scan direction, speed and white/dark acquisition details. A bright white board does not by itself supply known reflectance, and an unconfirmed final dark-looking strip must not automatically be treated as shutter-closed data.

## 4. Capture RGB-D data and operate the gantry

1. Open **Data Capture**. Choose the output folder and the intended backend.
2. Choose **RealSense Only** for stationary camera capture, or **ROS + Gantry** for the configured moving scan. **Auto** selects according to runtime availability; check the selection before starting.
3. For a moving scan, verify **Velocity (mm/s)** and **End (mm)** against the rig's approved travel. For camera-only capture, set **Duration (s, RealSense)** and FPS. Duration 0 means capture until Stop.
4. Check free RAM and disk space. Capture buffers frames before saving; long recordings require substantial memory.
5. Click **Capture**. Observe the progress and log. Use **Stop** to stop acquisition, then wait for buffered frames to finish saving.
6. Click **Open captured folder**. Confirm that RGB, depth, intrinsics and session metadata exist before disconnecting equipment or closing the application.

The separate **Gantry Control** panel provides **Jog**, **Go**, **Go Home** and **STOP**. It can operate independently of camera capture. Use the physical rig's operating procedure when moving equipment. On normal combined-scan completion the implemented workflow returns home; an operator Stop does not initiate a new homing move. Wait for saving to finish before exiting.

**Hypercam UI** opens the configured local hyperspectral service. The application permits this action only when reported gantry position is within 1.0–1.9 mm. If blocked, check the actual position and rig procedure; do not bypass the guard. This button opens the camera service—it does not automatically calibrate or fuse its output.

Typical saved capture layout:

```text
data/captures/<timestamp>/
  rgb/<frame>.png
  depth/<frame>.png
  kdc_intrinsics.txt
  kd_intrinsics.txt
  session.json
```

Successful capture populates Data Loading. Read the log for failures or incomplete output rather than treating the existence of a folder as success.

## 5. Import and check recordings

In **Data Loading**, select **RGB Images**, **Depth Images** and the appropriate intrinsics file. The main panel labels the intrinsics input **Intrinsics JSON**; the offline recording workflow also understands its documented recording metadata formats. Avoid substituting intrinsics from a different resolution or camera.

Use **Data Quality → Quick Check** for an initial sample and **Full Report** for the recording. Inspect valid-depth coverage, depth range, overlap, registration fitness and RMSE. Save the resulting report. A registration score does not certify a complete plant or accurate leaf dimensions.

For offline analysis, supported recordings include `rgb/` and `depth/` folders or flat `rgb_<ID>.png` / `depth_<ID>.png` files with genuine matching identifiers. RGB and aligned depth must correspond to the same observation. Never repair missing frames by renaming a nearby image to manufacture a pair.

Depth units are essential. The offline field is **raw depth units per metre**, the reciprocal of metres per raw count. For example, 0.0001 metres/count means 10000 units/metre. A value of 0 requests metadata where supported; it does not mean zero physical depth. Do not tune depth scale to make a plant agree with its manual height.

## 6. Reconstruct the plant

The existing main-window route is **Data Loading → Run Reconstruction**. **Step Size** uses every Nth frame. Review the live result and metrics, then use **File → Export PLY...** and **Export Metrics CSV...**. Keep the original lab workflow available for regression comparisons.

For the added offline route:

1. Open **Analysis → Offline reconstruction, traits and hyperspectral fusion...**.
2. Select **Reconstruct**, then the **Recording folder** and an explicit **Results parent folder** outside the raw recordings.
3. Enter verified raw depth units if metadata is missing. Leave near/far at estimate only if you will inspect the chosen interval.
4. Select camera views, motion direction, foreground selection and reconstruction method. Start with `auto` for the supported overlapping overhead gantry setup.
5. Supply **Saved camera poses** if required by the acquisition. These must be calibrated poses in the expected format, not arbitrary display rotations.
6. Click **Check recording and explain settings**. Review the chosen frames, units, range and selected method before the full run.
7. Click **Reconstruct from photographs + coloured ICP**. Review logs and open the completed result.

Automatic RGB reconstruction relies on supported overlapping camera motion and usable motion information, such as monotonic encoder positions. Without suitable metric motion information, automatic mode can use sensor-depth reconstruction instead. The button's wording does not mean every recording necessarily used RGB stereo. Read the saved method and diagnostics.

Foreground `auto` targets the supported scene geometry. `depth` retains surfaces in the selected range, which can include background. `colour` can miss tissue whose appearance does not match the segmentation. Inspect masks for red foliage, narrow leaves, stems and tips rather than trusting a colour filter alone.

Offline jobs run in a child process. **Cancel processing** or closing the analysis dialog can terminate the job and leave explicitly incomplete output. Capture takes priority over optional analysis. Keep the laptop awake while processing; sleep pauses local computation.

## 7. Inspect, clean and combine camera results

Rotate the cloud through front, side and overhead views. Look for duplicated leaves, disconnected stems, missing tips, background fragments and alignment errors. Inspect each plant separately as well as the full scene. A convincing view from one angle is insufficient.

Keep an original cloud and a separate cleaned cloud. Inspect any removed-point result or cleanup mask so thin genuine leaves are not silently discarded. Correct orientation using an explicit reviewed transform and choose the corresponding height axis. A display rotation alone does not prove stored measurement coordinates are upright.

For D405/L515 combination, reconstruct each independently, establish their common frame, then review the registration and supported contribution from each. The final sprint's fusion was an evidence-reviewed research procedure with saved transforms and checks. It is not a universal **Fuse both cameras** desktop button. Use the research workspace to retain the aligned clouds and provenance; do not simply concatenate unrelated coordinates.

ICP aligns observations that exist. It does not measure unseen leaf undersides or repair absent depth. Gap filling for appearance must remain distinguishable from measured geometry and must not be used as new measurement evidence.

## 8. Extract plant traits

1. Open **Model traits / RGB-D references**.
2. Select a **Reviewed plant-only PLY**. Exclude the pot, soil and other plants for plant-tissue measurements.
3. Set **Plant height axis** to the actual upright axis.
4. Review orientation and exclusions, then tick the confirmation and click **Extract 3D model traits**.
5. Inspect the saved trait values and retain the exact cloud used to calculate them.

Cloud spans, projected canopy area, projected convex hull and 3D hull quantities describe different things. A cloud's minimum-to-maximum height is not automatically a biological stem-base-to-tip height. Missing tips reduce an observed span; stray points can increase it.

The same tab can **Extract image-derived reference traits** from a recording using verified units and expected plant count. Review its selected images and masks. These references come from RGB-D data and are useful diagnostics, but are not independent physical ground truth.

## 9. Validate plant-level measurements

In **Validate traits**, select the parent containing `plant_N` trait folders, an optional image-reference JSON and/or a physical-measurement CSV. Enter explicit **Confirmed specimen pairs**, such as `1:2 2:1`, only when those reference/model identities are genuinely matched. Click **Create comparison report**.

Physical CSV columns include:

```text
plant_id
physical_plant_height_m
physical_canopy_major_span_m
physical_canopy_minor_span_m
physical_projected_canopy_area_m2
physical_projected_convex_hull_area_m2
```

Lengths are metres and areas are square metres. Leave unmeasured cells blank. Do not enter zero for unavailable measurements. Record the manual definition: for this study plant height was from stem base to the highest plant tip, including the tip. Pot-bottom height or a partial observed span is a different quantity.

Review individual comparisons, sample count, excluded measurements and reasons before quoting an aggregate error. Zero eligible comparisons means no validation result, not perfect accuracy. Retain ruler photographs, their interpretation and uncertain units alongside the CSV.

## 10. Validate identified leaves and source-cloud endpoints

For image-assisted leaf measurements, open **Matched leaves**. Choose the recording and verified depth units, then **Mark leaves on a source photograph**. Identify the same physical leaf and mark tip, blade base and the two width endpoints. Save the leaf annotation JSON and use **Measure marked leaves and compare**. The report separates length and width in millimetres. Review depth support; background or a neighbouring leaf must not supply the endpoint depth.

These are image-derived measurements. A 3D straight-line chord differs from a curved ruler measurement along a bent blade. Match definitions before calling a discrepancy an error.

For explicit measurements on saved research clouds, use **Research workspace**:

1. **Create workspace setup template** and fill the generated JSON with actual specimen IDs, cloud paths, coordinate units, orientation and references.
2. Use a fresh output location and **Build / check research workspace**. A units label does not rescale coordinates; an upright rotation does not repair scale.
3. Open the report. Choose **Mark first point**, double-click the intended source location, then **Mark second point**, **Keep endpoint pair** and **Download endpoint JSON**.
4. Retain cloud hashes and source point indices. Review the endpoint identity, measurement type and manual-reference match before using the exported annotations in a configured follow-up workspace.

Ordinary endpoint pairs are observed chords until their biological meaning is established. Full-height validation needs an identified stem base and highest tip. Review fields such as `landmarks_reviewed`, `organ_match_confirmed` and the reference ID must record real review, not merely enable acceptance. Replacing or reordering the cloud invalidates saved point identities; create and review new annotations.

The saved final-sprint report contains 13 conditional leaf comparisons and a ledger of all 47 manual dimensions. Its unresolved matches and photo/unit conflicts remain visible. Do not describe those results as validated full-plant height for all five specimens.

## 11. Extract hyperspectral measurements

Use **Research workspace → Extract measured spectra from reviewed regions** for compatible new recordings. Create the extraction configuration described in the bundled research-workspace reference guide: specify the real ENVI header/data, sensor identity, reviewed sample regions and applicable reference regions. Check header dimensions, wavelength metadata and binary size first.

Choose both available sensors through their actual recorded identity. The September headers identify **FX10 and FX17**; do not rename FX10 to FX15 based on earlier conversation shorthand. Keep each sensor's wavelengths, samples and products separate.

Save the extraction output including:

```text
measured_spectra.npz
measured_spectra.metadata.json
summary.json
```

Review source-pixel positions and quality flags. The September 13,343-sample result contains selected reviewed patches, not every pixel or complete plant segmentation. A region name alone is not proof of plant or organ identity.

## 12. Inspect spectra and interpret values

Open **Spectral review / 3D fusion**. Select the extracted result folder for the available sensors, choose a fresh output location and click **Build interactive spectral review**. Use **Open latest result** or open a saved spectral report. This input is the extracted bundle, not a raw ENVI directory.

Choose a sensor, displayed measurement and wavelength. Click a recorded sample to inspect its spectrum and source scan-line/detector-column identity. Download the sample CSV where available. Check quality flags before comparing values.

| Display | Interpretation | Requirement or limit |
|---|---|---|
| Raw DN | Recorded detector signal | Not reflectance; affected by exposure and illumination |
| Q | `(DN - D) / (W - D)` reference-relative signal | Requires applicable reviewed white/dark support and valid denominator |
| Q0 | `DN / W` white-relative signal | Omits dark correction; not calibrated reflectance |
| NDVI-style descriptor | Ratio derived from supported red/NIR bands | Its scientific interpretation depends on calibration and valid band data |
| FX17 SWIR ratio in the saved research report | Exploratory signal comparison | Not a calibrated measurement of water content |

Unknown white-panel reflectance and unconfirmed dark capture prevent claiming calibrated reflectance. FX17 lacks the red wavelength needed for the usual red/NIR NDVI formulation. Do not obtain it by silently mixing unrelated camera pixels. Missing values remain missing; grey points or gaps are not zeros. Per-view colour ranges can change, so compare numeric values rather than colour alone.

## 13. Associate measured spectra with 3D points

1. In **Spectral review / 3D fusion**, click **Create 3D fusion setup template**.
2. Enter the actual cloud and spectral-bundle paths, sensor identity, source sample indices, source vertex indices and correspondence evidence in that template.
3. Review the visible feature match and supporting RGB views. Retain the required source hashes and evidence; the template is a schema, not an automatic calibration.
4. Click **Build sparse measured fusion**, then inspect the result from multiple views.
5. Select a sensor and wavelength, inspect each association and export the complete result folder.

`sample_index` is an extracted-array row identity, not a wavelength index or raw detector column. `point_index` refers to the original cloud vertex. Use the generated template and the spectral-fusion reference guide for the full fields and evidence rules; fabricated indices or support records produce misleading associations.

The older three coloured markers show three provisional associations, with spectra from both cameras. Their enlarged display size does not represent detector footprint, and showing a marker through geometry is a viewing aid. Unassigned RGB geometry remains without a spectral measurement.

The later fusion-rescue result contains partial mappings on two upper Plant 5 leaves: 2,338 FX10 and 862 FX17 samples. It is a separately saved research investigation, not an automatic dense-fusion mode for any dataset. Those added upper patches provide raw DN; unsupported reference-relative values are not invented. The [sprint explanation](index.html) records the methods attempted, correspondence uncertainty and remaining gaps.

## 14. Replay the historical August workflow

**Hyperspectral / fusion · experimental** preserves the reviewed 28 August 2026 recipe. Its fixed calibration regions and specimen/frame assumptions are deliberately dataset-specific.

Select the exact paired FX10/FX17 recording and its matching RGB-D recording/reviewed ICP results. Choose **Spectral analysis only**, **Fusion from existing spectral results** or **Spectral analysis → RGB-D / ICP fusion**. Select a new results parent, run **Check historical inputs**, then **Run selected experimental workflow**. Use **Display saved report in software** to open its showcase.

Input checking restricts automatic replay to the reviewed historical data. The manual workspace for other inputs is unvalidated, not a promise of equivalent automatic results. Do not apply the August pixel warp to September plants or transfer a spectrum between datasets simply because the resulting picture looks plausible.

## 15. Save, reopen and share

Choose an explicit results parent so new analyses do not become mixed with raw input files. Offline tools commonly create timestamped `analysis_results` children; research builders use their selected output paths. Keep each version separately and check the saved completion status and log.

Retain the cloud, transforms, settings, source identities, annotations, numerical outputs, quality information and report assets together. Keep cancelled runs labelled incomplete. Reopen `index.html` or the saved report through the application's relevant report field. If a browser blocks local asset loading, serve the report directory locally or use the application's report viewer.

Copy the entire report folder for sharing; an HTML file alone may reference cloud binaries, JSON or scripts beside it. A `127.0.0.1` link works only on the computer running that server. A repository commit, push and successful public website deployment are separate steps. Verify the public URL before sending it to collaborators.

## 16. Troubleshooting

| Symptom | Check and action |
|---|---|
| No camera or wrong camera | Check connection, runtime and device serial; run setup check before changing dependencies |
| ROS + Gantry unavailable | Check existing ROS installation and workspace environment; do not pip-install ROS into the GUI environment |
| Hypercam UI blocked | Verify the live gantry position and approved positioning procedure |
| Capture stopped but app is busy | Wait for buffered frames to save; check free disk and log |
| Recording fails pairing checks | Restore the correct export; preserve original IDs rather than renaming unrelated frames |
| Cloud dimensions are implausible | Check camera depth units, intrinsics, calibration and coordinate scale |
| Cloud is fragmented | Inspect source depth, overlap, masks, frame rejection and pose support; missing observations may need recapture |
| Plant appears upside down | Verify the recorded frame and explicit upright transform before traits; select the correct height axis |
| Report is blank in the app | Try external browser viewing of the complete saved report; check optional WebEngine availability |
| Output path already exists | Use a fresh run folder so previous results remain inspectable |
| Validation has no eligible rows | Check specimen/organ identity, units, quantity definitions and endpoint evidence |
| Spectral value is grey or absent | Read flags and reference coverage; missing data must not become zero or interpolation labelled as measured |
| Cloud hash or point identity differs | Restore the original cloud or redo and review annotations on the replacement |
| Job ended during sleep or cancellation | Check completion status and logs; rerun into a new folder if incomplete |

## 17. Lab acceptance and supporting references

Before treating an updated checkout as accepted on the laboratory machine, verify launch, the selected RealSense camera, stationary capture, authorised gantry movement, combined capture, Stop behaviour, buffered saving, reload and a small reconstruction. Record the machine, commit, operator and outcome. Then test optional offline analysis separately. These checks are a pending operational handover where no physical test has been recorded; documentation does not certify that hardware was exercised.

The following bundled references provide detailed file schemas and specialist workflow instructions. They are snapshots of the repository documentation; some contain earlier research results. Use the dated sprint explanation and fusion-rescue evidence for the latest scientific interpretation.

- [Installation reference](reference/install.md)
- [Offline analysis reference](reference/ANALYSIS_WORKFLOW.md)
- [Trait validation reference](reference/TRAIT_VALIDATION.md)
- [Research workspace schemas and endpoint workflow](reference/RESEARCH_WORKSPACE.md)
- [Measured spectral fusion schema](reference/SPECTRAL_FUSION_WORKFLOW.md)
- [Historical hyperspectral recipe](reference/HYPERSPECTRAL_WORKFLOW.md)
- [Download this user guide](USER_GUIDE.md)

Documentation was checked against `main.py`, `app/main_window.py`, `app/analysis_dialog.py`, the capture/data/gantry panels, packaging metadata and the linked repository workflow guides. No camera motion, capture or reconstruction algorithm was changed to produce it.

# Offline reconstruction and trait validation

Open the normal application with `python main.py` or the existing lab launcher,
then choose **Analysis → Offline reconstruction and trait validation**. Capture,
gantry movement, the original reconstruction button and the lab launcher retain
their existing implementation. Analysis runs in a separate local Python process;
no API, model service, token, internet connection or Codex session is required.

The optional dependency group is `pip install -e '.[analysis]'` **inside the
existing application virtual environment**. It declares SciPy, which Open3D
environments commonly already contain. Do not reinstall ROS or change the pinned
RealSense SDK for this feature.

## Reconstruct a recording

1. Select the recording containing paired `rgb/` and `depth/` PNGs, or flat
   `rgb_ID.png` / `depth_ID.png` files, with `kdc_intrinsics.txt` RGB calibration.
   RGB and depth must be aligned at the same resolution and use matching IDs.
2. Enter the camera-reported raw depth units per metre only if missing from
   `session.json`. For example, a 0.0001 m camera depth scale means 10,000 units/m.
   This must be known from capture/calibration; the software will not infer units
   from the plant size. Missing metadata is reported before reconstruction.
3. Use **Check recording and explain settings** to save the selected frames,
   pose source, image hash, range and processing settings. Then reconstruct.
4. Open the offline interactive result and inspect every side, its masks,
   registration diagnostics and evidence. Previous output directories and raw
   images are preserved. Every new run has a separate timestamped directory.

### Automatic decisions

For a monotonic gantry pass with encoder positions, automatic mode estimates the
camera's horizontal motion direction from RGB correspondences, locates the useful
foliage interval, selects camera views by physical position, refines their poses,
chooses stereo neighbours by predicted disparity, checks repeated stereo depth,
and applies coloured ICP and volumetric fusion. The foreground selector uses a
dominant neutral support-depth layer and broad foliage colours. It does not
require green leaves. The optional depth mode retains all surfaces in an explicit
depth interval and is useful when appearance-based plant selection is unsuitable.

Central overlapping views also establish a shared foreground limit in the
reconstruction coordinates. This rejects distant floor fragments admitted by
per-frame masks when a raised support board leaves the image. The estimated
plane and source frames are recorded in the result summary. This assumes a
common overhead support surface; inspect it for unusual capture arrangements.
Visibility checks use bounded batches to reduce temporary memory demand.

Colour ICP can fall back to point-to-plane registration when colour
correspondences fail; the same overlap and motion gates still apply. Disconnected
or insufficiently supported surfaces are rejected. The voxel spacing is a
processing setting, not the achieved physical accuracy.

For recordings without encoder positions or supplied metric camera poses,
automatic mode selects the existing lab sensor-depth ICP implementation. This is
a different evidence path: its result explicitly states that stereo support-vote
validation is unavailable. Sensor-depth edge errors can survive this method.
The original reconstruction controls remain available as well.

### Advanced inputs and supported boundary

The new RGB route currently supports overlapping horizontal stereo baselines.
It is not a universal arbitrary-camera-motion reconstruction system. For another
capture geometry, supply measured camera-to-reference poses using a JSON object
with `reference` and `frames`, each frame containing `frame`, `accepted` and a
rigid 4×4 `transform`. IDs must match image filenames. Invalid, reversing or
ambiguous motion is reported instead of being silently treated as a linear pass.

Automatic foreground selection is a heuristic for overhead plant recordings.
Unusual foliage, coloured equipment, occlusion or a missing support surface may
require the depth interval/foreground controls and another capture. These are
normal operator inputs, not changes to the code. A new species or dataset name
does not require adding its name or frame numbers to the implementation.

The accepted Coleus research result used a more tightly reviewed capture-specific
recipe. This integration generalizes its calibrated RGB stereo, camera refinement,
ICP and visibility methods; it does not claim identical output for every new
automatically chosen recipe. No successful ICP score proves a complete plant.

## Model traits and image-derived references

Select a reviewed plant-only PLY and its height axis. Exclude the pot/background
and confirm orientation before extracting model traits. The app preserves the
existing hull metrics and adds matched projected canopy area, projected hull
area, and oriented canopy spans. Output is under `plant_1/traits.json`; assemble
multiple reviewed specimen results as `plant_N` folders before comparison.

Height uses the minimum model point as its base. That is a model descriptor,
not automatically the physical plant base. Review this definition before comparing
with a ruler height. A 3D convex-hull surface area is not the same quantity as a
2D projected canopy area or total leaf area.

The image-reference action discovers specimen views and writes reference traits,
mask/leaf overlays, a contact sheet, and a blank physical measurement CSV. Its
colour masks and visible-leaf separation remain exploratory. The chosen RGB/depth
images are undistorted together before metric calculations. These references
share the camera data and are not independent physical ground truth.

In **Validate traits**, select the `plant_N` traits parent directory and either
the image-reference JSON or completed physical CSV (or both). Supply confirmed
specimen pairs such as `1:2 2:1`. Missing measurements are blank, not zero; a
missing or duplicate identity is rejected. CSV dimensions use metres and areas
use square metres. Each comparison is retained with units and signed error.

## Matched leaf length and width

In **Matched leaves**, select the recording and depth scale. Mark the physical
leaf's tip, base and two width endpoints on a source photograph, enter its plant
and leaf IDs and manual dimensions in millimetres, then save the annotations.
Existing reviewed `guided_leaf_landmarks.json` plant/leaf files are also accepted.

The app samples coherent observed depth locally. If needed, it searches adjacent
frames using template correspondence, checks the match in both directions, and
records the selected frame, correlation and depth search radius. Radii can extend
to 25 pixels when local data is missing; large-radius results deserve particular
review because neighbouring geometry can influence their depth estimate.
No physical reference dimension is used to select a frame or fit a measurement.

Reports contain separate leaf-length and leaf-width rows, both projected depth-
scaled distances and 3D endpoint chords. These estimates are not curved leaf
length, full leaf surface area or measurements of automatically segmented 3D
leaf instances. Human-confirmed identity remains necessary. The software cannot
reliably infer which physical leaf was measured from a plant number alone.

## Capture priority and cancellation

An offline job will not start during an active capture or existing processing job.
Starting capture cancels the optional analysis process. Cancelling or closing the
analysis dialog terminates its child process and labels partial results as
cancelled. The existing camera/gantry safety and shutdown code is unchanged.

## Hyperspectral analysis and measured-spectrum fusion

The fifth tab, **Hyperspectral / fusion · experimental**, adds the copied
28 August 2026 spectral analysis and RGB-D / ICP mapping workflow. It includes
three automatic modes, the original manual spectral workspace, and an in-software
HTML result viewer. The automatic recipe is restricted to the historical dataset;
new recordings and physical fusion accuracy remain unvalidated. Current 3D
reconstruction and trait code is preserved. Read
[HYPERSPECTRAL_WORKFLOW.md](HYPERSPECTRAL_WORKFLOW.md) before running it.

## Lab acceptance

Offline checks cannot establish that the physical camera and gantry operate
correctly. On the lab machine, first verify startup, capture, jog/release-stop,
home, buffered save and shutdown using the existing procedure. Then test the new
analysis dialog on a copy of a saved recording. Inspect geometry against its
photographs and validate a few physical dimensions before relying on traits.

For more complete coverage, keep the plant in the camera's useful range, record
overlapping tilted/side views with calibrated poses, keep leaves still, and verify
coverage in a short pilot. Unobserved undersides cannot become measured geometry
through software-only hole filling.

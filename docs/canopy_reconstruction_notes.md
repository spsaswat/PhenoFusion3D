# rs_data_5 Plant 3D Reconstruction Notes

## What Data Is Used

The current working result was generated from:

```text
rs_data_5/test_plant_20230809132457
```

The `rs_data_5` folder currently contains six `test_plant_*` RGB-D scan folders. Each folder is treated as one plant/scan record and contains paired files:

```text
rgb_<timestamp>.png
depth_<timestamp>.png
kdc_intrinsics.txt
kd_intrinsics.txt
```

The reconstruction command can process either one record folder or the whole `rs_data_5` folder.

## Why The Original Reconstruction Was Poor

The original RGB-D stitching method used frame-to-frame ICP. That approach works best when consecutive point clouds observe the same rigid object with enough shared 3D geometry.

For `rs_data_5`, the camera is mostly top-down and the plant moves through the image like a rail/conveyor scan. The frames also include background objects such as rails, floor, boxes, colour chart, and sometimes other small plants. If all depth points are sent into ICP, the algorithm may align background instead of the target plant, so the final point cloud becomes scattered and the plant shape does not form cleanly.

The fixed pipeline therefore uses a plant-focused canopy reconstruction method instead of generic full-scene ICP.

## Algorithm Principle

1. Load one RGB-D record.

The program reads all `rgb_*.png` and `depth_*.png` pairs from a record folder, plus the RealSense intrinsics from `kdc_intrinsics.txt` or `kd_intrinsics.txt`.

2. Automatically segment the leaf canopy.

If there is no manual `reconstruction/masks` folder, the algorithm generates masks from RGB. It converts each image to HSV and also computes an excess-green score:

```text
ExG = 2 * G - R - B
```

Pixels are kept when they look green enough in hue, saturation, brightness, and ExG. Small components are removed so colour charts, noise, and weak background patches do not dominate.

3. Select strong target-plant frames.

Each generated mask is scored by plant area and edge quality. The frame with the strongest mask becomes the reference frame. Nearby high-quality frames are selected for fusion.

4. Align frames by plant motion, not by background.

Since this dataset behaves like a top-down rail scan, the code estimates the plant mask centroid in each selected frame and fits a simple linear image-plane motion model. Every selected frame is shifted onto the reference plant position. This avoids ordinary ICP locking onto floor, rails, or boxes.

5. Fuse depth maps on an expanded canvas.

The selected depth maps are warped into one canvas. The canvas is larger than one original image so shifted frames are not immediately clipped. Inside the plant mask, invalid depth values and holes are filled by nearest valid depth and then smoothed.

6. Convert fused depth to 3D.

For every valid canopy pixel, the code uses the camera intrinsics:

```text
X = (u - cx) * Z / fx
Y = (v - cy) * Z / fy
Z = depth
```

Then it builds a height surface from the fused depth. This gives a coloured canopy point cloud and a triangle mesh.

7. Generate an interactive browser viewer.

The point cloud is downsampled and embedded into `canopy_viewer.html`. You can drag to rotate, scroll to zoom, and double click to reset the view.

## How To Run

Process all records under `rs_data_5`:

```bash
python main.py --input rs_data_5 --max-frames 11 --coverage-threshold 1
```

Process one record:

```bash
python main.py --input rs_data_5/test_plant_20230809132457 --max-frames 11 --coverage-threshold 1
```

The default mode is now `canopy`, so `--mode canopy` is optional.

## Main Outputs

For each record, outputs are written under:

```text
rs_data_5/canopy_batch/<record_name>/
```

Important files:

```text
canopy_points.ply       coloured point cloud
canopy_mesh.ply         coloured triangle mesh
canopy_viewer.html      browser viewer with drag/zoom controls
fused_rgb_masked.png    fused top-view plant image
fused_mask.png          final plant mask
fused_depth_vis.png     depth/height preview
canopy_summary.json     selected frames, parameters, counts, paths
auto_masks/             automatically generated masks
```

## Code Map

Main CLI entry:

```text
main.py
```

- `_discover_records`: detects whether input is one record or a parent folder.
- `build_parser`: defines command-line arguments.
- `main`: runs canopy reconstruction for one or multiple records.

Canopy reconstruction:

```text
processing/canopy.py
```

- `CanopyReconstructionConfig`: parameters for masks, depth filtering, fusion, and output.
- `_auto_leaf_mask`: automatic green-leaf segmentation.
- `_load_auto_candidates`: generates and scores automatic masks.
- `_select_frames`: chooses the reference frame and nearby strong frames.
- `_estimate_alignment_transforms`: estimates plant motion from mask centroids.
- `_build_canvas_transforms`: expands the fusion canvas and offsets each frame.
- `_fill_depth_inside_mask`: filters, fills, and smooths depth inside the canopy mask.
- `_build_mesh_and_point_cloud`: converts fused depth and colour into a 3D point cloud and mesh.
- `reconstruct_canopy`: orchestrates the full pipeline and writes all outputs.

Interactive viewer:

```text
visualiser/viewer.py
```

- `write_point_cloud_viewer`: samples the point cloud and writes `canopy_viewer.html`.
- `_viewer_html`: contains the WebGL viewer code for drag rotation and zoom.

Tests:

```text
tests/test_e2e.py
```

- Checks normal RGB-D reconstruction still runs.
- Checks mask-guided canopy reconstruction.
- Checks automatic-mask canopy reconstruction and viewer generation.

## Verification

The end-to-end test command is:

```bash
python -m unittest tests.test_e2e -v
```

The latest run passed. Full `pytest` may require all dependencies from `requirements.txt`, including `Pygments`.

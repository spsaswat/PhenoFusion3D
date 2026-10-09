# Trait validation protocol

Use **Analysis → Offline reconstruction and trait validation** in the app.
[ANALYSIS_WORKFLOW.md](ANALYSIS_WORKFLOW.md) documents all four workflows,
required inputs, specimen matching and measurement limitations.

Keep model descriptors, image-derived RGB-D references and independent physical
measurements distinct. RGB-D references share the reconstruction input and cannot
establish independent physical accuracy.

## Command-line equivalents

Output directories must be new or empty. Replace the example scale with the
camera-reported raw depth units per metre for the recording.

```bash
python -m processing.analysis_workflow references --input RECORDING --output REFERENCES --depth-scale 10000 --plants 3
python -m processing.analysis_workflow traits --input PLANT_ONLY.ply --output MODEL_TRAITS --axis z
python -m processing.analysis_workflow compare --input MODEL_TRAITS --output COMPARISON --reference REFERENCES/reference_traits.json --mapping "1:1"
python -m processing.analysis_workflow compare --input MODEL_TRAITS --output PHYSICAL_COMPARISON --manual REFERENCES/manual_measurements_template.csv --mapping "1:1"
python -m processing.analysis_workflow leaves --input RECORDING --output LEAF_COMPARISON --config REVIEWED_LEAVES.json
```

For multiple plants, assemble model descriptors under `plant_N/traits.json` and
provide all confirmed pairs, for example `--mapping "1:2 2:3 3:1"`. Inspect the
reference contact sheet and model previews to establish identity. Missing,
duplicate or unmatched IDs are rejected. Blank measurements remain absent.

## Comparable definitions

| Quantity | Interpretation |
|---|---|
| Canopy major/minor span | Oriented projected spans in the same plane |
| Projected canopy area | Occupied calibrated pixel/grid footprint, including resolution |
| Projected convex-hull area | 2D hull; not 3D hull surface area |
| Height | Confirm physical base and axis; model minimum point may differ |
| Visible depth relief | Diagnostic percentile range; not ruler height |
| Matched leaf length/width | Confirmed endpoints and identity; projected distance and 3D chord reported separately |

Manual CSV dimensions use metres and square metres; leaf annotations use
millimetres. Record the measurement method, operator and date. Do not compare
total destructive leaf area with visible projected canopy area. Visible-leaf
segmentation remains exploratory.

Matched-leaf reports record adjacent-frame tracking and local depth sampling
radius. Review large-radius estimates because neighbouring geometry may affect
them. Physical reference dimensions are never used to fit computed measurements.

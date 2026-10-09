# L515 replacement data audit — 7 October 2026

The replacement resolves the earlier missing RGB/depth filename pairs. D405 remains the current reconstruction priority; L515 is prepared for a subsequent, separate reconstruction using its own calibration. No L515 reconstruction was started by this audit.

| Capture | RGB images | Depth images | Exact ID pairs | Unmatched images | Decode failures |
|---|---:|---:|---:|---:|---:|
| Calibration: `test_plant_20260928144647_L515` | 1,290 | 1,290 | 1,290 | 0 | 0 |
| Plants: `test_plant_20260928162111_L515` | 1,278 | 1,278 | 1,278 | 0 | 0 |

All 5,136 PNG files were decoded and hashed. RGB files are 1280 × 720, three-channel uint8; depth files are 1280 × 720, single-channel uint16. No duplicate numeric IDs were found within either modality. File names, sizes and modification times remained stable during the audit. Sample source images confirm the checkerboard scene in the calibration folder and plants in the plant folder. The plant folder contains 2,558 files including its two intrinsic files, agreeing with the user's Explorer count.

The previous plant export contained 233 RGB images, 490 depth images and only 89 exact pairs. Its original archive audit remains historical evidence; the replacement is a new source version. Exact pairing and successful decoding do not establish capture synchronization, original recording completeness or depth accuracy.

## Calibration readiness

Both saved intrinsic files are byte-identical across the calibration and plant folders. All four source RGB images and the colour intrinsic file used in the earlier L515 checkerboard diagnostic also match their saved SHA256 hashes. See [the input identity check](prior_checkerboard_input_check.json). This preserves that diagnostic's source identity; it is not a new calibration or an independent accuracy test.

The depth PNG dimensions match the colour profile, while `kd_intrinsics.txt` describes a native 1024 × 768 depth profile. Current capture code aligns depth to colour, which is consistent with this export, but the recording has no session-specific alignment record. Verify registration before choosing projection intrinsics; applying the native depth intrinsics directly to these PNGs would be inappropriate.

No metres-per-count depth scale accompanies the export. L515 must use its own verified scale or an explicitly conditional estimate; the D405 scale cannot be transferred. Physical checkerboard square size also remains unverified. These issues must be assessed before reporting metric plant measurements. See [the independent metadata audit](../research_20260928_improvement_20261007/sensor_audit/l515_replacement_metadata/L515_METADATA_AUDIT.md).

## Evidence and next stage

- [Audit summary](replacement_audit.json), including historical counts and source-stability checks.
- `*_manifest.json`: every source file's SHA256 and size, plus decoded image format.
- `*_exact_pairs.csv`: exact numeric-ID RGB/depth pair lists.
- `audit_replacement.py`: repeatable, read-only source audit.

After the D405 reconstruction review, use the L515 checkerboard capture to assess its camera model, depth scale and alignment, then reconstruct the L515 plants independently. Compare observed coverage and geometric agreement before considering camera fusion. Another camera may contribute useful views, but filling the D405 gaps is not established by this inventory.

Raw recordings, D405 reconstruction products, application source, camera capture and gantry controls were not modified.

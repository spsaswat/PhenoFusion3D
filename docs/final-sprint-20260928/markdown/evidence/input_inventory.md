# New recording inventory — 7 October 2026

> **Replacement follow-up, 7 October 2026:** The user has supplied replacement L515 data. The plant folder now has **1,278 exact RGB/depth pairs** and the calibration folder **1,290 pairs**, with no unmatched images or decoding failures. See [the replacement audit](../l515_replacement_audit_20261007/README.md). The inventory below describes the original downloaded archive and is retained as historical evidence.

Source: `data/main/test_plant_10-7`; original download: `OneDrive_1_07-10-2026.zip`.
This index is non-destructive. Paths in the CSV files are relative to the source folder. No images, spectra, or calibration files were renamed or moved.

| Capture | RGB PNGs | Depth PNGs | Exact frame-ID pairs | Assessment |
|---|---:|---:|---:|---|
| `test_plant_20260928143911` (D405) | 1270 | 1270 | 1270 | Complete filename pairing; checkerboard seen in a sampled frame. |
| `test_plant_20260928144647_L515` | 1290 | 1290 | 1290 | Complete filename pairing; checkerboard seen in a sampled frame. |
| `test_plant_20260928162111_L515` | 233 | 490 | 89 | Incomplete source: 144 RGB files lack depth, 401 depth files lack RGB. Last RGB ID 724878; depth continues to 1633036. |
| `test_plant_20260928162354` (D405) | 1207 | 1207 | 1207 | Complete filename pairing; plants seen in a sampled frame. |

The ZIP contains 8273 files. Every archive entry exists in the extracted folder at its declared uncompressed size. The incomplete later L515 recording is therefore already incomplete inside the downloaded ZIP. Re-extracting this ZIP cannot recover those files. The nearest unmatched IDs are typically around 760 or 1520 units apart, consistent with adjacent gantry frames; they must not be renamed into false RGB/depth pairs. The 89 exact pairs cover IDs 18837–724878 and do not reach the end of the run.

The `20260928` folder contains FX10 and FX17 `.hdr`/`.bil` pairs for runs `002` and `003`, each 224 bands. The headers and BIL byte counts agree. The sampled RGB-D images show calibration boards in the first two capture folders and plants in the later folders. Run association is inferred from folder times and `order_of_scan`, and needs confirmation from the recorder. No `session.json`, saved pose trajectory, or separate depth-scale record is present in this download.

`later_L515_frame_inventory.csv` lists each available numeric frame ID and which modality is present. `later_L515_matched_pairs.csv` lists only exact pairs for possible limited diagnostic use. For a full second-camera plant reconstruction, obtain a complete re-export of the 16:21 L515 capture or repeat that recording. The intact 16:23 D405 plant capture can be assessed separately once camera depth units and capture/calibration details are confirmed.

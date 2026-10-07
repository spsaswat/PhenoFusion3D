# Offline measured spectral extraction

The Research workspace can run `processing.research_workspace.spectral_extract` on a new local recording using an explicit reviewed-region JSON configuration. This is separate from the preserved historical 28 August hyperspectral recipe. It extracts actual source spectra; it does not automatically segment plants, estimate optical calibration, join cameras, or produce 3D spectral fusion.

```powershell
python -m processing.research_workspace.spectral_extract --config docs/examples/research_spectral_20260928_fx10.json --output generated/my_spectral_run
```

The output must be new or empty, outside the source recording folder. Open `result/index.html` inside that output directory. The desktop Research workspace's extraction action uses the same command. Python callers can use `extract_reviewed_spectra(config_path, output_dir, progress=None)` from the module. NumPy is required; reviewed polygon rasterization also requires OpenCV. No camera or gantry is contacted.

Start from [the raw-only template](examples/research_spectral_template.json), replacing its recording and reviewed label-mask paths. Relative input paths resolve against the configuration file's directory. The saved `result/input_config.json` resolves input paths absolutely so it can be replayed locally; its original configuration path/hash remains in provenance. The [FX10](examples/research_spectral_20260928_fx10.json) and [FX17](examples/research_spectral_20260928_fx17.json) examples retain the source-reviewed 28 September patches and reference assumptions. They are dataset-specific examples, not reusable plant segmentation. Their raw recording files remain local/untracked.

Required recording metadata are an ENVI header with positive lines/bands/samples, `data type=12` (unsigned 16-bit), `interleave=bil`, declared byte order 0 or 1, nonnegative header offset, and a strictly increasing recorded wavelength vector in nanometres. Byte length, band count, offsets, wavelength units and duplicate header keys are checked. Other storage formats/units are rejected rather than guessed. A nonzero source offset and either byte order are supported.

Supply one reviewed selection: either `selection.polygons`, each with a unique positive `patch_id`, name and zero-based `column_line` vertices, or a `selection.label_mask_npy` integer array with source shape `(lines,columns)`, zero for unselected and positive patch IDs. State `review_status` as `assistant_reviewed` or `operator_reviewed`, with a provenance description. Polygon overlaps and out-of-image vertices are rejected. The sampling grid starts at source (0,0) and uses the explicit positive `line_step` and `column_step`. A selected region missed by that grid remains explicitly listed with zero measured samples. These masks and sample statistics are not complete or validated plant/organ traits.

With `normalization: null`, the extractor preserves raw DN and quality flags only. Set `suspected_clipping_dn` to a justified source ceiling or null to leave clipping unevaluated; the 28 September examples use the observed 65520 ceiling, whose export packing remains unconfirmed. Raw clipped/zero/uncovered samples are never discarded or repaired.

For provisional board-relative Q and offset sensitivity Q0, supply both same-recording white and dark ROIs. Each ROI is `[line_start,line_stop,column_start,column_stop]` with exclusive stops. Include `white_identity`, `settings_assumption`, `dark_status` (`assumed_tail` or `confirmed_dark`) and `dark_provenance`. For example:

```json
{
  "white_roi": [20, 140, 180, 850],
  "dark_roi": [2080, 2127, 0, 1024],
  "white_identity": "Intended white board; spectral reflectance unknown",
  "settings_assumption": "Fixed exposure confirmed by operator",
  "dark_status": "assumed_tail",
  "dark_provenance": "Final low-signal tail; shutter closure unconfirmed"
}
```

This object goes in the `normalization` field. Q=(DN−D)/(W−D) uses per-band, per-column reference medians; Q0=DN/W retains the same conservative eligibility to isolate the chosen offset effect. Support is the intersection of reviewed white/dark columns, with no extrapolation. Suspected clipping, raw zero and weak reference contrast invalidate Q/Q0; low signal remains an advisory band flag and invalidates required descriptor inputs. Weak-reference and low-signal thresholds are documented exploratory heuristics, not calibrated noise confidence bounds. Invalid floating values are NaN; negative and above-one finite signals remain. Even confirmed dark acquisition does not establish reflectance when the white board's spectral response is unknown.

Optional `indices` requests can name `NDVI_800_680`, `NDRE_790_720`, `GNDVI_800_550`, `PRI_531_570`, `PSRI_678_500_750` and `SIPI_800_445_680`. They require provisional normalization and an explicit positive `max_band_error_nm`. The report records each actual wavelength/source band and formula. Missing wavelengths or multiple targets selecting one recorded band omit that descriptor with a reason; FX17 cannot supply the red/NIR formulas here. Reference scan lines, invalid required bands, low signals and unstable denominators are excluded. SIPI retains its difference denominator. All are exploratory descriptors on Q, not validated physiological indices or health diagnoses.

Outputs include `measured_spectra.npz` (all measured bands, wavelengths, source coordinates, flags, optional Q/Q0 and descriptors), `patch_spectral_summary.csv`, optional `patch_index_summary.csv`, reviewed mask, reference profiles, machine-readable provenance and an HTML review. Keep warnings/metadata with the arrays. Per-band Q medians can use different valid pixel subsets; valid counts accompany every summary. Raw medians retain clipped values.

Reads are bounded to small BIL line windows and reference-band batches. Explicit caps limit the mask to 25 million scene pixels, output to 20 million sample×band values, and each full BIL read/reference batch to 4 million values. Oversized inputs are rejected with an actionable error. Raw files are read-only memory maps. Config/header/mask hashes and raw-file size/mtime/inode are captured before processing and checked before completion. The raw-file check is weaker than a full content hash, which is deliberately omitted; the extracted canonical DN values have their own SHA-256. `run_status.json` reports running/failed/complete, so an interrupted output is not accepted as complete.

Focused tests cover synthetic byte order/offsets, storage rejection, mask/reference/clipping behavior, negative and above-one Q, descriptors, unavailable bands, source changes, allocation limits and an actual current-recording subset parity check. The real-data check skips when the optional local recording and previously reviewed spectra are absent. Software consistency and synthetic tests do not validate physical radiometry, plant ownership or cross-sensor mapping.

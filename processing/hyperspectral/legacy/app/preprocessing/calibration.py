import spectral
import numpy as np
import cv2
import time
import os


def _extract_calibration_region(image, coordinates):
    """Extract calibration ROI with bounds checks."""
    rows_range = (int(coordinates[0, 1]), int(coordinates[2, 1]))  # Top to Bottom
    cols_range = (int(coordinates[0, 0]), int(coordinates[1, 0]))  # Left to Right

    rows_range = (max(0, rows_range[0]), min(image.shape[0], rows_range[1]))
    cols_range = (max(0, cols_range[0]), min(image.shape[1], cols_range[1]))

    region = image[rows_range[0] : rows_range[1], cols_range[0] : cols_range[1], :]
    if region.size == 0:
        raise ValueError("Calibration ROI is empty after bounds checking")
    return region


def _smooth_row_profiles(row_profiles, smooth_window=9):
    """Smooth per-row spectra using an edge-padded moving average."""
    if smooth_window <= 1 or row_profiles.shape[0] < 3:
        return row_profiles

    smooth_window = int(smooth_window)
    if smooth_window % 2 == 0:
        smooth_window += 1
    smooth_window = min(smooth_window, row_profiles.shape[0])
    if smooth_window % 2 == 0:
        smooth_window -= 1
    if smooth_window <= 1:
        return row_profiles

    kernel = np.ones(smooth_window, dtype=np.float64) / smooth_window
    pad = smooth_window // 2
    padded = np.pad(row_profiles, ((pad, pad), (0, 0)), mode="edge")
    smoothed = np.apply_along_axis(
        lambda col: np.convolve(col, kernel, mode="valid"),
        axis=0,
        arr=padded,
    )
    return smoothed


def _smooth_1d_profile(profile, smooth_window=9):
    """Smooth a 1D profile with an edge-padded moving average."""
    if smooth_window <= 1 or profile.shape[0] < 3:
        return profile

    smooth_window = int(smooth_window)
    if smooth_window % 2 == 0:
        smooth_window += 1
    smooth_window = min(smooth_window, profile.shape[0])
    if smooth_window % 2 == 0:
        smooth_window -= 1
    if smooth_window <= 1:
        return profile

    kernel = np.ones(smooth_window, dtype=np.float64) / smooth_window
    pad = smooth_window // 2
    padded = np.pad(profile, (pad, pad), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _destripe_columns_with_white_roi(
    calibrated,
    white_relative_coordinates,
    smooth_window=151,
    strength=0.9,
    min_gain=0.8,
    max_gain=1.2,
    min_rows=32,
):
    """Reduce column-wise striping using white ROI statistics after calibration."""
    if calibrated.ndim != 3:
        return calibrated

    h, _, b = calibrated.shape
    row_start = max(0, min(h - 1, int(white_relative_coordinates[0, 1])))
    row_end = max(0, min(h, int(white_relative_coordinates[2, 1])))
    if row_end <= row_start:
        row_end = min(h, row_start + 1)

    current_rows = row_end - row_start
    if current_rows < min_rows:
        center = (row_start + row_end) // 2
        half = min_rows // 2
        row_start = max(0, center - half)
        row_end = min(h, row_start + min_rows)
        row_start = max(0, row_end - min_rows)

    white_patch = calibrated[row_start:row_end, :, :].astype(np.float64, copy=False)
    if white_patch.size == 0:
        return calibrated

    col_profile = np.median(white_patch, axis=0)  # (width, bands)
    corrected = calibrated.astype(np.float64, copy=True)

    for band_idx in range(b):
        raw_col = col_profile[:, band_idx]
        smooth_col = _smooth_1d_profile(raw_col, smooth_window=smooth_window)

        gain = smooth_col / (raw_col + 1e-8)
        gain = 1.0 + strength * (gain - 1.0)
        gain = np.clip(gain, min_gain, max_gain)

        corrected[:, :, band_idx] *= gain[np.newaxis, :]

    corrected = np.clip(corrected, 0, 1)
    return corrected.astype(calibrated.dtype, copy=False)


def _destripe_rows_with_white_roi(
    calibrated,
    white_relative_coordinates,
    smooth_window=181,
    strength=0.9,
    min_gain=0.85,
    max_gain=1.15,
    min_cols=64,
    background_percentile=80.0,
):
    """Reduce row-wise striping using white ROI statistics after calibration."""
    if calibrated.ndim != 3:
        return calibrated

    h, w, b = calibrated.shape
    col_start = max(0, min(w - 1, int(white_relative_coordinates[0, 0])))
    col_end = max(0, min(w, int(white_relative_coordinates[1, 0])))
    if col_end <= col_start:
        col_end = min(w, col_start + 1)

    current_cols = col_end - col_start
    if current_cols < min_cols:
        center = (col_start + col_end) // 2
        half = min_cols // 2
        col_start = max(0, center - half)
        col_end = min(w, col_start + min_cols)
        col_start = max(0, col_end - min_cols)

    white_patch = calibrated[:, col_start:col_end, :].astype(np.float64, copy=False)
    if white_patch.size == 0:
        return calibrated

    # Use high-percentile background statistics to avoid plant pixels driving row gains.
    p = float(np.clip(background_percentile, 50.0, 99.5))
    row_profile = np.percentile(white_patch, p, axis=1)  # (height, bands)
    corrected = calibrated.astype(np.float64, copy=True)

    for band_idx in range(b):
        raw_row = row_profile[:, band_idx]
        smooth_row = _smooth_1d_profile(raw_row, smooth_window=smooth_window)

        gain = smooth_row / (raw_row + 1e-8)
        gain = 1.0 + strength * (gain - 1.0)
        gain = np.clip(gain, min_gain, max_gain)

        corrected[:, :, band_idx] *= gain[:, np.newaxis]

    corrected = np.clip(corrected, 0, 1)
    return corrected.astype(calibrated.dtype, copy=False)


def destripe_cube_columns(
    cube,
    reference_rows=None,
    smooth_window=151,
    strength=0.85,
    min_gain=0.85,
    max_gain=1.15,
    min_rows=32,
):
    """Destripe a raw/calibrated cube by correcting column gain per band."""
    if cube.ndim != 3:
        return cube

    h, _, b = cube.shape
    if reference_rows is None:
        patch = cube
    else:
        row_start = max(0, min(h - 1, int(reference_rows[0])))
        row_end = max(0, min(h, int(reference_rows[1])))
        if row_end <= row_start:
            row_end = min(h, row_start + 1)

        current_rows = row_end - row_start
        if current_rows < min_rows:
            center = (row_start + row_end) // 2
            half = min_rows // 2
            row_start = max(0, center - half)
            row_end = min(h, row_start + min_rows)
            row_start = max(0, row_end - min_rows)

        patch = cube[row_start:row_end, :, :]

    patch = patch.astype(np.float64, copy=False)
    if patch.size == 0:
        return cube

    col_profile = np.median(patch, axis=0)  # (width, bands)
    corrected = cube.astype(np.float64, copy=True)

    for band_idx in range(b):
        raw_col = col_profile[:, band_idx]
        smooth_col = _smooth_1d_profile(raw_col, smooth_window=smooth_window)
        gain = smooth_col / (raw_col + 1e-8)
        gain = 1.0 + strength * (gain - 1.0)
        gain = np.clip(gain, min_gain, max_gain)
        corrected[:, :, band_idx] *= gain[np.newaxis, :]

    return corrected.astype(cube.dtype, copy=False)


def build_reference_from_roi(
    image,
    coordinates,
    target_shape,
    method="row_mean",
    smooth_window=9,
):
    """
    Build a full-size calibration reference from ROI using a configurable strategy.

    Methods:
    - replicate: Legacy vertical tiling of ROI (kept for comparison/backward compatibility)
    - row_mean: Mean spectrum over ROI, broadcast over full image
    - row_interp_smooth: Mean ROI spectrum per row, smoothed + interpolated over image rows
    - row_col_separable: Smoothed row and column profiles combined per band
    """
    if method == "replicate":
        return replicate_and_extend(image, coordinates, target_shape)

    region = _extract_calibration_region(image, coordinates).astype(
        np.float64, copy=False
    )
    target_h, target_w, target_b = target_shape

    if method == "row_mean":
        mean_spectrum = np.mean(region, axis=(0, 1), dtype=np.float64)
        reference = np.broadcast_to(mean_spectrum.reshape(1, 1, -1), target_shape)
        return reference.astype(image.dtype, copy=False)

    if method == "row_interp_smooth":
        row_profiles = np.mean(region, axis=1, dtype=np.float64)  # (roi_h, bands)
        row_profiles = _smooth_row_profiles(row_profiles, smooth_window=smooth_window)

        if row_profiles.shape[0] == 1:
            interp_rows = np.repeat(row_profiles, target_h, axis=0)
        else:
            src_y = np.linspace(0, target_h - 1, row_profiles.shape[0])
            tgt_y = np.arange(target_h)
            interp_rows = np.empty((target_h, target_b), dtype=np.float64)
            for band_idx in range(target_b):
                interp_rows[:, band_idx] = np.interp(
                    tgt_y, src_y, row_profiles[:, band_idx]
                )

        reference = np.broadcast_to(
            interp_rows[:, np.newaxis, :], (target_h, target_w, target_b)
        )
        return reference.astype(image.dtype, copy=False)

    if method == "row_col_separable":
        # Separable model preserves detector column response and scan-line illumination.
        row_profiles = np.mean(region, axis=1, dtype=np.float64)  # (roi_h, bands)
        col_profiles = np.mean(region, axis=0, dtype=np.float64)  # (roi_w, bands)

        row_profiles = _smooth_row_profiles(row_profiles, smooth_window=smooth_window)

        interp_rows = np.empty((target_h, target_b), dtype=np.float64)
        if row_profiles.shape[0] == 1:
            interp_rows[:] = row_profiles[0]
        else:
            src_y = np.linspace(0, target_h - 1, row_profiles.shape[0])
            tgt_y = np.arange(target_h)
            for band_idx in range(target_b):
                interp_rows[:, band_idx] = np.interp(
                    tgt_y, src_y, row_profiles[:, band_idx]
                )

        interp_cols = np.empty((target_w, target_b), dtype=np.float64)
        if col_profiles.shape[0] == 1:
            interp_cols[:] = col_profiles[0]
        else:
            src_x = np.linspace(0, target_w - 1, col_profiles.shape[0])
            tgt_x = np.arange(target_w)
            for band_idx in range(target_b):
                smoothed_col = _smooth_1d_profile(
                    col_profiles[:, band_idx], smooth_window=smooth_window
                )
                interp_cols[:, band_idx] = np.interp(tgt_x, src_x, smoothed_col)

        row_mean = np.mean(interp_rows, axis=0)
        col_mean = np.mean(interp_cols, axis=0)
        gain = np.where(col_mean == 0, 1.0, row_mean / (col_mean + 1e-12))
        interp_cols *= gain[np.newaxis, :]

        reference = (
            interp_rows[:, np.newaxis, :]
            + interp_cols[np.newaxis, :, :]
            - row_mean[np.newaxis, np.newaxis, :]
        )
        reference = np.clip(reference, 0, None)
        return reference.astype(image.dtype, copy=False)

    raise ValueError(
        f"Unknown reference method '{method}'. Use 'replicate', 'row_mean', 'row_interp_smooth', or 'row_col_separable'."
    )


def find_nearest_band(wavelengths, target_wavelength):
    """
    Find the index of the band with the wavelength closest to the target wavelength.

    Parameters:
    - wavelengths: List or array of wavelengths (as strings or floats).
    - target_wavelength: The target wavelength (float).

    Returns:
    - index: Index of the band closest to the target wavelength.
    """
    wavelengths_float = np.array([float(w) for w in wavelengths])
    return np.argmin(np.abs(wavelengths_float - target_wavelength))


def resize_for_display(image, max_height=900):
    """
    Resize the image to fit within the specified maximum height while maintaining aspect ratio.

    Parameters:
    - image: The input image to be resized.
    - max_height: The maximum height for the resized image.

    Returns:
    - resized: The resized image.
    - scale: The scaling factor applied to the original image.
    """
    h, w = image.shape[:2]
    if h <= max_height:
        return image, 1.0

    scale = max_height / h
    resized = cv2.resize(
        image,
        (int(w * scale), int(h * scale)),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def select_coordinates(image, image_path: str, file_name: str):
    """
    Allow the user to select a set of rectangular coordinates on the given image.

    Parameters:
    - image: The input image on which to select the coordinates.
    - image_path: The file path of the image.
    - file_name: A string identifier for saving the coordinates.

    Returns:
    - coordinates: A tuple (x, y, w, h) representing the selected coordinates.
    """
    # Resize image for display if it's too tall
    display_image, scale = resize_for_display(image, max_height=900)

    # Select ROI on resized image
    coordinates = cv2.selectROI(
        file_name.upper(), display_image, fromCenter=False, showCrosshair=True
    )
    cv2.destroyAllWindows()

    # Scale coordinates back to original image dimensions
    scaled_coordinates = (
        int(coordinates[0] / scale),
        int(coordinates[1] / scale),
        int(coordinates[2] / scale),
        int(coordinates[3] / scale),
    )

    top_left = (scaled_coordinates[0], scaled_coordinates[1])
    top_right = (scaled_coordinates[0] + scaled_coordinates[2], scaled_coordinates[1])
    bottom_right = (
        scaled_coordinates[0] + scaled_coordinates[2],
        scaled_coordinates[1] + scaled_coordinates[3],
    )
    bottom_left = (scaled_coordinates[0], scaled_coordinates[1] + scaled_coordinates[3])
    calibration_coordinates = [top_left, top_right, bottom_right, bottom_left]

    # Save in corner format matching notebook format
    save_path = os.path.splitext(image_path)[0] + "_" + file_name + "_coordinates.npy"
    with open(save_path, "wb") as f:
        np.save(f, calibration_coordinates)

    return calibration_coordinates


def get_rois(dark_coords, white_coords):
    """
    Process dark and white calibration coordinates to create a bounding box.

    Parameters:
    - dark_coords: List of corner coordinates [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    - white_coords: List of corner coordinates [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]

    Returns:
    - dark_coords: A numpy array of corner coordinates for dark calibration.
    - white_coords: A numpy array of corner coordinates for white calibration.
    - bounding_box: A numpy array representing the bounding box coordinates.
    """

    dark_coords = np.array(dark_coords)
    white_coords = np.array(white_coords)

    # Create bounding box from white top edge and dark bottom edge
    bounding_box = np.array(
        [
            [white_coords[0][0], white_coords[0][1]],  # TL from white
            [white_coords[1][0], white_coords[1][1]],  # TR from white
            [white_coords[3][0], dark_coords[3][1]],  # BL: white x, dark y
            [white_coords[2][0], dark_coords[2][1]],  # BR: white x, dark y
        ]
    )
    return white_coords, dark_coords, bounding_box


def crop_image(image, bounding_box):
    """
    Crop the input image using the provided bounding box.

    Parameters:
    - image: The input image to be cropped.
    - bounding_box: A 2D array of corner coordinates [[x1, y1], [x2, y2], [x3, y3], [x4, y4]].

    Returns:
    - cropped_image: The cropped image.
    """
    # Bounding_box format: [[TL_x, TL_y], [TR_x, TR_y], [BR_x, BR_y], [BL_x, BL_y]]
    rows_range = (
        bounding_box[0, 1],
        bounding_box[2, 1],
    )  # Top to Bottom (y coordinates)

    cols_range = (
        bounding_box[0, 0],
        bounding_box[1, 0],
    )  # Left to Right (x coordinates)

    cropped_image = image[
        rows_range[0] : rows_range[1], cols_range[0] : cols_range[1], :
    ]

    return cropped_image


def normalize_image(image):
    """
    Normalize the input image to the range [0, 1].

    Parameters:
    - image: The input image to be normalized.

    Returns:
    - normalized_image: The normalized image.
    """
    min_val = np.min(image)
    max_val = np.max(image)
    normalized_image = (image - min_val) / (max_val - min_val)
    return normalized_image


def normalize_boxes(
    white_calibration_coordinates, dark_calibration_coordinates, bounding_box
):
    """
    Normalize calibration coordinates relative to the bounding box.

    Parameters:
    - white_calibration_coordinates: 3D array of white calibration corner coordinates.
    - dark_calibration_coordinates: 3D array of dark calibration corner coordinates.
    - bounding_box: 2D array of bounding box coordinates.

    Returns:
    - white_calibration_relative_coordinates: Numpy array of normalized white calibration coordinates.
    - dark_calibration_relative_coordinates: Numpy array of normalized dark calibration coordinates.
    """

    white_calibration_coordinates = np.array(white_calibration_coordinates)
    dark_calibration_coordinates = np.array(dark_calibration_coordinates)
    bounding_box = np.array(bounding_box)

    # Flatten to 2D if needed (from [[x, y]] format to [x, y] format)
    if white_calibration_coordinates.ndim == 3:
        white_calibration_coordinates = white_calibration_coordinates.reshape(-1, 2)
    if dark_calibration_coordinates.ndim == 3:
        dark_calibration_coordinates = dark_calibration_coordinates.reshape(-1, 2)

    # Reorder wc and dc to match order (TL, TR, BL, BR)
    reorder_idx = [0, 1, 3, 2]
    white_calibration_coordinates = white_calibration_coordinates[reorder_idx]
    dark_calibration_coordinates = dark_calibration_coordinates[reorder_idx]

    # Offset (top-left of big_rect)
    offset = bounding_box[0]

    # Relative coordinates
    white_calibration_relative_coordinates = white_calibration_coordinates - offset
    dark_calibration_relative_coordinates = dark_calibration_coordinates - offset

    # Force ONLY dark to span full width of big_rect (matches notebook behavior)
    left_x = 0
    right_x = bounding_box[1][0] - bounding_box[0][0]

    dark_calibration_relative_coordinates[0][0] = left_x  # TL
    dark_calibration_relative_coordinates[1][0] = right_x  # TR
    dark_calibration_relative_coordinates[2][0] = left_x  # BL
    dark_calibration_relative_coordinates[3][0] = right_x  # BR

    return white_calibration_relative_coordinates, dark_calibration_relative_coordinates


def replicate_and_extend(image, coordinates, target_shape):
    """
    Replicate and extend the calibration region vertically to match the target shape.
    This matches the notebook implementation (extract_and_replicate).

    Parameters:
    - image: The input image to be replicated and extended.
    - coordinates: The coordinates used for replication (4x2 array).
    - target_shape: The desired shape (height, width, bands) for the output image.

    Returns:
    - replicated_image: The replicated image matching target_shape vertically.
    """
    rows_range = (int(coordinates[0, 1]), int(coordinates[2, 1]))  # Top to Bottom
    cols_range = (int(coordinates[0, 0]), int(coordinates[1, 0]))  # Left to Right

    # Ensure coordinates are within image bounds
    rows_range = (max(0, rows_range[0]), min(image.shape[0], rows_range[1]))
    cols_range = (max(0, cols_range[0]), min(image.shape[1], cols_range[1]))

    # Extract the calibration region
    region = image[rows_range[0] : rows_range[1], cols_range[0] : cols_range[1], :]

    # Replicate vertically to match target height
    height_diff = rows_range[1] - rows_range[0]
    num_repeats = target_shape[0] // height_diff
    replicated_image = np.concatenate([region] * num_repeats, axis=0)

    # Add remaining rows if needed
    if replicated_image.shape[0] < target_shape[0]:
        additional_rows = target_shape[0] - replicated_image.shape[0]
        last_piece = region[:additional_rows, :, :]
        replicated_image = np.concatenate([replicated_image, last_piece], axis=0)

    return replicated_image


def white_dark_calibrate(raw_hdr, white_hdr, dark_hdr, outdir):
    """
    Perform white-dark calibration on a hyperspectral image cube.

    Parameters:
    - raw_hdr: Path to the raw hyperspectral image header file (.hdr)
    - white_hdr: Path to the white reference hyperspectral image header file (.hdr)
    - dark_hdr: Path to the dark reference hyperspectral image header file (.hdr)
    - outdir: Directory to save the calibrated output cube

    Returns:
    - calibrated_cube: The calibrated hyperspectral image cube
    """

    # Load hyperspectral image cubes
    raw_cube = spectral.open_image(raw_hdr).load()
    white_cube = spectral.open_image(white_hdr).load()
    dark_cube = spectral.open_image(dark_hdr).load()

    # Ensure all cubes have the same dimensions
    if raw_cube.shape != white_cube.shape or raw_cube.shape != dark_cube.shape:
        raise ValueError("Input cubes must have the same dimensions")

    # Perform white-dark calibration
    calibrated_cube = (raw_cube - dark_cube) / (white_cube - dark_cube)
    calibrated_cube = np.clip(calibrated_cube, 0, 1)  # Clip values to [0, 1]

    # Save the calibrated cube
    calibrated_hdr = outdir + f"/calibrated_cube_{int(time.time())}.hdr"
    meta = spectral.open_image(raw_hdr).metadata
    meta["description"] = f"Calibrated using ROIs at {time.ctime()}"
    spectral.envi.save_image(
        calibrated_hdr,
        calibrated_cube,
        dtype=np.float32,
        interleave="bil",
        metadata=meta,
        force=True,
    )

    print(f"Calibrated cube saved to {calibrated_hdr}")
    return calibrated_cube


def white_dark_calibrate_from_rois(
    raw_hdr,
    white_roi,
    dark_roi,
    outdir,
    reference_method="row_col_separable",
    smooth_window=9,
    pre_destripe_raw=True,
    pre_destripe_smooth_window=151,
    pre_destripe_strength=0.85,
    pre_destripe_min_gain=0.85,
    pre_destripe_max_gain=1.15,
    apply_column_destriping=True,
    destripe_smooth_window=151,
    destripe_strength=0.9,
    destripe_min_gain=0.8,
    destripe_max_gain=1.2,
    apply_row_destriping=False,
    row_destripe_smooth_window=181,
    row_destripe_strength=0.9,
    row_destripe_min_gain=0.85,
    row_destripe_max_gain=1.15,
    row_destripe_background_percentile=80.0,
):
    """
    Perform white-dark calibration on a hyperspectral image cube using specified ROIs.

    Parameters:
    - raw_hdr: Path to the raw hyperspectral image header file (.hdr)
    - white_roi: List of corner coordinates [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    - dark_roi: List of corner coordinates [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    - outdir: Directory to save the calibrated output cube
    - reference_method: ROI reference construction strategy ('replicate', 'row_mean', 'row_interp_smooth', 'row_col_separable')
    - smooth_window: Row smoothing window when using row_interp_smooth
    - pre_destripe_raw: Enable column destriping on raw cropped cube before calibration
    - pre_destripe_smooth_window: Column smoothing window for pre-calibration destriping
    - pre_destripe_strength: Strength of pre-calibration gain correction [0, 1]
    - pre_destripe_min_gain: Minimum allowed gain for pre-calibration destriping
    - pre_destripe_max_gain: Maximum allowed gain for pre-calibration destriping
    - apply_column_destriping: Enable post-calibration white-ROI-based column correction
    - destripe_smooth_window: Column smoothing window for destriping profile
    - destripe_strength: Strength of applied gain correction [0, 1]
    - destripe_min_gain: Minimum allowed column gain during destriping
    - destripe_max_gain: Maximum allowed column gain during destriping
    - apply_row_destriping: Enable post-calibration row-wise stripe correction (off by default; can amplify scene texture)
    - row_destripe_smooth_window: Row smoothing window for row destriping profile
    - row_destripe_strength: Strength of applied row gain correction [0, 1]
    - row_destripe_min_gain: Minimum allowed row gain during destriping
    - row_destripe_max_gain: Maximum allowed row gain during destriping
    - row_destripe_background_percentile: Percentile used to estimate row background (higher reduces plant leakage)

    Returns:
    - calibrated: The calibrated hyperspectral image cube
    """
    cube = spectral.open_image(raw_hdr).load()

    white_calibration_coordinates, dark_calibration_coordinates, bounding_box = (
        get_rois(dark_roi, white_roi)
    )
    cropped = crop_image(cube, bounding_box)

    white_calibration_relative_coordinates, dark_calibration_relative_coordinates = (
        normalize_boxes(
            white_calibration_coordinates, dark_calibration_coordinates, bounding_box
        )
    )

    if pre_destripe_raw:
        white_rows = (
            int(white_calibration_relative_coordinates[0, 1]),
            int(white_calibration_relative_coordinates[2, 1]),
        )
        cropped = destripe_cube_columns(
            cropped,
            reference_rows=white_rows,
            smooth_window=pre_destripe_smooth_window,
            strength=pre_destripe_strength,
            min_gain=pre_destripe_min_gain,
            max_gain=pre_destripe_max_gain,
        )

    white_calibration_reference = build_reference_from_roi(
        cropped,
        white_calibration_relative_coordinates,
        cropped.shape,
        method=reference_method,
        smooth_window=smooth_window,
    )
    dark_calibration_reference = build_reference_from_roi(
        cropped,
        dark_calibration_relative_coordinates,
        cropped.shape,
        method=reference_method,
        smooth_window=smooth_window,
    )

    assert (
        cropped.shape
        == white_calibration_reference.shape
        == dark_calibration_reference.shape
    ), "Shapes of cropped image and calibration references do not match."

    denominator = white_calibration_reference - dark_calibration_reference
    epsilon = 1e-6
    denominator = np.where(
        denominator >= 0,
        np.maximum(denominator, epsilon),
        np.minimum(denominator, -epsilon),
    )

    calibrated = (cropped - dark_calibration_reference) / denominator
    calibrated = np.clip(calibrated, 0, 1)

    if apply_column_destriping:
        calibrated = _destripe_columns_with_white_roi(
            calibrated,
            white_calibration_relative_coordinates,
            smooth_window=destripe_smooth_window,
            strength=destripe_strength,
            min_gain=destripe_min_gain,
            max_gain=destripe_max_gain,
        )

    if apply_row_destriping:
        calibrated = _destripe_rows_with_white_roi(
            calibrated,
            white_calibration_relative_coordinates,
            smooth_window=row_destripe_smooth_window,
            strength=row_destripe_strength,
            min_gain=row_destripe_min_gain,
            max_gain=row_destripe_max_gain,
            background_percentile=row_destripe_background_percentile,
        )

    # Do not auto-save the ROI-calibrated cube here —
    # let the caller (GUI) decide when/where to save the result.
    return calibrated

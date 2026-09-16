import numpy as np
import matplotlib.pyplot as plt
from skimage.filters import threshold_otsu, threshold_yen
from sklearn.mixture import GaussianMixture
from scipy.ndimage import gaussian_filter
from scipy.signal import savgol_filter


def find_ndvi_threshold_consensus(ndvi):
    """
    Find NDVI threshold using multiple methods and return consensus value.

    Parameters:
    - ndvi: 2D array of NDVI values

    Returns:
    - threshold: Consensus NDVI threshold
    """
    ndvi_flat = ndvi[np.isfinite(ndvi)]  # remove NaNs / infs

    # Method 1: Otsu Thresholding
    otsu_thresh = threshold_otsu(ndvi_flat)

    # Method 2: Percentile Based (93rd percentile)
    perc_thresh = np.percentile(ndvi_flat, 93)

    # Method 3: Gaussian Mixture Model
    X = ndvi_flat.reshape(-1, 1)
    gmm = GaussianMixture(n_components=2, random_state=0)
    gmm.fit(X)
    means = gmm.means_.flatten()
    xs = np.linspace(ndvi_flat.min(), ndvi_flat.max(), 1000)
    probs = gmm.predict_proba(xs.reshape(-1, 1))
    veg_comp = np.argmax(means)
    gmm_thresh = xs[np.argmax(probs[:, veg_comp] > 0.5)]

    # Method 4: Spatial-consistency aware thresholding
    ndvi_smooth = gaussian_filter(ndvi, sigma=2)
    spatial_thresh = threshold_otsu(ndvi_smooth[np.isfinite(ndvi_smooth)])

    # Consensus: median of all methods
    thresholds = np.array(
        [
            otsu_thresh,
            perc_thresh,
            gmm_thresh,
            spatial_thresh,
        ]
    )

    final_thresh = np.median(thresholds)
    return final_thresh


def remove_background_vnir(image, wavelengths):
    """
    Remove plant background from VNIR (fx10) hyperspectral image using NDVI.

    Parameters:
    - image: 3D hyperspectral image cube (height, width, bands)
    - wavelengths: List of wavelength values corresponding to bands

    Returns:
    - plant_only: 3D image with background removed
    - plant_mask: 2D boolean mask indicating plant pixels
    - ndvi: 2D NDVI map
    """
    wavelengths = np.array(wavelengths, dtype=float)

    # Define wavelength ranges (nm)
    red_min, red_max = 665.0, 680.0
    nir_min, nir_max = 750.0, 800.0

    # Find indices
    red_indices = np.where((wavelengths >= red_min) & (wavelengths <= red_max))[0]
    nir_indices = np.where((wavelengths >= nir_min) & (wavelengths <= nir_max))[0]

    if len(red_indices) == 0 or len(nir_indices) == 0:
        raise ValueError(
            "Cannot find RED or NIR bands in the specified wavelength ranges"
        )

    red_start, red_end = red_indices[0], red_indices[-1]
    nir_start, nir_end = nir_indices[0], nir_indices[-1]

    # Calculate reflectance
    red_reflectance = image[:, :, red_start : red_end + 1].mean(axis=2)
    nir_reflectance = image[:, :, nir_start : nir_end + 1].mean(axis=2)

    # Calculate NDVI
    ndvi = (nir_reflectance - red_reflectance) / (
        nir_reflectance + red_reflectance + 1e-8
    )

    # Find consensus threshold
    threshold = find_ndvi_threshold_consensus(ndvi)

    # Create mask
    plant_mask = ndvi > threshold

    # Apply mask to all bands
    plant_only = image.copy()
    for band in range(image.shape[2]):
        plant_only[:, :, band][~plant_mask] = 0

    return plant_only, plant_mask, ndvi


def find_nwaci_threshold_consensus(nwaci):
    """
    Find NWACI threshold using multiple methods and return consensus value.

    Parameters:
    - nwaci: 2D array of NWACI values

    Returns:
    - threshold: Consensus NWACI threshold
    """
    nwaci_flat = nwaci[np.isfinite(nwaci)]  # remove NaNs / infs

    # Method 1: Otsu Thresholding
    otsu_thresh = threshold_otsu(nwaci_flat)

    # Method 2: Percentile Based (93rd percentile)
    perc_thresh = np.percentile(nwaci_flat, 93)

    # Method 3: Gaussian Mixture Model
    X = nwaci_flat.reshape(-1, 1)
    gmm = GaussianMixture(n_components=2, random_state=0)
    gmm.fit(X)
    means = gmm.means_.flatten()
    xs = np.linspace(nwaci_flat.min(), nwaci_flat.max(), 1000)
    probs = gmm.predict_proba(xs.reshape(-1, 1))
    veg_comp = np.argmax(means)
    nwaci_thresh = xs[np.argmax(probs[:, veg_comp] > 0.5)]

    # Method 4: Spatial-consistency aware thresholding
    nwaci_smooth = gaussian_filter(nwaci, sigma=2)
    spatial_thresh = threshold_otsu(nwaci_smooth[np.isfinite(nwaci_smooth)])

    # Consensus: median of all methods
    thresholds = np.array(
        [
            otsu_thresh,
            perc_thresh,
            nwaci_thresh,
            spatial_thresh,
        ]
    )

    final_thresh = np.median(thresholds)
    return final_thresh


def remove_background_swir(image, wavelengths):
    """
    Remove plant background from SWIR (fx17) hyperspectral image using NWACI.

    Parameters:
    - image: 3D hyperspectral image cube (height, width, bands)
    - wavelengths: List of wavelength values corresponding to bands

    Returns:
    - plant_only: 3D image with background removed
    - plant_mask: 2D boolean mask indicating plant pixels
    - nwaci: 2D NWACI map
    """
    wavelengths = np.array(wavelengths, dtype=float)

    # Define wavelength ranges (nm) for water absorption features
    r1_min, r1_max = 1080.0, 1150.0
    r2_min, r2_max = 1400.0, 1470.0

    # Find indices
    r1_indices = np.where((wavelengths >= r1_min) & (wavelengths <= r1_max))[0]
    r2_indices = np.where((wavelengths >= r2_min) & (wavelengths <= r2_max))[0]

    if len(r1_indices) == 0 or len(r2_indices) == 0:
        raise ValueError(
            "Cannot find required water absorption bands in the specified wavelength ranges"
        )

    r1_start, r1_end = r1_indices[0], r1_indices[-1]
    r2_start, r2_end = r2_indices[0], r2_indices[-1]

    # Calculate reflectance
    r1_reflectance = image[:, :, r1_start : r1_end + 1].mean(axis=2)
    r2_reflectance = image[:, :, r2_start : r2_end + 1].mean(axis=2)

    # Calculate NWACI (Normalized Water Absorption Contrast Index)
    nwaci = (r1_reflectance - r2_reflectance) / (r1_reflectance + r2_reflectance + 1e-8)

    # Find consensus threshold
    threshold = find_nwaci_threshold_consensus(nwaci)

    # Create mask
    plant_mask = nwaci > threshold

    # Apply mask to all bands
    plant_only = image.copy()
    for band in range(image.shape[2]):
        plant_only[:, :, band][~plant_mask] = 0

    return plant_only, plant_mask, nwaci


def remove_background(image, wavelengths, camera_type):
    """
    Remove plant background based on camera type.

    Parameters:
    - image: 3D hyperspectral image cube (height, width, bands)
    - wavelengths: List of wavelength values corresponding to bands
    - camera_type: "fx10" for VNIR or "fx17" for SWIR

    Returns:
    - plant_only: 3D image with background removed
    - plant_mask: 2D boolean mask indicating plant pixels
    - index_map: 2D map (NDVI for fx10, NWACI for fx17)
    """
    if camera_type == "fx10":
        return remove_background_vnir(image, wavelengths)
    elif camera_type == "fx17":
        return remove_background_swir(image, wavelengths)
    else:
        raise ValueError(f"Unknown camera type: {camera_type}")

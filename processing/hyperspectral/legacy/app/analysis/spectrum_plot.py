import numpy as np
import matplotlib.pyplot as plt
import spectral 


def cross_calibrate_and_plot(fx10_path, fx17_path, overlap=(900, 1000), overlap_grid_n=300):
    """Cross-calibrate FX17 to FX10 using overlap and plot continuous reflectance.
    Steps:
    - Load FX10 and FX17 HDRs and compute spatial mean spectra.
    - Interpolate both spectra over a dense grid inside `overlap` and fit
      FX17_corrected = a * FX17 + b to match FX10 on the overlap (least-squares).
    - Apply correction to all FX17 bands.
    - Build a continuous spectrum using FX10 where available and FX17_corrected
      for wavelengths beyond the FX10 range.
    Parameters:
    - fx10_path (str): path to FX10 .hdr file
    - fx17_path (str): path to FX17 .hdr file
    - overlap (tuple): (start_nm, stop_nm) overlap for fitting
    - overlap_grid_n (int): number of points in dense overlap grid for fitting
    Returns:
    - dict with keys: 'fx10_wl','fx10_spec','fx17_wl','fx17_spec','fx17_corr_wl',
      'fx17_corr_spec','combined_wl','combined_spec','a','b'
    """

    def _load_mean(hdr_path):
        img = spectral.open_image(hdr_path)
        data = img.load()
        mean_spec = np.nanmean(data, axis=(0, 1))
        wls = img.metadata.get("wavelength", None)
        if wls is None:
            print("Warning: No wavelength info found in metadata. Using band indices as wavelengths.")
            wls = np.arange(mean_spec.size)
        else:
            try:
                wls = np.array([float(w) for w in wls])
            except Exception:
                print("Warning: Failed to convert wavelength info to float. Using band indices as wavelengths.")
                wls = np.arange(mean_spec.size)
        return np.array(wls), np.array(mean_spec)

    fx10_wl, fx10_spec = _load_mean(fx10_path)
    fx17_wl, fx17_spec = _load_mean(fx17_path)

    # Prepare dense overlap grid
    s, e = overlap
    # Dense overlap grid
    ol_grid = np.linspace(s, e, overlap_grid_n)
    
    # Interpolate BOTH to same grid
    fx10_ol = np.interp(ol_grid, fx10_wl, fx10_spec)
    fx17_ol = np.interp(ol_grid, fx17_wl, fx17_spec)
    
    # Fit a,b  (or fit gain-only)
    A = np.vstack([fx17_ol, np.ones_like(fx17_ol)]).T
    a, b = np.linalg.lstsq(A, fx10_ol, rcond=None)[0]
    
    fx17_corr_spec = np.clip(a * fx17_spec + b, 0, 1)
    
    # Build fused spectrum with BLENDING in overlap
    # Regions
    fx10_left_mask = fx10_wl < s
    fx17_right_mask = fx17_wl > e
    
    # Overlap on common grid
    fx10_ol2 = np.interp(ol_grid, fx10_wl, fx10_spec)
    fx17_ol2 = np.interp(ol_grid, fx17_wl, fx17_corr_spec)
    
    w = (ol_grid - s) / (e - s)
    fused_ol = (1 - w) * fx10_ol2 + w * fx17_ol2
    
    combined_wl = np.concatenate([fx10_wl[fx10_left_mask], ol_grid, fx17_wl[fx17_right_mask]])
    combined_spec = np.concatenate([fx10_spec[fx10_left_mask], fused_ol, fx17_corr_spec[fx17_right_mask]])
    # Sort combined by wavelength (in case inputs are unordered)
    order = np.argsort(combined_wl)
    combined_wl = combined_wl[order]
    combined_spec = combined_spec[order]

    # Plotting: FX10, original FX17, corrected FX17, combined continuous curve
    plt.figure(figsize=(9, 5))
    plt.plot(fx10_wl, fx10_spec, label="FX10 (reference)", color="tab:blue")
    plt.plot(fx17_wl, fx17_spec, label="FX17 (original)", color="tab:orange", alpha=0.6)
    plt.plot(fx17_wl, fx17_corr_spec, label="FX17 (corrected)", color="tab:green", linestyle="--")
    plt.plot(combined_wl, combined_spec, label="Combined continuous", color="k", linewidth=1)
    plt.axvspan(s, e, color="gray", alpha=0.08)
    plt.title("Cross-calibrated reflectance (FX10 reference)")
    plt.xlabel("Wavelength (nm)")
    plt.ylabel("Reflectance")
    plt.legend()
    plt.tight_layout()
    plt.show()

    # return (combined_wl, combined_spec)
    # print(fx17_corr_spec.shape)
    # print(fx10_spec.shape)
    # plt.imshow(fx17_corr_spec[:, :, 50], cmap='gray')
    # plt.title("FX17 Corrected Band 50")
    # plt.show()

    return {
        "fx10_wl": fx10_wl,
        "fx10_spec": fx10_spec,
        "fx17_wl": fx17_wl,
        "fx17_spec": fx17_spec,
        "fx17_corr_wl": fx17_wl,
        "fx17_corr_spec": fx17_corr_spec,
        "combined_wl": combined_wl,
        "combined_spec": combined_spec,
        "a": float(a),
        "b": float(b),
    }


if __name__ == "__main__":
    # Example usage:
    fx17path = r'/home/sriram/ANU/data/aruco_only_arucoplants/calibrated/003-specim-fx17_calibrated.hdr'
    fx10path = r'/home/sriram/ANU/data/aruco_only_arucoplants/calibrated/003-specim-fx10_calibrated.hdr'
    results = cross_calibrate_and_plot(fx10path, fx17path)
    print(results)
    img = spectral.open_image(fx17path)
    cube = img.load().astype(np.float32)   # (H, W, Bands)

    # Apply calibration to every pixel and band
    corrected_cube = results["a"] * cube + results["b"]

    # Optional: clip to valid reflectance range
    corrected_cube = np.clip(corrected_cube, 0, 1)



    def plotimg(image):
        # Open hyperspectral image

        # Load hyperspectral cube
        data = image  # shape: (H, W, Bands)

        # Read wavelengths from metadata
        wls = img.metadata.get("wavelength")

        if wls is None:
            raise ValueError("No wavelength information found in metadata.")

        # Convert wavelength strings to float array
        wls = np.array([float(w) for w in wls])

        # Find band indices between 900 and 1000 nm
        band_mask = (wls >= 900) & (wls <= 1000)

        if not np.any(band_mask):
            raise ValueError("No bands found between 900 and 1000 nm.")

        # Average selected bands
        avg_img = np.mean(data[:, :, band_mask], axis=2)
        return avg_img

    avg_img1 = plotimg(cube)
    avg_img2 = plotimg(corrected_cube)

    # Plot
    plt.figure(figsize=(8, 6))
    plt.subplot(1, 2, 1)
    plt.imshow(avg_img1, cmap="gray")
    plt.title("Average Image (900-1000 nm) - FX17")
    plt.colorbar(label="Mean Reflectance / Intensity")
    plt.axis("off")
    plt.subplot(1, 2, 2)
    plt.imshow(avg_img2, cmap="gray")
    plt.title("Average Image (900-1000 nm) - FX17 Corrected")
    plt.colorbar(label="Mean Reflectance / Intensity")
    plt.axis("off")

    plt.show()

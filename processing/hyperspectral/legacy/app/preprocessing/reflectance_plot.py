import spectral as spy
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


def plot_reflectance(hdr_file_path, start_wavelength=None, stop_wavelength=None):
    """
    Plot reflectance vs wavelength for a calibrated hyperspectral HDR image.
    
    Parameters:
    -----------
    hdr_file_path : str
        Path to the .hdr file of the hyperspectral image
    start_wavelength : float, optional
        Starting wavelength for the plot (if None, uses metadata)
    stop_wavelength : float, optional
        Stopping wavelength for the plot (if None, uses metadata)
    
    Returns:
    --------
    fig : matplotlib figure
        The generated figure
    """
    
    # Load the hyperspectral image
    img = spy.open_image(hdr_file_path)
    
    # Get metadata
    metadata = img.metadata
    
    # Get wavelengths from metadata
    if 'wavelength' in metadata:
        wavelengths = np.array(metadata['wavelength'], dtype=float)
    else:
        # If wavelengths not in metadata, create based on start/stop wavelengths
        num_bands = img.nbands
        if start_wavelength is not None and stop_wavelength is not None:
            wavelengths = np.linspace(start_wavelength, stop_wavelength, num_bands)
        else:
            # Fallback: use band indices
            wavelengths = np.arange(num_bands)
    
    # Apply wavelength range if provided
    if start_wavelength is not None or stop_wavelength is not None:
        start_wl = start_wavelength if start_wavelength is not None else wavelengths[0]
        stop_wl = stop_wavelength if stop_wavelength is not None else wavelengths[-1]
        
        # Filter wavelengths and corresponding bands
        mask = (wavelengths >= start_wl) & (wavelengths <= stop_wl)
        wavelengths = wavelengths[mask]
        band_indices = np.where(mask)[0]
    else:
        band_indices = np.arange(len(wavelengths))
    
    # Load image data
    img_data = img.load()
    
    # Calculate mean reflectance across spatial dimensions
    mean_reflectance = np.mean(img_data[:, :, band_indices], axis=(0, 1))
    
    # Create the plot
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(wavelengths, mean_reflectance, linewidth=2)
    ax.set_xlabel('Wavelength (nm)', fontsize=12)
    ax.set_ylabel('Reflectance', fontsize=12)
    ax.set_title('Mean Reflectance Spectrum', fontsize=14)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    return fig

if __name__ == "__main__":
    hdr_file = r"D:\anu-files\ANU\data\csiro_fx10_17_2_wheat\no-background\004-specim-fx17_no_background.hdr"
    fig = plot_reflectance(hdr_file, 900, 1000)
    plt.show()

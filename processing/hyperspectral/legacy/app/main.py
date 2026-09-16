import sys
import os
import numpy as np
import matplotlib.pyplot as plt
import time
import spectral
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QLabel,
    QFileDialog,
    QVBoxLayout,
    QHBoxLayout,
    QRadioButton,
    QGroupBox,
    QMessageBox,
    QTextEdit,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
import cv2
from preprocessing.calibration import (
    white_dark_calibrate,
    white_dark_calibrate_from_rois,
    destripe_cube_columns,
    select_coordinates,
    find_nearest_band,
    normalize_image,
)
from preprocessing.background_removal import remove_background
from analysis.window import AnalysisWindow


class CalibrationWorker(QThread):
    status = pyqtSignal(str)
    image_ready = pyqtSignal(np.ndarray, list)  # image and wavelengths
    output = pyqtSignal(str)  # for print output

    def __init__(self, raw, white, dark, outdir):
        super().__init__()
        self.raw = raw
        self.white = white
        self.dark = dark
        self.outdir = outdir

    def run(self):
        self.output.emit("Running calibration...\n")
        calibrated = white_dark_calibrate(self.raw, self.white, self.dark, self.outdir)

        # Extract wavelengths from the raw image header
        import spectral

        raw_img = spectral.open_image(self.raw)
        wavelengths = raw_img.metadata.get("wavelength", [])
        wavelengths = [float(w) for w in wavelengths] if wavelengths else []

        self.image_ready.emit(calibrated, wavelengths)
        self.output.emit("Calibration done ✔\n")


class CalibrationWorkerROI(QThread):
    status = pyqtSignal(str)
    image_ready = pyqtSignal(np.ndarray, list)  # image and wavelengths
    output = pyqtSignal(str)  # for print output

    def __init__(self, raw, white_roi, dark_roi, outdir, camera_type="fx10"):
        super().__init__()
        self.raw = raw
        self.white_roi = white_roi
        self.dark_roi = dark_roi
        self.outdir = outdir
        self.camera_type = camera_type

    def run(self):
        import io
        import sys

        self.output.emit("Running ROI-based calibration...\n")

        # Redirect stdout to capture prints
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            is_swir = self.camera_type == "fx17"
            calibrated = white_dark_calibrate_from_rois(
                self.raw,
                self.white_roi,
                self.dark_roi,
                self.outdir,
                reference_method="row_col_separable",
                smooth_window=31,
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
                # Horizontal stripe suppression is needed for FX17 only.
                apply_row_destriping=is_swir,
                row_destripe_smooth_window=181 if is_swir else 121,
                row_destripe_strength=0.78 if is_swir else 0.55,
                row_destripe_min_gain=0.92 if is_swir else 0.85,
                row_destripe_max_gain=1.08 if is_swir else 1.15,
                row_destripe_background_percentile=88.0 if is_swir else 75.0,
            )
        finally:
            # Capture output and restore stdout
            output_text = sys.stdout.getvalue()
            sys.stdout = old_stdout
            if output_text:
                self.output.emit(output_text)

        # Extract wavelengths from the raw image header
        import spectral

        raw_img = spectral.open_image(self.raw)
        wavelengths = raw_img.metadata.get("wavelength", [])
        wavelengths = [float(w) for w in wavelengths] if wavelengths else []

        self.image_ready.emit(calibrated, wavelengths)
        self.output.emit("Calibration done ✔\n")


# Analysis dialog and functions removed (not used in this simplified UI)


class CalibApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FX White–Dark Calibration")

        self.raw_hdr = None
        self.camera_type = "fx10"  # Default to fx10
        # Initialize with FX10 coordinates by default
        self.white_roi = [(165, 77), (900, 77), (900, 110), (165, 110)]
        self.dark_roi = [(165, 2091), (900, 2091), (900, 2100), (165, 2100)]
        self.calibrated_image = None
        self.calibrated_wavelengths = None
        # For manual saving
        self.plant_only = None
        self.plant_mask = None
        self.index_map = None

        layout = QVBoxLayout()

        # Camera type selection
        self.cam_fx10 = QRadioButton("FX10 (VNIR)")
        self.cam_fx17 = QRadioButton("FX17 (SWIR)")
        self.cam_fx10.setChecked(True)

        cam_group = QGroupBox("Camera Type")
        # cam_layout = QVBoxLayout()
        cam_layout = QHBoxLayout()
        cam_layout.addWidget(self.cam_fx10)
        cam_layout.addWidget(self.cam_fx17)
        cam_group.setLayout(cam_layout)

        self.btn_raw = QPushButton("Select RAW cube (.hdr)")
        self.btn_run = QPushButton("Run calibration")
        self.btn_remove_bg = QPushButton("Remove plant background")
        self.btn_save_calib = QPushButton("Save calibrated image")
        self.btn_save_bg_removal = QPushButton("Save background-removed image")

        self.btn_raw.clicked.connect(lambda: self.select_file("raw"))
        self.btn_run.clicked.connect(self.run_calibration)
        self.btn_remove_bg.clicked.connect(self.remove_background)
        self.btn_save_calib.clicked.connect(self.save_calibrated_image)
        self.btn_save_bg_removal.clicked.connect(self.save_removed_background)
        # Disable save buttons until results are available
        self.btn_save_calib.setEnabled(False)
        self.btn_save_bg_removal.setEnabled(False)
        self.btn_save_bg_removal.setEnabled(False)
        self.btn_remove_bg.setEnabled(False)
        # Analyze button (launches separate analysis app)
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.clicked.connect(self.open_analysis_app)

        layout.addWidget(cam_group)
        layout.addWidget(self.btn_raw)

        # layout.addWidget(self.btn_run)
        # layout.addWidget(self.btn_save_calib)
        # layout.addWidget(self.btn_remove_bg)
        # layout.addWidget(self.btn_save_bg_removal)
        # layout.addWidget(self.btn_analyze)

        # --- Row 1: Run Calibration + Save Calibrated ---
        row1 = QHBoxLayout()
        row1.addWidget(self.btn_run)
        row1.addWidget(self.btn_save_calib)

        # --- Row 2: Remove Background + Save Background Removed ---
        row2 = QHBoxLayout()
        row2.addWidget(self.btn_remove_bg)
        row2.addWidget(self.btn_save_bg_removal)

        # --- Add to main layout ---
        layout.addLayout(row1)
        layout.addLayout(row2)

        # Analyze button below
        layout.addWidget(self.btn_analyze)

        # Output text display
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        layout.addWidget(QLabel("Output:"))
        layout.addWidget(self.output_text)

        self.setLayout(layout)
        self.cam_fx10.toggled.connect(self.update_camera_type)

    def open_analysis_app(self):
        """Launch the analysis application window."""
        try:
            # Create a top-level analysis window (no parent) and keep a reference
            if not hasattr(self, "analysis_window") or self.analysis_window is None:
                self.analysis_window = AnalysisWindow()

                # When the analysis window closes, re-enable the Analyze button
                try:
                    self.analysis_window.closed.connect(self._on_analysis_closed)
                except Exception:
                    pass

            self.analysis_window.show()
            self.analysis_window.raise_()
            # Disable the analyze button while analysis window is open
            self.btn_analyze.setEnabled(False)
            self.append_output("Analysis window opened")
        except Exception as e:
            self.append_output(f"ERROR: Failed to open analysis window: {e}")

    def _on_analysis_closed(self):
        # Re-enable analyze button and clear reference
        try:
            self.btn_analyze.setEnabled(True)
        except Exception:
            pass
        self.analysis_window = None

    def update_camera_type(self):
        """Update camera type and reset UI state."""
        # Reset stored results
        self.calibrated_image = None
        self.calibrated_wavelengths = None
        self.plant_only = None
        self.plant_mask = None
        self.index_map = None

        # Disable buttons (grey out)
        self.btn_save_calib.setEnabled(False)
        self.btn_remove_bg.setEnabled(False)
        self.btn_save_bg_removal.setEnabled(False)

        if self.cam_fx10.isChecked():
            self.camera_type = "fx10"
            self.white_roi = [(165, 77), (900, 77), (900, 110), (165, 110)]
            self.dark_roi = [(165, 2091), (900, 2091), (900, 2100), (165, 2100)]
            self.append_output("Camera type: FX10 (VNIR)")
            self.append_output("Auto-loaded FX10 calibration coordinates")
        else:
            self.camera_type = "fx17"
            self.white_roi = [(75, 28), (545, 28), (545, 30), (75, 30)]
            self.dark_roi = [(100, 2085), (540, 2085), (540, 2087), (100, 2087)]
            self.append_output("Camera type: FX17 (SWIR)")
            self.append_output("Auto-loaded FX17 calibration coordinates")

    def select_file(self, kind):
        """Select HDR file for RAW cube."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select HDR file", "", "HDR Files (*.hdr)"
        )
        if not path:
            return
        setattr(self, f"{kind}_hdr", path)
        self.append_output(f"{kind.upper()} selected: {path}")

    def append_output(self, text):
        """
        Append text to the output display.

        Parameters:
        - text (str): Text to append.

        """
        self.output_text.append(text.rstrip())

    def run_calibration(self):
        """Run the calibration process using ROI-based calibration."""
        if not self.raw_hdr:
            self.append_output("ERROR: Missing RAW cube")
            return

        # Create calibrated folder if it doesn't exist
        raw_dir = os.path.dirname(self.raw_hdr)
        output_dir = os.path.join(raw_dir, "calibrated")
        os.makedirs(output_dir, exist_ok=True)

        if self.white_roi is None or self.dark_roi is None:
            self.append_output("ERROR: ROI coordinates not set")
            return

        self.worker = CalibrationWorkerROI(
            self.raw_hdr,
            self.white_roi,
            self.dark_roi,
            output_dir,
            camera_type=self.camera_type,
        )

        self.worker.status.connect(self.append_output)
        self.worker.image_ready.connect(self.display_calibrated_image)
        self.worker.output.connect(self.append_output)
        self.worker.start()

    def display_calibrated_image(self, image, wavelengths):
        """
        Display raw and calibrated previews using the selected calibration run.

        Parameters:
        - image (np.ndarray): The calibrated hyperspectral data cube.
        - wavelengths (list): List of wavelength values corresponding to bands.

        Returns:
        - None
        """
        # Store for later background removal
        self.calibrated_image = image
        self.calibrated_wavelengths = wavelengths

        def robust_normalize_band(band, low=2.0, high=98.0):
            band = np.asarray(band, dtype=float)
            band = np.nan_to_num(band, nan=0.0, posinf=0.0, neginf=0.0)
            lo, hi = np.percentile(band, [low, high])
            if hi <= lo:
                return np.zeros_like(band, dtype=float)
            return np.clip((band - lo) / (hi - lo), 0.0, 1.0)

        def rgb_targets_from_wavelengths(wavs):
            if not wavs:
                return None
            wmin = float(min(wavs))
            wmax = float(max(wavs))
            # VNIR true-color-like visualization (FX10 can extend a little above 1000nm)
            if wmin < 700 and wmax <= 1100:
                return (660.0, 550.0, 470.0)
            # SWIR false-color visualization (avoid non-existent 450nm channel)
            return (1600.0, 1300.0, 1050.0)

        def cube_to_rgb(cube, wavs):
            if wavs and len(wavs) > 0:
                targets = rgb_targets_from_wavelengths(wavs)
                red_idx = int(find_nearest_band(wavs, targets[0]))
                green_idx = int(find_nearest_band(wavs, targets[1]))
                blue_idx = int(find_nearest_band(wavs, targets[2]))

                r = np.squeeze(robust_normalize_band(cube[:, :, red_idx]))
                g = np.squeeze(robust_normalize_band(cube[:, :, green_idx]))
                b = np.squeeze(robust_normalize_band(cube[:, :, blue_idx]))
                rgb = np.stack([r, g, b], axis=-1)
            else:
                r = np.squeeze(normalize_image(cube[:, :, 60].astype(float)))
                g = np.squeeze(normalize_image(cube[:, :, 30].astype(float)))
                b = np.squeeze(normalize_image(cube[:, :, 10].astype(float)))
                rgb = np.stack([r, g, b], axis=-1)

            rgb = np.squeeze(rgb)
            rgb = np.nan_to_num(rgb, nan=0.0, posinf=1.0, neginf=0.0)
            return np.clip(rgb, 0.0, 1.0)

        try:
            # Load raw image for side-by-side comparison only.
            import spectral

            raw_img_data = spectral.open_image(self.raw_hdr)
            # Use .load() to get the full array instead of slicing
            raw_image = raw_img_data.load()
            raw_image = destripe_cube_columns(
                raw_image,
                smooth_window=151,
                strength=0.85,
                min_gain=0.85,
                max_gain=1.15,
            )

            # Safely extract wavelengths from metadata
            raw_wavelengths = []
            try:
                raw_wavelengths_raw = raw_img_data.metadata.get("wavelength", [])
                if raw_wavelengths_raw is not None:
                    # Convert to list if it's array-like
                    if hasattr(raw_wavelengths_raw, "__iter__") and not isinstance(
                        raw_wavelengths_raw, (str, bytes)
                    ):
                        raw_wavelengths = [float(w) for w in raw_wavelengths_raw]
            except (TypeError, ValueError):
                raw_wavelengths = []

            raw_rgb = cube_to_rgb(raw_image, raw_wavelengths)
            calibrated_rgb = cube_to_rgb(image, wavelengths)

            fig, axes = plt.subplots(1, 2, figsize=(16, 7))
            for ax in axes:
                ax.axis("off")

            axes[0].imshow(raw_rgb)
            axes[0].set_title("Raw", fontsize=14, fontweight="bold")
            axes[1].imshow(calibrated_rgb)
            axes[1].set_title(
                "Calibrated (Row+Col Separable)", fontsize=14, fontweight="bold"
            )

            plt.tight_layout()
            plt.show()

        except Exception as e:
            import traceback

            error_msg = f"Failed to display image: {str(e)}\n{traceback.format_exc()}"
            self.append_output(f"ERROR: {error_msg}")
            QMessageBox.warning(self, "Display Error", error_msg)

        # Enable save button now that calibrated image is available
        self.btn_save_calib.setEnabled(True)
        self.btn_remove_bg.setEnabled(True)

    @staticmethod
    def resize_for_display_static(image, max_height=900):
        """
        Resize image for display if needed.

        Parameters:
        - image (np.ndarray): Input image.
        - max_height (int): Maximum height for display.

        Returns:
        - resized (np.ndarray): Resized image.
        - scale (float): Scaling factor applied.

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

    def remove_background(self):
        """Remove plant background from calibrated image based on camera type."""
        if self.calibrated_image is None or self.calibrated_wavelengths is None:
            self.append_output("ERROR: Run calibration first")
            return

        self.append_output(
            f"Removing plant background using {self.camera_type.upper()}..."
        )

        try:
            plant_only, plant_mask, index_map = remove_background(
                self.calibrated_image,
                self.calibrated_wavelengths,
                self.camera_type,
            )

            # Store results for manual saving
            self.plant_only = plant_only
            self.plant_mask = plant_mask
            self.index_map = index_map

            # Display the results
            self.display_removal_results(plant_only, plant_mask, index_map)

            self.append_output("Plant background removal complete ✔")
            # Enable save button now that results are available
            self.btn_save_bg_removal.setEnabled(True)
        except Exception as e:
            self.append_output(f"ERROR: Background removal failed: {str(e)}")

    def save_calibrated_image(self):
        """Save calibrated image to user-selected directory."""
        if self.calibrated_image is None:
            self.append_output("ERROR: No calibrated image available")
            return

        # Open directory selection dialog
        output_dir = QFileDialog.getExistingDirectory(
            self, "Select directory to save calibrated image"
        )
        if not output_dir:
            return

        try:
            import spectral

            raw_basename = os.path.basename(self.raw_hdr)[:-4]
            out_hdr = os.path.join(output_dir, f"{raw_basename}_calibrated.hdr")
            meta = spectral.open_image(self.raw_hdr).metadata
            meta["description"] = f"Calibrated using ROIs at {time.ctime()}"
            # fix 1
            spectral.envi.save_image(
                out_hdr,
                self.calibrated_image,
                dtype=np.float32,
                interleave="bil",
                force=True,
                metadata=meta,
            )
            self.append_output(f"Calibrated image saved to {out_hdr}")
            QMessageBox.information(
                self, "Success", f"Calibrated image saved to:\n{out_hdr}"
            )
        except Exception as e:
            error_msg = f"Failed to save calibrated image: {str(e)}"
            self.append_output(f"ERROR: {error_msg}")
            QMessageBox.warning(self, "Save Error", error_msg)

    def save_removed_background(self):
        """Save background-removed image to user-selected directory."""
        if self.plant_only is None:
            self.append_output("ERROR: No background-removed image available")
            return

        # Open directory selection dialog
        output_dir = QFileDialog.getExistingDirectory(
            self, "Select directory to save background-removed image"
        )
        if not output_dir:
            return

        try:
            import spectral

            raw_basename = os.path.basename(self.raw_hdr)[:-4]
            out_hdr = os.path.join(output_dir, f"{raw_basename}_no_background.hdr")

            meta = spectral.open_image(self.raw_hdr).metadata
            meta["description"] = f"Background removed using method at {time.ctime()}"
            # fix 2
            spectral.envi.save_image(
                out_hdr,
                self.plant_only,
                dtype=np.float32,
                interleave="bil",
                force=True,
                metadata=meta,
            )
            self.append_output(f"Background-removed image saved to {out_hdr}")
            QMessageBox.information(
                self, "Success", f"Background-removed image saved to:\n{out_hdr}"
            )
        except Exception as e:
            error_msg = f"Failed to save background-removed image: {str(e)}"
            self.append_output(f"ERROR: {error_msg}")
            QMessageBox.warning(self, "Save Error", error_msg)

    def display_removal_results(self, plant_only, plant_mask, index_map):
        """
        Display plant background removal results.

        Parameters:
        - plant_only: 3D image with background removed
        - plant_mask: 2D boolean mask
        - index_map: 2D map (NDVI or NWACI)
        """
        try:
            # Create a figure with subplots
            fig, axes = plt.subplots(1, 3, figsize=(15, 4))

            # Determine index map title
            if self.camera_type == "fx10":
                index_title = "NDVI"
                cmap = "RdYlGn"
            else:
                index_title = "NWACI"
                cmap = "RdYlGn"

            # Plot 1: Index map (NDVI, NWACI, or Green reflectance)
            im0 = axes[0].imshow(index_map, cmap=cmap)
            axes[0].set_title(index_title)
            axes[0].axis("off")
            plt.colorbar(im0, ax=axes[0])

            # Plot 2: Plant mask
            axes[1].imshow(plant_mask, cmap="gray")
            axes[1].set_title("Plant Mask")
            axes[1].axis("off")

            # Plot 3: Plant pixels only (RGB preview)
            if self.calibrated_wavelengths and len(self.calibrated_wavelengths) > 0:
                red_idx = find_nearest_band(self.calibrated_wavelengths, 660)
                green_idx = find_nearest_band(self.calibrated_wavelengths, 550)
                blue_idx = find_nearest_band(self.calibrated_wavelengths, 450)

                rgb = np.stack(
                    [
                        normalize_image(plant_only[:, :, red_idx]),
                        normalize_image(plant_only[:, :, green_idx]),
                        normalize_image(plant_only[:, :, blue_idx]),
                    ],
                    axis=-1,
                )
                rgb = np.clip(rgb, 0, 1)
            else:
                # Fallback
                rgb = plant_only[:, :, [60, 30, 10]]
                rgb = normalize_image(rgb)

            axes[2].imshow(rgb)
            axes[2].set_title("Plant Pixels Only")
            axes[2].axis("off")

            plt.tight_layout()
            plt.show()

        except Exception as e:
            QMessageBox.warning(
                self, "Display Error", f"Failed to display results: {str(e)}"
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CalibApp()
    window.show()
    sys.exit(app.exec_())

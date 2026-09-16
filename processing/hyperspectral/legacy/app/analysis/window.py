import os
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
from PyQt5.QtWidgets import (
	QWidget,
	QPushButton,
	QLabel,
	QFileDialog,
	QVBoxLayout,
	QHBoxLayout,
	QMessageBox,
	QSpinBox,
	QGroupBox,
	QFormLayout,
	QComboBox,
	QSlider,
	QCheckBox,
	QScrollArea,
	QGridLayout,
)
from PyQt5.QtCore import pyqtSignal , Qt
import datetime
import spectral

from .spectrum_plot import cross_calibrate_and_plot
from .spatial_registration import register_fx10_fx17
from .split import split_cube, visualize_splits
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from preprocessing.background_removal import remove_background



class AnalysisWindow(QWidget):
	"""Simple analysis window to load FX10 and FX17 HDRs and plot mean spectra.

	- Select FX10 file and FX17 file using two buttons.
	- When both are selected, click "Plot" to show two plots (one per camera).
	"""

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Analysis")
		# Enforce a sensible minimum and initial size
		self.setMinimumSize(300, 200)
		# self.resize(800, 520)
		self.fx10_path = None
		self.fx17_path = None
		self.corrected_fx17_path = None  # Path to saved corrected FX17

		layout = QVBoxLayout()

		# FX10 selector
		h1 = QHBoxLayout()
		self.fx10_btn = QPushButton("Select FX10 HDR")
		self.fx10_btn.clicked.connect(self.select_fx10)
		self.fx10_label = QLabel("No file selected")
		h1.addWidget(self.fx10_btn)
		h1.addWidget(self.fx10_label)

		# FX17 selector
		h2 = QHBoxLayout()
		self.fx17_btn = QPushButton("Select FX17 HDR")
		self.fx17_btn.clicked.connect(self.select_fx17)
		self.fx17_label = QLabel("No file selected")
		h2.addWidget(self.fx17_btn)
		h2.addWidget(self.fx17_label)

		# Plot button
		self.plot_btn = QPushButton("Plot")
		self.plot_btn.setEnabled(False)
		self.plot_btn.clicked.connect(self.plot_spectra)

		# Save Corrected FX17 button
		self.save_fx17_btn = QPushButton("Save Corrected FX17")
		self.save_fx17_btn.setEnabled(False)
		self.save_fx17_btn.clicked.connect(self.save_corrected_fx17)

		# Overlay Preview button
		self.overlay_btn = QPushButton("Overlay Preview")
		self.overlay_btn.setEnabled(False)
		self.overlay_btn.clicked.connect(self.show_overlay_preview)

		# Save Wrap Matrix button
		self.save_warp_btn = QPushButton("Save Wrap Matrix")
		self.save_warp_btn.setEnabled(False)
		self.save_warp_btn.clicked.connect(self.save_wrap_matrix)

		# Save Registered Image button
		self.save_registered_btn = QPushButton("Save Registered Image")
		self.save_registered_btn.setEnabled(False)
		self.save_registered_btn.clicked.connect(self.save_registered_image)

		# Split Cube controls
		self.split_group = QGroupBox("Split Cube")
		split_form = QFormLayout()

		self.spin_top_pad = QSpinBox()
		self.spin_top_pad.setRange(0, 99999)
		self.spin_top_pad.setValue(200)
		split_form.addRow("Top Pad:", self.spin_top_pad)

		self.spin_n_rows = QSpinBox()
		self.spin_n_rows.setRange(1, 100)
		self.spin_n_rows.setValue(3)
		split_form.addRow("N Rows:", self.spin_n_rows)

		self.spin_n_cols = QSpinBox()
		self.spin_n_cols.setRange(0, 100)
		self.spin_n_cols.setValue(0)
		split_form.addRow("N Cols (0 = full width):", self.spin_n_cols)

		self.spin_bottom_pad = QSpinBox()
		self.spin_bottom_pad.setRange(0, 99999)
		self.spin_bottom_pad.setValue(50)
		split_form.addRow("Bottom Pad:", self.spin_bottom_pad)

		self.split_group.setLayout(split_form)

		self.split_btn = QPushButton("Split Cube")
		self.split_btn.setEnabled(False)
		self.split_btn.clicked.connect(self.split_cube_action)

		self.remove_bg_segments_btn = QPushButton("Remove Background from Segments")
		self.remove_bg_segments_btn.setEnabled(False)
		self.remove_bg_segments_btn.clicked.connect(self.remove_bg_from_segments_action)
		#adding button for saving the background removed images 
		self.save_bg_segments_btn = QPushButton("Save Background Removed Segments")
		self.save_bg_segments_btn.setEnabled(False)
		self.save_bg_segments_btn.clicked.connect(self.save_bg_segments_action)

		self.segments = None  # Segments of the cube
		self.segments_no_bg = {} # Segments without background
		self.wls = None
		
		#storage variable for fx17 corrected varaible
		self.cross_results = None
		self.registration_results = None  # Store wrap matrix and inliers
		self.registered_hdr_path = None  # Path to saved registered image

		layout.addLayout(h1)
		layout.addLayout(h2)
		layout.addWidget(self.plot_btn)
		layout.addWidget(self.save_fx17_btn)
		layout.addWidget(self.overlay_btn)
		layout.addWidget(self.save_warp_btn)
		layout.addWidget(self.save_registered_btn)
		layout.addWidget(self.split_group)
		layout.addWidget(self.split_btn)
		layout.addWidget(self.remove_bg_segments_btn)
		layout.addWidget(self.save_bg_segments_btn)

		
		# INDEX VISUALIZATION SECTION
		self.index_group = QGroupBox("Vegetation Indices")

		index_layout = QVBoxLayout()

		
		# INDEX DROPDOWN
		self.index_combo = QComboBox()

		self.index_map_names = {
			"Normalised Difference Vegetation Index (NDVI)": "NDVI",
			"Normalised Pigment Chlorophyll Index (NPCI)": "NPCI",
			"Plant Senescence Reflectance Index (PSRI)": "PSRI",
			"Photochemical Reflectance Index (PRI)": "PRI",
			"Simple Ratio (SR)": "SR",
			"Structure-Insensitive Pigment Index (SIPI)": "SIPI",
			"Red Edge Normalised Difference Vegetation Index (RENDVI)": "RENDVI",
			"Normalised Phaeophytinization Index (NPQI)": "NPQI",
			"Normalised Difference Red Edge (NDRE)": "NDRE",
			"Canopy Chlorophyll Content Index (CCCI)": "CCCI",
			"Carotenoid Reflectance Index 2 (CRI2)": "CRI2",
			"Normalized Difference Water Index (NDWI)": "NDWI",
			"Moisture Stress Index (MSI)": "MSI",
			"Normalized Difference Nitrogen Index (NDNI)": "NDNI",
		}

		self.index_combo.addItems(
			list(self.index_map_names.keys())
		)

		
		# THRESHOLD
		self.threshold_slider = QSlider(Qt.Horizontal)

		self.threshold_slider.setMinimum(0)
		self.threshold_slider.setMaximum(100)

		# default = 0.50
		self.threshold_slider.setValue(50)

		# normalized threshold label
		self.threshold_label = QLabel(
			"Normalized Threshold: 0.50"
		)

		# actual threshold label	
		self.actual_threshold_label = QLabel(
			"Actual Threshold: --"
		)

		# horizontal row
		threshold_row = QHBoxLayout()

		threshold_row.addWidget(self.threshold_label)
		threshold_row.addWidget(self.actual_threshold_label)


		self.threshold_slider.valueChanged.connect(
			lambda v: (
				self.threshold_label.setText(
					f"Normalized Threshold: {v/100:.2f}"
				),

				self.actual_threshold_label.setText(
					f"Actual Threshold: "
					f"{self.current_vmin + (v/100)*(self.current_vmax - self.current_vmin):.6f}"
				)
				if hasattr(self, "current_vmin")
				else None
			)
		)

					
		# SHOW ALL CHECKBOX
		self.show_all_checkbox = QCheckBox(
			"Disable Threshold / Show Full Heatmap"
		)

		self.plot_index_btn = QPushButton(
			"Plot Full Image Index"
		)

		self.plot_index_btn.setEnabled(False)

		self.plot_index_btn.clicked.connect(
			self.plot_selected_index
		)

		# SAVE BUTTONS
		
		self.save_index_btn = QPushButton(
			"Save Heatmaps"
		)

		self.save_index_btn.setEnabled(False)

		self.save_index_btn.clicked.connect(
			self.save_index_plot
		)

		self.save_overlay_btn = QPushButton(
			"Save Overlays"
		)

		self.save_overlay_btn.setEnabled(False)

		self.save_overlay_btn.clicked.connect(
			self.save_overlay_plot
		)

		
		# ADD WIDGETS
		index_layout.addWidget(
			QLabel("Select Vegetation Index")
		)

		index_layout.addWidget(self.index_combo)

		index_layout.addLayout(threshold_row)
		index_layout.addWidget(self.threshold_slider)

		index_layout.addWidget(
			self.show_all_checkbox
		)

		index_layout.addWidget(
			self.plot_index_btn
		)

		index_layout.addWidget(
			self.save_index_btn
		)

		index_layout.addWidget(
			self.save_overlay_btn
		)

		self.index_group.setLayout(
			index_layout
		)

		layout.addWidget(self.index_group)
		self.setLayout(layout)

	closed = pyqtSignal()

	def closeEvent(self, event):
		# Emit a closed signal so callers (main window) can re-enable buttons
		try:
			self.closed.emit()
		except Exception:
			pass
		super().closeEvent(event)

	def select_fx10(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select FX10 HDR", "", "HDR Files (*.hdr)")
		if not path:
			return
		self.fx10_path = path
		self.fx10_label.setText(os.path.basename(path))
		self._update_plot_enabled()

	def select_fx17(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select FX17 HDR", "", "HDR Files (*.hdr)")
		if not path:
			return
		self.fx17_path = path
		self.fx17_label.setText(os.path.basename(path))
		self._update_plot_enabled()

	def _update_plot_enabled(self):
		self.plot_btn.setEnabled(bool(self.fx10_path and self.fx17_path))

	def _mark_extrema(self, ax, wl, spectrum):
		"""Mark only prominent local minima and maxima with wavelength labels.

		Uses `scipy.signal.find_peaks` with a prominence threshold (10% of
		the spectrum dynamic range) to avoid annotating small fluctuations.
		"""
		# Guard against empty or constant spectra
		if spectrum is None or spectrum.size == 0:
			return
		s = np.nanmin(spectrum)
		e = np.nanmax(spectrum)
		rng = float(e - s)
		if rng <= 0 or not np.isfinite(rng):
			return

		# Prominence threshold as a fraction of dynamic range (increased to 10%)
		prom = max(rng * 0.10, 1e-6)

		# Find prominent maxima and minima
		max_idx, _ = signal.find_peaks(spectrum, prominence=prom)
		min_idx, _ = signal.find_peaks(-spectrum, prominence=prom)

		# Plot maxima (black dots)
		for idx in max_idx:
			# ax.plot(wl[idx], spectrum[idx], "ko", markersize=5)
			ax.annotate(f"{wl[idx]:.2f} nm", xy=(wl[idx], spectrum[idx]),
						xytext=(2, 3), textcoords="offset points",
						ha="left", fontsize=7, color="black", fontweight="bold",
						bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7, edgecolor="none"))

		# Plot minima (black dots)
		for idx in min_idx:
			# ax.plot(wl[idx], spectrum[idx], "ko", markersize=5)
			ax.annotate(f"{wl[idx]:.2f} nm", xy=(wl[idx], spectrum[idx]),
						xytext=(2, -8), textcoords="offset points",
						ha="left", fontsize=7, color="black", fontweight="bold",
						bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7, edgecolor="none"))

	def _load_mean_spectrum(self, hdr_path):
		img = spectral.open_image(hdr_path)
		data = img.load()  # H x W x B
		# mean across spatial dims
		mean_spectrum = np.nanmean(data, axis=(0, 1))
		# attempt to read wavelengths metadata
		wls = img.metadata.get("wavelength", None)
		if wls is None:
			# fallback to band indices
			wls = np.arange(mean_spectrum.size)
		else:
			try:
				wls = [float(w) for w in wls]
			except Exception:
				wls = np.arange(mean_spectrum.size)
		return np.array(wls), np.array(mean_spectrum)

	def plot_spectra(self):
		try:
			fx10_wl, fx10_spec = self._load_mean_spectrum(self.fx10_path)
			fx17_wl, fx17_spec = self._load_mean_spectrum(self.fx17_path)

			results = cross_calibrate_and_plot(
				fx10_path=self.fx10_path,
				fx17_path=self.fx17_path
			)

			self.cross_results = results
			self.save_fx17_btn.setEnabled(True)

			fx17_corr_wl = results["fx17_corr_wl"]
			fx17_corr_spec = results["fx17_corr_spec"]

			# Mask ≥ 900nm
			mask = fx17_corr_wl >= 900
			fx17_corr_wl_masked = fx17_corr_wl[mask]
			fx17_corr_spec_masked = fx17_corr_spec[mask]

			fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=False)

			# FX10
			axes[0].plot(fx10_wl, fx10_spec, color="tab:blue")
			axes[0].set_title("FX10 ROI mean")
			axes[0].set_ylabel("Reflectance")
			axes[0].set_xlabel("Wavelength")
			self._mark_extrema(axes[0], fx10_wl, fx10_spec)

			# FX17
			axes[1].plot(fx17_wl, fx17_spec, color="tab:green")
			axes[1].set_title("FX17 original ROI mean")
			axes[1].set_ylabel("Reflectance")
			axes[1].set_xlabel("Wavelength")
			self._mark_extrema(axes[1], fx17_wl, fx17_spec)

			# Corrected FX17 ≥ 900nm
			axes[2].plot(fx17_corr_wl_masked, fx17_corr_spec_masked,
						color="tab:purple")
			axes[2].set_title("FX17 corrected ROI mean")
			axes[2].set_ylabel("Reflectance")
			axes[2].set_xlabel("Wavelength")
			self._mark_extrema(axes[2],
							fx17_corr_wl_masked,
							fx17_corr_spec_masked)

			plt.tight_layout()
			plt.show()

		except Exception as e:
			QMessageBox.warning(self, "Plot Error",
								f"Failed to plot spectra: {e}")

	#function for saving the corrected fx17 
	def save_corrected_fx17(self):
		if self.cross_results is None:
			QMessageBox.warning(self, "Error", "No corrected spectrum available")
			return

		try:
			import spectral
			import time

			
			# Create /corrected folder beside FX17 file
			
			parent_dir = os.path.dirname(self.fx17_path)
			corrected_dir = os.path.join(parent_dir, "corrected")
			os.makedirs(corrected_dir, exist_ok=True)

			output_dir = QFileDialog.getExistingDirectory(
				self,
				"Select directory to save corrected FX17",
				corrected_dir
			)

			if not output_dir:
				return

			
			# Load original FX17 cube
			
			img = spectral.open_image(self.fx17_path)
			cube = img.load()  # H x W x B
			cube = np.array(cube, dtype=np.float32)

			H, W, B = cube.shape

			
			# Load correction spectrum
			
			fx17_corr_spec = self.cross_results["fx17_corr_spec"]
			fx17_corr_spec = np.array(fx17_corr_spec, dtype=np.float32)

			if len(fx17_corr_spec) != B:
				raise ValueError("Corrected spectrum size does not match FX17 bands")

			
			# Apply correction to every pixel
			
			# corrected_cube = cube * fx17_corr_spec  # broadcast across H,W
			corrected_cube = self.cross_results["a"]*cube + self.cross_results["b"]  # linear correction

			
			# Copy metadata
			
			meta = img.metadata.copy()

			meta["description"] = f"Corrected FX17 cube saved at {time.ctime()}"
			meta["samples"] = W
			meta["lines"] = H
			meta["bands"] = B
			meta["data type"] = 4  # float32
			meta["interleave"] = "bil"

			
			# Output file name
			
			raw_name = os.path.basename(self.fx17_path)[:-4]

			out_hdr = os.path.join(
				output_dir,
				f"{raw_name}_corrected-FX17.hdr"
			)

			
			# Save full hyperspectral cube
			
			spectral.envi.save_image(
				out_hdr,
				corrected_cube,
				dtype=np.float32,
				interleave="bil",
				metadata=meta,
				force=True
			)

			# Store the corrected FX17 path
			self.corrected_fx17_path = out_hdr
			self.overlay_btn.setEnabled(True)

			QMessageBox.information(
				self,
				"Success",
				f"Corrected FX17 cube saved to:\n{out_hdr}"
			)

		except Exception as e:
			QMessageBox.warning(self, "Save Error", f"Failed to save:\n{e}")

	def show_overlay_preview(self):
		"""Show overlay preview by performing spatial registration."""
		if not self.fx10_path or not self.corrected_fx17_path:
			QMessageBox.warning(self, "Error", "FX10 path or corrected FX17 path not available")
			return

		try:
			print(f"Registering FX10: {self.fx10_path}")
			print(f"Registering corrected FX17: {self.corrected_fx17_path}")
			
			# Call the registration function
			cube17_registered, M, inliers = register_fx10_fx17(
				self.fx10_path,
				self.corrected_fx17_path
			)

			# Store registration results
			self.registration_results = {
				"cube": cube17_registered,
				"M": M,
				"inliers": inliers
			}

			# Enable save wrap matrix button
			self.save_warp_btn.setEnabled(True)
			self.save_registered_btn.setEnabled(True)

			# Display wrap matrix and inliers information
			msg = f"Registration Complete!\n\n"
			msg += f"Wrap Matrix (Affine 2x3):\n{M}\n\n"
			msg += f"Number of Affine Inliers: {np.sum(inliers)}\n"
			msg += f"Total Inliers: {np.sum(inliers)}"
			
			QMessageBox.information(self, "Registration Results", msg)

		except Exception as e:
			QMessageBox.warning(self, "Registration Error", f"Failed to register:\n{e}")

	def save_wrap_matrix(self):
		"""Save the wrap matrix to a file selected by user."""
		if self.registration_results is None:
			QMessageBox.warning(self, "Error", "No wrap matrix available")
			return

		try:
			# Get output file path from user
			file_path, _ = QFileDialog.getSaveFileName(
				self,
				"Save Wrap Matrix",
				"",
				"Text Files (*.txt);;NumPy Files (*.npy);;CSV Files (*.csv)"
			)

			if not file_path:
				return

			M = self.registration_results["M"]
			inliers = self.registration_results["inliers"]

			# Save based on file extension
			if file_path.endswith('.npy'):
				np.save(file_path, M)
				np.save(file_path.replace('.npy', '_inliers.npy'), inliers)
				QMessageBox.information(
					self,
					"Success",
					f"Wrap matrix saved to:\n{file_path}\n\nInliers saved to:\n{file_path.replace('.npy', '_inliers.npy')}"
				)
			elif file_path.endswith('.csv'):
				np.savetxt(file_path, M, delimiter=',')
				np.savetxt(file_path.replace('.csv', '_inliers.csv'), inliers, delimiter=',')
				QMessageBox.information(
					self,
					"Success",
					f"Wrap matrix saved to:\n{file_path}\n\nInliers saved to:\n{file_path.replace('.csv', '_inliers.csv')}"
				)
			else:  # .txt or default
				with open(file_path, 'w') as f:
					f.write("Affine Transformation Matrix (2x3):\n")
					f.write(str(M))
					f.write("\n\nInliers:\n")
					f.write(str(inliers))
				QMessageBox.information(
					self,
					"Success",
					f"Wrap matrix saved to:\n{file_path}"
				)

		except Exception as e:
			QMessageBox.warning(self, "Save Error", f"Failed to save:\n{e}")

	def save_registered_image(self):
		"""Save the merged registered image (FX10 + registered FX17) with wavelengths."""
		if self.registration_results is None or not self.fx10_path or not self.corrected_fx17_path:
			QMessageBox.warning(self, "Error", "Registration results or file paths not available")
			return

		try:
			# Get output directory from user
			output_dir = QFileDialog.getExistingDirectory(
				self,
				"Select directory to save registered image"
			)

			if not output_dir:
				return

			print("Loading FX10 cube...")
			# Load FX10 cube and metadata
			fx10_img = spectral.open_image(self.fx10_path)
			fx10_cube = fx10_img.load().astype(np.float32)
			fx10_meta = fx10_img.metadata.copy()
			fx10_wl = np.array([float(w) for w in fx10_meta.get("wavelength", [])])
			fx10_bands = fx10_cube.shape[2]

			print("Loading FX17 corrected cube...")
			# Load FX17 corrected cube and metadata
			fx17_img = spectral.open_image(self.corrected_fx17_path)
			fx17_cube = fx17_img.load().astype(np.float32)
			fx17_meta = fx17_img.metadata.copy()
			fx17_wl = np.array([float(w) for w in fx17_meta.get("wavelength", [])])
			fx17_bands = fx17_cube.shape[2]

			print(f"FX10 cube shape: {fx10_cube.shape}, wavelength range: {fx10_wl[0]:.2f}-{fx10_wl[-1]:.2f} nm")
			print(f"FX17 cube shape: {fx17_cube.shape}, wavelength range: {fx17_wl[0]:.2f}-{fx17_wl[-1]:.2f} nm")

			# Get registered FX17 cube from registration results
			fx17_registered = self.registration_results["cube"]
			print(f"Registered FX17 cube shape: {fx17_registered.shape}")

			# Ensure same spatial dimensions
			H, W, _ = fx10_cube.shape
			if fx17_registered.shape[:2] != (H, W):
				raise ValueError(f"Spatial dimension mismatch: FX10 {(H, W)} vs FX17 registered {fx17_registered.shape[:2]}")

			# Find band indices for wavelength ranges
			# FX10: 400-900nm
			fx10_900_idx = np.where(fx10_wl <= 900)[0]
			# FX17: 900-1700nm
			fx17_900_idx = np.where(fx17_wl >= 900)[0]
			fx17_1000_idx = np.where(fx17_wl >= 1000)[0]

			print(f"FX10 bands up to 900nm: {len(fx10_900_idx)}")
			print(f"FX17 bands from 900nm: {len(fx17_900_idx)}")
			print(f"FX17 bands from 1000nm: {len(fx17_1000_idx)}")

			# Build merged wavelength list and cube
			merged_wl_list = []
			merged_bands = []

			# Part 1: FX10 400-900nm
			merged_wl_list.extend(fx10_wl[fx10_900_idx].tolist())
			for idx in fx10_900_idx:
				merged_bands.append(fx10_cube[:, :, idx])

			# Part 2: FX17 900-1000nm (overlap region - use FX10 wavelengths but could add both)
			overlap_900_1000_fx10 = fx10_wl[(fx10_wl >= 900) & (fx10_wl <= 1000)]
			overlap_900_1000_fx17 = fx17_wl[(fx17_wl >= 900) & (fx17_wl <= 1000)]
			
			# For overlap: include unique wavelengths from both, prioritizing FX10
			overlap_all_wl = np.unique(np.concatenate([overlap_900_1000_fx10, overlap_900_1000_fx17]))
			
			for wl in overlap_all_wl:
				# Prefer FX10 if available
				if wl in fx10_wl:
					idx = np.where(fx10_wl == wl)[0][0]
					merged_wl_list.append(wl)
					merged_bands.append(fx10_cube[:, :, idx])
				elif wl in fx17_wl:
					idx = np.where(fx17_wl == wl)[0][0]
					merged_wl_list.append(wl)
					merged_bands.append(fx17_registered[:, :, idx])

			# Part 3: FX17 1000-1700nm
			merged_wl_list.extend(fx17_wl[fx17_1000_idx].tolist())
			for idx in fx17_1000_idx:
				merged_bands.append(fx17_registered[:, :, idx])

			# Stack all bands
			merged_cube = np.stack(merged_bands, axis=2).astype(np.float32)
			merged_wl_list = np.array(merged_wl_list)

			print(f"Merged cube shape: {merged_cube.shape}")
			print(f"Merged wavelength range: {merged_wl_list[0]:.2f}-{merged_wl_list[-1]:.2f} nm")

			# Update metadata
			meta = fx10_meta.copy()
			meta["description"] = "Merged FX10 (400-900nm) + Registered FX17 (900-1700nm)"
			meta["samples"] = W
			meta["lines"] = H
			meta["bands"] = merged_cube.shape[2]
			meta["data type"] = 4  # float32
			meta["interleave"] = "bil"
			meta["wavelength"] = merged_wl_list.tolist()

			# Output file name
			timestamp = __import__('time').strftime("%Y%m%d_%H%M%S")
			out_hdr = os.path.join(
				output_dir,
				f"merged_fx10_fx17_registered_{timestamp}.hdr"
			)

			print(f"Saving merged image to: {out_hdr}")

			# Save merged hyperspectral cube
			spectral.envi.save_image(
				out_hdr,
				merged_cube,
				dtype=np.float32,
				interleave="bil",
				metadata=meta,
				force=True
			)

			# Store path so Split Cube can use it
			self.registered_hdr_path = out_hdr
			self.split_btn.setEnabled(True)

			QMessageBox.information(
				self,
				"Success",
				f"Registered merged image saved to:\n{out_hdr}\n\n"
				f"Shape: {merged_cube.shape}\n"
				f"Wavelength range: {merged_wl_list[0]:.2f}-{merged_wl_list[-1]:.2f} nm"
			)

		except Exception as e:
			import traceback
			QMessageBox.warning(self, "Save Error", f"Failed to save:\n{str(e)}\n{traceback.format_exc()}")

	def split_cube_action(self):
		"""Load the saved registered image and split it based on user parameters."""
		# If no registered image was saved in this session, ask the user to pick one
		hdr_path = self.registered_hdr_path
		if not hdr_path or not os.path.exists(hdr_path):
			hdr_path, _ = QFileDialog.getOpenFileName(
				self,
				"Select registered / merged HDR to split",
				"",
				"HDR Files (*.hdr)"
			)
			if not hdr_path:
				return

		try:
			img = spectral.open_image(hdr_path)
			cube = img.load().astype(np.float32)
			wls = img.metadata.get("wavelength", None)
			if wls is not None:
				wls = [float(w) for w in wls]
			self.wls = wls

			top_pad = self.spin_top_pad.value()
			bottom_pad = self.spin_bottom_pad.value()
			n_rows = self.spin_n_rows.value()
			n_cols = self.spin_n_cols.value()

			print(f"Splitting cube {cube.shape} with "
				  f"top_pad={top_pad}, bottom_pad={bottom_pad}, "
				  f"n_rows={n_rows}, n_cols={n_cols}")

			self.segments, self.cropped = split_cube(
				cube, top_pad, bottom_pad, n_rows, n_cols
			)

			print(f"Split into {len(self.segments)} segment(s).")
			for seg in self.segments:
				print(f"  {seg['label']}: shape={seg['data'].shape}, "
					  f"rows={seg['row_slice']}, cols={seg['col_slice']}")

			# Visualize
			visualize_splits(self.segments, wavelengths=wls, cropped_cube=self.cropped)
			self.remove_bg_segments_btn.setEnabled(True)

		except Exception as e:
			import traceback
			QMessageBox.warning(
				self, "Split Error",
				f"Failed to split cube:\n{str(e)}\n{traceback.format_exc()}"
			)

	def remove_bg_from_segments_action(self):
		if not self.segments:
			QMessageBox.warning(self, "Error", "No segments to process. Split the cube first.")
			return

		try:
			self.segments_no_bg = {}
			visualize_segments = []

			print(f"Removing background from {len(self.segments)} segments...")

			for seg in self.segments:
				print(f"  Processing {seg['label']}...")
				# We treat the merged cube as "fx10" to use NDVI from the visible/NIR bands
				plant_only, plant_mask, index_map = remove_background(
					seg['data'], self.wls, "fx10"
				)
				self.segments_no_bg[seg['label']] = plant_only

				# Create segment for visualization
				vis_seg = seg.copy()
				vis_seg['data'] = plant_only
				visualize_segments.append(vis_seg)

			print("Background removal complete.")
			self.save_bg_segments_btn.setEnabled(True)
			self.plot_index_btn.setEnabled(True)
			self.plot_index_btn.setEnabled(True)
			visualize_splits(visualize_segments, wavelengths=self.wls, cropped_cube=None)

		except Exception as e:
			import traceback
			QMessageBox.warning(
				self, "Background Removal Error",
				f"Failed to remove background:\n{str(e)}\n{traceback.format_exc()}"
			)
	def save_bg_segments_action(self):
		"""Save background removed segments as ENVI HDR files."""
		if not self.segments_no_bg:
			QMessageBox.warning(
				self,
				"Error",
				"No background removed segments available."
			)
			return

		try:
			import spectral
			import time

			# Ask user for output directory
			output_dir = QFileDialog.getExistingDirectory(
				self,
				"Select folder to save background removed segments"
			)

			if not output_dir:
				return

			# Create subfolder
			save_dir = os.path.join(
				output_dir,
				f"background_removed_segments_{time.strftime('%Y%m%d_%H%M%S')}"
			)

			os.makedirs(save_dir, exist_ok=True)

			print(f"Saving segments to: {save_dir}")
		
 
			for idx, (label, cube) in enumerate(self.segments_no_bg.items(), start=1): 

				cube = np.array(cube, dtype=np.float32)
				H, W, B = cube.shape

				# Metadata
				meta = {
					"description": f"Background removed segment {idx}",
					"samples": W,
					"lines": H,
					"bands": B,
					"data type": 4,
					"interleave": "bil",
				}

				# Preserve wavelengths if available
				if self.wls is not None:
					meta["wavelength"] = [float(w) for w in self.wls]

				# Output filename
				out_hdr = os.path.join(
					save_dir,
					f"segment{idx}.hdr"
				)

				# Save ENVI image
				spectral.envi.save_image(
					out_hdr,
					cube,
					dtype=np.float32,
					interleave="bil",
					metadata=meta,
					force=True
				)

				
				# Save metadata TXT
				meta_txt_path = os.path.join(
					save_dir,
					f"segment{idx}_metadata.txt"
				)

				with open(meta_txt_path, "w") as f:

					f.write(f"Segment Label: {label}\n")
					f.write(f"Shape: {cube.shape}\n")
					f.write(f"Saved Time: {time.ctime()}\n\n")

					f.write(" ENVI Metadata \n")

					for k, v in meta.items():
						f.write(f"{k}: {v}\n")

					# Save original segment information if available
					if idx - 1 < len(self.segments):

						orig_seg = self.segments[idx - 1]

						f.write("\n Original Segment Info \n")

						for key, value in orig_seg.items():

							# Avoid dumping full cube array
							if key == "data":
								f.write(f"{key}: ndarray shape={value.shape}\n")
							else:
								f.write(f"{key}: {value}\n")

					print(f"Saved: {out_hdr}")

			QMessageBox.information(
				self,
				"Success",
				f"Background removed segments saved to:\n{save_dir}"
			)

		except Exception as e:
			import traceback
			QMessageBox.warning(
				self,
				"Save Error",
				f"Failed to save segments:\n{str(e)}\n{traceback.format_exc()}"
			)

	def get_band_index(self, wavelength):
		wls = np.array(self.wls)
		return np.argmin(np.abs(wls - wavelength))
	
	def calculate_index(self, cube, index_name):

		eps = 1e-8

		def R(w):
			return cube[:, :, self.get_band_index(w)]

		if index_name == "NDVI":
			return (R(800) - R(680)) / (R(800) + R(680) + eps)

		elif index_name == "NPCI":
			return (R(680) - R(430)) / (R(680) + R(430) + eps)

		elif index_name == "PSRI":
			return (R(678) - R(500)) / (R(750) + eps)

		elif index_name == "PRI":
			return (R(531) - R(570)) / (R(531) + R(570) + eps)

		elif index_name == "SR":
			return R(800) / (R(680) + eps)

		elif index_name == "SIPI":
			return (R(800) - R(445)) / (R(800) + R(680) + eps)

		elif index_name == "RENDVI":
			return (R(750) - R(705)) / (R(750) + R(705) + eps)

		elif index_name == "NPQI":
			return (R(415) - R(430)) / (R(415) + R(430) + eps)

		elif index_name == "NDRE":
			return (R(790) - R(720)) / (R(790) + R(720) + eps)

		elif index_name == "CCCI":

			ndre = (R(790) - R(720)) / (R(790) + R(720) + eps)
			ndvi = (R(800) - R(670)) / (R(800) + R(670) + eps)

			return ndre / (ndvi + eps)

		elif index_name == "CRI2":
			return (1/(R(510)+eps)) - (1/(R(700)+eps))

		elif index_name == "NDWI":
			return (R(860) - R(1240)) / (R(860) + R(1240) + eps)

		elif index_name == "MSI":
			return R(1600) / (R(820) + eps)

		# elif index_name == "CAI":
		# 	return 0.5 * (R(2000) + R(2200)) - R(2100)

		elif index_name == "NDNI":
			return (np.log(1/(R(1510)+eps)) - np.log(1/(R(1680)+eps))) / (
				np.log(1/(R(1510)+eps)) + np.log(1/(R(1680)+eps)) + eps
			)

		else:
			raise ValueError(f"Unknown index: {index_name}")
	
	def plot_selected_index(self):

		if not self.segments_no_bg:
			QMessageBox.warning(self, "Error", "No background removed segments available.")
			return

		try:
			segment_arrays = []

			for label in self.segments_no_bg:

				segment_arrays.append(
					self.segments_no_bg[label]
				)

			cube = np.concatenate(
				segment_arrays,
				axis=0
			)

			index_full_name = self.index_combo.currentText()
			index_name = self.index_map_names[index_full_name]

			index_map = self.calculate_index(cube, index_name)

			index_map = np.nan_to_num(index_map)
			valid_pixels = index_map[np.isfinite(index_map)]

			vmin = np.min(valid_pixels)
			vmax = np.max(valid_pixels)

  

			# Convert slider to ACTUAL VALUE
			# NORMALIZED THRESHOLD (0 -> 1)

			threshold_normalized = (
				self.threshold_slider.value()
				/
				100
			)

			# CONVERT TO ACTUAL INDEX RANGE

			threshold_actual = (
				vmin
				+
				threshold_normalized
				*
				(vmax - vmin)
			)
			# show actual threshold being used internally
			self.actual_threshold_label.setText(
				f"Actual Threshold: {threshold_actual:.6f}"
			)
			index_map_thresholded = np.copy(index_map)

			if not self.show_all_checkbox.isChecked():

				index_map_thresholded[
					index_map_thresholded < threshold_actual
				] = np.nan

				
			self.current_index_raw = index_map_thresholded
			self.current_vmin = vmin
			self.current_vmax = vmax


			self.current_metadata = {
				"index": index_name,
				"threshold_normalized": threshold_normalized,
				"threshold_actual": threshold_actual,
				"datetime": str(datetime.datetime.now()),
				"shape": str(cube.shape),
				"wavelength_range": f"{self.wls[0]} - {self.wls[-1]}"
			}


			# Update label with REAL VALUE
			self.threshold_label.setText(
				f"Normalized Threshold: {threshold_normalized:.2f}"
			)

			
			# APPLY THRESHOLD USING REAL INDEX VALUES
			# APPLY THRESHOLD DIRECTLY TO INDEX MAP


			# RGB image
			r = cube[:, :, self.get_band_index(680)]
			g = cube[:, :, self.get_band_index(550)]
			b = cube[:, :, self.get_band_index(450)]

			rgb = np.stack([r, g, b], axis=2)

			rgb = rgb - rgb.min()
			rgb = rgb / (rgb.max() + 1e-8)
 
			heat = index_map_thresholded
			# Overlay
			alpha = 0.5

			# NORMALIZE ONLY FOR DISPLAY
			display_norm = (
				(index_map_thresholded - vmin)
				/
				(vmax - vmin + 1e-8)
			)

			display_norm = np.nan_to_num(display_norm)

			heat_rgb = plt.cm.inferno(display_norm)[:, :, :3]

			overlay = (
				(1 - alpha) * rgb
				+
				alpha * heat_rgb
			)

			overlay = np.clip(overlay, 0, 1)

			# Save references
			self.current_index_plot = heat
			self.current_overlay_plot = overlay

			fig, axes = plt.subplots(1, 3, figsize=(18, 6))

			axes[0].imshow(rgb)
			axes[0].set_title("Original Image")
			axes[0].axis("off")

			im = axes[1].imshow(
				index_map_thresholded,
				cmap="inferno",
				vmin=vmin,
				vmax=vmax
			)

			axes[1].set_title(f"{index_name} Heatmap")
			axes[1].axis("off")

			cbar = fig.colorbar(
				im,
				ax=axes[1],
				fraction=0.046,
				pad=0.04
			)

			cbar.set_label(index_name)

			axes[2].imshow(overlay)
			axes[2].set_title("Overlay")
			axes[2].axis("off")

			plt.tight_layout()
			plt.show()

			self.save_index_btn.setEnabled(True)
			self.save_overlay_btn.setEnabled(True)

		except Exception as e:
			import traceback

			QMessageBox.warning(
				self,
				"Plot Error",
				f"{str(e)}\n\n{traceback.format_exc()}"
			)
	def save_index_plot(self):
		output_dir = QFileDialog.getExistingDirectory(
			self,
			"Select Save Folder"
		)

		if not output_dir:
			return

		path = os.path.join(
			output_dir,
			"heatmap.png"
		)

		fig, ax = plt.subplots(
			figsize=(10,10)
		)

		im = ax.imshow(
			self.current_index_raw,
			cmap="inferno",
			vmin=self.current_vmin,
			vmax=self.current_vmax
		)

		ax.axis("off")

		ax.set_title(
			"Vegetation Index Heatmap"
		)

		# COLORBAR
		cbar = fig.colorbar(
			im,
			ax=ax,
			fraction=0.046,
			pad=0.04
		)

		cbar.set_label(
			self.current_metadata["index"]
		)

		metadata_text = (
			f"Index: {self.current_metadata['index']}\n"
			f"Threshold (0-1): {self.current_metadata['threshold_normalized']:.2f}\n"
			f"Actual Threshold: {self.current_metadata['threshold_actual']:.4f}\n"
			f"Datetime: {self.current_metadata['datetime']}\n"
			f"Shape: {self.current_metadata['shape']}\n"
			f"Wavelengths: {self.current_metadata['wavelength_range']}"
		)

		ax.text(
			0.99,
			0.99,
			metadata_text,
			transform=ax.transAxes,
			ha="right",
			va="top",
			fontsize=8,
			color="white",
			bbox=dict(
				facecolor="black",
				alpha=0.7
			)
		)

		plt.savefig(
			path,
			bbox_inches="tight",
			dpi=300
		)

		plt.close()

		QMessageBox.information(
			self,
			"Saved",
			f"Saved:\n{path}"
		)
	def save_overlay_plot(self):

		output_dir = QFileDialog.getExistingDirectory(
			self,
			"Select Save Folder"
		)

		if not output_dir:
			return

		path = os.path.join(
			output_dir,
			"overlay.png"
		)

		fig, ax = plt.subplots(
			figsize=(10,10)
		)

		im = ax.imshow(self.current_overlay_plot)

		mappable = plt.cm.ScalarMappable(
			cmap="inferno"
		)

		mappable.set_clim(
			self.current_vmin,
			self.current_vmax
		)

		cbar = fig.colorbar(
			mappable,
			ax=ax,
			fraction=0.046,
			pad=0.04
		)

		cbar.set_label(
			self.current_metadata["index"]
		)

		ax.axis("off")

		ax.set_title(
			"Overlay"
		)

		metadata_text = (
			f"Index: {self.current_metadata['index']}\n"
			f"Threshold (0-1): {self.current_metadata['threshold_normalized']:.2f}\n"
			f"Actual Threshold: {self.current_metadata['threshold_actual']:.4f}\n"
			f"Datetime: {self.current_metadata['datetime']}\n"
			f"Shape: {self.current_metadata['shape']}\n"
			f"Wavelengths: {self.current_metadata['wavelength_range']}"
		)

		ax.text(
			0.99,
			0.99,
			metadata_text,
			transform=ax.transAxes,
			ha="right",
			va="top",
			fontsize=8,
			color="white",
			bbox=dict(
				facecolor="black",
				alpha=0.7
			)
		)

		plt.savefig(
			path,
			bbox_inches="tight",
			dpi=300
		)

		plt.close()

		QMessageBox.information(
			self,
			"Saved",
			f"Saved:\n{path}"
		)
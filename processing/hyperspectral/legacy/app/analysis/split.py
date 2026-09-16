"""
split.py – Break a merged hyperspectral cube into smaller spatial segments.

User-controlled parameters (set from the AnalysisWindow UI):
    top_pad    : rows to remove from the top of the cube
    bottom_pad : rows to remove from the bottom of the cube
    n_rows     : number of row-wise splits (≥ 1)
    n_cols     : number of column-wise splits (0 means keep full width)

The pipeline:
    1. Strip top/bottom padding rows.
    2. Divide the cropped region into an (n_rows × n_cols) grid.
    3. Return a list of sub-cubes together with their spatial coordinates.
"""

import numpy as np
import matplotlib.pyplot as plt


def split_cube(cube, top_pad, bottom_pad, n_rows, n_cols):
    """Split a hyperspectral cube into spatial segments.

    Parameters
    ----------
    cube : np.ndarray
        3-D array of shape (H, W, B).
    top_pad : int
        Number of rows to remove from the top.
    bottom_pad : int
        Number of rows to remove from the bottom.
    n_rows : int
        Number of row-wise divisions (must be >= 1).
    n_cols : int
        Number of column-wise divisions.
        0 means no column splitting (treated as 1).

    Returns
    -------
    segments : list[dict]
        Each dict contains:
            "data"      : np.ndarray  - the sub-cube (h, w, B)
            "row_idx"   : int         - row index in the grid (0-based)
            "col_idx"   : int         - col index in the grid (0-based)
            "row_slice" : tuple       - (start_row, end_row) in the *original* cube
            "col_slice" : tuple       - (start_col, end_col) in the *original* cube
    cropped_cube : np.ndarray
        The cube after padding removal (before grid split).
    """

    H, W, B = cube.shape

    # --- Validate padding ---
    if top_pad < 0 or bottom_pad < 0:
        raise ValueError("Padding values must be non-negative.")
    if top_pad + bottom_pad >= H:
        raise ValueError(
            f"top_pad ({top_pad}) + bottom_pad ({bottom_pad}) = {top_pad + bottom_pad} "
            f"exceeds cube height ({H})."
        )

    # --- Validate splits ---
    if n_rows < 1:
        raise ValueError("n_rows must be >= 1.")
    # Treat n_cols == 0 as "no column split" → 1
    if n_cols <= 0:
        n_cols = 1

    # --- Crop top/bottom padding from the whole image first ---
    # cropped_cube = cube[top_pad:H - bottom_pad, :, :]
    cropped_cube = cube[top_pad:-bottom_pad if bottom_pad > 0 else None, :, :]
    cropped_H, cropped_W = cropped_cube.shape[0], cropped_cube.shape[1]

    # --- Split the cropped image into equal parts ---
    row_edges = np.linspace(0, cropped_H, n_rows + 1, dtype=int)
    col_edges = np.linspace(0, cropped_W, n_cols + 1, dtype=int)

    segments = []
    for ri in range(n_rows):
        for ci in range(n_cols):
            r0, r1 = int(row_edges[ri]), int(row_edges[ri + 1])
            c0, c1 = int(col_edges[ci]), int(col_edges[ci + 1])

            sub_cube = cropped_cube[r0:r1, c0:c1, :]
            segments.append({
                "data": sub_cube,
                "row_idx": ri,
                "col_idx": ci,
                "row_slice": (top_pad + r0, top_pad + r1),
                "col_slice": (c0, c1),
                "label": f"R{ri}_C{ci}",
            })

    return segments, cropped_cube


def _to_rgb(cube, wavelengths=None):
    """Create a simple RGB composite from a hyperspectral sub-cube.

    Uses bands closest to 660 nm (R), 550 nm (G), 450 nm (B) when
    wavelength metadata is available; otherwise falls back to evenly
    spaced band indices.
    """
    B = cube.shape[2]

    if wavelengths is not None and len(wavelengths) == B:
        wl = np.array(wavelengths, dtype=float)
        r_idx = int(np.argmin(np.abs(wl - 660)))
        g_idx = int(np.argmin(np.abs(wl - 550)))
        b_idx = int(np.argmin(np.abs(wl - 450)))
    else:
        # Evenly spaced fallback
        r_idx = min(int(B * 0.75), B - 1)
        g_idx = min(int(B * 0.50), B - 1)
        b_idx = min(int(B * 0.15), B - 1)

    def _norm(ch):
        ch = ch.astype(np.float64)
        lo, hi = np.nanmin(ch), np.nanmax(ch)
        if hi - lo < 1e-8:
            return np.zeros_like(ch)
        return (ch - lo) / (hi - lo)

    rgb = np.stack([
        _norm(cube[:, :, r_idx]),
        _norm(cube[:, :, g_idx]),
        _norm(cube[:, :, b_idx]),
    ], axis=-1)
    return np.clip(rgb, 0, 1)


def visualize_splits(segments, wavelengths=None, cropped_cube=None):
    """Show every segment as an RGB thumbnail in a single figure.

    Parameters
    ----------
    segments : list[dict]
        Output of :func:`split_cube`.
    wavelengths : list or np.ndarray, optional
        Band wavelengths for RGB mapping.
    cropped_cube : np.ndarray, optional
        If provided, the full cropped cube is shown in a top panel with
        grid lines indicating where the splits are.
    """

    n_segs = len(segments)
    if n_segs == 0:
        print("No segments to visualize.")
        return

    # Determine grid dimensions from segment metadata
    max_row = max(s["row_idx"] for s in segments) + 1
    max_col = max(s["col_idx"] for s in segments) + 1

    # Extra row for the overview if cropped_cube is given
    extra = 1 if cropped_cube is not None else 0
    fig_rows = max_row + extra

    fig, axes = plt.subplots(
        fig_rows, max_col,
        figsize=(4 * max_col, 3.5 * fig_rows),
        squeeze=False,
    )

    # --- Overview panel ---
    if cropped_cube is not None:
        # Merge all overview columns into one axes via gridspec
        for c in range(max_col):
            axes[0, c].axis("off")
        # Use the first axes spanning full width for the overview
        overview_ax = fig.add_subplot(fig_rows, 1, 1)
        overview_rgb = _to_rgb(cropped_cube, wavelengths)
        overview_ax.imshow(overview_rgb)
        overview_ax.set_title("Cropped Cube (after padding removal)", fontsize=12, fontweight="bold")
        overview_ax.axis("off")

        # Draw grid lines
        H_c, W_c = cropped_cube.shape[:2]
        row_edges = np.linspace(0, H_c, max_row + 1)
        col_edges = np.linspace(0, W_c, max_col + 1)
        for r_edge in row_edges[1:-1]:
            overview_ax.axhline(r_edge, color="red", linewidth=1.5, linestyle="--")
        for c_edge in col_edges[1:-1]:
            overview_ax.axvline(c_edge, color="red", linewidth=1.5, linestyle="--")

    # --- Segment panels ---
    for seg in segments:
        ri = seg["row_idx"] + extra
        ci = seg["col_idx"]
        ax = axes[ri, ci]
        rgb = _to_rgb(seg["data"], wavelengths)
        ax.imshow(rgb)
        r_sl = seg["row_slice"]
        c_sl = seg["col_slice"]
        ax.set_title(
            f'{seg["label"]}\n'
            f'rows {r_sl[0]}–{r_sl[1]}, cols {c_sl[0]}–{c_sl[1]}\n'
            f'shape {seg["data"].shape[:2]}',
            fontsize=9,
        )
        ax.axis("off")

    # Hide any unused axes
    for ri in range(extra, fig_rows):
        for ci in range(max_col):
            idx_r = ri - extra
            idx_c = ci
            if not any(s["row_idx"] == idx_r and s["col_idx"] == idx_c for s in segments):
                axes[ri, ci].axis("off")

    plt.tight_layout()
    plt.show()


# ------------------------------------------------------------------ #
#  Standalone test
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    import sys
    import spectral

    hdr_path   = '/home/sriram/ANU/data/csiro_fx10_17_2_wheat/calibrated/corrected/registered/merged_fx10_fx17_registered_20260525_100338.hdr'
    top_pad    = 200
    n_rows     = 3
    n_cols     = 0
    bottom_pad = 50

    print(f"Loading: {hdr_path}")
    img = spectral.open_image(hdr_path)
    cube = img.load().astype(np.float32)
    wls = img.metadata.get("wavelength", None)
    if wls is not None:
        wls = [float(w) for w in wls]

    print(f"Cube shape: {cube.shape}")
    print(f"Params: top_pad={top_pad}, n_rows={n_rows}, n_cols={n_cols}, bottom_pad={bottom_pad}")

    segments, cropped = split_cube(cube, top_pad, bottom_pad, n_rows, n_cols)

    print(f"\nSplit into {len(segments)} segment(s):")
    for seg in segments:
        print(f"  {seg['label']}: shape={seg['data'].shape}, "
              f"rows={seg['row_slice']}, cols={seg['col_slice']}")

    visualize_splits(segments, wavelengths=wls, cropped_cube=None)


    # overview = _to_rgb(cube, wls)
    # plt.imshow(overview)
    # plt.show()

    overview = _to_rgb(cropped, wls)
    plt.imshow(overview)
    plt.show()

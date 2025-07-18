#!/usr/bin/env python3
"""
debug_fixed_fits.py

This script is hardcoded to read the three converted FITS files from the specified folder
and perform data integrity checks (existence, shapes, monotonicity, NaNs, summary stats).
"""
import os
import sys
import numpy as np
from astropy.io import fits


def main():
    # === UPDATE THIS PATH if needed ===
    input_dir = (
        "/Users/anthonymunozperez/Desktop/"
        "spectrum_analyzer-main 2/"
        "Matthews_MIRI_reduction_May_2025/converted_all_channels"
    )

    flux_path = os.path.join(input_dir, 'flux.fits')
    wav_path  = os.path.join(input_dir, 'wavelength.fits')
    time_path = os.path.join(input_dir, 'time.fits')

    # Check files
    for p in (flux_path, wav_path, time_path):
        if not os.path.isfile(p):
            print(f"ERROR: Missing file {p}")
            sys.exit(1)
    print("All files found. Loading data...")

    # Load data
    flux       = fits.getdata(flux_path)
    wavelength = fits.getdata(wav_path)
    with fits.open(time_path) as hdul:
        time_arr = hdul[0].data

    # Shape validations
    if flux.ndim != 2:
        print(f"ERROR: flux.fits should be 2D but has shape {flux.shape}")
    n_times, n_wave = flux.shape
    if wavelength.ndim != 1:
        print(f"ERROR: wavelength.fits should be 1D but has shape {wavelength.shape}")
    if time_arr is None or time_arr.ndim != 1:
        print(f"ERROR: time.fits should be 1D but has data={time_arr}")
    if len(wavelength) != n_wave:
        print(f"ERROR: wavelength length {len(wavelength)} != flux columns {n_wave}")
    if len(time_arr) != n_times:
        print(f"ERROR: time length {len(time_arr)} != flux rows {n_times}")

    print(f"flux shape:      {flux.shape}")
    print(f"wavelength len:  {len(wavelength)}")
    print(f"time length:     {len(time_arr)}")

    # Monotonicity checks
    dw = np.diff(wavelength)
    if not np.all(dw > 0):
        print("WARNING: wavelength array is not strictly increasing.")
    dt = np.diff(time_arr)
    if not np.all(dt >= 0):
        print("WARNING: time array is not non-decreasing.")

    # NaN check
    nan_flux = np.isnan(flux).sum()
    if nan_flux:
        print(f"WARNING: flux contains {nan_flux} NaN values")
    else:
        print("flux contains no NaNs")

    # Summary stats
    print("\nSummary statistics:")
    print(f"  Wavelength: min={wavelength.min()}, max={wavelength.max()}")
    print(f"  Time:       min={time_arr.min()}, max={time_arr.max()}")
    print(f"  Flux:       min={np.nanmin(flux)}, max={np.nanmax(flux)}, mean={np.nanmean(flux)}")

    print("\nDebug complete.")

if __name__ == '__main__':
    main()

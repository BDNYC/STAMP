"""
Numerical processing pipeline for JWST spectral time-series data.
"""

import os
import logging
import time as _time

import numpy as np
from scipy.stats import binned_statistic
from scipy.ndimage import gaussian_filter
from scipy import interpolate
from concurrent.futures import ThreadPoolExecutor
from astropy.io import fits
import h5py

from data_io import (
    load_integrations_from_fits,
    load_integrations_from_h5,
    _first_key,
)

logger = logging.getLogger(__name__)


def calculate_bin_size(data_length, num_plots):
    """Return the binning factor to reduce data_length to ~num_plots bins."""
    return max(1, data_length // num_plots)


def bin_flux_arr(fluxarr, bin_size):
    """Median-bin a 2-D flux array along the time axis using a thread pool."""
    try:
        n_bins = fluxarr.shape[1] // bin_size
        bin_edges = np.linspace(0, fluxarr.shape[1], n_bins + 1)

        def bin_row(row):
            return binned_statistic(
                np.arange(len(row)), row, statistic='median', bins=bin_edges
            )[0]

        with ThreadPoolExecutor() as executor:
            fluxarrbin = np.array(list(executor.map(bin_row, fluxarr)))
        return fluxarrbin
    except Exception as e:
        logger.error(f"Error in bin_flux_arr: {str(e)}")
        raise


def smooth_flux(flux, sigma=2):
    """Apply a Gaussian filter to a flux array."""
    try:
        return gaussian_filter(flux, sigma=sigma)
    except Exception as e:
        logger.error(f"Error in smooth_flux: {str(e)}")
        raise


def process_data(flux, wavelength, time, num_plots, apply_binning=True,
                 smooth_sigma=2, wavelength_unit='um',
                 z_axis_display='variability'):
    """Prepare raw arrays for Plotly plotting: align, clean, bin, smooth, meshgrid."""
    try:
        logger.info('Shape before processing: %s', flux.shape)
        logger.info(f'Time array shape: {time.shape if hasattr(time, "shape") else len(time)}')
        logger.info(f'Z-axis display mode: {z_axis_display}')

        min_length = min(flux.shape[0], len(wavelength))
        flux = flux[:min_length]
        wavelength = np.asarray(wavelength[:min_length], dtype=float)

        finite_mask = np.isfinite(wavelength)
        if not np.all(finite_mask):
            logger.info(f"Removing {np.count_nonzero(~finite_mask)} non-finite wavelength rows")
        wavelength = wavelength[finite_mask]
        flux = flux[finite_mask, :]

        sort_idx = np.argsort(wavelength)
        if not np.all(sort_idx == np.arange(len(sort_idx))):
            logger.info("Sorting wavelengths to be strictly increasing")
        wavelength = wavelength[sort_idx]
        flux = flux[sort_idx, :]

        if not isinstance(time, np.ndarray):
            time = np.array(time, dtype=float)
        else:
            time = time.astype(float)

        bin_size = calculate_bin_size(flux.shape[1], num_plots)
        logger.info(f'Calculated bin size: {bin_size}')
        if bin_size > 1 and apply_binning:
            flux = bin_flux_arr(flux, bin_size)
            time = time[::bin_size]
            logger.info('Shape after binning: %s', flux.shape)

        flux = smooth_flux(flux, sigma=smooth_sigma)
        logger.info('Shape after smoothing: %s', flux.shape)

        if wavelength_unit == 'nm':
            wavelength = wavelength / 1000.0
            wavelength_label = 'Wavelength (nm)'
        elif wavelength_unit == 'A':
            wavelength = wavelength / 10000.0
            wavelength_label = 'Wavelength (A)'
        else:
            wavelength_label = 'Wavelength (um)'

        x = time
        logger.info(f'Time array after processing: min={np.nanmin(x):.4f}, max={np.nanmax(x):.4f}, shape={x.shape}')
        y = wavelength
        X, Y = np.meshgrid(x, y)

        if z_axis_display == 'flux':
            Z = flux
            logger.info(f'Raw flux range: {np.nanmin(Z):.4e} to {np.nanmax(Z):.4e}')
        else:
            Z = (flux - 1) * 100
            logger.info(f'Variability range: {np.nanmin(Z):.2f}% to {np.nanmax(Z):.2f}%')

        return x, y, X, Y, Z, wavelength_label
    except Exception as e:
        logger.error(f"Error in process_data: {str(e)}")
        raise


def identify_visits(times_hours, gap_threshold=0.5):
    """Segment a time series into visits (gaps > gap_threshold hours).
    Returns list of (start_idx, end_idx) pairs.
    """
    if len(times_hours) == 0:
        return []
    visits = []
    start_idx = 0
    if len(times_hours) == 1:
        return [(0, 1)]
    for i in range(1, len(times_hours)):
        time_gap = times_hours[i] - times_hours[i - 1]
        if time_gap > gap_threshold:
            visits.append((start_idx, i))
            start_idx = i
    visits.append((start_idx, len(times_hours)))
    logger.info(f"Identified {len(visits)} visits with gaps > {gap_threshold} hours")
    for i, (start, end) in enumerate(visits):
        duration = times_hours[end - 1] - times_hours[start] if end > start else 0
        logger.info(
            f"Visit {i + 1}: {end - start} integrations, time range: "
            f"{times_hours[start]:.2f} to {times_hours[end - 1]:.2f} hours "
            f"(duration: {duration:.2f} hours)"
        )
    return visits


def calculate_variability_from_raw_flux(flux_raw_2d):
    """Normalise raw flux per wavelength channel by its median (centered around 1.0)."""
    median_flux_per_wavelength = np.nanmedian(flux_raw_2d, axis=1, keepdims=True)
    median_flux_per_wavelength[median_flux_per_wavelength == 0] = 1.0
    flux_norm_2d = flux_raw_2d / median_flux_per_wavelength
    logger.info(f"Median flux per wavelength shape: {median_flux_per_wavelength.shape}")
    logger.info(f"Normalized flux range: {np.nanmin(flux_norm_2d):.4f} to {np.nanmax(flux_norm_2d):.4f}")
    return flux_norm_2d


def process_mast_files_with_gaps(file_paths, use_interpolation=False,
                                 max_integrations=None, progress_cb=None):
    """Run the full processing pipeline on FITS/H5 files.
    Stages: scan, read, regrid, (optional) interpolate, normalise.
    Returns (common_wl, flux_norm_2d, flux_raw_2d, times_hours, metadata, error_raw_2d).
    """
    # Stage 1: Scan files
    if progress_cb:
        progress_cb(2.0, "Scanning files...", stage="scan")

    scans = []
    for fp in file_paths or []:
        try:
            if fp.endswith('.fits'):
                with fits.open(fp, memmap=True) as hdul:
                    mids = hdul['INT_TIMES'].data['int_mid_MJD_UTC']
                    count = len(mids)
                    first_t = float(mids[0])
            elif fp.endswith('.h5'):
                with h5py.File(fp, 'r') as h:
                    fk = _first_key(h, "calibrated_optspec", "stdspec", "optspec")
                    count = h[fk].shape[0] if fk else 0
                    if 'time' in h:
                        first_t = float(h['time'][0])
                    else:
                        first_t = None
            else:
                continue
            scans.append({"path": fp, "count": int(count), "first_t": first_t})
        except Exception as e:
            logger.warning(f"Error scanning {os.path.basename(fp)}: {e}")
            scans.append({"path": fp, "count": 0, "first_t": None})

    scans = [s for s in scans if s["count"] > 0]
    scans.sort(key=lambda d: (float('inf') if d["first_t"] is None else d["first_t"]))

    total_files = len(scans)
    total_est_integrations = sum(s["count"] for s in scans) if scans else 0

    logger.info(f"Scanned files: {total_files} valid files, {total_est_integrations} total integrations")

    if progress_cb:
        progress_cb(
            10.0,
            f"Found {total_est_integrations} integrations in {total_files} files",
            stage="scan",
            processed_integrations=0,
            total_integrations=total_est_integrations,
        )

    # Stage 2: Read integrations from each file
    all_integrations = []
    all_headers = []
    processed_count = 0
    read_start, read_end = 10.0, 60.0

    def pct_for_read(processed):
        if total_est_integrations == 0:
            return read_start
        frac = processed / total_est_integrations
        return read_start + (read_end - read_start) * min(1.0, max(0.0, frac))

    for i, s in enumerate(scans):
        fp = s["path"]
        file_total = s["count"]

        logger.info(f"Processing file {i + 1}/{total_files}: {os.path.basename(fp)}")
        logger.info(f"   Expected integrations: {file_total}")

        def per_integ_cb(done_local, total_local):
            nonlocal processed_count
            processed_count += 1
            if progress_cb:
                progress_cb(
                    pct_for_read(processed_count),
                    f"Reading {i + 1}/{total_files} - {done_local}/{file_total} integrations",
                    stage="read",
                    processed_integrations=processed_count,
                    total_integrations=total_est_integrations,
                )

        if fp.endswith('.fits'):
            logger.info(f"   Calling load_integrations_from_fits()...")
            integrations, header_info = load_integrations_from_fits(
                fp, per_integ_cb=per_integ_cb, total_in_file=file_total
            )
            logger.info(
                f"   Returned: integrations="
                f"{len(integrations) if integrations else 'None'}, "
                f"header_info={'OK' if header_info else 'None'}"
            )
        elif fp.endswith('.h5'):
            logger.info(f"   Calling load_integrations_from_h5()...")
            integrations, header_info = load_integrations_from_h5(
                fp, per_integ_cb=per_integ_cb, total_in_file=file_total
            )
            logger.info(
                f"   Returned: integrations="
                f"{len(integrations) if integrations else 'None'}, "
                f"header_info={'OK' if header_info else 'None'}"
            )
        else:
            logger.warning(f"   Skipping unknown file type")
            integrations, header_info = (None, None)

        if integrations:
            logger.info(f"   Adding {len(integrations)} integrations")
            all_integrations.extend(integrations)
            all_headers.append(header_info)
        else:
            logger.error(f"   No integrations returned from this file!")

        if progress_cb:
            progress_cb(
                pct_for_read(processed_count),
                f"Loaded {i + 1}/{total_files} files",
                stage="read",
                processed_integrations=processed_count,
                total_integrations=total_est_integrations,
            )

    logger.info(f"Total integrations collected: {len(all_integrations)}")

    if not all_integrations:
        raise ValueError("No valid integrations found in files")

    all_integrations.sort(
        key=lambda x: x['time'] if not hasattr(x['time'], 'mjd') else x['time'].mjd
    )
    original_count = len(all_integrations)

    # Stage 3: Regrid to common wavelength grid
    min_wl = max(np.min(integ['wavelength']) for integ in all_integrations)
    max_wl = min(np.max(integ['wavelength']) for integ in all_integrations)
    n_wave = 1000
    common_wl = np.linspace(min_wl, max_wl, n_wave)

    flux_raw_list = []
    error_raw_list = []
    times = []
    total_integ = len(all_integrations)
    regrid_start, regrid_end = 60.0, 88.0

    def pct_for_regrid(done):
        if total_integ == 0:
            return regrid_start
        frac = done / total_integ
        return regrid_start + (regrid_end - regrid_start) * min(1.0, max(0.0, frac))

    if progress_cb:
        progress_cb(
            regrid_start, "Regridding integrations...", stage="regrid",
            processed_integrations=processed_count,
            total_integrations=total_est_integrations,
        )

    t_start = _time.time()

    for k, integ in enumerate(all_integrations):
        f_interp = interpolate.interp1d(
            integ['wavelength'],
            integ['flux'],
            kind='linear',
            bounds_error=False,
            fill_value=np.nan,
        )
        flux_raw_list.append(f_interp(common_wl))

        if 'error' in integ and integ['error'] is not None:
            e_interp = interpolate.interp1d(
                integ['wavelength'],
                integ['error'],
                kind='linear',
                bounds_error=False,
                fill_value=np.nan,
            )
            error_raw_list.append(e_interp(common_wl))
        else:
            error_raw_list.append(np.full_like(common_wl, np.nan))

        t = integ['time'].mjd if hasattr(integ['time'], 'mjd') else integ['time']
        times.append(t)

        if progress_cb:
            elapsed = _time.time() - t_start
            done_total = processed_count + (k + 1)
            tp = done_total / elapsed if elapsed > 0 else None
            progress_cb(
                pct_for_regrid(k + 1),
                f"Regridding {k + 1}/{total_integ} integrations",
                stage="regrid",
                processed_integrations=done_total,
                total_integrations=total_est_integrations,
                throughput=(tp if tp is not None else None),
            )

    flux_raw_2d = np.array(flux_raw_list).T
    error_raw_2d = np.array(error_raw_list).T
    times_arr = np.array(times)
    t0 = times_arr.min()
    times_hours = (times_arr - t0) * 24.0

    # Stage 4 (optional): Interpolate across time gaps
    if use_interpolation:
        if progress_cb:
            progress_cb(88.0, "Interpolating across time...", stage="interpolate")

        time_grid = np.linspace(times_hours.min(), times_hours.max(), len(times_hours))
        flux_raw_interpolated = np.zeros((flux_raw_2d.shape[0], len(time_grid)))
        error_raw_interpolated = np.zeros((error_raw_2d.shape[0], len(time_grid)))

        for i in range(flux_raw_2d.shape[0]):
            f_raw_interp = interpolate.interp1d(
                times_hours, flux_raw_2d[i, :], kind='linear',
                bounds_error=False, fill_value='extrapolate',
            )
            e_raw_interp = interpolate.interp1d(
                times_hours, error_raw_2d[i, :], kind='linear',
                bounds_error=False, fill_value='extrapolate',
            )
            flux_raw_interpolated[i, :] = f_raw_interp(time_grid)
            error_raw_interpolated[i, :] = e_raw_interp(time_grid)

            if progress_cb and i % 50 == 0:
                progress_cb(
                    88.0 + 4.0 * (i / max(1, flux_raw_2d.shape[0])),
                    "Interpolating across time...",
                    stage="interpolate",
                )

        flux_raw_2d = flux_raw_interpolated
        error_raw_2d = error_raw_interpolated
        times_hours = time_grid

    # Stage 5: Normalise and assemble metadata
    if progress_cb:
        progress_cb(
            92.0, "Computing variability & metadata...", stage="finalize",
            processed_integrations=processed_count + total_integ,
            total_integrations=total_est_integrations,
        )

    flux_norm_2d = calculate_variability_from_raw_flux(flux_raw_2d)

    metadata = {
        'total_integrations': original_count,
        'plotted_integrations': original_count,
        'files_processed': len(file_paths),
        'wavelength_range': f"{common_wl.min():.3f}-{common_wl.max():.3f} um",
        'time_range': f"{times_hours.min():.2f}-{times_hours.max():.2f} hours",
        'targets': list(set(h['target'] for h in all_headers if h)),
        'instruments': list(set(h['instrument'] for h in all_headers if h)),
        'filters': list(set(h['filter'] for h in all_headers if h)),
        'gratings': list(set(h['grating'] for h in all_headers if h)),
        'flux_unit': all_headers[0]['flux_unit'] if all_headers else 'Unknown',
    }

    logger.info(f"PROCESSING COMPLETE:")
    logger.info(f"   Original integrations: {original_count}")
    logger.info(f"   Final time points: {len(times_hours)}")
    logger.info(f"   Wavelength points: {len(common_wl)}")
    logger.info(f"   Flux shape: {flux_norm_2d.shape}")

    return common_wl, flux_norm_2d, flux_raw_2d, times_hours, metadata, error_raw_2d

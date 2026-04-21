"""
File I/O for JWST spectral data (FITS, HDF5, and TXT light curve formats).
"""

import os
import re
import logging

import numpy as np
from astropy.io import fits
from astropy.time import Time
import h5py

logger = logging.getLogger(__name__)


def _first_key(group, *candidates):
    """Return the first key from candidates that exists in group, or None."""
    for k in candidates:
        if k in group:
            return k
    return None


def apply_data_ranges(wavelength, flux, time, wavelength_range=None,
                      time_range=None):
    """Filter wavelength and time axes to user-specified ranges.
    Returns (filtered_wavelength, filtered_flux, filtered_time, range_info).
    """
    range_info = []
    original_wl_range = (wavelength.min(), wavelength.max())
    original_time_range = (time.min(), time.max())

    # Wavelength mask
    if wavelength_range and (wavelength_range[0] is not None
                             or wavelength_range[1] is not None):
        wl_min = (wavelength_range[0]
                  if wavelength_range[0] is not None else original_wl_range[0])
        wl_max = (wavelength_range[1]
                  if wavelength_range[1] is not None else original_wl_range[1])
        wl_min = max(wl_min, original_wl_range[0])
        wl_max = min(wl_max, original_wl_range[1])
        if wl_min >= wl_max:
            logger.warning(
                f"Invalid wavelength range: {wl_min} to {wl_max}. Using full range."
            )
            wl_mask = np.ones(len(wavelength), dtype=bool)
        else:
            wl_mask = (wavelength >= wl_min) & (wavelength <= wl_max)
            range_info.append(f"Wavelength: {wl_min:.3f} - {wl_max:.3f} um")
    else:
        wl_mask = np.ones(len(wavelength), dtype=bool)

    # Time mask
    if time_range and (time_range[0] is not None
                       or time_range[1] is not None):
        time_min = (time_range[0]
                    if time_range[0] is not None else original_time_range[0])
        time_max = (time_range[1]
                    if time_range[1] is not None else original_time_range[1])
        time_min = max(time_min, original_time_range[0])
        time_max = min(time_max, original_time_range[1])
        if time_min >= time_max:
            logger.warning(
                f"Invalid time range: {time_min} to {time_max}. Using full range."
            )
            time_mask = np.ones(len(time), dtype=bool)
        else:
            time_mask = (time >= time_min) & (time <= time_max)
            range_info.append(f"Time: {time_min:.2f} - {time_max:.2f} hours")
    else:
        time_mask = np.ones(len(time), dtype=bool)

    filtered_wavelength = wavelength[wl_mask]
    filtered_flux = flux[wl_mask, :][:, time_mask]
    filtered_time = time[time_mask]

    logger.info(
        f"Wavelength filtering: {len(wavelength)} -> "
        f"{len(filtered_wavelength)} points"
    )
    logger.info(
        f"Time filtering: {len(time)} -> {len(filtered_time)} points"
    )
    return filtered_wavelength, filtered_flux, filtered_time, range_info


def load_lightcurve_txt_folder(folder_path, progress_cb=None):
    """Load pre-binned light curve data from a folder of .txt files.

    Each .txt file represents one wavelength bin with filename pattern
    ``<prefix>_<wl_lo>_<wl_hi>.txt``. Each file has 3 whitespace-separated
    columns (no header): time (hours), normalized flux, flux error.

    Returns the same 6-tuple as process_mast_files_with_gaps:
        (wavelength_1d, flux_norm_2d, flux_raw_2d, time_1d, metadata, error_raw_2d)
    where 2D arrays have shape [n_wavelength, n_time].
    """
    # Find and parse .txt files
    pattern = re.compile(r'(\d+\.?\d*)_(\d+\.?\d*)\.txt$')
    bins = []
    for root, dirs, files in os.walk(folder_path):
        # Skip macOS resource fork directories
        dirs[:] = [d for d in dirs if d != '__MACOSX']
        for fname in files:
            if not fname.lower().endswith('.txt'):
                continue
            # Skip macOS resource fork files and hidden files
            if fname.startswith('._') or fname.startswith('.'):
                continue
            m = pattern.search(fname)
            if not m:
                logger.warning(f"Skipping txt file with unrecognized name: {fname}")
                continue
            wl_lo, wl_hi = float(m.group(1)), float(m.group(2))
            bins.append((wl_lo, wl_hi, os.path.join(root, fname)))

    if not bins:
        raise ValueError("No .txt files with wavelength bin edges found in folder.")

    bins.sort(key=lambda x: x[0])
    n_files = len(bins)
    logger.info(f"Found {n_files} txt light curve files in {folder_path}")

    # Read each file
    wavelengths = []
    flux_list = []
    error_list = []
    ref_time = None

    for i, (wl_lo, wl_hi, fpath) in enumerate(bins):
        data = np.loadtxt(fpath)
        if data.ndim != 2 or data.shape[1] != 3:
            raise ValueError(
                f"{os.path.basename(fpath)}: expected 3 columns, "
                f"got shape {data.shape}"
            )

        time_col = data[:, 0]
        flux_col = data[:, 1]
        error_col = data[:, 2]

        if ref_time is None:
            ref_time = time_col
        elif not np.allclose(time_col, ref_time, atol=1e-6):
            logger.warning(
                f"{os.path.basename(fpath)}: time array differs from first file, "
                f"using first file's time array"
            )

        wavelengths.append((wl_lo + wl_hi) / 2.0)
        flux_list.append(flux_col)
        error_list.append(error_col)

        if progress_cb:
            pct = 10.0 + (i + 1) / n_files * 50.0
            progress_cb(pct, f"Reading {i + 1}/{n_files} txt files…", stage="read")

    # Assemble arrays
    wavelength_1d = np.array(wavelengths)
    time_1d = ref_time
    flux_norm_2d = np.vstack(flux_list)       # [n_wavelength, n_time]
    error_raw_2d = np.vstack(error_list)
    flux_raw_2d = flux_norm_2d.copy()

    # Validation
    if not np.all(np.diff(time_1d) > 0):
        logger.warning("Time array is not monotonically increasing — sorting")
        sort_idx = np.argsort(time_1d)
        time_1d = time_1d[sort_idx]
        flux_norm_2d = flux_norm_2d[:, sort_idx]
        flux_raw_2d = flux_raw_2d[:, sort_idx]
        error_raw_2d = error_raw_2d[:, sort_idx]

    median_flux = np.nanmedian(flux_norm_2d)
    if not (0.9 <= median_flux <= 1.1):
        logger.warning(f"Median flux is {median_flux:.4f} — expected near 1.0")

    if np.any(error_raw_2d < 0):
        logger.warning("Some flux error values are negative")

    metadata = {
        'total_integrations': len(time_1d),
        'plotted_integrations': len(time_1d),
        'files_processed': n_files,
        'wavelength_range': f"{wavelength_1d.min():.3f}-{wavelength_1d.max():.3f} um",
        'time_range': f"{time_1d.min():.2f}-{time_1d.max():.2f} hours",
        'targets': ['Unknown'],
        'instruments': ['Unknown'],
        'filters': ['Unknown'],
        'gratings': ['Unknown'],
        'flux_unit': 'Normalized',
        'data_format': 'lightcurve_txt',
    }

    if progress_cb:
        progress_cb(65.0, "Light curve data assembled", stage="regrid")

    logger.info(
        f"Loaded {n_files} wavelength bins x {len(time_1d)} time steps "
        f"from txt files"
    )

    return wavelength_1d, flux_norm_2d, flux_raw_2d, time_1d, metadata, error_raw_2d


def load_integrations_from_h5(file_path, per_integ_cb=None,
                              total_in_file=None):
    """Load spectral integrations from an HDF5 file.
    Returns (integrations, header_info) or (None, None) on failure.
    """
    with h5py.File(file_path, 'r') as f:
        flux_k = _first_key(f, "calibrated_optspec", "stdspec", "optspec")
        wave_k = _first_key(f, "eureka_wave_1d", "wave_1d", "wavelength", "wave")
        time_k = _first_key(f, "time", "bmjd", "mjd", "bjd", "time_bjd", "time_mjd")
        err_k = _first_key(f, "calibrated_opterr", "stdvar", "error", "flux_error", "sigma")

        if not (flux_k and wave_k and time_k):
            return None, None

        flux = f[flux_k][:]
        wl = f[wave_k][:]
        t = f[time_k][:]

        err = None
        if err_k:
            err_data = f[err_k][:]
            err_key_lower = err_k.lower()
            is_variance = ('var' in err_key_lower and 'err' not in err_key_lower) or err_key_lower.endswith('stdvar')
            err_units = str(f[err_k].attrs.get('units', '')) if hasattr(f[err_k], 'attrs') else ''
            if is_variance or '^2' in err_units or 'squared' in err_units.lower():
                err = np.sqrt(np.abs(err_data))
            else:
                err = err_data

        integrations = []
        nint = flux.shape[0]
        for i in range(flux.shape[0]):
            integrations.append({
                "wavelength": wl,
                "flux": flux[i, :],
                "error": (err[i, :] if err is not None
                          else np.full(flux.shape[1], np.nan)),
                "time": t[i],
            })
            if per_integ_cb:
                per_integ_cb(i + 1, total_in_file or nint)

        header_info = {
            "filename": os.path.basename(file_path),
            "target": "Unknown",
            "instrument": "Unknown",
            "filter": "Unknown",
            "grating": "Unknown",
            "obs_date": "Unknown",
            "exposure_time": "Unknown",
            "flux_unit": "Unknown",
        }
        return integrations, header_info


def load_integrations_from_fits(file_path, per_integ_cb=None,
                                total_in_file=None):
    """Load spectral integrations from a JWST _x1dints.fits file.
    Handles three FITS layout variants. Returns (integrations, header_info)
    or (None, None) on failure.
    """
    try:
        logger.info(f"Opening FITS file: {os.path.basename(file_path)}")
        with fits.open(file_path) as hdul:
            logger.info(f"   Available extensions: {[hdu.name for hdu in hdul]}")

            if 'INT_TIMES' not in hdul:
                logger.error(f"   No INT_TIMES extension found")
                return None, None

            mids = hdul['INT_TIMES'].data['int_mid_MJD_UTC']
            logger.info(f"   Found INT_TIMES with {len(mids)} entries")

            if 'EXTRACT1D' not in hdul:
                logger.error(f"   No EXTRACT1D extension found")
                return None, None

            header_info = {
                'filename': os.path.basename(file_path),
                'target': hdul[0].header.get('TARGNAME', 'Unknown'),
                'instrument': hdul[0].header.get('INSTRUME', 'Unknown'),
                'filter': hdul[0].header.get('FILTER', 'Unknown'),
                'grating': hdul[0].header.get('GRATING', 'Unknown'),
                'obs_date': hdul[0].header.get('DATE-OBS', 'Unknown'),
                'exposure_time': hdul[0].header.get('EXPTIME', 'Unknown'),
            }

            flux_unit = hdul[0].header.get('BUNIT', None)
            if flux_unit is None and 'EXTRACT1D' in hdul:
                flux_unit = hdul['EXTRACT1D'].header.get('BUNIT', None)
            if flux_unit is None:
                for i in range(1, 10):
                    unit = hdul['EXTRACT1D'].header.get(f'TUNIT{i}', None)
                    if (unit and 'flux' in
                            hdul['EXTRACT1D'].header.get(f'TTYPE{i}', '').lower()):
                        flux_unit = unit
                        break
            if flux_unit is None:
                flux_unit = 'MJy'
            header_info['flux_unit'] = flux_unit

            integrations = []
            nint = len(mids)

            # Detect which FITS layout variant we have
            extract_table = hdul['EXTRACT1D'].data
            has_table_format = len(extract_table) > 0
            has_time_in_table = any(
                col in extract_table.columns.names
                for col in ['MJD-AVG', 'MJD-BEG', 'MJD-END']
            )

            # Branch 1: Table with embedded MJD time columns
            if has_table_format and has_time_in_table:
                logger.info(
                    f"   EXTRACT1D format: table with embedded time columns"
                )
                logger.info(
                    f"   Processing {len(extract_table)} integrations from table..."
                )

                time_col = None
                if 'MJD-AVG' in extract_table.columns.names:
                    time_col = 'MJD-AVG'
                elif 'MJD-BEG' in extract_table.columns.names:
                    time_col = 'MJD-BEG'
                elif 'MJD-END' in extract_table.columns.names:
                    time_col = 'MJD-END'

                logger.info(f"   Using time column: {time_col}")

                for idx in range(len(extract_table)):
                    try:
                        row = extract_table[idx]
                        w = row['WAVELENGTH']
                        f = row['FLUX']
                        e = (row['FLUX_ERROR']
                             if 'FLUX_ERROR' in extract_table.columns.names
                             else np.full_like(f, np.nan))
                        mjd = row[time_col]

                        mask = np.isfinite(f) & np.isfinite(w)
                        n_valid = np.sum(mask)

                        if idx < 3:
                            logger.info(
                                f"   Integration {idx + 1}: {n_valid}/{len(f)} "
                                f"valid flux points, time={mjd:.6f}"
                            )

                        if n_valid < 10:
                            logger.warning(
                                f"   Skipping integration {idx + 1}: "
                                f"only {n_valid} valid points"
                            )
                            continue

                        integrations.append({
                            'wavelength': w[mask],
                            'flux': f[mask],
                            'error': e[mask],
                            'time': Time(mjd, format='mjd', scale='utc'),
                        })

                        if per_integ_cb:
                            per_integ_cb(idx + 1, len(extract_table))

                    except Exception as e:
                        logger.error(
                            f"   ERROR processing integration {idx + 1}: {e}",
                            exc_info=True,
                        )
                        continue

            else:
                # Check for individual EXTRACT1D extensions
                has_individual_extensions = False
                try:
                    test_data = hdul['EXTRACT1D', 1].data
                    has_individual_extensions = True
                    logger.info(f"   EXTRACT1D format: individual extensions")
                except (KeyError, IndexError, TypeError):
                    logger.info(f"   EXTRACT1D format: single table")

                # Branch 2: Individual EXTRACT1D extensions (1-indexed)
                if has_individual_extensions:
                    logger.info(
                        f"   Processing {nint} individual EXTRACT1D extensions..."
                    )
                    for idx, mjd in enumerate(mids, start=1):
                        try:
                            data = hdul['EXTRACT1D', idx].data
                            w = data['WAVELENGTH']
                            f = data['FLUX']
                            e = (data['FLUX_ERROR']
                                 if 'FLUX_ERROR' in data.names
                                 else np.full_like(f, np.nan))

                            mask = np.isfinite(f) & np.isfinite(w)
                            n_valid = np.sum(mask)

                            if idx <= 3:
                                logger.info(
                                    f"   Integration {idx} (individual): "
                                    f"{n_valid}/{len(f)} valid points"
                                )

                            if n_valid < 10:
                                logger.warning(
                                    f"   Skipping integration {idx}: "
                                    f"only {n_valid} valid points"
                                )
                                continue

                            integrations.append({
                                'wavelength': w[mask],
                                'flux': f[mask],
                                'error': e[mask],
                                'time': Time(mjd, format='mjd', scale='utc'),
                            })
                            if per_integ_cb:
                                per_integ_cb(idx, nint)

                        except (KeyError, IndexError) as e:
                            logger.error(
                                f"   ERROR processing integration {idx}: {e}",
                                exc_info=True,
                            )
                            continue

                # Branch 3: Single table, times from INT_TIMES
                else:
                    logger.info(
                        f"   Processing {nint} integrations from table "
                        f"(using INT_TIMES for time)..."
                    )

                    for idx, mjd in enumerate(mids):
                        if idx >= len(extract_table):
                            logger.warning(
                                f"   Skipping integration {idx + 1}: "
                                f"table only has {len(extract_table)} rows"
                            )
                            continue

                        try:
                            row = extract_table[idx]
                            w = row['WAVELENGTH']
                            f = row['FLUX']
                            e = (row['FLUX_ERROR']
                                 if 'FLUX_ERROR' in extract_table.columns.names
                                 else np.full_like(f, np.nan))

                            mask = np.isfinite(f) & np.isfinite(w)
                            n_valid = np.sum(mask)

                            if idx < 3:
                                logger.info(
                                    f"   Integration {idx + 1} (fallback): "
                                    f"{n_valid}/{len(f)} valid points"
                                )

                            if n_valid < 10:
                                logger.warning(
                                    f"   Skipping integration {idx + 1}: "
                                    f"only {n_valid} valid points"
                                )
                                continue

                            integrations.append({
                                'wavelength': w[mask],
                                'flux': f[mask],
                                'error': e[mask],
                                'time': Time(mjd, format='mjd', scale='utc'),
                            })
                            if per_integ_cb:
                                per_integ_cb(idx + 1, nint)

                        except Exception as e:
                            logger.error(
                                f"   ERROR processing integration {idx + 1}: {e}",
                                exc_info=True,
                            )
                            continue

            logger.info(
                f"   Loaded {len(integrations)} integrations "
                f"from {len(mids)} INT_TIMES entries"
            )

            if len(integrations) == 0:
                logger.error(f"   No integrations were successfully loaded!")
                return None, None

            return integrations, header_info

    except Exception as e:
        logger.error(
            f"Error reading FITS file {file_path}: {e}", exc_info=True
        )
        return None, None

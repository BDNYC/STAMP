"""
File I/O for JWST spectral data (FITS and HDF5 formats).
"""

import os
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
                f"Invalid wavelength range: {wl_min} to {wl_max}.Using full range."
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
                f"Invalid time range: {time_min} to {time_max}.Using full range."
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
            if err_k.endswith("stdvar"):
                err = np.sqrt(err_data)
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

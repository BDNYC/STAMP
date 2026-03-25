"""Model grid loading and indexing for spectral template fitting.

Loads model atmosphere grids from disk, caches them in memory, and provides
lookup utilities. Grid directories live under SA3D/model_grids/<grid_name>/.
"""

import os
import csv
import logging

import numpy as np

logger = logging.getLogger(__name__)

# Module-level cache: grids load once per server lifetime
_loaded_grids = {}


def _read_model_spectrum(filepath, grid_type=None):
    """Read a single model spectrum file.

    Supports .dat/.txt (numpy loadtxt, two-column: wavelength, flux)
    and .fits (astropy, first table extension or primary HDU).
    Auto-converts Angstroms to microns if max wavelength > 100.

    Returns (wavelengths, flux, flux_unit) where flux_unit is one of:
        "W/m2/m"        — Sonora grids (header: flux_W_m2_m)
        "erg/s/cm2/A"   — PHOENIX / blackbody (header: flux_erg_s_cm2_A)
        "unknown"       — FITS or unrecognized headers
    """
    ext = os.path.splitext(filepath)[1].lower()
    flux_unit = "unknown"

    if ext in ('.dat', '.txt', '.csv'):
        # Parse header comment to detect flux unit
        with open(filepath, 'r') as fh:
            first_line = fh.readline().strip()
        if 'flux_W_m2_m' in first_line:
            flux_unit = "W/m2/m"
        elif 'flux_erg_s_cm2_A' in first_line:
            flux_unit = "erg/s/cm2/A"

        data = np.loadtxt(filepath, dtype=float)
        wavelengths = data[:, 0]
        flux = data[:, 1]
    elif ext == '.fits':
        from astropy.io import fits
        with fits.open(filepath) as hdul:
            if len(hdul) > 1 and hdul[1].data is not None:
                tbl = hdul[1].data
                wl_col = next((c for c in tbl.columns.names
                               if c.lower() in ('wavelength', 'wave', 'lambda', 'wl')), tbl.columns.names[0])
                fl_col = next((c for c in tbl.columns.names
                               if c.lower() in ('flux', 'flam', 'f_lambda', 'fnu')), tbl.columns.names[1])
                wavelengths = np.asarray(tbl[wl_col], dtype=float)
                flux = np.asarray(tbl[fl_col], dtype=float)
            else:
                flux = np.asarray(hdul[0].data, dtype=float)
                wavelengths = np.arange(len(flux), dtype=float)
    else:
        raise ValueError(f"Unsupported file format: {ext}")

    # Auto-convert Angstroms to microns
    if len(wavelengths) > 0 and np.nanmax(wavelengths) > 100:
        wavelengths = wavelengths / 1e4

    # Ensure wavelengths are in ascending order (Sonora files are descending)
    if len(wavelengths) > 1 and wavelengths[0] > wavelengths[-1]:
        sort_idx = np.argsort(wavelengths)
        wavelengths = wavelengths[sort_idx]
        flux = flux[sort_idx]

    return wavelengths, flux, flux_unit


def load_grid_from_directory(grid_dir, grid_type=None):
    """Load a model grid from a directory containing index.csv + spectrum files.

    Expected structure:
        grid_dir/
            index.csv        (columns: filename,Teff,logg,metallicity,...)
            spectra/         (spectrum files referenced by index.csv)

    Returns dict: {wavelengths, spectra (N_models x W), params [{Teff, logg, ...}], n_models}
    Uses module-level cache so grids load once per server lifetime.
    """
    cache_key = os.path.abspath(grid_dir)
    if cache_key in _loaded_grids:
        return _loaded_grids[cache_key]

    index_path = os.path.join(grid_dir, 'index.csv')
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"No index.csv found in {grid_dir}")

    spectra_dir = os.path.join(grid_dir, 'spectra')
    if not os.path.isdir(spectra_dir):
        spectra_dir = grid_dir  # Fall back to grid_dir itself

    params = []
    spectra_list = []
    ref_wavelengths = None
    grid_flux_unit = None

    with open(index_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row.pop('filename', None)
            if not filename:
                continue
            filepath = os.path.join(spectra_dir, filename)
            if not os.path.exists(filepath):
                logger.warning(f"Spectrum file not found: {filepath}")
                continue

            try:
                wl, flux, flux_unit_str = _read_model_spectrum(filepath, grid_type)
            except Exception as exc:
                logger.warning(f"Failed to read {filepath}: {exc}")
                continue

            if grid_flux_unit is None:
                grid_flux_unit = flux_unit_str

            if ref_wavelengths is None:
                ref_wavelengths = wl
            else:
                # Interpolate onto reference grid if wavelengths differ
                if len(wl) != len(ref_wavelengths) or not np.allclose(wl, ref_wavelengths, atol=1e-6):
                    flux = np.interp(ref_wavelengths, wl, flux)

            spectra_list.append(flux)

            # Convert parameter values to float where possible
            param_dict = {}
            for k, v in row.items():
                try:
                    param_dict[k] = float(v)
                except (ValueError, TypeError):
                    param_dict[k] = v
            params.append(param_dict)

    if not spectra_list:
        raise ValueError(f"No valid spectra loaded from {grid_dir}")

    spectra_array = np.array(spectra_list)

    # ------------------------------------------------------------------
    # Convert F_lambda → F_nu (Jy) so grid spectra match JWST observations.
    #
    # F_nu = F_lambda * lambda^2 / c   (SI)
    # 1 Jy = 1e-26 W/m^2/Hz  →  F_nu[Jy] = F_nu[W/m^2/Hz] / 1e-26
    #
    # For erg/s/cm^2/A: multiply by 1e7 to get W/m^2/m first.
    # ------------------------------------------------------------------
    if grid_flux_unit in ("W/m2/m", "erg/s/cm2/A"):
        wl_m = np.asarray(ref_wavelengths) * 1e-6  # microns → metres
        c = 2.998e8  # speed of light, m/s

        if grid_flux_unit == "W/m2/m":
            # F_nu [Jy] = F_lambda [W/m2/m] * lambda_m^2 / (c * 1e-26)
            conv = wl_m ** 2 / (c * 1e-26)
        else:
            # erg/s/cm2/A → W/m2/m: 1e-7 (erg→W) × 1e4 (cm²→m²) × 1e10 (Å→m) = 1e7
            conv = 1e7 * wl_m ** 2 / (c * 1e-26)

        # Broadcast: conv is (W,), spectra_array is (N, W)
        spectra_array = spectra_array * conv[np.newaxis, :]
        logger.info(
            f"Converted grid '{os.path.basename(grid_dir)}' from "
            f"{grid_flux_unit} to Jy ({spectra_array.shape[0]} spectra)"
        )
        grid_flux_unit = "Jy"

    result = {
        "wavelengths": ref_wavelengths.tolist(),
        "spectra": spectra_array,
        "params": params,
        "n_models": len(spectra_list),
        "flux_unit": grid_flux_unit if grid_flux_unit else "unknown",
    }

    _loaded_grids[cache_key] = result
    logger.info(f"Loaded grid '{os.path.basename(grid_dir)}' with {len(spectra_list)} models")
    return result


def list_available_grids(grids_base_dir):
    """Scan model_grids/ directory and return list of available grids.

    Returns list of {name, path, n_models, grid_type} for each grid
    that has a valid index.csv.
    """
    if not os.path.isdir(grids_base_dir):
        return []

    grids = []
    for entry in sorted(os.listdir(grids_base_dir)):
        grid_dir = os.path.join(grids_base_dir, entry)
        if not os.path.isdir(grid_dir):
            continue
        index_path = os.path.join(grid_dir, 'index.csv')
        if not os.path.exists(index_path):
            continue

        # Count models without fully loading them
        try:
            with open(index_path, 'r') as f:
                reader = csv.DictReader(f)
                n_models = sum(1 for _ in reader)
        except Exception:
            n_models = 0

        grids.append({
            "name": entry,
            "path": grid_dir,
            "n_models": n_models,
            "grid_type": entry,
        })

    return grids

#!/usr/bin/env python3
"""Download and convert BT-Settl CIFIST model spectra for SA3D grid fitting.

Downloads the BT_SETTL_full.nc NetCDF archive from Zenodo (record 8015969),
inspects or converts all (Teff, logg) combinations, trims to JWST-relevant
wavelength range, downsamples to 2000 points, and writes two-column .dat files
compatible with the SA3D model_grids loader.

The NetCDF file is ~2.37 GB.  After conversion the script optionally deletes
it (unless --keep-raw is passed).

Parameters covered:
    Teff  : 1200 - 7000 K
    logg  : 2.5 - 5.5
    [M/H] : 0.0 (solar only)
    Models: ~266

Usage:
    python scripts/download_btsettl.py [options]

    # First run: inspect the NetCDF structure
    python scripts/download_btsettl.py --inspect

    # Full conversion
    python scripts/download_btsettl.py

    # Keep the raw .nc file after conversion
    python scripts/download_btsettl.py --keep-raw

Options:
    --inspect     Download .nc, print dataset structure, then exit
    --output-dir  Output grid directory (default: model_grids/bt_settl_cifist)
    --wl-min      Min wavelength in microns (default: 0.5)
    --wl-max      Max wavelength in microns (default: 5.5)
    --n-points    Downsampled wavelength pts (default: 2000)
    --keep-raw    Keep the downloaded .nc file after processing
    --dry-run     Show model count without downloading

Requires: numpy, requests, xarray, netcdf4
Reference: Allard et al. (2012) - BT-Settl CIFIST
Data:      https://zenodo.org/records/8015969
"""

import os
import sys
import argparse
import logging

import numpy as np

# Check for xarray/netcdf4 early so users get a clear error message
try:
    import xarray as xr
except ImportError:
    sys.exit(
        "ERROR: xarray and netcdf4 are required.\n"
        "Install with: pip install xarray netcdf4"
    )

# Import shared grid utilities from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_utils import (
    download_with_progress,
    trim_and_downsample,
    trim_and_downsample_angstrom,
    write_dat_file,
    write_index_csv,
    add_common_args,
    print_summary,
    PROJECT_ROOT,
)

logger = logging.getLogger(__name__)

# Constants

ZENODO_RECORD = "8015969"
NC_FILENAME = "BT_SETTL_full.nc"
NC_URL = (
    f"https://zenodo.org/api/records/{ZENODO_RECORD}"
    f"/files/{NC_FILENAME}/content"
)

GRID_NAME = "bt_settl_cifist"
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "model_grids", GRID_NAME)

# Wavelength output range in Angstroms
WL_MIN_A = 5000.0
WL_MAX_A = 55000.0

# Metallicity is always solar for this grid
METALLICITY = 0.0


# Wavelength unit detection

def _detect_wavelength_unit(wl_array, attrs=None):
    """Auto-detect wavelength unit from range and/or attributes.

    Returns one of: 'angstrom', 'micron', 'nm', 'cm', 'm'.
    Falls back to heuristic based on the numerical range.
    """
    # Check attributes first
    if attrs:
        unit_str = ""
        for key in ("units", "unit", "Unit", "Units"):
            if key in attrs:
                unit_str = str(attrs[key]).strip().lower()
                break

        if unit_str:
            if unit_str in ("angstrom", "angstroms", "a", "aa"):
                return "angstrom"
            if unit_str in ("micron", "microns", "um", "micrometer", "micrometers"):
                return "micron"
            if unit_str in ("nm", "nanometer", "nanometers", "nanometre"):
                return "nm"
            if unit_str in ("cm", "centimeter", "centimeters"):
                return "cm"
            if unit_str in ("m", "meter", "meters", "metre"):
                return "m"

    # Heuristic based on range
    wl_min = float(np.nanmin(wl_array))
    wl_max = float(np.nanmax(wl_array))

    if wl_max > 1e6:
        # Likely Angstroms (e.g., 1000 - 5,500,000 A)
        return "angstrom"
    elif wl_max > 1e3:
        # Likely nanometers (e.g., 100 - 550,000 nm)
        return "nm"
    elif wl_max > 50:
        # Likely microns (e.g., 0.1 - 5500 um) -- but 50+ is suspicious
        # Could also be microns if range is 0.1-55
        return "micron"
    elif wl_max > 0.01:
        # Likely microns
        return "micron"
    elif wl_max > 1e-4:
        # Likely cm
        return "cm"
    else:
        # Likely meters
        return "m"


def _convert_to_angstrom(wl_array, unit):
    """Convert wavelength array to Angstroms."""
    conversions = {
        "angstrom": 1.0,
        "nm": 10.0,
        "micron": 1e4,
        "cm": 1e8,
        "m": 1e10,
    }
    factor = conversions.get(unit)
    if factor is None:
        raise ValueError(f"Unknown wavelength unit: {unit}")
    return wl_array * factor


# Dataset inspection

def _inspect_dataset(nc_path):
    """Open the NetCDF and print its full structure, then exit."""
    print(f"\n{'=' * 70}")
    print(f"Inspecting: {nc_path}")
    print(f"{'=' * 70}\n")

    ds = xr.open_dataset(nc_path)

    print("--- Dataset repr ---")
    print(ds)
    print()

    print("--- Dimensions ---")
    for dim_name, dim_size in ds.dims.items():
        print(f"  {dim_name}: {dim_size}")
    print()

    print("--- Coordinates ---")
    for coord_name, coord in ds.coords.items():
        vals = coord.values
        print(f"  {coord_name}:")
        print(f"    dtype: {vals.dtype}, shape: {vals.shape}")
        if hasattr(coord, "attrs") and coord.attrs:
            print(f"    attrs: {dict(coord.attrs)}")
        if vals.ndim == 1 and len(vals) <= 30:
            print(f"    values: {vals}")
        elif vals.ndim == 1:
            print(f"    first 10: {vals[:10]}")
            print(f"    last  10: {vals[-10:]}")
            print(f"    min={np.nanmin(vals)}, max={np.nanmax(vals)}")
    print()

    print("--- Data variables ---")
    for var_name, var in ds.data_vars.items():
        print(f"  {var_name}:")
        print(f"    dims: {var.dims}, shape: {var.shape}, dtype: {var.dtype}")
        if hasattr(var, "attrs") and var.attrs:
            print(f"    attrs: {dict(var.attrs)}")
        # Print a small sample
        try:
            flat = var.values.ravel()
            finite = flat[np.isfinite(flat)]
            if len(finite) > 0:
                print(f"    sample finite values: min={np.nanmin(finite):.6e}, "
                      f"max={np.nanmax(finite):.6e}, "
                      f"mean={np.nanmean(finite):.6e}")
        except Exception:
            pass
    print()

    print("--- Global attributes ---")
    for attr_name, attr_val in ds.attrs.items():
        print(f"  {attr_name}: {attr_val}")
    print()

    ds.close()
    print("Inspection complete. Use this info to verify coordinate/variable names.")


# Conversion

def _find_dimensions(ds):
    """Identify wavelength, Teff, and logg dimensions/variables in the dataset.

    Returns a dict with keys:
        wl_name    - name of the wavelength coordinate
        teff_name  - name of the Teff coordinate
        logg_name  - name of the logg coordinate
        flux_name  - name of the flux data variable
        wl_unit    - detected wavelength unit string
    """
    # Common aliases for wavelength
    wl_candidates = ["wavelength", "wl", "wave", "lam", "lambda", "Wavelength"]
    # Common aliases for Teff
    teff_candidates = ["Teff", "teff", "T_eff", "temperature", "temp", "T"]
    # Common aliases for logg
    logg_candidates = ["logg", "log_g", "gravity", "grav", "Logg", "log(g)"]

    coord_names = list(ds.coords.keys())
    dim_names = list(ds.dims.keys())
    var_names = list(ds.data_vars.keys())
    all_names = coord_names + dim_names + var_names

    def _find(candidates, all_names):
        # Exact match first
        for c in candidates:
            if c in all_names:
                return c
        # Case-insensitive
        lower_map = {n.lower(): n for n in all_names}
        for c in candidates:
            if c.lower() in lower_map:
                return lower_map[c.lower()]
        return None

    wl_name = _find(wl_candidates, all_names)
    teff_name = _find(teff_candidates, all_names)
    logg_name = _find(logg_candidates, all_names)

    # Fallback: check global attrs for dimension mapping (e.g. BT-Settl uses
    # par1/par2 with attrs['key']=['par1','par2'], attrs['par']=['teff','logg'])
    if (teff_name is None or logg_name is None) and "par" in ds.attrs:
        par_names = ds.attrs.get("par", [])
        key_names = ds.attrs.get("key", [])
        if hasattr(par_names, "tolist"):
            par_names = par_names.tolist()
        if hasattr(key_names, "tolist"):
            key_names = key_names.tolist()
        for dim_key, param in zip(key_names, par_names):
            p = param.lower().strip()
            if p in ("teff", "t_eff", "temperature") and teff_name is None:
                if dim_key in all_names:
                    teff_name = dim_key
                    print(f"    Mapped {dim_key} -> Teff (via attrs)")
            elif p in ("logg", "log_g", "gravity") and logg_name is None:
                if dim_key in all_names:
                    logg_name = dim_key
                    print(f"    Mapped {dim_key} -> logg (via attrs)")

    # Flux variable is typically the main data variable
    flux_name = None
    flux_candidates = ["flux", "flam", "sed", "spectra", "spectrum", "Flux"]
    flux_name = _find(flux_candidates, var_names)
    if flux_name is None and len(var_names) == 1:
        flux_name = var_names[0]
    elif flux_name is None:
        # Pick the variable with the most dimensions
        best = None
        best_ndim = 0
        for vn in var_names:
            ndim = ds[vn].ndim
            if ndim > best_ndim:
                best_ndim = ndim
                best = vn
        flux_name = best

    # Detect wavelength unit
    wl_unit = None
    if wl_name is not None:
        wl_coord = ds[wl_name] if wl_name in ds.coords else ds[wl_name]
        wl_attrs = dict(wl_coord.attrs) if hasattr(wl_coord, "attrs") else {}
        wl_unit = _detect_wavelength_unit(wl_coord.values, wl_attrs)

    result = {
        "wl_name": wl_name,
        "teff_name": teff_name,
        "logg_name": logg_name,
        "flux_name": flux_name,
        "wl_unit": wl_unit,
    }

    # Report findings
    print("  Detected dataset structure:")
    for k, v in result.items():
        print(f"    {k}: {v}")

    # Validate
    missing = [k for k, v in result.items() if v is None]
    if missing:
        print(f"\n  WARNING: Could not identify: {missing}")
        print("  Run with --inspect to examine the dataset manually.")
        print("  You may need to update _find_dimensions() for this dataset.\n")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Download and convert BT-Settl CIFIST spectra for SA3D"
    )
    add_common_args(parser)

    parser.add_argument(
        "--inspect", action="store_true",
        help="Download .nc file, print dataset structure, then exit"
    )

    # Override default output-dir from add_common_args
    parser.set_defaults(output_dir=DEFAULT_OUTPUT_DIR)

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    cache_dir = os.path.join(output_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)

    nc_path = os.path.join(cache_dir, NC_FILENAME)

    # ------------------------------------------------------------------
    # Step 1: Download the NetCDF file
    # ------------------------------------------------------------------
    print(f"\n--- BT-Settl CIFIST Grid Downloader ---")
    print(f"Source: https://zenodo.org/records/{ZENODO_RECORD}")
    print(f"File:   {NC_FILENAME} (~2.37 GB)\n")

    if not args.dry_run:
        import requests
        session = requests.Session()

        ok = download_with_progress(
            NC_URL, nc_path,
            session=session,
            label=NC_FILENAME,
            timeout=1800,  # 30 min timeout for large file
        )
        if not ok:
            print("ERROR: Could not download NetCDF file. Aborting.")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Inspect mode
    # ------------------------------------------------------------------
    if args.inspect:
        _inspect_dataset(nc_path)
        return

    # ------------------------------------------------------------------
    # Step 3: Dry-run mode
    # ------------------------------------------------------------------
    if args.dry_run:
        print("Dry run: would download and convert BT-Settl CIFIST grid")
        print(f"  Teff range: 1200 - 7000 K")
        print(f"  logg range: 2.5 - 5.5")
        print(f"  Metallicity: {METALLICITY} (solar)")
        print(f"  Expected models: ~266")
        print(f"  Output dir: {output_dir}")
        print(f"  Wavelength: {args.wl_min} - {args.wl_max} um "
              f"({args.wl_min * 1e4:.0f} - {args.wl_max * 1e4:.0f} A)")
        print(f"  Points per spectrum: {args.n_points}")
        return

    # ------------------------------------------------------------------
    # Step 4: Open dataset and determine structure
    # ------------------------------------------------------------------
    print(f"\nOpening {nc_path}...")
    ds = xr.open_dataset(nc_path)

    dims = _find_dimensions(ds)
    wl_name = dims["wl_name"]
    teff_name = dims["teff_name"]
    logg_name = dims["logg_name"]
    flux_name = dims["flux_name"]
    wl_unit = dims["wl_unit"]

    # Validate that we found everything
    if any(v is None for v in [wl_name, teff_name, logg_name, flux_name, wl_unit]):
        print("\nERROR: Could not auto-detect all dataset dimensions.")
        print("Run with --inspect to examine the dataset structure.")
        ds.close()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 5: Get coordinate arrays
    # ------------------------------------------------------------------
    wl_raw = ds[wl_name].values
    teff_values = ds[teff_name].values
    logg_values = ds[logg_name].values

    # Convert wavelength to Angstroms
    wl_angstrom = _convert_to_angstrom(wl_raw, wl_unit)

    print(f"\n  Wavelength: {len(wl_raw)} points, unit={wl_unit}")
    print(f"    range: {np.nanmin(wl_raw):.4f} - {np.nanmax(wl_raw):.4f} {wl_unit}")
    print(f"    in Angstroms: {np.nanmin(wl_angstrom):.1f} - {np.nanmax(wl_angstrom):.1f} A")
    print(f"  Teff: {len(teff_values)} values, "
          f"{np.nanmin(teff_values):.0f} - {np.nanmax(teff_values):.0f} K")
    print(f"  logg: {len(logg_values)} values, {logg_values}")

    # Detect flux unit from attributes
    flux_var = ds[flux_name]
    flux_attrs = dict(flux_var.attrs) if hasattr(flux_var, "attrs") else {}
    flux_unit_tag = "flux_erg_s_cm2_A"  # default assumption
    for key in ("units", "unit", "Unit", "Units"):
        if key in flux_attrs:
            raw_unit = str(flux_attrs[key]).strip()
            print(f"  Flux unit from attrs: {raw_unit}")
            if "W" in raw_unit and "m" in raw_unit:
                flux_unit_tag = "flux_W_m2_m"
            break

    # ------------------------------------------------------------------
    # Step 6: Convert each (Teff, logg) combination
    # ------------------------------------------------------------------
    spectra_dir = os.path.join(output_dir, "spectra")
    os.makedirs(spectra_dir, exist_ok=True)

    # Compute target range in Angstroms from args (which are in microns)
    target_wl_min_a = args.wl_min * 1e4  # 5000 A
    target_wl_max_a = args.wl_max * 1e4  # 55000 A

    total_models = len(teff_values) * len(logg_values)
    print(f"\n--- Converting {total_models} model spectra ---")
    print(f"  Target range: {target_wl_min_a:.0f} - {target_wl_max_a:.0f} A")
    print(f"  Target points: {args.n_points}\n")

    rows = []
    n_ok = 0
    n_skip = 0
    count = 0

    for teff in teff_values:
        for logg in logg_values:
            count += 1
            teff_val = float(teff)
            logg_val = float(logg)

            dat_filename = f"btsettl_T{int(teff_val)}_g{logg_val:.1f}.dat"
            dat_path = os.path.join(spectra_dir, dat_filename)
            label = (f"[{count}/{total_models}] "
                     f"Teff={int(teff_val)} logg={logg_val:.1f}")

            # Skip if already converted
            if os.path.exists(dat_path):
                print(f"{label} -- already converted")
                rows.append({
                    "filename": dat_filename,
                    "Teff": int(teff_val),
                    "logg": logg_val,
                    "metallicity": METALLICITY,
                })
                n_ok += 1
                continue

            try:
                # Extract flux for this (Teff, logg) combination
                # Use .sel() with method='nearest' for robustness
                spectrum = flux_var.sel(
                    **{teff_name: teff, logg_name: logg}
                )
                flux_data = spectrum.values

                # Handle multi-dimensional flux (squeeze extra dims)
                if flux_data.ndim > 1:
                    # Find the wavelength axis and squeeze others
                    flux_data = flux_data.squeeze()

                if flux_data.ndim != 1:
                    print(f"{label} -- SKIP: unexpected flux shape {flux_data.shape}")
                    n_skip += 1
                    continue

                # Check for all-NaN or all-zero spectra
                finite_mask = np.isfinite(flux_data)
                if not np.any(finite_mask):
                    print(f"{label} -- SKIP: all NaN")
                    n_skip += 1
                    continue

                if np.all(flux_data[finite_mask] == 0):
                    print(f"{label} -- SKIP: all zeros")
                    n_skip += 1
                    continue

                # Replace NaN with 0 for interpolation
                flux_clean = np.where(finite_mask, flux_data, 0.0)

                # Trim and downsample (already in Angstroms)
                wl_out, fl_out = trim_and_downsample_angstrom(
                    wl_angstrom, flux_clean,
                    wl_min_a=target_wl_min_a,
                    wl_max_a=target_wl_max_a,
                    n_pts=args.n_points,
                )

                if len(wl_out) == 0:
                    print(f"{label} -- SKIP: no data in wavelength range")
                    n_skip += 1
                    continue

                # Write .dat file
                write_dat_file(dat_path, wl_out, fl_out, unit_tag=flux_unit_tag)

                rows.append({
                    "filename": dat_filename,
                    "Teff": int(teff_val),
                    "logg": logg_val,
                    "metallicity": METALLICITY,
                })
                n_ok += 1

                if count <= 5 or count % 50 == 0:
                    print(f"{label} -- OK ({len(wl_out)} pts)")

            except Exception as exc:
                logger.warning(f"{label} -- FAILED: {exc}")
                n_skip += 1
                continue

    ds.close()

    # ------------------------------------------------------------------
    # Step 7: Write index.csv
    # ------------------------------------------------------------------
    index_path = os.path.join(output_dir, "index.csv")
    write_index_csv(
        index_path,
        rows,
        fieldnames=["filename", "Teff", "logg", "metallicity"],
    )

    # ------------------------------------------------------------------
    # Step 8: Print summary
    # ------------------------------------------------------------------
    print_summary(output_dir, n_ok, n_skip)

    # ------------------------------------------------------------------
    # Step 9: Optionally delete the .nc file
    # ------------------------------------------------------------------
    if not args.keep_raw and os.path.exists(nc_path) and n_ok > 0:
        nc_size = os.path.getsize(nc_path) / 1e9
        print(f"\nRemoving {NC_FILENAME} ({nc_size:.2f} GB) to save disk space...")
        os.remove(nc_path)
        # Remove cache dir if empty
        try:
            os.rmdir(cache_dir)
        except OSError:
            pass
    elif args.keep_raw:
        print(f"\nKept raw file: {nc_path}")
    elif n_ok == 0:
        print(f"\nKept {NC_FILENAME} (no models converted -- re-run to retry)")


if __name__ == "__main__":
    main()

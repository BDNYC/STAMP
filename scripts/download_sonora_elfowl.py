#!/usr/bin/env python3
"""Download and convert Sonora Elf Owl model spectra for SA3D grid fitting.

Downloads spectra from Zenodo v2 (corrected CO2, April 2025), processes
piecewise through tar.gz chunks containing NetCDF (.nc) files, trims to
JWST-relevant wavelength range, downsamples, and writes two-column .dat
files compatible with the SA3D model_grids loader.

Three sub-grids (spectral types) are available:
    Y   Y-type dwarfs (cooler), Zenodo record 15150865
    T   T-type dwarfs (mid),    Zenodo record 15150874
    L   L-type dwarfs (warmer), Zenodo record 15150881

Each sub-grid consists of 4 tar.gz chunks (~9.5 GB each, ~38 GB total).
Chunks are named like teff_{min}_{max}.tar.gz and contain NetCDF files.

Parameters per sub-grid:
    Teff:       Varies by sub-grid (Y: cooler, T: mid, L: warmer)
    logg:       3.25, 3.5, 3.75, 4.0, 4.25, 4.5, 4.75, 5.0, 5.25, 5.5
    [M/H]:      -1.0, -0.5, 0.0, +0.5, +0.7, +1.0
    C/O:        4 values (e.g., 0.5, 0.75, 1.0, 1.5 x solar)
    log(Kzz):   5 values (e.g., 2, 4, 6, 7, 8)
    Models:     ~14,400 per sub-grid, ~43,200 total

CRITICAL: Piecewise processing to fit in limited disk space (~27 GB free).
Each chunk is downloaded, extracted, processed, then deleted before the next.
Peak disk usage: ~20 GB (one ~9.5 GB tar.gz + extracted .nc files).

Usage:
    python scripts/download_sonora_elfowl.py --subgrid Y [options]
    python scripts/download_sonora_elfowl.py --subgrid T --inspect
    python scripts/download_sonora_elfowl.py --subgrid L --dry-run

Options:
    --subgrid     REQUIRED: Y, T, or L (one at a time for disk safety)
    --inspect     Download first chunk, open one .nc, print structure, exit
    --output-dir  Output grid directory (default: model_grids/sonora_elfowl_{Y|T|L})
    --wl-min      Min wavelength in microns (default: 0.5)
    --wl-max      Max wavelength in microns (default: 5.5)
    --n-points    Downsampled wavelength points (default: 2000)
    --keep-raw    Keep downloaded tar.gz chunks after processing
    --dry-run     List chunks and estimated model count, exit

Requires: numpy, requests, xarray, netcdf4
Reference: Mukherjee et al. (2024) — Sonora Elf Owl
Data:      https://zenodo.org/records/15150865 (Y)
           https://zenodo.org/records/15150874 (T)
           https://zenodo.org/records/15150881 (L)
"""

import os
import re
import sys
import json
import argparse
import logging
import tarfile
import tempfile
import glob as globmod

import numpy as np

# ---------------------------------------------------------------------------
# Dependency check: xarray + netcdf4 required for .nc files
# ---------------------------------------------------------------------------
try:
    import xarray as xr
except ImportError:
    sys.exit(
        "ERROR: xarray and netcdf4 required. Install: pip install xarray netcdf4"
    )

# ---------------------------------------------------------------------------
# Import shared grid utilities from the same scripts/ directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_utils import (download_with_progress, trim_and_downsample,
                        write_dat_file, write_index_csv, add_common_args,
                        print_summary, PROJECT_ROOT)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Zenodo record IDs — one per sub-grid (spectral type)
# ---------------------------------------------------------------------------
ZENODO_RECORDS = {
    "Y": "15150865",
    "T": "15150874",
    "L": "15150881",
}

ZENODO_API_BASE = "https://zenodo.org/api/records"


# ---------------------------------------------------------------------------
# Zenodo API helpers
# ---------------------------------------------------------------------------

def fetch_chunk_info(record_id, session=None):
    """Query Zenodo API for chunk filenames and download URLs.

    Returns a list of dicts, each with keys:
        key      — filename (e.g., "teff_200_400.tar.gz")
        size     — file size in bytes
        url      — direct download URL
    Sorted by filename for deterministic ordering.
    """
    import requests

    sess = session or requests.Session()
    api_url = f"{ZENODO_API_BASE}/{record_id}"

    print(f"  Querying Zenodo API: {api_url}")
    resp = sess.get(api_url, timeout=60)
    resp.raise_for_status()

    record = resp.json()
    files = record.get("files", [])

    chunks = []
    for f in files:
        key = f.get("key", "")
        if key.endswith(".tar.gz"):
            chunks.append({
                "key": key,
                "size": f.get("size", 0),
                "url": f.get("links", {}).get("self", ""),
            })

    # Sort by filename so processing order is deterministic
    chunks.sort(key=lambda c: c["key"])
    return chunks


# ---------------------------------------------------------------------------
# NetCDF parsing helpers
# ---------------------------------------------------------------------------

# Regex to extract parameters from .nc filenames.
# Expected patterns like:
#   teff_500_logg_4.0_mh_0.0_co_1.0_kzz_4.nc
#   or similar with varying separators/formats.
# We try multiple patterns to be flexible.
_NC_PATTERNS = [
    # Pattern: teff_XXX_logg_X.X_mh_X.X_co_X.X_kzz_X
    re.compile(
        r"teff[_-]?(\d+(?:\.\d+)?)"
        r".*logg[_-]?(\d+(?:\.\d+)?)"
        r".*m(?:h|eta(?:llicity)?)[_-]?([+-]?\d+(?:\.\d+)?)"
        r".*c(?:/)?o[_-]?(\d+(?:\.\d+)?)"
        r".*k(?:zz)[_-]?(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    # Pattern: T{teff}_g{logg}_m{metal}_co{co}_kzz{kzz}
    re.compile(
        r"[tT](\d+(?:\.\d+)?)"
        r".*[gG](\d+(?:\.\d+)?)"
        r".*[mM]([+-]?\d+(?:\.\d+)?)"
        r".*co(\d+(?:\.\d+)?)"
        r".*kzz(\d+(?:\.\d+)?)",
    ),
]


def _parse_nc_filename(path):
    """Try to extract (teff, logg, metallicity, c_o_ratio, log_kzz) from
    a NetCDF filename.  Returns a dict or None if no pattern matches."""
    basename = os.path.basename(path)

    for pat in _NC_PATTERNS:
        m = pat.search(basename)
        if m:
            return {
                "teff": float(m.group(1)),
                "logg": float(m.group(2)),
                "metal": float(m.group(3)),
                "co": float(m.group(4)),
                "kzz": float(m.group(5)),
            }

    return None


def _extract_spectrum_from_nc(nc_path):
    """Open a single .nc file with xarray and extract wavelength + flux.

    Returns (wavelength_microns, flux_erg_s_cm2_cm) as numpy arrays,
    or (None, None) if extraction fails.

    The NetCDF structure may vary.  We look for:
      - A wavelength variable/coordinate (in microns)
      - A flux variable (in erg/s/cm^2/cm)
    Common names: 'wavelength', 'wl', 'wave', 'lambda' for wavelength;
                  'flux', 'flam', 'spectrum' for flux.
    """
    try:
        ds = xr.open_dataset(nc_path)
    except Exception as exc:
        logger.warning(f"  Cannot open {nc_path}: {exc}")
        return None, None

    # --- Find wavelength ---
    wl = None
    wl_candidates = ["wavelength", "wl", "wave", "lambda", "wlen",
                     "Wavelength", "WAVELENGTH"]
    # Check coordinates first, then data variables
    for name in wl_candidates:
        if name in ds.coords:
            wl = ds.coords[name].values
            break
        if name in ds.data_vars:
            wl = ds[name].values
            break

    # If not found by name, try the first 1-D coordinate
    if wl is None:
        for coord_name in ds.coords:
            coord = ds.coords[coord_name]
            if coord.ndim == 1 and len(coord) > 100:
                wl = coord.values
                break

    # --- Find flux ---
    flux = None
    flux_candidates = ["flux", "flam", "spectrum", "Flux", "FLUX",
                       "thermal_spectrum", "spectra", "fnu"]
    for name in flux_candidates:
        if name in ds.data_vars:
            var = ds[name]
            # If multi-dimensional, we want the 1-D spectrum
            if var.ndim == 1:
                flux = var.values
                break
            elif var.ndim > 1:
                # Take the first spectrum if it's a collection
                flux = var.values.flatten()
                if len(flux) != len(wl) if wl is not None else True:
                    flux = var.values[0] if var.shape[0] < var.shape[-1] else var.values[:, 0]
                break

    # If not found by name, try the first data variable with matching shape
    if flux is None and wl is not None:
        for var_name in ds.data_vars:
            var = ds[var_name]
            if var.ndim == 1 and len(var) == len(wl):
                flux = var.values
                break

    ds.close()

    if wl is None or flux is None:
        return None, None

    # Ensure 1-D arrays
    wl = np.asarray(wl).flatten()
    flux = np.asarray(flux).flatten()

    # Ensure matching lengths
    if len(wl) != len(flux):
        min_len = min(len(wl), len(flux))
        wl = wl[:min_len]
        flux = flux[:min_len]

    # Ensure ascending wavelength order
    if len(wl) > 1 and wl[0] > wl[-1]:
        sort_idx = np.argsort(wl)
        wl = wl[sort_idx]
        flux = flux[sort_idx]

    return wl, flux


def _inspect_nc(nc_path):
    """Print detailed xarray repr for a NetCDF file (for --inspect mode)."""
    ds = xr.open_dataset(nc_path)
    print(f"\n{'=' * 70}")
    print(f"File: {os.path.basename(nc_path)}")
    print(f"{'=' * 70}")
    print(ds)
    print(f"\nDimensions: {dict(ds.dims)}")
    print(f"\nCoordinates:")
    for name, coord in ds.coords.items():
        print(f"  {name}: shape={coord.shape}, dtype={coord.dtype}")
        if coord.ndim == 1 and len(coord) <= 10:
            print(f"    values: {coord.values}")
        elif coord.ndim == 1:
            print(f"    range: [{coord.values[0]}, ..., {coord.values[-1]}] "
                  f"({len(coord)} points)")
    print(f"\nData variables:")
    for name, var in ds.data_vars.items():
        print(f"  {name}: shape={var.shape}, dtype={var.dtype}")
        if var.attrs:
            print(f"    attrs: {dict(var.attrs)}")
    print(f"\nGlobal attributes:")
    for key, val in ds.attrs.items():
        print(f"  {key}: {val}")
    ds.close()


# ---------------------------------------------------------------------------
# .dat filename builder
# ---------------------------------------------------------------------------

def _dat_filename(subgrid, teff, logg, metal, co, kzz):
    """Build the standardised .dat filename for an Elf Owl model."""
    return (f"elfowl_{subgrid}_T{int(teff)}_g{logg:.2f}"
            f"_m{metal:+.1f}_co{co}_kzz{kzz}.dat")


# ---------------------------------------------------------------------------
# Chunk processing (piecewise for disk safety)
# ---------------------------------------------------------------------------

def _process_chunk(chunk_info, subgrid, output_dir, args, session,
                   chunk_idx, total_chunks):
    """Process a single tar.gz chunk: download, extract, convert, cleanup.

    Steps:
        1. Download chunk tar.gz to cache_dir
        2. Extract .nc files to a temporary directory
        3. For each .nc: open with xarray, extract spectrum, convert, write .dat
        4. Delete extracted .nc files
        5. Delete chunk tar.gz (unless --keep-raw)

    Returns list of index row dicts for successfully converted models.
    """
    cache_dir = os.path.join(output_dir, ".cache")
    spectra_dir = os.path.join(output_dir, "spectra")
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(spectra_dir, exist_ok=True)

    chunk_key = chunk_info["key"]
    chunk_url = chunk_info["url"]
    chunk_size = chunk_info["size"]
    tar_path = os.path.join(cache_dir, chunk_key)

    print(f"\n{'=' * 60}")
    print(f"  Chunk {chunk_idx}/{total_chunks}: {chunk_key} "
          f"({chunk_size / 1e9:.1f} GB)")
    print(f"{'=' * 60}")

    # Step 1: Download
    if not download_with_progress(chunk_url, tar_path, session=session,
                                  label=chunk_key, timeout=3600):
        print(f"  ERROR: Could not download {chunk_key}. Skipping.")
        return []

    # Step 2: Extract .nc files to temp directory
    extract_dir = os.path.join(cache_dir, f"extract_{chunk_key.replace('.tar.gz', '')}")
    os.makedirs(extract_dir, exist_ok=True)

    print(f"  Extracting .nc files from {chunk_key}...")
    nc_files = []
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            members = [m for m in tf.getmembers()
                       if m.isfile() and m.name.endswith(".nc")]
            print(f"  Found {len(members)} .nc files in archive")

            for member in members:
                # Extract preserving just the basename to avoid deep paths
                member.name = os.path.basename(member.name)
                tf.extract(member, path=extract_dir)
                nc_files.append(os.path.join(extract_dir, member.name))
    except Exception as exc:
        print(f"  ERROR extracting {chunk_key}: {exc}")
        # Clean up partial extraction
        _cleanup_directory(extract_dir)
        if not args.keep_raw:
            _safe_remove(tar_path)
        return []

    print(f"  Extracted {len(nc_files)} .nc files")

    # Step 3: Process each .nc file
    rows = []
    n_ok = 0
    n_skip = 0
    total_nc = len(nc_files)

    for i, nc_path in enumerate(sorted(nc_files), 1):
        basename = os.path.basename(nc_path)

        # Try to parse parameters from filename
        parsed = _parse_nc_filename(basename)

        step_label = f"  [{i}/{total_nc}]"

        if parsed is None:
            # Try to extract parameters from the NetCDF attributes instead
            try:
                ds = xr.open_dataset(nc_path)
                attrs = ds.attrs
                parsed = {
                    "teff": float(attrs.get("Teff", attrs.get("teff", 0))),
                    "logg": float(attrs.get("logg", attrs.get("log_g", 0))),
                    "metal": float(attrs.get("metallicity",
                                             attrs.get("M_H",
                                             attrs.get("[M/H]", 0)))),
                    "co": float(attrs.get("C_O", attrs.get("c_o_ratio",
                                attrs.get("C/O", 0)))),
                    "kzz": float(attrs.get("log_Kzz", attrs.get("logKzz",
                                 attrs.get("Kzz", 0)))),
                }
                ds.close()

                # Validate we got real values
                if parsed["teff"] == 0:
                    logger.warning(f"{step_label} Cannot parse parameters "
                                   f"from {basename} -- skipping")
                    n_skip += 1
                    continue
            except Exception:
                logger.warning(f"{step_label} Cannot parse parameters "
                               f"from {basename} -- skipping")
                n_skip += 1
                continue

        teff = parsed["teff"]
        logg = parsed["logg"]
        metal = parsed["metal"]
        co = parsed["co"]
        kzz = parsed["kzz"]

        dat_fname = _dat_filename(subgrid, teff, logg, metal, co, kzz)
        dat_path = os.path.join(spectra_dir, dat_fname)

        param_str = (f"Teff={int(teff)} logg={logg:.2f} [M/H]={metal:+.1f} "
                     f"C/O={co} Kzz={kzz}")

        # Skip if already converted
        if os.path.exists(dat_path):
            print(f"{step_label} {param_str} -- already converted")
            rows.append({
                "filename": dat_fname,
                "Teff": int(teff),
                "logg": logg,
                "metallicity": metal,
                "c_o_ratio": co,
                "log_kzz": kzz,
            })
            n_ok += 1
            continue

        # Extract spectrum from NetCDF
        try:
            wl_micron, flux_cgs = _extract_spectrum_from_nc(nc_path)

            if wl_micron is None or flux_cgs is None:
                logger.warning(f"{step_label} {param_str} -- "
                               f"no spectrum data in {basename}")
                n_skip += 1
                continue

            if len(wl_micron) == 0:
                logger.warning(f"{step_label} {param_str} -- "
                               f"empty spectrum in {basename}")
                n_skip += 1
                continue

            # Convert flux: erg/s/cm2/cm -> erg/s/cm2/A (divide by 1e8)
            flux_angstrom = flux_cgs / 1e8

            # Trim to range and downsample
            # trim_and_downsample takes microns, returns Angstroms
            wl_out, fl_out = trim_and_downsample(
                wl_micron, flux_angstrom,
                wl_min=args.wl_min,
                wl_max=args.wl_max,
                n_pts=args.n_points,
            )

            if len(wl_out) == 0:
                logger.warning(f"{step_label} {param_str} -- "
                               f"no data in wavelength range")
                n_skip += 1
                continue

            # Write .dat file
            write_dat_file(dat_path, wl_out, fl_out,
                           unit_tag="flux_erg_s_cm2_A")

            rows.append({
                "filename": dat_fname,
                "Teff": int(teff),
                "logg": logg,
                "metallicity": metal,
                "c_o_ratio": co,
                "log_kzz": kzz,
            })
            n_ok += 1

            if i % 100 == 0 or i == total_nc:
                print(f"{step_label} {param_str} -- OK "
                      f"({n_ok} converted, {n_skip} skipped so far)")
            elif i <= 5:
                print(f"{step_label} {param_str} -- OK")

        except Exception as exc:
            logger.warning(f"{step_label} {param_str} -- FAILED: {exc}")
            n_skip += 1
            continue

    print(f"\n  Chunk {chunk_key}: {n_ok} converted, {n_skip} skipped")

    # Step 4: Delete extracted .nc files
    print(f"  Cleaning up extracted .nc files...")
    _cleanup_directory(extract_dir)

    # Step 5: Delete chunk tar.gz (unless --keep-raw)
    if not args.keep_raw:
        print(f"  Removing {chunk_key} to save disk space...")
        _safe_remove(tar_path)

    return rows


def _safe_remove(path):
    """Remove a file, ignoring errors."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning(f"  Could not remove {path}: {exc}")


def _cleanup_directory(dir_path):
    """Remove a directory and all its contents."""
    import shutil
    try:
        if os.path.isdir(dir_path):
            shutil.rmtree(dir_path)
    except OSError as exc:
        logger.warning(f"  Could not clean up {dir_path}: {exc}")


# ---------------------------------------------------------------------------
# Inspect mode
# ---------------------------------------------------------------------------

def _run_inspect(subgrid, session):
    """Download first chunk, extract one .nc, print structure, exit."""
    record_id = ZENODO_RECORDS[subgrid]

    print(f"\nSonora Elf Owl -- Inspect mode (sub-grid {subgrid})")
    print(f"Zenodo record: {record_id}")

    # Fetch chunk info
    chunks = fetch_chunk_info(record_id, session)
    if not chunks:
        print("ERROR: No tar.gz chunks found in Zenodo record.")
        sys.exit(1)

    print(f"\nChunks in record:")
    for c in chunks:
        print(f"  {c['key']}  ({c['size'] / 1e9:.1f} GB)  {c['url']}")

    # Download first chunk to a temp location
    chunk = chunks[0]
    tmp_dir = tempfile.mkdtemp(prefix="elfowl_inspect_")
    tar_path = os.path.join(tmp_dir, chunk["key"])

    print(f"\nDownloading first chunk: {chunk['key']}...")
    if not download_with_progress(chunk["url"], tar_path, session=session,
                                  label=chunk["key"], timeout=3600):
        print("ERROR: Could not download chunk.")
        _cleanup_directory(tmp_dir)
        sys.exit(1)

    # List tar.gz contents and extract first .nc
    print(f"\nListing contents of {chunk['key']}:")
    first_nc = None
    nc_count = 0
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            members = tf.getmembers()
            print(f"  Total entries: {len(members)}")
            print(f"  First 20 entries:")
            for m in members[:20]:
                tag = " [NC]" if m.name.endswith(".nc") else ""
                print(f"    {m.name} ({m.size / 1e6:.1f} MB){tag}")

            nc_members = [m for m in members
                          if m.isfile() and m.name.endswith(".nc")]
            nc_count = len(nc_members)
            print(f"\n  Total .nc files: {nc_count}")

            if nc_members:
                # Extract just the first .nc file
                first_member = nc_members[0]
                first_member_basename = os.path.basename(first_member.name)
                first_member.name = first_member_basename
                tf.extract(first_member, path=tmp_dir)
                first_nc = os.path.join(tmp_dir, first_member_basename)

    except Exception as exc:
        print(f"  ERROR reading tar.gz: {exc}")
        _cleanup_directory(tmp_dir)
        sys.exit(1)

    if first_nc and os.path.exists(first_nc):
        print(f"\nNetCDF file inspection:")
        _inspect_nc(first_nc)

        # Also try parsing the filename
        parsed = _parse_nc_filename(first_nc)
        if parsed:
            print(f"\nParsed from filename: {parsed}")
        else:
            print(f"\nCould not parse parameters from filename: "
                  f"{os.path.basename(first_nc)}")

        # Try extracting spectrum
        wl, flux = _extract_spectrum_from_nc(first_nc)
        if wl is not None:
            print(f"\nSpectrum extraction:")
            print(f"  Wavelength: {len(wl)} points, "
                  f"range [{wl[0]:.4f}, {wl[-1]:.4f}] microns")
            print(f"  Flux: range [{flux.min():.4e}, {flux.max():.4e}] "
                  f"erg/s/cm2/cm")
        else:
            print(f"\nWARNING: Could not extract spectrum. "
                  f"Manual inspection of the NetCDF structure above is needed "
                  f"to determine variable names.")

    # Cleanup
    print(f"\nCleaning up temporary files...")
    _cleanup_directory(tmp_dir)
    print(f"\nInspection complete. Use this information to verify the "
          f"script's parsing logic before full download.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download and convert Sonora Elf Owl spectra for SA3D"
    )
    parser.add_argument(
        "--subgrid", type=str, required=True, choices=["Y", "T", "L"],
        help="REQUIRED: Which sub-grid to download (Y, T, or L). "
             "Process one at a time to fit in available disk space."
    )
    parser.add_argument(
        "--inspect", action="store_true",
        help="Download first chunk, open one .nc, print structure, then exit"
    )
    add_common_args(parser)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    subgrid = args.subgrid
    record_id = ZENODO_RECORDS[subgrid]

    # Default output directory per sub-grid
    if args.output_dir is None:
        args.output_dir = os.path.join(
            PROJECT_ROOT, "model_grids", f"sonora_elfowl_{subgrid}"
        )

    output_dir = args.output_dir

    print(f"Sonora Elf Owl Model Grid Downloader")
    print(f"Sub-grid:  {subgrid}-type dwarfs")
    print(f"Source:    https://zenodo.org/records/{record_id}")
    print(f"Wavelength range: {args.wl_min}-{args.wl_max} um "
          f"({args.wl_min * 1e4:.0f}-{args.wl_max * 1e4:.0f} A)")
    print(f"Downsampled points: {args.n_points}")
    print(f"Output:    {output_dir}")

    import requests
    session = requests.Session()

    # --- Inspect mode ---
    if args.inspect:
        _run_inspect(subgrid, session)
        return

    # --- Fetch chunk info from Zenodo API ---
    print(f"\nQuerying Zenodo for available chunks...")
    chunks = fetch_chunk_info(record_id, session)

    if not chunks:
        print("ERROR: No tar.gz chunks found in Zenodo record.")
        sys.exit(1)

    total_size = sum(c["size"] for c in chunks)
    print(f"\nFound {len(chunks)} chunks ({total_size / 1e9:.1f} GB total):")
    for c in chunks:
        print(f"  {c['key']}  ({c['size'] / 1e9:.1f} GB)")

    # --- Dry run ---
    if args.dry_run:
        print(f"\nDry run -- would process {len(chunks)} chunks")
        print(f"Each chunk: ~9.5 GB download, extracted .nc files, "
              f"then converted to .dat")
        print(f"Peak disk usage: ~20 GB (one chunk at a time)")
        print(f"Expected models per sub-grid: ~14,400")
        print(f"\nTo start download:")
        print(f"  python scripts/download_sonora_elfowl.py "
              f"--subgrid {subgrid}")
        return

    # --- Process chunks piecewise ---
    cache_dir = os.path.join(output_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)

    all_rows = []
    total_ok = 0
    total_skip = 0

    for idx, chunk in enumerate(chunks, 1):
        rows = _process_chunk(
            chunk, subgrid, output_dir, args, session,
            chunk_idx=idx, total_chunks=len(chunks),
        )
        all_rows.extend(rows)
        total_ok += len(rows)

    # --- Write index.csv ---
    if all_rows:
        index_path = os.path.join(output_dir, "index.csv")
        fieldnames = ["filename", "Teff", "logg", "metallicity",
                      "c_o_ratio", "log_kzz"]
        write_index_csv(index_path, all_rows, fieldnames)
        print(f"\nWrote index.csv with {len(all_rows)} entries")

    # --- Summary ---
    print_summary(output_dir, total_ok, total_skip)

    if total_ok > 0:
        print(f"\nSub-grid {subgrid} complete!")
        print(f"To process another sub-grid:")
        other = [s for s in ["Y", "T", "L"] if s != subgrid]
        for s in other:
            print(f"  python scripts/download_sonora_elfowl.py --subgrid {s}")


if __name__ == "__main__":
    main()

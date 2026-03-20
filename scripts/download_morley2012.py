#!/usr/bin/env python3
"""Download and convert Morley et al. 2012 sulfide cloud model spectra for SA3D.

Downloads the sulfide cloud model archive from Dropbox, extracts plain-text
spectra, trims to JWST-relevant wavelength range, downsamples, and writes
two-column .dat files compatible with the SA3D model_grids loader.

Parameters:
    Teff:        400-1300 K
    logg:        4.0-5.5
    fsed:        varies (sedimentation efficiency)
    [M/H]:       0.0 (solar, all models)
    ~50-100 models total

Source: Morley et al. (2012) — sulfide cloud models
Data:   https://www.dropbox.com/s/3lnt7pyitueor2r/sulfideclouds.tar.gz?dl=1

Raw format: Plain text files (wavelength + flux columns).
The exact column format is auto-detected from the data range.
Use --inspect to examine the raw file contents before processing.

Output:
    model_grids/morley2012/
        index.csv              # filename,Teff,logg,metallicity,fsed
        spectra/<name>.dat     # 2-column: wavelength (Angstroms), flux

Usage:
    python scripts/download_morley2012.py [options]
    python scripts/download_morley2012.py --inspect   # examine raw files first

Options:
    --inspect     Download and show raw file format, then exit
    --output-dir  Output grid directory (default: model_grids/morley2012)
    --wl-min      Min wavelength in microns (default: 0.5)
    --wl-max      Max wavelength in microns (default: 5.5)
    --n-points    Downsampled wavelength pts (default: 2000)
    --dry-run     List files in archive without processing
    --keep-raw    Keep the downloaded tar.gz after processing

Requires: numpy, requests
"""

import os
import re
import sys
import tarfile
import argparse
import logging
import tempfile

import numpy as np

# ---------------------------------------------------------------------------
# Import shared utilities from grid_utils (same directory)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_utils import (download_with_progress, trim_and_downsample,
                        write_dat_file, write_index_csv, add_common_args,
                        print_summary, PROJECT_ROOT)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DROPBOX_URL = "https://www.dropbox.com/s/3lnt7pyitueor2r/sulfideclouds.tar.gz?dl=1"
ARCHIVE_FILENAME = "sulfideclouds.tar.gz"
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "model_grids", "morley2012")

# Morley 2012 filenames typically embed Teff, gravity, and fsed.
# Common patterns:
#   sp_t800g1000f5    (t=Teff, g=gravity in m/s^2, f=fsed)
#   sp_t1000g316nc_m0.0   (nc = no clouds variant?)
# We try several regex patterns to be robust.
_MORLEY_PATTERNS = [
    # Pattern: sp_t{teff}g{gravity}f{fsed} (most common)
    re.compile(
        r"sp_t(\d+)g(\d+)f(\d+)",
        re.IGNORECASE,
    ),
    # Pattern: t{teff}g{gravity}f{fsed} (without sp_ prefix)
    re.compile(
        r"(?:^|[/_])t(\d+)g(\d+)f(\d+)",
        re.IGNORECASE,
    ),
    # Pattern with underscores: t{teff}_g{gravity}_f{fsed}
    re.compile(
        r"t(\d+)_g(\d+)_f(\d+)",
        re.IGNORECASE,
    ),
]

# Mapping from g_mks (gravity in m/s^2 / 100) to log(g)
# 10^logg / 100 = g_mks  =>  logg = log10(g_mks * 100)
_GMKS_TO_LOGG = {
    100: 4.0,     # 10^4.0 / 100 = 100
    178: 4.25,    # 10^4.25 / 100 ~ 178
    316: 4.5,     # 10^4.5 / 100 ~ 316
    562: 4.75,    # 10^4.75 / 100 ~ 562
    1000: 5.0,    # 10^5.0 / 100 = 1000
    1778: 5.25,   # 10^5.25 / 100 ~ 1778
    3162: 5.5,    # 10^5.5 / 100 ~ 3162
    31: 3.5,      # 10^3.5 / 100 ~ 31
    10: 3.0,      # 10^3.0 / 100 = 10
}


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

def _parse_morley_filename(name):
    """Parse Teff, g_mks, and fsed from a Morley 2012 filename.

    Returns dict with keys: teff, g_mks, logg, fsed, or None if no match.
    """
    basename = os.path.basename(name)

    for pattern in _MORLEY_PATTERNS:
        m = pattern.search(basename)
        if m:
            teff = int(m.group(1))
            g_mks = int(m.group(2))
            fsed = int(m.group(3))

            # Convert g_mks to log(g)
            logg = _GMKS_TO_LOGG.get(g_mks)
            if logg is None:
                # Fallback: compute from g_mks
                import math
                logg = round(math.log10(g_mks * 100), 2)
                # Round to nearest 0.25 for cleanliness
                logg = round(logg * 4) / 4

            return {
                "teff": teff,
                "g_mks": g_mks,
                "logg": logg,
                "fsed": fsed,
            }

    return None


# ---------------------------------------------------------------------------
# Unit auto-detection
# ---------------------------------------------------------------------------

def _read_morley_spectrum(filepath):
    """Read a Morley 2012 spectrum file.

    File format:
        Line 0: parameter values + labels (e.g. '1000.  1000.  0.28 ... Teff, grav...')
        Line 1: column labels ('microns  Flux (erg/cm^2/s/Hz)')
        Line 2: blank
        Lines 3+: two-column data (wavelength_microns  flux_erg_cm2_s_Hz)

    Returns (wavelength_microns, flux_erg_cm2_s_Hz) as numpy arrays.
    """
    # Find the first line with exactly 2 numeric columns
    skip = 0
    with open(filepath, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                skip += 1
                continue
            parts = stripped.split()
            if len(parts) == 2:
                try:
                    float(parts[0])
                    float(parts[1])
                    break  # Found first data line
                except ValueError:
                    pass
            skip += 1

    data = np.loadtxt(filepath, dtype=float, skiprows=skip)
    return data[:, 0], data[:, 1]


# Speed of light in Angstroms/s (for F_nu -> F_lambda conversion)
_C_ANG_S = 2.99792458e18


# ---------------------------------------------------------------------------
# Inspect mode
# ---------------------------------------------------------------------------

def _inspect_archive(tar_path):
    """Open the tar.gz, list contents, and show sample file data."""
    print(f"\n--- Inspecting archive: {tar_path} ---\n")

    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()
        file_members = [m for m in members if m.isfile()]
        dir_members = [m for m in members if m.isdir()]

        print(f"Total entries: {len(members)}")
        print(f"  Directories: {len(dir_members)}")
        print(f"  Files:       {len(file_members)}")

        # List all files
        print(f"\n--- File listing ({len(file_members)} files) ---")
        for m in sorted(file_members, key=lambda x: x.name)[:50]:
            size_kb = m.size / 1024
            print(f"  {m.name}  ({size_kb:.1f} KB)")

        if len(file_members) > 50:
            print(f"  ... and {len(file_members) - 50} more files")

        # Show first 20 lines of up to 3 sample files
        sample_files = file_members[:3]
        print(f"\n--- Sample file contents (first 20 lines each) ---")

        for member in sample_files:
            print(f"\n  === {member.name} ({member.size / 1024:.1f} KB) ===")
            try:
                f = tf.extractfile(member)
                if f is None:
                    print("    (could not extract)")
                    continue

                lines = []
                for i, raw_line in enumerate(f):
                    if i >= 20:
                        break
                    try:
                        line = raw_line.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        line = str(raw_line)
                    lines.append(line)
                    print(f"    {line}")

                f.close()

                # Try to parse as numeric data to show format info
                parsed = _parse_morley_filename(member.name)
                if parsed:
                    print(f"\n    Parsed params: Teff={parsed['teff']} "
                          f"g_mks={parsed['g_mks']} logg={parsed['logg']:.2f} "
                          f"fsed={parsed['fsed']}")
                else:
                    print(f"\n    Could not parse parameters from filename")

            except Exception as exc:
                print(f"    Error reading file: {exc}")

        # Try reading the first parseable file to detect units
        print(f"\n--- Unit detection ---")
        for member in file_members[:10]:
            try:
                f = tf.extractfile(member)
                if f is None:
                    continue

                # Write to temp file for read_text_spectrum
                with tempfile.NamedTemporaryFile(
                    mode="wb", suffix=".txt", delete=False
                ) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                f.close()

                try:
                    wl, flux = read_text_spectrum(tmp_path)

                    wl_unit = _detect_wavelength_unit(wl)
                    fl_unit = _detect_flux_unit(flux)

                    print(f"  File: {member.name}")
                    print(f"  Wavelength range: {wl[0]:.4f} - {wl[-1]:.4f} "
                          f"(detected: {wl_unit})")
                    print(f"  Flux range: {np.min(flux):.4e} - {np.max(flux):.4e} "
                          f"(detected: {fl_unit})")
                    print(f"  Data points: {len(wl)}")
                    print(f"  Columns: {wl.shape} wavelengths, {flux.shape} flux")
                    break
                finally:
                    os.unlink(tmp_path)

            except Exception as exc:
                logger.debug(f"Could not read {member.name}: {exc}")
                continue

    print(f"\n--- End of inspection ---")
    print(f"Re-run without --inspect to process all files.")


# ---------------------------------------------------------------------------
# Output filename builder
# ---------------------------------------------------------------------------

def _dat_filename(teff, logg, fsed):
    """Build the standardised .dat filename for a Morley 2012 model."""
    return f"morley12_T{int(teff)}_g{logg:.1f}_f{int(fsed)}.dat"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download and convert Morley et al. 2012 sulfide cloud "
                    "spectra for SA3D"
    )
    add_common_args(parser)

    # Override default output-dir
    parser.set_defaults(output_dir=DEFAULT_OUTPUT_DIR)

    # Morley-specific arguments
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Download archive, show file format and samples, then exit",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Resolve output directory
    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    cache_dir = os.path.join(output_dir, ".cache")
    spectra_dir = os.path.join(output_dir, "spectra")

    # Wavelength range in Angstroms for trim_and_downsample_angstrom
    wl_min_a = args.wl_min * 1e4   # 5000 A
    wl_max_a = args.wl_max * 1e4   # 55000 A

    print(f"Morley et al. 2012 Sulfide Cloud Model Downloader")
    print(f"Source: {DROPBOX_URL}")
    print(f"Output: {output_dir}")
    print(f"Wavelength range: {args.wl_min}-{args.wl_max} um "
          f"({wl_min_a:.0f}-{wl_max_a:.0f} A)")
    print(f"Downsampled points: {args.n_points}")

    # --- Step 1: Download the tar.gz archive ---
    os.makedirs(cache_dir, exist_ok=True)
    tar_path = os.path.join(cache_dir, ARCHIVE_FILENAME)

    print(f"\n--- Downloading sulfide cloud archive ---")
    if not download_with_progress(
        DROPBOX_URL, tar_path, label="sulfideclouds.tar.gz"
    ):
        print("ERROR: Could not download archive. Aborting.")
        sys.exit(1)

    # --- Step 2: Inspect mode ---
    if args.inspect:
        _inspect_archive(tar_path)
        return

    # --- Step 3: Open archive and discover files ---
    print(f"\n--- Scanning archive contents ---")

    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()
        file_members = [m for m in members if m.isfile()]

        print(f"  Archive contains {len(file_members)} files")

        # Try to parse parameters from each filename
        parseable = []
        unparseable = []

        for member in file_members:
            parsed = _parse_morley_filename(member.name)
            if parsed is not None:
                parsed["member"] = member
                parseable.append(parsed)
            else:
                unparseable.append(member.name)

        print(f"  Parseable spectrum files: {len(parseable)}")
        if unparseable:
            print(f"  Unparseable files: {len(unparseable)}")
            for name in unparseable[:5]:
                print(f"    {name}")
            if len(unparseable) > 5:
                print(f"    ... and {len(unparseable) - 5} more")

        if not parseable:
            print("ERROR: Could not parse any spectrum filenames. "
                  "Use --inspect to examine the archive.")
            sys.exit(1)

        # Summary of parameter ranges
        teffs = sorted(set(p["teff"] for p in parseable))
        loggs = sorted(set(p["logg"] for p in parseable))
        fseds = sorted(set(p["fsed"] for p in parseable))

        print(f"\n  Parameter ranges:")
        print(f"    Teff: {teffs[0]}-{teffs[-1]} K ({len(teffs)} values: "
              f"{teffs})")
        print(f"    logg: {loggs[0]:.2f}-{loggs[-1]:.2f} ({len(loggs)} values: "
              f"{loggs})")
        print(f"    fsed: {fseds} ({len(fseds)} values)")
        print(f"    [M/H]: 0.0 (solar, all models)")

        # Dry run: just print the list
        if args.dry_run:
            print(f"\nModels to process:")
            for p in sorted(parseable,
                            key=lambda x: (x["teff"], x["logg"], x["fsed"])):
                dat = _dat_filename(p["teff"], p["logg"], p["fsed"])
                print(f"  Teff={p['teff']} logg={p['logg']:.2f} "
                      f"fsed={p['fsed']}  -> {dat}")
            print(f"\nTotal: {len(parseable)} models (dry run, nothing "
                  f"processed)")
            return

        # --- Step 4: Extract and convert each spectrum ---
        os.makedirs(spectra_dir, exist_ok=True)

        index_rows = []
        n_ok = 0
        n_skip = 0
        total = len(parseable)

        # Sort for deterministic processing order
        parseable.sort(key=lambda x: (x["teff"], x["logg"], x["fsed"]))

        for i, params in enumerate(parseable, 1):
            teff = params["teff"]
            logg = params["logg"]
            fsed = params["fsed"]
            member = params["member"]

            dat_fname = _dat_filename(teff, logg, fsed)
            dat_path = os.path.join(spectra_dir, dat_fname)
            label = (f"[{i}/{total}] Teff={teff} logg={logg:.2f} fsed={fsed}")

            # Skip if already converted
            if os.path.exists(dat_path):
                print(f"{label} -- already converted")
                index_rows.append({
                    "filename": dat_fname,
                    "Teff": teff,
                    "logg": logg,
                    "metallicity": 0.0,
                    "fsed": fsed,
                })
                n_ok += 1
                continue

            # Extract to a temp file
            try:
                f = tf.extractfile(member)
                if f is None:
                    logger.warning(f"{label} -- could not extract from archive")
                    n_skip += 1
                    continue

                with tempfile.NamedTemporaryFile(
                    mode="wb", suffix=".txt", delete=False
                ) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                f.close()

            except Exception as exc:
                logger.warning(f"{label} -- extraction failed: {exc}")
                n_skip += 1
                continue

            # Read the spectrum
            try:
                wl_raw, fl_raw = _read_morley_spectrum(tmp_path)
            except Exception as exc:
                logger.warning(f"{label} -- failed to read spectrum: {exc}")
                n_skip += 1
                continue
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            if len(wl_raw) == 0:
                logger.warning(f"{label} -- empty spectrum, skipping")
                n_skip += 1
                continue

            # Ensure ascending wavelength order
            if len(wl_raw) > 1 and wl_raw[0] > wl_raw[-1]:
                sort_idx = np.argsort(wl_raw)
                wl_raw = wl_raw[sort_idx]
                fl_raw = fl_raw[sort_idx]

            # Convert F_nu (erg/cm2/s/Hz) to F_lambda (erg/cm2/s/A)
            # F_lambda = F_nu * c / lambda^2  (with lambda in Angstroms)
            wl_angstrom = wl_raw * 1e4  # microns -> Angstroms
            fl_raw = fl_raw * _C_ANG_S / (wl_angstrom ** 2)

            # Trim and downsample (wavelength is in microns, output in Angstroms)
            wl_out, fl_out = trim_and_downsample(
                wl_raw, fl_raw,
                wl_min=args.wl_min,
                wl_max=args.wl_max,
                n_pts=args.n_points,
            )

            if len(wl_out) == 0:
                logger.warning(f"{label} -- no data in wavelength range, "
                               f"skipping")
                n_skip += 1
                continue

            # Write .dat file (flux is now in erg/cm2/s/A)
            write_dat_file(dat_path, wl_out, fl_out,
                           unit_tag="flux_erg_s_cm2_A")

            index_rows.append({
                "filename": dat_fname,
                "Teff": teff,
                "logg": logg,
                "metallicity": 0.0,
                "fsed": fsed,
            })
            n_ok += 1

            if i == 1:
                print(f"  Input: microns, F_nu (erg/cm2/s/Hz) -> "
                      f"converted to F_lambda (erg/cm2/s/A)")
                print(f"  Output range: {wl_out[0]:.1f}-{wl_out[-1]:.1f} A, "
                      f"{len(wl_out)} points")

            print(f"{label} -- OK")

    # --- Step 5: Write index.csv ---
    if index_rows:
        index_path = os.path.join(output_dir, "index.csv")
        fieldnames = ["filename", "Teff", "logg", "metallicity", "fsed"]
        write_index_csv(index_path, index_rows, fieldnames)

    # --- Step 6: Print summary ---
    print_summary(output_dir, n_ok, n_skip)

    # --- Step 7: Clean up archive unless --keep-raw ---
    if not args.keep_raw and os.path.exists(tar_path) and n_ok > 0:
        print(f"\nRemoving {ARCHIVE_FILENAME} to save disk space...")
        os.remove(tar_path)
        # Remove cache dir if empty
        try:
            os.rmdir(cache_dir)
        except OSError:
            pass
    elif not args.keep_raw and n_ok == 0:
        print(f"\nKeeping {ARCHIVE_FILENAME} (no models processed -- "
              f"re-run to retry)")


if __name__ == "__main__":
    main()

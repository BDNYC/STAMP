#!/usr/bin/env python3
"""Download and convert Sonora Bobcat model spectra for SA3D grid fitting.

Downloads spectra archives from Zenodo (Marley et al. 2021), extracts
.spec files from three metallicity tar.gz bundles, trims to JWST-relevant
wavelength range, downsamples, and writes two-column .dat files compatible
with the SA3D model_grids loader.

The three tar.gz files total ~3.2 GB.  The script processes one at a time
to keep peak disk usage around ~1.5 GB.

Parameters:
    Teff:        200-2400 K
    logg:        3.25, 3.5, 3.75, 4.0, 4.25, 4.5, 4.75, 5.0, 5.25, 5.5
    [M/H]:       -0.5, 0.0, +0.5
    Models:      ~690

Usage:
    python scripts/download_sonora_bobcat.py [options]

Options:
    --metals      Comma-separated [M/H] values (default: -0.5,0.0,+0.5)
    --output-dir  Output grid directory (default: model_grids/sonora_bobcat)
    --wl-min      Min wavelength in microns (default: 0.5)
    --wl-max      Max wavelength in microns (default: 5.5)
    --n-points    Downsampled wavelength points (default: 2000)
    --keep-raw    Keep downloaded tar.gz files after extraction
    --dry-run     List files without downloading

Requires: numpy, requests
Reference: Marley et al. (2021) https://doi.org/10.5281/zenodo.5063476
Data:      https://zenodo.org/records/5063476
"""

import os
import re
import sys
import math
import gzip
import argparse
import logging
import tarfile
import tempfile

import numpy as np

# Import shared grid utilities from the same scripts/ directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_utils import (download_with_progress, trim_and_downsample,
                        write_dat_file, write_index_csv, add_common_args,
                        print_summary, PROJECT_ROOT)

logger = logging.getLogger(__name__)

# Speed of light in Angstroms/s for F_nu -> F_lambda conversion
_C_ANG_S = 2.99792458e18


def _read_bobcat_spectrum(filepath):
    """Read a Bobcat spectrum file (2-column: wavelength um, flux erg/cm2/s/Hz).

    The file format has a parameter header on line 0 (starts with a number
    but contains text), a column label line, then 2-column data.
    This reader finds the first line with exactly 2 numeric values.
    """
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
                    break
                except ValueError:
                    pass
            skip += 1
    data = np.loadtxt(filepath, dtype=float, skiprows=skip)
    return data[:, 0], data[:, 1]


# Zenodo archive URLs — one tar.gz per metallicity
ZENODO_RECORD = "5063476"
METAL_ARCHIVES = {
    0.0:  {
        "url": f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/spectra_m+0.0.tar.gz/content",
        "filename": "spectra_m+0.0.tar.gz",
        "label": "[M/H] = +0.0",
    },
    0.5:  {
        "url": f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/spectra_m+0.5.tar.gz/content",
        "filename": "spectra_m+0.5.tar.gz",
        "label": "[M/H] = +0.5",
    },
    -0.5: {
        "url": f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/spectra_m-0.5.tar.gz/content",
        "filename": "spectra_m-0.5.tar.gz",
        "label": "[M/H] = -0.5",
    },
}

# Filename parsing
# Bobcat .spec filenames follow the pattern:
#   sp_t{teff}g{g_cgs}nc_m{metal}.spec
# where g_cgs is the surface gravity in cm/s^2 (e.g., 10000 for logg=4.0).
# Some variants may include additional suffixes — the regex is kept flexible.
_BOBCAT_RE = re.compile(
    r"sp_t(\d+)g(\d+)nc_m([+-]?\d+\.?\d*)(?:\.spec)?(?:\.gz)?$"
)


def _parse_bobcat_name(path):
    """Parse Teff, gravity (cgs), and metallicity from a Bobcat .spec filename.

    Returns dict with parsed values or None if the pattern doesn't match.
    """
    basename = os.path.basename(path)
    m = _BOBCAT_RE.search(basename)
    if not m:
        return None
    return {
        "teff": int(m.group(1)),
        "g_cgs": int(m.group(2)),
        "metal": float(m.group(3)),
        "basename": basename,
    }


def _g_cgs_to_logg(g_cgs):
    """Convert surface gravity in cm/s^2 to log10(g)."""
    if g_cgs <= 0:
        return None
    return round(math.log10(g_cgs), 2)


def _dat_filename(teff, logg, metal):
    """Build the standardised .dat filename for a Bobcat model."""
    return f"bobcat_T{int(teff)}_g{logg:.2f}_m{metal:+.1f}.dat"


# Main processing

def _process_tar(archive_path, metal, output_dir, args):
    """Process all .spec files inside a single metallicity tar.gz.

    Returns list of index row dicts for successfully converted models.
    """
    spectra_dir = os.path.join(output_dir, "spectra")
    os.makedirs(spectra_dir, exist_ok=True)

    rows = []
    n_ok = 0
    n_skip = 0

    with tarfile.open(archive_path, "r:gz") as tf:
        # Collect all .spec members
        spec_members = [m for m in tf.getmembers()
                        if m.isfile() and _BOBCAT_RE.search(
                            os.path.basename(m.name))]

        print(f"  Archive contains {len(spec_members)} spectrum files")

        for i, member in enumerate(sorted(spec_members, key=lambda m: m.name), 1):
            parsed = _parse_bobcat_name(member.name)
            if parsed is None:
                logger.debug(f"  Skipping non-matching entry: {member.name}")
                n_skip += 1
                continue

            teff = parsed["teff"]
            g_cgs = parsed["g_cgs"]
            logg = _g_cgs_to_logg(g_cgs)
            if logg is None:
                logger.warning(f"  Invalid gravity {g_cgs} in {member.name}")
                n_skip += 1
                continue

            dat_fname = _dat_filename(teff, logg, metal)
            dat_path = os.path.join(spectra_dir, dat_fname)
            step_label = (f"  [{i}/{len(spec_members)}] Teff={teff} "
                          f"logg={logg:.2f} [M/H]={metal:+.1f}")

            # Skip if already converted
            if os.path.exists(dat_path):
                print(f"{step_label} -- already converted")
                rows.append({
                    "filename": dat_fname,
                    "Teff": teff,
                    "logg": logg,
                    "metallicity": metal,
                })
                n_ok += 1
                continue

            try:
                # Extract spectrum to a temporary file
                with tempfile.NamedTemporaryFile(suffix=".spec",
                                                 delete=False) as tmp:
                    tmp_path = tmp.name
                    src = tf.extractfile(member)
                    if src is None:
                        logger.warning(f"{step_label} -- cannot extract")
                        n_skip += 1
                        continue
                    raw_data = src.read()
                    # Handle individually gzipped files (.gz inside tar)
                    if member.name.endswith(".gz"):
                        raw_data = gzip.decompress(raw_data)
                    tmp.write(raw_data)

                # Read the two-column text spectrum
                wl_um, fl_raw = _read_bobcat_spectrum(tmp_path)

                # Ensure ascending wavelength order
                if len(wl_um) > 1 and wl_um[0] > wl_um[-1]:
                    sort_idx = np.argsort(wl_um)
                    wl_um = wl_um[sort_idx]
                    fl_raw = fl_raw[sort_idx]

                # Convert F_nu (erg/cm2/s/Hz) -> F_lambda (erg/cm2/s/A)
                wl_angstrom_raw = wl_um * 1e4  # microns -> Angstroms
                fl_lambda = fl_raw * _C_ANG_S / (wl_angstrom_raw ** 2)

                # Trim to range and downsample (input: microns, output: Angstroms)
                wl_angstrom, fl_out = trim_and_downsample(
                    wl_um, fl_lambda,
                    wl_min=args.wl_min,
                    wl_max=args.wl_max,
                    n_pts=args.n_points,
                )

                if len(wl_angstrom) == 0:
                    logger.warning(f"{step_label} -- no data in wavelength range")
                    n_skip += 1
                    continue

                # Write .dat file
                write_dat_file(dat_path, wl_angstrom, fl_out,
                               unit_tag="flux_erg_s_cm2_A")

                rows.append({
                    "filename": dat_fname,
                    "Teff": teff,
                    "logg": logg,
                    "metallicity": metal,
                })
                n_ok += 1
                print(f"{step_label} -- OK")

            except Exception as exc:
                logger.warning(f"{step_label} -- FAILED: {exc}")
                n_skip += 1
                continue

            finally:
                # Clean up temp file
                try:
                    os.remove(tmp_path)
                except (OSError, UnboundLocalError):
                    pass

    print(f"  Metallicity {metal:+.1f}: {n_ok} converted, {n_skip} skipped")
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Download and convert Sonora Bobcat spectra for SA3D"
    )
    parser.add_argument(
        "--metals", type=str, default="-0.5,0.0,+0.5",
        help="Comma-separated [M/H] values to process (default: -0.5,0.0,+0.5)"
    )
    add_common_args(parser)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Default output directory
    if args.output_dir is None:
        args.output_dir = os.path.join(PROJECT_ROOT, "model_grids",
                                       "sonora_bobcat")

    output_dir = args.output_dir
    cache_dir = os.path.join(output_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)

    # Parse requested metallicities
    metal_values = [float(x) for x in args.metals.split(",")]

    print(f"Sonora Bobcat Model Grid Downloader")
    print(f"Source: https://zenodo.org/records/{ZENODO_RECORD}")
    print(f"Metallicities: {metal_values}")
    print(f"Wavelength range: {args.wl_min}-{args.wl_max} um "
          f"({args.wl_min * 1e4:.0f}-{args.wl_max * 1e4:.0f} A)")
    print(f"Downsampled points: {args.n_points}")
    print(f"Output: {output_dir}")

    # Validate metallicity selections
    for met in metal_values:
        if met not in METAL_ARCHIVES:
            print(f"ERROR: Unknown metallicity {met:+.1f}. "
                  f"Available: {sorted(METAL_ARCHIVES.keys())}")
            sys.exit(1)

    if args.dry_run:
        print(f"\nDry run -- would download:")
        for met in metal_values:
            info = METAL_ARCHIVES[met]
            print(f"  {info['label']}: {info['url']}")
        print(f"\nTotal: {len(metal_values)} archive(s) (~3.2 GB if all)")
        return

    import requests
    session = requests.Session()

    all_rows = []
    total_ok = 0
    total_skip = 0

    for met in metal_values:
        info = METAL_ARCHIVES[met]
        tar_path = os.path.join(cache_dir, info["filename"])

        print(f"\n{'=' * 60}")
        print(f"  {info['label']}")
        print(f"{'=' * 60}")

        # Step 1: Download the tar.gz
        if not download_with_progress(info["url"], tar_path,
                                      session=session,
                                      label=info["filename"],
                                      timeout=1200):
            print(f"ERROR: Could not download {info['filename']}. Skipping.")
            continue

        # Step 2: Process all .spec files inside
        print(f"  Processing {info['filename']}...")
        rows = _process_tar(tar_path, met, output_dir, args)
        all_rows.extend(rows)
        total_ok += len(rows)

        # Step 3: Remove tar.gz to save disk (unless --keep-raw)
        if not args.keep_raw and os.path.exists(tar_path):
            print(f"  Removing {info['filename']} to save disk space...")
            os.remove(tar_path)

    # Write combined index.csv
    if all_rows:
        index_path = os.path.join(output_dir, "index.csv")
        fieldnames = ["filename", "Teff", "logg", "metallicity"]
        write_index_csv(index_path, all_rows, fieldnames)

    # Print summary
    print_summary(output_dir, total_ok, total_skip)


if __name__ == "__main__":
    main()

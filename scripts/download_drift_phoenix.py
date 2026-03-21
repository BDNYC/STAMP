#!/usr/bin/env python3
"""Download and convert DRIFT-PHOENIX model spectra from SVO for SA3D grid fitting.

Downloads spectra from the SVO Theoretical Spectra Server, trims to
JWST-relevant wavelength range, downsamples, and writes two-column .dat
files compatible with the SA3D model_grids loader.

Parameters:
    Teff:        1000-3000 K
    logg:        3.0-6.0
    [M/H]:       -0.6, -0.3, 0.0, +0.3
    ~520 models total

Source: SVO — http://svo2.cab.inta-csic.es/theory/newov2/ssap.php?model=drift
Raw format: VOTable XML — WAVELENGTH (Angstroms), FLUX (erg/cm2/s/A)

Usage:
    python scripts/download_drift_phoenix.py [options]

Options:
    --output-dir  Output grid directory     (default: model_grids/drift_phoenix)
    --wl-min      Min wavelength in microns  (default: 0.5)
    --wl-max      Max wavelength in microns  (default: 5.5)
    --n-points    Downsampled wavelength pts (default: 2000)
    --dry-run     List models without downloading

Requires: numpy, requests
"""

import os
import sys
import argparse
import logging

import numpy as np

# Import shared utilities from grid_utils (same directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_utils import (parse_svo_votable, download_svo_spectrum,
                        trim_and_downsample_angstrom, write_dat_file,
                        write_index_csv, add_common_args, print_summary,
                        PROJECT_ROOT, SVO_BASE)

logger = logging.getLogger(__name__)

# SVO listing URL for DRIFT-PHOENIX models
LISTING_URL = f"{SVO_BASE}/ssap.php?model=drift"

# Default output directory
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "model_grids", "drift_phoenix")


def _dat_filename(teff, logg, metal):
    """Build the output .dat filename for a DRIFT-PHOENIX model."""
    return f"drift_T{int(teff)}_g{logg:.1f}_m{metal:+.1f}.dat"


def fetch_model_listing(session=None):
    """Fetch the DRIFT-PHOENIX model listing VOTable from SVO.

    Returns a list of dicts with keys: Teff, logg, meta, fid, etc.
    """
    import requests

    sess = session or requests.Session()
    print(f"Fetching model listing from SVO...")
    print(f"  URL: {LISTING_URL}")

    resp = sess.get(LISTING_URL, timeout=120)
    resp.raise_for_status()

    models = parse_svo_votable(resp.content)
    print(f"  Found {len(models)} models in listing")
    return models


def main():
    parser = argparse.ArgumentParser(
        description="Download and convert DRIFT-PHOENIX spectra from SVO for SA3D"
    )
    add_common_args(parser)

    # Override default output-dir
    parser.set_defaults(output_dir=DEFAULT_OUTPUT_DIR)

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Resolve output directory
    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    spectra_dir = os.path.join(output_dir, "spectra")

    # Wavelength range in Angstroms (args are in microns)
    wl_min_a = args.wl_min * 1e4   # 5000 A
    wl_max_a = args.wl_max * 1e4   # 55000 A

    # --- Fetch model listing from SVO ---
    import requests
    session = requests.Session()

    models = fetch_model_listing(session)

    if not models:
        print("ERROR: No models found in SVO listing. Aborting.")
        sys.exit(1)

    # Extract parameter ranges for summary
    teffs = sorted(set(float(m.get("Teff", 0)) for m in models))
    loggs = sorted(set(float(m.get("logg", 0)) for m in models))
    metals = sorted(set(float(m.get("meta", 0)) for m in models))

    print(f"\nDRIFT-PHOENIX grid: {len(models)} models")
    print(f"  Teff:  {teffs[0]:.0f}-{teffs[-1]:.0f} K ({len(teffs)} values)")
    print(f"  logg:  {loggs[0]:.1f}-{loggs[-1]:.1f} ({len(loggs)} values)")
    print(f"  [M/H]: {metals}")
    print(f"  Output: {output_dir}")

    if args.dry_run:
        print(f"\nModels to download:")
        for m in models:
            teff = float(m.get("Teff", 0))
            logg = float(m.get("logg", 0))
            metal = float(m.get("meta", 0))
            fid = m.get("fid", "?")
            print(f"  Teff={teff:.0f} logg={logg:.1f} [M/H]={metal:+.1f}  fid={fid}")
        print(f"\nTotal: {len(models)} models (dry run, nothing downloaded)")
        return

    # --- Download and convert each spectrum ---
    os.makedirs(spectra_dir, exist_ok=True)

    index_rows = []
    n_ok = 0
    n_skip = 0
    total = len(models)

    for i, m in enumerate(models, 1):
        teff = float(m.get("Teff", 0))
        logg = float(m.get("logg", 0))
        metal = float(m.get("meta", 0))
        fid = m.get("fid", "")

        if not fid:
            logger.warning(f"[{i}/{total}] No fid for Teff={teff:.0f} — skipping")
            n_skip += 1
            continue

        dat_fname = _dat_filename(teff, logg, metal)
        dat_path = os.path.join(spectra_dir, dat_fname)
        label = (f"[{i}/{total}] Teff={teff:.0f} logg={logg:.1f} "
                 f"[M/H]={metal:+.1f}")

        # Skip already-converted .dat files
        if os.path.exists(dat_path):
            print(f"{label} -- already converted")
            index_rows.append({
                "filename": dat_fname,
                "Teff": int(teff),
                "logg": logg,
                "metallicity": metal,
            })
            n_ok += 1
            continue

        # Download spectrum from SVO
        print(f"{label} -- downloading fid={fid}")
        try:
            wl_raw, fl_raw = download_svo_spectrum(
                LISTING_URL, fid, session=session
            )
        except Exception as exc:
            logger.warning(f"  FAILED to download: {exc}")
            n_skip += 1
            continue

        if len(wl_raw) == 0:
            logger.warning(f"  Empty spectrum returned — skipping")
            n_skip += 1
            continue

        # Ensure ascending wavelength order
        if len(wl_raw) > 1 and wl_raw[0] > wl_raw[-1]:
            sort_idx = np.argsort(wl_raw)
            wl_raw = wl_raw[sort_idx]
            fl_raw = fl_raw[sort_idx]

        # Trim and downsample (input is already in Angstroms from SVO)
        wl_out, fl_out = trim_and_downsample_angstrom(
            wl_raw, fl_raw,
            wl_min_a=wl_min_a,
            wl_max_a=wl_max_a,
            n_pts=args.n_points,
        )

        if len(wl_out) == 0:
            logger.warning(f"  No data in wavelength range — skipping")
            n_skip += 1
            continue

        # Write .dat file
        write_dat_file(dat_path, wl_out, fl_out, unit_tag="flux_erg_s_cm2_A")

        index_rows.append({
            "filename": dat_fname,
            "Teff": int(teff),
            "logg": logg,
            "metallicity": metal,
        })
        n_ok += 1

    # --- Write index.csv ---
    index_path = os.path.join(output_dir, "index.csv")
    fieldnames = ["filename", "Teff", "logg", "metallicity"]
    write_index_csv(index_path, index_rows, fieldnames)

    # --- Summary ---
    print_summary(output_dir, n_ok, n_skip)


if __name__ == "__main__":
    main()

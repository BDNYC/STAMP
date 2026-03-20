#!/usr/bin/env python3
"""Download and convert ATMO 2020 model spectra for SA3D grid fitting.

Downloads spectra from the SVO Theoretical Spectra Server (Phillips et al.
2020), trims to JWST-relevant wavelength range, downsamples, and writes
two-column .dat files compatible with the SA3D model_grids loader.

Three sub-grids are available:
    ceq             Chemical equilibrium, Teff 200-3000 K, logg 2.5-5.5
    neq_strong      Non-equilibrium strong mixing, Teff 200-1800 K, logg 2.5-5.5
    neq_weak        Non-equilibrium weak mixing, Teff 200-1800 K, logg 2.5-5.5

All models assume solar metallicity (0.0).

Usage:
    python scripts/download_atmo2020.py [options]

Options:
    --subgrid       Which sub-grid(s) to download (default: all)
    --output-dir    Base output directory (default: auto per sub-grid)
    --wl-min        Min wavelength in microns (default: 0.5)
    --wl-max        Max wavelength in microns (default: 5.5)
    --n-points      Downsampled wavelength points (default: 2000)
    --dry-run       List models without downloading
    --keep-raw      Keep raw downloaded files after processing

Requires: numpy, requests
Source:   SVO Theoretical Spectra Server
          http://svo2.cab.inta-csic.es/theory/newov2/
"""

import os
import sys
import argparse
import logging

import numpy as np

# Import shared grid utilities from the same scripts/ directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_utils import (parse_svo_votable, download_svo_spectrum,
                        trim_and_downsample_angstrom, write_dat_file,
                        write_index_csv, add_common_args, print_summary,
                        PROJECT_ROOT)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SVO listing URLs for ATMO 2020 sub-grids
# ---------------------------------------------------------------------------
SVO_SSAP_BASE = "http://svo2.cab.inta-csic.es/theory/newov2/ssap.php"

SUBGRIDS = {
    "ceq": {
        "model": "atmo2020_ceq",
        "label": "ATMO 2020 Chemical Equilibrium",
        "dir_name": "atmo2020_ceq",
        "prefix": "atmo_ceq",
    },
    "neq_strong": {
        "model": "atmo2020_neq_strong",
        "label": "ATMO 2020 Non-Equilibrium (Strong Mixing)",
        "dir_name": "atmo2020_neq_strong",
        "prefix": "atmo_neq_strong",
    },
    "neq_weak": {
        "model": "atmo2020_neq_weak",
        "label": "ATMO 2020 Non-Equilibrium (Weak Mixing)",
        "dir_name": "atmo2020_neq_weak",
        "prefix": "atmo_neq_weak",
    },
}


def _listing_url(model_name):
    """Build the SVO SSAP listing URL for an ATMO 2020 sub-grid."""
    return f"{SVO_SSAP_BASE}?model={model_name}"


def _fetch_model_list(model_name, session):
    """Fetch and parse the SVO VOTable listing for a sub-grid.

    Returns a list of dicts with keys: Teff, logg, metallicity, fid.
    """
    import requests

    url = _listing_url(model_name)
    logger.info(f"Fetching model listing from {url}")

    sess = session or requests.Session()
    resp = sess.get(url, timeout=120)
    resp.raise_for_status()

    raw_rows = parse_svo_votable(resp.content)
    if not raw_rows:
        logger.warning(f"No models found for {model_name}")
        return []

    models = []
    for row in raw_rows:
        try:
            teff = float(row.get("Teff", ""))
            logg = float(row.get("logg", ""))
            metallicity = float(row.get("meta", "0.0"))
            fid = row.get("fid", "")
            if not fid:
                continue
            models.append({
                "Teff": teff,
                "logg": logg,
                "metallicity": metallicity,
                "fid": fid,
            })
        except (ValueError, TypeError) as exc:
            logger.debug(f"Skipping unparseable row: {row} ({exc})")
            continue

    # Sort by Teff, then logg for deterministic ordering
    models.sort(key=lambda m: (m["Teff"], m["logg"]))
    return models


def _dat_filename(prefix, teff, logg):
    """Build the standardised .dat filename for an ATMO 2020 model."""
    return f"{prefix}_T{int(teff)}_g{logg:.1f}.dat"


def _process_subgrid(subgrid_key, args, session):
    """Download and convert all models for a single ATMO 2020 sub-grid.

    Returns (n_ok, n_skip) counts.
    """
    info = SUBGRIDS[subgrid_key]
    model_name = info["model"]
    prefix = info["prefix"]
    label = info["label"]

    # Determine output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(PROJECT_ROOT, "model_grids", info["dir_name"])

    spectra_dir = os.path.join(output_dir, "spectra")
    os.makedirs(spectra_dir, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  SVO model: {model_name}")
    print(f"  Output:    {output_dir}")
    print(f"{'=' * 60}")

    # Fetch model listing from SVO
    print(f"\nFetching model listing from SVO...")
    models = _fetch_model_list(model_name, session)
    if not models:
        print(f"  ERROR: No models returned for {model_name}. Skipping.")
        return 0, 0

    print(f"  Found {len(models)} models")
    print(f"  Teff range: {models[0]['Teff']:.0f} - {models[-1]['Teff']:.0f} K")
    logg_vals = sorted(set(m["logg"] for m in models))
    print(f"  logg values: {logg_vals}")

    # Dry run: just print the model list
    if args.dry_run:
        print(f"\n  Models to download:")
        for m in models:
            fname = _dat_filename(prefix, m["Teff"], m["logg"])
            print(f"    Teff={m['Teff']:.0f}  logg={m['logg']:.1f}  "
                  f"[M/H]={m['metallicity']:.1f}  fid={m['fid']}  -> {fname}")
        print(f"\n  Total: {len(models)} models (dry run, nothing downloaded)")
        return len(models), 0

    # Convert wavelength limits from microns to Angstroms
    wl_min_a = args.wl_min * 1e4
    wl_max_a = args.wl_max * 1e4

    # The listing URL is also the base URL for individual spectrum downloads
    base_url = _listing_url(model_name)

    index_rows = []
    n_ok = 0
    n_skip = 0
    total = len(models)

    for i, model in enumerate(models, 1):
        teff = model["Teff"]
        logg = model["logg"]
        metallicity = model["metallicity"]
        fid = model["fid"]

        dat_fname = _dat_filename(prefix, teff, logg)
        dat_path = os.path.join(spectra_dir, dat_fname)
        step_label = (f"[{i}/{total}] Teff={teff:.0f} logg={logg:.1f} "
                      f"[M/H]={metallicity:.1f}")

        # Skip if already converted
        if os.path.exists(dat_path):
            print(f"{step_label} -- already converted")
            index_rows.append({
                "filename": dat_fname,
                "Teff": int(teff),
                "logg": logg,
                "metallicity": metallicity,
            })
            n_ok += 1
            continue

        # Download spectrum from SVO
        print(f"{step_label} -- downloading fid={fid}...")
        try:
            wl_angstrom, flux = download_svo_spectrum(
                base_url, fid, session=session
            )
        except Exception as exc:
            logger.warning(f"  FAILED to download fid={fid}: {exc}")
            n_skip += 1
            continue

        if len(wl_angstrom) == 0:
            logger.warning(f"  Empty spectrum for fid={fid}. Skipping.")
            n_skip += 1
            continue

        # Trim and downsample (input is Angstroms)
        wl_out, fl_out = trim_and_downsample_angstrom(
            wl_angstrom, flux,
            wl_min_a=wl_min_a,
            wl_max_a=wl_max_a,
            n_pts=args.n_points,
        )

        if len(wl_out) == 0:
            logger.warning(f"  No data in wavelength range for fid={fid}. Skipping.")
            n_skip += 1
            continue

        # Write .dat file
        write_dat_file(dat_path, wl_out, fl_out, unit_tag="flux_erg_s_cm2_A")

        index_rows.append({
            "filename": dat_fname,
            "Teff": int(teff),
            "logg": logg,
            "metallicity": metallicity,
        })
        n_ok += 1

    # Write index.csv
    if index_rows:
        index_path = os.path.join(output_dir, "index.csv")
        fieldnames = ["filename", "Teff", "logg", "metallicity"]
        write_index_csv(index_path, index_rows, fieldnames)

    # Print summary
    print_summary(output_dir, n_ok, n_skip)

    return n_ok, n_skip


def main():
    parser = argparse.ArgumentParser(
        description="Download and convert ATMO 2020 spectra from SVO for SA3D"
    )
    parser.add_argument(
        "--subgrid",
        type=str,
        default="all",
        choices=["ceq", "neq_strong", "neq_weak", "all"],
        help="Which sub-grid to download (default: all)"
    )
    add_common_args(parser)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Determine which sub-grids to process
    if args.subgrid == "all":
        subgrid_keys = list(SUBGRIDS.keys())
    else:
        subgrid_keys = [args.subgrid]

    print(f"ATMO 2020 Model Grid Downloader")
    print(f"Sub-grids: {', '.join(subgrid_keys)}")
    print(f"Wavelength range: {args.wl_min}-{args.wl_max} um "
          f"({args.wl_min * 1e4:.0f}-{args.wl_max * 1e4:.0f} A)")
    print(f"Downsampled points: {args.n_points}")

    import requests
    session = requests.Session()

    total_ok = 0
    total_skip = 0

    for key in subgrid_keys:
        # When processing multiple sub-grids, override output-dir per sub-grid
        # only if user did not specify a custom output-dir
        n_ok, n_skip = _process_subgrid(key, args, session)
        total_ok += n_ok
        total_skip += n_skip

    if len(subgrid_keys) > 1:
        print(f"\n{'=' * 60}")
        print(f"All sub-grids complete: {total_ok} models converted, "
              f"{total_skip} skipped")


if __name__ == "__main__":
    main()

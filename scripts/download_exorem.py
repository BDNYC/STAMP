#!/usr/bin/env python3
"""Download and convert Exo-REM Low-Resolution (cloudless) model spectra for SA3D.

Downloads the cloudless spectra archive from LESIA (Charnay et al.), converts
from wavenumber-space text .dat files to wavelength-space .dat files compatible
with the SA3D model_grids loader.

Source: https://lesia.obspm.fr/exorem/YGP_grids/Exo-REMk26/Low_Res_grid_2026/
Files:
    R500_cloudless_2026.tar.gz  (~523 MB) — text spectra archive

Each spectrum file inside the archive is a 3-column text file:
    Column 1: wavenumber (cm-1)
    Column 2: spectral_flux (W/m2/cm-1)
    Column 3: transit_depth (unused)

Parameters are parsed from filenames:
    spectra_YGP_{Teff}K_logg{logg}_met{met_xsolar}_CO{c_o}.dat

Conversions:
    Wavenumber -> Wavelength:  lambda(um) = 10000 / wn(cm-1), flip to ascending
    Flux:  F_wn (W/m2/cm-1) -> F_lambda (W/m2/m) = F_wn * wn^2 / 1e4
    Metallicity:  x_solar -> [M/H] = log10(x_solar)

Output:
    model_grids/exorem_lowres/
        index.csv               # filename,Teff,logg,metallicity,c_o_ratio
        spectra/<name>.dat      # 2-column: wavelength (Angstroms), flux (W/m2/m)

Usage:
    python scripts/download_exorem.py [options]

Requires: numpy, requests
Reference: Charnay et al. (2018)
"""

import os
import sys
import re
import tarfile
import argparse
import logging

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_utils import (download_with_progress, trim_and_downsample,
                        write_dat_file, write_index_csv, add_common_args,
                        print_summary, PROJECT_ROOT)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source URLs
# ---------------------------------------------------------------------------
BASE_URL = "https://lesia.obspm.fr/exorem/YGP_grids/Exo-REMk26/Low_Res_grid_2026"
TARBALL_URL = f"{BASE_URL}/R500_cloudless_2026.tar.gz"

DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "model_grids", "exorem_lowres")

# Regex to parse spectrum filenames like:
#   spectra_YGP_550K_logg4.5_met3.16_CO0.50.dat
_SPECTRUM_RE = re.compile(
    r"spectra_YGP_(\d+)K_logg([\d.]+)_met([\d.]+)_CO([\d.]+)\.dat$"
)


def _parse_spectrum_name(name):
    """Extract Teff, logg, metallicity (x-solar), C/O from a spectrum filename.

    Returns dict or None if filename doesn't match the expected pattern.
    """
    basename = os.path.basename(name)
    m = _SPECTRUM_RE.search(basename)
    if not m:
        return None
    teff = int(m.group(1))
    logg = float(m.group(2))
    met_xsolar = float(m.group(3))
    c_o = float(m.group(4))

    # Convert x-solar metallicity to [M/H] = log10(x_solar)
    if met_xsolar <= 0:
        return None
    metallicity = round(np.log10(met_xsolar), 2)

    return {
        "teff": teff,
        "logg": round(logg, 2),
        "metallicity": metallicity,
        "met_xsolar": met_xsolar,
        "c_o": round(c_o, 2),
    }


def _read_exorem_spectrum(fobj):
    """Read a 3-column Exo-REM text spectrum from a file object.

    Returns (wavenumber_cm, flux_wn) as numpy arrays.
    Skips header lines starting with '#'.
    """
    lines = fobj.read().decode("utf-8").strip().splitlines()
    data_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    arr = np.loadtxt(data_lines, dtype=float)
    # Columns: wavenumber (cm-1), spectral_flux (W/m2/cm-1), transit_depth
    return arr[:, 0], arr[:, 1]


def _convert_wn_to_wl(wn_cm, flux_wn):
    """Convert wavenumber spectrum to wavelength spectrum.

    Input:  wn_cm (cm-1, ascending), flux_wn (W/m2/cm-1)
    Output: wl_um (microns, ascending), flux_wl (W/m2/m)
    """
    # Filter out zero wavenumber
    mask = wn_cm > 0
    wn = wn_cm[mask]
    fl = flux_wn[mask]

    # Wavelength in microns: lambda = 10000 / wn
    wl_um = 10000.0 / wn

    # Convert flux: F_lambda = F_wn * wn^2 / 1e4
    flux_wl = fl * (wn ** 2) / 1.0e4

    # Reverse to get ascending wavelength order
    wl_um = wl_um[::-1]
    flux_wl = flux_wl[::-1]

    return wl_um, flux_wl


def dat_filename(teff, logg, metal, c_o):
    """Build the output .dat filename for an Exo-REM model."""
    return f"exorem_T{int(teff)}_g{logg:.1f}_m{metal:+.1f}_co{c_o:.2f}.dat"


def main():
    parser = argparse.ArgumentParser(
        description="Download and convert Exo-REM Low-Resolution (cloudless) "
                    "spectra for SA3D"
    )
    add_common_args(parser)
    parser.set_defaults(output_dir=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    cache_dir = os.path.join(output_dir, ".cache")
    spectra_dir = os.path.join(output_dir, "spectra")
    os.makedirs(cache_dir, exist_ok=True)

    print("Exo-REM Low-Resolution (Cloudless) Grid Downloader")
    print(f"  Source: {BASE_URL}")
    print(f"  Output: {output_dir}")
    print(f"  Wavelength range: {args.wl_min}-{args.wl_max} um "
          f"({args.wl_min * 1e4:.0f}-{args.wl_max * 1e4:.0f} A)")
    print(f"  Downsampled points: {args.n_points}")

    # ------------------------------------------------------------------
    # Step 1: Download tar.gz archive
    # ------------------------------------------------------------------
    print(f"\n--- Step 1: Download spectra archive ---")
    tarball_path = os.path.join(cache_dir, "R500_cloudless_2026.tar.gz")

    if not args.dry_run:
        import requests
        session = requests.Session()
        ok = download_with_progress(TARBALL_URL, tarball_path,
                                    session=session, label="tar.gz archive")
        if not ok:
            print("ERROR: Could not download spectra archive. Aborting.")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Scan tar.gz for spectrum files
    # ------------------------------------------------------------------
    print(f"\n--- Step 2: Scanning archive ---")

    with tarfile.open(tarball_path, "r:gz") as tf:
        all_members = tf.getmembers()
        spectrum_members = []
        for m in all_members:
            if not m.isfile():
                continue
            basename = os.path.basename(m.name)
            if basename.startswith("spectra_") and basename.endswith(".dat"):
                parsed = _parse_spectrum_name(basename)
                if parsed:
                    spectrum_members.append((m, parsed))

        print(f"  Total archive entries: {len(all_members)}")
        print(f"  Spectrum files found: {len(spectrum_members)}")

        if not spectrum_members:
            print("ERROR: No spectrum files found in archive.")
            sys.exit(1)

        # Show parameter ranges
        teffs = sorted(set(p["teff"] for _, p in spectrum_members))
        loggs = sorted(set(p["logg"] for _, p in spectrum_members))
        metals = sorted(set(p["metallicity"] for _, p in spectrum_members))
        cos = sorted(set(p["c_o"] for _, p in spectrum_members))

        print(f"  Teff:  {teffs[0]}-{teffs[-1]} K ({len(teffs)} values)")
        print(f"  logg:  {loggs[0]:.2f}-{loggs[-1]:.2f} ({len(loggs)} values)")
        print(f"  [M/H]: {metals}")
        print(f"  C/O:   {cos}")

        if args.dry_run:
            print(f"\nDry run -- {len(spectrum_members)} models would be converted")
            for _, p in spectrum_members[:10]:
                fname = dat_filename(p["teff"], p["logg"],
                                     p["metallicity"], p["c_o"])
                print(f"  Teff={p['teff']} logg={p['logg']:.2f} "
                      f"[M/H]={p['metallicity']:+.2f} C/O={p['c_o']:.2f} "
                      f"-> {fname}")
            if len(spectrum_members) > 10:
                print(f"  ... and {len(spectrum_members) - 10} more")
            return

        # ------------------------------------------------------------------
        # Step 3: Extract and convert each spectrum
        # ------------------------------------------------------------------
        print(f"\n--- Step 3: Converting spectra ---")
        os.makedirs(spectra_dir, exist_ok=True)

        index_rows = []
        n_ok = 0
        n_skip = 0
        total = len(spectrum_members)

        for i, (member, params) in enumerate(
                sorted(spectrum_members, key=lambda x: x[1]["teff"]), 1):
            teff = params["teff"]
            logg = params["logg"]
            metal = params["metallicity"]
            c_o = params["c_o"]

            out_fname = dat_filename(teff, logg, metal, c_o)
            out_path = os.path.join(spectra_dir, out_fname)
            label = (f"[{i}/{total}] Teff={teff} logg={logg:.2f} "
                     f"[M/H]={metal:+.2f} C/O={c_o:.2f}")

            # Skip already-converted
            if os.path.exists(out_path):
                index_rows.append({
                    "filename": out_fname,
                    "Teff": int(teff),
                    "logg": logg,
                    "metallicity": metal,
                    "c_o_ratio": c_o,
                })
                n_ok += 1
                continue

            try:
                fobj = tf.extractfile(member)
                if fobj is None:
                    n_skip += 1
                    continue

                # Read wavenumber + flux from text file
                wn_cm, flux_wn = _read_exorem_spectrum(fobj)
                fobj.close()

                # Convert wavenumber -> wavelength, flux units
                wl_um, flux_wl = _convert_wn_to_wl(wn_cm, flux_wn)

                # Trim and downsample (microns in, Angstroms out)
                wl_out, fl_out = trim_and_downsample(
                    wl_um, flux_wl,
                    wl_min=args.wl_min,
                    wl_max=args.wl_max,
                    n_pts=args.n_points,
                )

                if len(wl_out) == 0:
                    logger.warning(f"{label} -- no data in wavelength range")
                    n_skip += 1
                    continue

                write_dat_file(out_path, wl_out, fl_out,
                               unit_tag="flux_W_m2_m")

                index_rows.append({
                    "filename": out_fname,
                    "Teff": int(teff),
                    "logg": logg,
                    "metallicity": metal,
                    "c_o_ratio": c_o,
                })
                n_ok += 1

                if i <= 5 or i % 500 == 0 or i == total:
                    print(f"{label} -- OK")

            except Exception as exc:
                if i <= 10 or i % 1000 == 0:
                    logger.warning(f"{label} -- FAILED: {exc}")
                n_skip += 1

    # ------------------------------------------------------------------
    # Step 4: Write index.csv and summary
    # ------------------------------------------------------------------
    if index_rows:
        index_path = os.path.join(output_dir, "index.csv")
        fieldnames = ["filename", "Teff", "logg", "metallicity", "c_o_ratio"]
        write_index_csv(index_path, index_rows, fieldnames)

    print_summary(output_dir, n_ok, n_skip)

    # Delete tar.gz unless --keep-raw
    if not args.keep_raw and os.path.exists(tarball_path) and n_ok > 0:
        tar_size = os.path.getsize(tarball_path) / 1e6
        print(f"\nRemoving tar.gz to save {tar_size:.0f} MB of disk space...")
        os.remove(tarball_path)


if __name__ == "__main__":
    main()

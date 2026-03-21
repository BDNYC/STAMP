#!/usr/bin/env python3
"""Download and convert Phoenix-ACES model spectra for SA3D grid fitting.

Downloads HiRes FITS spectra from the Göttingen Phoenix server, trims to
JWST-relevant wavelength range, downsamples, and writes two-column .dat
files compatible with the SA3D model_grids loader.

Usage:
    python scripts/download_phoenix_grid.py [options]

Options:
    --teff-min    Minimum Teff in K         (default: 2500)
    --teff-max    Maximum Teff in K         (default: 5000)
    --teff-step   Teff step size in K       (default: 100)
    --logg        Comma-separated logg vals (default: 3.5,4.0,4.5,5.0,5.5)
    --metals      Comma-separated [Fe/H]    (default: -1.0,-0.5,0.0,+0.5)
    --output-dir  Output grid directory     (default: model_grids/phoenix_cool)
    --wl-min      Min wavelength in Å       (default: 5000)
    --wl-max      Max wavelength in Å       (default: 55000)
    --n-points    Downsampled wavelength pts (default: 2000)
    --dry-run     List files without downloading

Requires: astropy, numpy, requests (all in SA3D's existing environment)
"""

import os
import sys
import csv
import argparse
import logging

import numpy as np

logger = logging.getLogger(__name__)

# Phoenix server layout
PHOENIX_BASE = "https://phoenix.astro.physik.uni-goettingen.de/data/HiResFITS"
WAVE_FILE_URL = f"{PHOENIX_BASE}/WAVE_PHOENIX-ACES-AGSS-COND-2011.fits"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)


def _phoenix_fits_url(teff, logg, metal):
    """Build the URL for a single Phoenix FITS spectrum.

    Phoenix directory structure:
        PHOENIX-ACES-AGSS-COND-2011/Z{metal}/
            lte{teff:05d}-{logg:.2f}{metal:+.1f}.PHOENIX-ACES-AGSS-COND-2011-HiRes.fits
    """
    # Phoenix server uses "Z-0.0" for solar metallicity (not "Z+0.0")
    if metal == 0.0:
        metal_str = "-0.0"
    else:
        sign = "+" if metal >= 0 else "-"
        metal_str = f"{sign}{abs(metal):.1f}"
    metal_dir = f"Z{metal_str}"

    filename = (
        f"lte{int(teff):05d}-{logg:.2f}{metal_str}"
        f".PHOENIX-ACES-AGSS-COND-2011-HiRes.fits"
    )
    return f"{PHOENIX_BASE}/PHOENIX-ACES-AGSS-COND-2011/{metal_dir}/{filename}"


def _download_file(url, dest, session=None):
    """Download a file with progress indication. Skip if exists."""
    import requests
    if os.path.exists(dest):
        return True

    os.makedirs(os.path.dirname(dest), exist_ok=True)

    sess = session or requests.Session()
    try:
        resp = sess.get(url, stream=True, timeout=120)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"  SKIP {os.path.basename(dest)}: {exc}")
        return False

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(dest + ".partial", "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded / total * 100
                print(f"\r  Downloading {os.path.basename(dest)}: {pct:.0f}%", end="", flush=True)

    os.rename(dest + ".partial", dest)
    print()
    return True


def _read_phoenix_wavelengths(wave_fits_path):
    """Read the shared Phoenix wavelength grid from FITS."""
    from astropy.io import fits
    with fits.open(wave_fits_path) as hdul:
        wave = np.asarray(hdul[0].data, dtype=float)  # Angstroms
    return wave


def _read_phoenix_flux(fits_path):
    """Read flux from a Phoenix HiRes FITS primary HDU.

    Raw flux is in erg/s/cm^2/cm.  We convert to erg/s/cm^2/Å (÷ 1e8).
    """
    from astropy.io import fits
    with fits.open(fits_path) as hdul:
        flux = np.asarray(hdul[0].data, dtype=float)
    # Convert erg/s/cm^2/cm → erg/s/cm^2/Å
    flux /= 1e8
    return flux


def _trim_and_downsample(wavelengths, flux, wl_min, wl_max, n_points):
    """Trim to wavelength range and downsample to n_points."""
    mask = (wavelengths >= wl_min) & (wavelengths <= wl_max)
    wl_trim = wavelengths[mask]
    fl_trim = flux[mask]

    if len(wl_trim) <= n_points:
        return wl_trim, fl_trim

    wl_new = np.linspace(wl_trim[0], wl_trim[-1], n_points)
    fl_new = np.interp(wl_new, wl_trim, fl_trim)
    return wl_new, fl_new


def main():
    parser = argparse.ArgumentParser(
        description="Download and convert Phoenix-ACES spectra for SA3D"
    )
    parser.add_argument("--teff-min", type=int, default=2500)
    parser.add_argument("--teff-max", type=int, default=5000)
    parser.add_argument("--teff-step", type=int, default=100)
    parser.add_argument("--logg", type=str, default="3.5,4.0,4.5,5.0,5.5")
    parser.add_argument("--metals", type=str, default="-1.0,-0.5,0.0,+0.5")
    parser.add_argument("--output-dir", type=str,
                        default=os.path.join(PROJECT_ROOT, "model_grids", "phoenix_cool"))
    parser.add_argument("--wl-min", type=float, default=5000.0)
    parser.add_argument("--wl-max", type=float, default=55000.0)
    parser.add_argument("--n-points", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true",
                        help="List models without downloading")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    teff_values = list(range(args.teff_min, args.teff_max + 1, args.teff_step))
    logg_values = [float(x) for x in args.logg.split(",")]
    metal_values = [float(x) for x in args.metals.split(",")]

    total = len(teff_values) * len(logg_values) * len(metal_values)
    print(f"Phoenix grid: {len(teff_values)} Teff × {len(logg_values)} logg "
          f"× {len(metal_values)} [Fe/H] = {total} models")

    if args.dry_run:
        for teff in teff_values:
            for logg in logg_values:
                for met in metal_values:
                    print(f"  Teff={teff} logg={logg:.1f} [Fe/H]={met:+.1f}")
        print(f"\nTotal: {total} models (dry run, nothing downloaded)")
        return

    import requests
    session = requests.Session()

    spectra_dir = os.path.join(args.output_dir, "spectra")
    os.makedirs(spectra_dir, exist_ok=True)

    # --- Download shared wavelength file ---
    cache_dir = os.path.join(args.output_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    wave_local = os.path.join(cache_dir, "WAVE_PHOENIX-ACES-AGSS-COND-2011.fits")

    print("\n--- Downloading shared wavelength file ---")
    if not _download_file(WAVE_FILE_URL, wave_local, session):
        print("ERROR: Could not download wavelength file. Aborting.")
        sys.exit(1)

    print("Reading wavelength grid...")
    full_wavelengths = _read_phoenix_wavelengths(wave_local)
    print(f"  Full grid: {len(full_wavelengths)} points, "
          f"{full_wavelengths[0]:.1f}–{full_wavelengths[-1]:.1f} Å")

    # --- Download and convert each spectrum ---
    rows = []
    done = 0
    skipped = 0

    for teff in teff_values:
        for logg in logg_values:
            for met in metal_values:
                done += 1
                label = f"[{done}/{total}] Teff={teff} logg={logg:.1f} [Fe/H]={met:+.1f}"
                print(f"\n{label}")

                dat_filename = f"phoenix_T{teff}_g{logg:.1f}_m{met:+.1f}.dat"
                dat_path = os.path.join(spectra_dir, dat_filename)

                # Skip if already converted
                if os.path.exists(dat_path):
                    print("  Already converted, skipping.")
                    rows.append({
                        "filename": dat_filename,
                        "Teff": teff,
                        "logg": logg,
                        "metallicity": met,
                    })
                    continue

                # Download FITS
                url = _phoenix_fits_url(teff, logg, met)
                fits_local = os.path.join(
                    cache_dir,
                    f"lte{teff:05d}-{logg:.2f}{met:+.1f}.fits"
                )
                if not _download_file(url, fits_local, session):
                    skipped += 1
                    continue

                # Read flux
                try:
                    flux = _read_phoenix_flux(fits_local)
                except Exception as exc:
                    logger.warning(f"  Failed to read {fits_local}: {exc}")
                    skipped += 1
                    continue

                if len(flux) != len(full_wavelengths):
                    logger.warning(
                        f"  Wavelength/flux length mismatch: "
                        f"{len(full_wavelengths)} vs {len(flux)}. Skipping."
                    )
                    skipped += 1
                    continue

                # Trim and downsample
                wl_out, fl_out = _trim_and_downsample(
                    full_wavelengths, flux,
                    args.wl_min, args.wl_max, args.n_points,
                )

                # Write two-column .dat
                data = np.column_stack([wl_out, fl_out])
                np.savetxt(dat_path, data, fmt="%.6e",
                           header="wavelength_Angstrom  flux_erg_s_cm2_A")

                rows.append({
                    "filename": dat_filename,
                    "Teff": teff,
                    "logg": logg,
                    "metallicity": met,
                })

                # Remove cached FITS to save disk space
                try:
                    os.remove(fits_local)
                except OSError:
                    pass

    # --- Write index.csv ---
    index_path = os.path.join(args.output_dir, "index.csv")
    with open(index_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["filename", "Teff", "logg", "metallicity"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{'='*60}")
    print(f"Done! Converted {len(rows)} models, skipped {skipped}")
    print(f"Spectra: {spectra_dir}")
    print(f"Index:   {index_path}")


if __name__ == "__main__":
    main()

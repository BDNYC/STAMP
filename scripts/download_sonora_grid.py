#!/usr/bin/env python3
"""Download and convert Sonora Diamondback model spectra for SA3D grid fitting.

Downloads the spectra archive from Zenodo (Morley et al. 2024), extracts
selected models, trims to JWST-relevant wavelength range, downsamples, and
writes two-column .dat files compatible with the SA3D model_grids loader.

The full spectra.zip is ~8.6 GB.  After download the script extracts only
the Teff/logg/metallicity combinations you select and deletes the zip
(unless --keep-zip is passed).

Usage:
    python scripts/download_sonora_grid.py [options]

Options:
    --teff-min    Minimum Teff in K         (default: 900)
    --teff-max    Maximum Teff in K         (default: 2400)
    --teff-step   Teff step size in K       (default: 100)
    --logg        Comma-separated logg vals (default: 3.5,4.0,4.5,5.0,5.5)
    --metals      Comma-separated [M/H]     (default: -0.5,0.0,+0.5)
    --fsed        Comma-separated fsed vals  (default: 2,3,4,8)
    --co          C/O ratio                  (default: 1.0 = solar)
    --output-dir  Output grid directory     (default: model_grids/sonora_diamondback)
    --wl-min      Min wavelength in microns  (default: 0.5)
    --wl-max      Max wavelength in microns  (default: 5.5)
    --n-points    Downsampled wavelength pts (default: 2000)
    --keep-zip    Keep the downloaded zip after extraction
    --dry-run     List files without downloading
    --from-cache  Regenerate .dat files from cached .spec files (no download)

Requires: numpy, requests
Reference: Morley et al. (2024) https://arxiv.org/abs/2402.00758
Data:      https://zenodo.org/records/12735103
"""

import os
import re
import sys
import csv
import argparse
import logging
import zipfile
import io

import math

import numpy as np

logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# Zenodo direct-download URL for the spectra archive
ZENODO_RECORD = "12735103"
SPECTRA_ZIP_URL = f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/spectra.zip/content"


def _sonora_filename(teff, logg, fsed, metal, co):
    """Build the expected filename inside the Sonora spectra archive.

    Naming convention: t{Teff}g{g_mks}f{fsed}_m{metal}_co{co}
    where g_mks = int(10^logg / 100)  (surface gravity in m/s², truncated).
    Examples:
        t900g31f1_m0.0_co1.0      (logg=3.5 → 10^3.5/100 = 31.6 → 31)
        t1100g316f1_m-0.5_co1.0   (logg=4.5 → 10^4.5/100 = 316.2 → 316)
    """
    g_val = int(10**logg / 100)

    # Metallicity formatting: "0.0" for solar, "-0.5", "+0.5"
    if metal == 0.0:
        metal_str = "0.0"
    elif metal > 0:
        metal_str = f"+{metal:.1f}"
    else:
        metal_str = f"{metal:.1f}"

    return f"t{int(teff)}g{g_val}f{fsed}_m{metal_str}_co{co}"


_SONORA_RE = re.compile(
    r"t(\d+)g(\d+)f(\d+)_m([+-]?\d+\.?\d*)_co(\d+\.?\d*)"
)


def _parse_sonora_name(path):
    """Parse Teff, g_mks, fsed, metal, co from a Sonora filename/path.

    Returns dict with parsed values or None if pattern doesn't match.
    """
    basename = os.path.basename(path)
    m = _SONORA_RE.search(basename)
    if not m:
        return None
    return {
        "teff": int(m.group(1)),
        "g_mks": int(m.group(2)),
        "fsed": int(m.group(3)),
        "metal": float(m.group(4)),
        "co": float(m.group(5)),
        "path": path,
    }


def _read_sonora_spectrum(filepath):
    """Read a Sonora Diamondback spectrum file.

    Format: tab-delimited, two columns (wavelength in microns, flux in W/m^2/m).
    Has text header lines (not '#'-prefixed) that must be skipped.
    Returns (wavelength_microns, flux_W_m2_m).
    """
    # Auto-detect number of non-numeric header lines
    skip = 0
    with open(filepath, "r") as f:
        for line in f:
            try:
                float(line.strip().split()[0])
                break
            except (ValueError, IndexError):
                skip += 1
    data = np.loadtxt(filepath, dtype=float, skiprows=skip)
    wavelengths = data[:, 0]  # microns
    flux = data[:, 1]         # W/m^2/m (Fν = 4π × Hν)

    # Ensure ascending wavelength order (Sonora files are descending)
    if len(wavelengths) > 1 and wavelengths[0] > wavelengths[-1]:
        sort_idx = np.argsort(wavelengths)
        wavelengths = wavelengths[sort_idx]
        flux = flux[sort_idx]

    return wavelengths, flux


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


def _download_with_progress(url, dest, session=None):
    """Download a large file with progress bar. Skip if exists."""
    import requests

    if os.path.exists(dest):
        print(f"  Archive already exists: {dest}")
        return True

    os.makedirs(os.path.dirname(dest), exist_ok=True)

    sess = session or requests.Session()
    try:
        resp = sess.get(url, stream=True, timeout=600)
        resp.raise_for_status()
    except Exception as exc:
        logger.error(f"Download failed: {exc}")
        return False

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    print(f"  Downloading spectra.zip ({total / 1e9:.1f} GB)...")
    with open(dest + ".partial", "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded / total * 100
                bar_len = 40
                filled = int(bar_len * downloaded / total)
                bar = "█" * filled + "░" * (bar_len - filled)
                print(f"\r  [{bar}] {pct:.1f}% ({downloaded / 1e9:.2f}/{total / 1e9:.2f} GB)",
                      end="", flush=True)
    print()

    os.rename(dest + ".partial", dest)
    return True


_GMKS_TO_LOGG = {31: 3.5, 100: 4.0, 316: 4.5, 1000: 5.0, 3162: 5.5}


def _from_cache(output_dir, wl_min, wl_max, n_points):
    """Regenerate .dat files from cached .spec files without re-downloading."""
    cache_dir = os.path.join(output_dir, ".cache")
    spectra_dir = os.path.join(output_dir, "spectra")

    if not os.path.isdir(cache_dir):
        print(f"ERROR: Cache directory not found: {cache_dir}")
        sys.exit(1)

    spec_files = [f for f in os.listdir(cache_dir) if f.endswith(".spec")]
    if not spec_files:
        print(f"ERROR: No .spec files found in {cache_dir}")
        sys.exit(1)

    print(f"Found {len(spec_files)} cached .spec files in {cache_dir}")

    # Clean existing spectra
    if os.path.isdir(spectra_dir):
        old_dats = [f for f in os.listdir(spectra_dir) if f.endswith(".dat")]
        if old_dats:
            print(f"Removing {len(old_dats)} existing .dat files...")
            for f in old_dats:
                os.remove(os.path.join(spectra_dir, f))
    os.makedirs(spectra_dir, exist_ok=True)

    rows = []
    done = 0
    skipped = 0

    for spec_file in sorted(spec_files):
        done += 1
        parsed = _parse_sonora_name(spec_file)
        if parsed is None:
            print(f"[{done}/{len(spec_files)}] SKIP — cannot parse: {spec_file}")
            skipped += 1
            continue

        g_mks = parsed["g_mks"]
        logg = _GMKS_TO_LOGG.get(g_mks)
        if logg is None:
            # Fallback: compute from g_mks
            logg = round(math.log10(g_mks * 100), 1)

        teff = parsed["teff"]
        met = parsed["metal"]
        fsed = parsed["fsed"]
        co = parsed["co"]

        dat_filename = f"sonora_T{teff}_g{logg:.1f}_m{met:+.1f}_f{fsed}.dat"
        dat_path = os.path.join(spectra_dir, dat_filename)
        label = f"[{done}/{len(spec_files)}] Teff={teff} logg={logg:.1f} [M/H]={met:+.1f} fsed={fsed}"

        try:
            spec_path = os.path.join(cache_dir, spec_file)
            wl, flux = _read_sonora_spectrum(spec_path)

            wl_out, fl_out = _trim_and_downsample(wl, flux, wl_min, wl_max, n_points)

            # Convert wavelength from microns to Angstroms for consistency
            # with the Phoenix grid (model_grids.py auto-converts A -> um)
            wl_angstrom = wl_out * 1e4

            data = np.column_stack([wl_angstrom, fl_out])
            np.savetxt(dat_path, data, fmt="%.6e",
                       header="wavelength_Angstrom  flux_W_m2_m")

            rows.append({
                "filename": dat_filename,
                "Teff": teff,
                "logg": logg,
                "metallicity": met,
                "fsed": fsed,
            })
            print(f"{label} — OK ({len(set(fl_out))} unique flux values)")

        except Exception as exc:
            logger.warning(f"{label} — FAILED: {exc}")
            skipped += 1
            continue

    # Write index.csv
    index_path = os.path.join(output_dir, "index.csv")
    with open(index_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["filename", "Teff", "logg", "metallicity", "fsed"]
        )
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["Teff"], r["logg"], r["metallicity"], r["fsed"])))

    print(f"\n{'=' * 60}")
    print(f"Done! Converted {len(rows)} models, skipped {skipped}")
    print(f"Spectra: {spectra_dir}")
    print(f"Index:   {index_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Download and convert Sonora Diamondback spectra for SA3D"
    )
    parser.add_argument("--teff-min", type=int, default=900)
    parser.add_argument("--teff-max", type=int, default=2400)
    parser.add_argument("--teff-step", type=int, default=100)
    parser.add_argument("--logg", type=str, default="3.5,4.0,4.5,5.0,5.5")
    parser.add_argument("--metals", type=str, default="-0.5,0.0,+0.5")
    parser.add_argument("--fsed", type=str, default="2,3,4,8",
                        help="Comma-separated fsed values (default: 2,3,4,8)")
    parser.add_argument("--co", type=float, default=1.0)
    parser.add_argument("--output-dir", type=str,
                        default=os.path.join(PROJECT_ROOT, "model_grids", "sonora_diamondback"))
    parser.add_argument("--wl-min", type=float, default=0.5,
                        help="Min wavelength in microns (default: 0.5)")
    parser.add_argument("--wl-max", type=float, default=5.5,
                        help="Max wavelength in microns (default: 0.5)")
    parser.add_argument("--n-points", type=int, default=2000)
    parser.add_argument("--keep-zip", action="store_true",
                        help="Keep the downloaded zip after extraction")
    parser.add_argument("--dry-run", action="store_true",
                        help="List models without downloading")
    parser.add_argument("--from-cache", action="store_true",
                        help="Regenerate .dat files from cached .spec files (no download)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.from_cache:
        _from_cache(args.output_dir, args.wl_min, args.wl_max, args.n_points)
        return

    teff_values = list(range(args.teff_min, args.teff_max + 1, args.teff_step))
    logg_values = [float(x) for x in args.logg.split(",")]
    metal_values = [float(x) for x in args.metals.split(",")]
    fsed_values = [int(x) for x in args.fsed.split(",")]

    total = len(teff_values) * len(logg_values) * len(metal_values) * len(fsed_values)
    print(f"Sonora Diamondback grid: {len(teff_values)} Teff x {len(logg_values)} logg "
          f"x {len(metal_values)} [M/H] x {len(fsed_values)} fsed = {total} models")
    print(f"  Teff: {teff_values[0]}–{teff_values[-1]} K (step {args.teff_step})")
    print(f"  logg: {logg_values}")
    print(f"  [M/H]: {metal_values}")
    print(f"  fsed: {fsed_values}, C/O: {args.co}")

    # Build list of expected filenames
    model_list = []
    for teff in teff_values:
        for logg in logg_values:
            for met in metal_values:
                for fsed in fsed_values:
                    fname = _sonora_filename(teff, logg, fsed, met, args.co)
                    model_list.append({
                        "sonora_name": fname,
                        "teff": teff,
                        "logg": logg,
                        "metal": met,
                        "fsed": fsed,
                    })

    if args.dry_run:
        print(f"\nModels to download:")
        for m in model_list:
            print(f"  Teff={m['teff']} logg={m['logg']:.1f} [M/H]={m['metal']:+.1f} fsed={m['fsed']}  ->  {m['sonora_name']}")
        print(f"\nTotal: {total} models (dry run, nothing downloaded)")
        print(f"Source: https://zenodo.org/records/{ZENODO_RECORD}")
        return

    # --- Download spectra.zip ---
    import requests
    session = requests.Session()

    cache_dir = os.path.join(args.output_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    zip_path = os.path.join(cache_dir, "spectra.zip")

    print(f"\n--- Downloading Sonora Diamondback spectra archive ---")
    print(f"Source: https://zenodo.org/records/{ZENODO_RECORD}")
    if not _download_with_progress(SPECTRA_ZIP_URL, zip_path, session):
        print("ERROR: Could not download spectra.zip. Aborting.")
        sys.exit(1)

    # --- Extract and convert selected models ---
    spectra_dir = os.path.join(args.output_dir, "spectra")
    os.makedirs(spectra_dir, exist_ok=True)

    print(f"\n--- Extracting and converting models ---")
    rows = []
    done = 0
    skipped = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        # --- Zip content discovery ---
        all_names = zf.namelist()
        print(f"  Archive contains {len(all_names)} entries")
        print(f"  Sample filenames:")
        for sample in all_names[:10]:
            print(f"    {sample}")

        # Build lookup: (teff, g_mks, fsed, metal) -> zip path
        zip_lookup = {}
        for zname in all_names:
            parsed = _parse_sonora_name(zname)
            if parsed is not None:
                key = (parsed["teff"], parsed["g_mks"], parsed["fsed"], parsed["metal"])
                zip_lookup[key] = zname

        print(f"  Parsed {len(zip_lookup)} model spectra from archive\n")

        for m in model_list:
            done += 1
            sonora_name = m["sonora_name"]
            teff = m["teff"]
            logg = m["logg"]
            met = m["metal"]
            fsed = m["fsed"]

            label = f"[{done}/{total}] Teff={teff} logg={logg:.1f} [M/H]={met:+.1f} fsed={fsed}"

            dat_filename = f"sonora_T{teff}_g{logg:.1f}_m{met:+.1f}_f{fsed}.dat"
            dat_path = os.path.join(spectra_dir, dat_filename)

            # Skip if already converted
            if os.path.exists(dat_path):
                print(f"{label} — already converted")
                rows.append({
                    "filename": dat_filename,
                    "Teff": teff,
                    "logg": logg,
                    "metallicity": met,
                    "fsed": fsed,
                })
                continue

            # Match by parsed parameter values (robust to path/extension variations)
            g_mks = int(10**logg / 100)
            lookup_key = (teff, g_mks, fsed, met)
            found_path = zip_lookup.get(lookup_key)

            # Handle minor rounding differences (e.g., g3162 vs g3160 for logg=5.5)
            if found_path is None:
                best_delta = None
                for key, path in zip_lookup.items():
                    if key[0] == teff and key[2] == fsed and key[3] == met:
                        delta = abs(key[1] - g_mks)
                        if delta <= 5 and (best_delta is None or delta < best_delta):
                            best_delta = delta
                            found_path = path

            if found_path is None:
                print(f"{label} — NOT FOUND in archive (expected: {sonora_name}, key: {lookup_key})")
                skipped += 1
                continue

            print(f"{label} — extracting {found_path}")

            try:
                # Extract to temp file, read, convert
                tmp_path = os.path.join(cache_dir, os.path.basename(found_path))
                with zf.open(found_path) as src, open(tmp_path, "wb") as dst:
                    dst.write(src.read())

                wl, flux = _read_sonora_spectrum(tmp_path)

                # Sonora wavelengths are already in microns — trim and downsample
                wl_out, fl_out = _trim_and_downsample(
                    wl, flux,
                    args.wl_min, args.wl_max, args.n_points,
                )

                # Convert wavelength from microns to Angstroms for consistency
                # with the Phoenix grid (model_grids.py auto-converts Å → μm)
                wl_angstrom = wl_out * 1e4

                # Write two-column .dat (Angstroms, flux)
                data = np.column_stack([wl_angstrom, fl_out])
                np.savetxt(dat_path, data, fmt="%.6e",
                           header="wavelength_Angstrom  flux_W_m2_m")

                rows.append({
                    "filename": dat_filename,
                    "Teff": teff,
                    "logg": logg,
                    "metallicity": met,
                    "fsed": fsed,
                })

                # Clean up temp file
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

            except Exception as exc:
                logger.warning(f"  Failed to process {sonora_name}: {exc}")
                skipped += 1
                continue

    # --- Write index.csv ---
    index_path = os.path.join(args.output_dir, "index.csv")
    with open(index_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["filename", "Teff", "logg", "metallicity", "fsed"]
        )
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["Teff"], r["logg"], r["metallicity"], r["fsed"])))

    # --- Clean up zip (only after successful extraction) ---
    if not args.keep_zip and os.path.exists(zip_path) and len(rows) > 0:
        print(f"\nRemoving spectra.zip to save disk space...")
        os.remove(zip_path)
    elif not args.keep_zip and len(rows) == 0:
        print(f"\nKeeping spectra.zip (no models extracted — re-run to retry)")

    print(f"\n{'=' * 60}")
    print(f"Done! Converted {len(rows)} models, skipped {skipped}")
    print(f"Spectra: {spectra_dir}")
    print(f"Index:   {index_path}")
    print(f"\nTo validate:")
    print(f"  python scripts/validate_fitting.py --grid sonora_diamondback --teff 1100 --logg 4.5 --feh 0.0")


if __name__ == "__main__":
    main()

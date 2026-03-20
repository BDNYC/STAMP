#!/usr/bin/env python3
"""Shared utilities for model-grid download/conversion scripts.

All download scripts produce:
    model_grids/<grid_name>/
        index.csv                 # filename,Teff,logg,metallicity[,extras]
        spectra/<name>.dat        # 2-column: wavelength (Angstroms), flux

This module centralises the repeated download, trim, write, and parse logic.
"""

import os
import sys
import csv
import time
import argparse
import logging
import xml.etree.ElementTree as ET

import numpy as np

logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# Default wavelength range and downsampling for all grids
DEFAULT_WL_MIN = 0.5     # microns
DEFAULT_WL_MAX = 5.5     # microns
DEFAULT_N_POINTS = 2000

# SVO Theoretical Spectra Server base
SVO_BASE = "http://svo2.cab.inta-csic.es/theory/newov2"


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_with_progress(url, dest, session=None, label=None, timeout=600):
    """Stream-download *url* to *dest* with a progress bar.

    Uses a ``.partial`` intermediate to avoid corrupt files on interrupt.
    Skips if *dest* already exists.  Returns True on success.
    """
    import requests

    if os.path.exists(dest):
        if label:
            print(f"  {label}: already downloaded")
        return True

    os.makedirs(os.path.dirname(dest), exist_ok=True)

    sess = session or requests.Session()
    try:
        resp = sess.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        logger.error(f"Download failed ({url}): {exc}")
        return False

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    display = label or os.path.basename(dest)

    if total > 0:
        size_str = (f"{total / 1e9:.2f} GB" if total > 5e8
                    else f"{total / 1e6:.1f} MB")
        print(f"  Downloading {display} ({size_str})...")
    else:
        print(f"  Downloading {display}...")

    partial = dest + ".partial"
    with open(partial, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded / total * 100
                bar_len = 40
                filled = int(bar_len * downloaded / total)
                bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
                print(f"\r  [{bar}] {pct:.1f}%", end="", flush=True)
    print()

    os.rename(partial, dest)
    return True


# ---------------------------------------------------------------------------
# Spectral processing
# ---------------------------------------------------------------------------

def trim_and_downsample(wl_um, flux, wl_min=None, wl_max=None, n_pts=None):
    """Trim wavelength range (microns) and downsample.

    Returns (wl_angstrom, flux) — wavelengths converted to Angstroms.
    """
    wl_min = wl_min if wl_min is not None else DEFAULT_WL_MIN
    wl_max = wl_max if wl_max is not None else DEFAULT_WL_MAX
    n_pts = n_pts if n_pts is not None else DEFAULT_N_POINTS

    mask = (wl_um >= wl_min) & (wl_um <= wl_max)
    wl_trim = wl_um[mask]
    fl_trim = flux[mask]

    if len(wl_trim) == 0:
        return np.array([]), np.array([])

    if len(wl_trim) > n_pts:
        wl_new = np.linspace(wl_trim[0], wl_trim[-1], n_pts)
        fl_new = np.interp(wl_new, wl_trim, fl_trim)
        wl_trim, fl_trim = wl_new, fl_new

    # Convert microns → Angstroms
    return wl_trim * 1e4, fl_trim


def trim_and_downsample_angstrom(wl_a, flux, wl_min_a=None, wl_max_a=None,
                                  n_pts=None):
    """Like trim_and_downsample but input/output are in Angstroms."""
    wl_min_a = wl_min_a if wl_min_a is not None else DEFAULT_WL_MIN * 1e4
    wl_max_a = wl_max_a if wl_max_a is not None else DEFAULT_WL_MAX * 1e4
    n_pts = n_pts if n_pts is not None else DEFAULT_N_POINTS

    mask = (wl_a >= wl_min_a) & (wl_a <= wl_max_a)
    wl_trim = wl_a[mask]
    fl_trim = flux[mask]

    if len(wl_trim) == 0:
        return np.array([]), np.array([])

    if len(wl_trim) > n_pts:
        wl_new = np.linspace(wl_trim[0], wl_trim[-1], n_pts)
        fl_new = np.interp(wl_new, wl_trim, fl_trim)
        wl_trim, fl_trim = wl_new, fl_new

    return wl_trim, fl_trim


# ---------------------------------------------------------------------------
# .dat and index.csv writers
# ---------------------------------------------------------------------------

def write_dat_file(path, wl_angstrom, flux, unit_tag="flux_erg_s_cm2_A"):
    """Write a standardised two-column .dat file.

    Parameters
    ----------
    unit_tag : str
        One of ``flux_erg_s_cm2_A`` or ``flux_W_m2_m``.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = np.column_stack([wl_angstrom, flux])
    np.savetxt(path, data, fmt="%.6e",
               header=f"wavelength_Angstrom  {unit_tag}")


def write_index_csv(path, rows, fieldnames):
    """Write a sorted index.csv.

    *rows* is a list of dicts.  Sorted by Teff, then remaining columns.
    """
    sort_keys = [k for k in fieldnames if k != "filename"]
    rows_sorted = sorted(rows, key=lambda r: tuple(
        float(r.get(k, 0)) if k != "filename" else r.get(k, "")
        for k in sort_keys
    ))
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_sorted)


# ---------------------------------------------------------------------------
# Text spectrum reader
# ---------------------------------------------------------------------------

def read_text_spectrum(filepath):
    """Generic reader for 2-column text spectra with header auto-detection.

    Skips leading non-numeric lines.  Returns (col0, col1) as numpy arrays.
    """
    skip = 0
    with open(filepath, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                skip += 1
                continue
            try:
                float(stripped.split()[0])
                break
            except (ValueError, IndexError):
                skip += 1

    data = np.loadtxt(filepath, dtype=float, skiprows=skip)
    return data[:, 0], data[:, 1]


# ---------------------------------------------------------------------------
# SVO VOTable helpers
# ---------------------------------------------------------------------------

def parse_svo_votable(xml_bytes):
    """Parse an SVO SSAP VOTable listing into model metadata.

    Returns a list of dicts, each with normalised keys:
    ``Teff``, ``logg``, ``meta``, ``fid``, plus raw VOTable field names.

    SVO returns lowercase ``teff``; this function adds a ``Teff`` alias.
    The ``fid`` is extracted from the ``Access.Reference`` URL.
    """
    import re

    root = ET.fromstring(xml_bytes)
    # Namespace handling — SVO uses the VOTable namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    # Find TABLE > FIELD definitions to get column names
    table = root.find(f".//{ns}TABLE")
    if table is None:
        table = root.find(f".//{ns}RESOURCE/{ns}TABLE")
    if table is None:
        return []

    fields = [f.attrib.get("name", f"col{i}")
              for i, f in enumerate(table.findall(f"{ns}FIELD"))]

    rows = []
    for tr in table.findall(f".//{ns}TABLEDATA/{ns}TR"):
        tds = tr.findall(f"{ns}TD")
        row = {}
        for i, td in enumerate(tds):
            if i < len(fields):
                row[fields[i]] = td.text.strip() if td.text else ""

        # Normalise: SVO uses lowercase 'teff' — add 'Teff' alias
        if "teff" in row and "Teff" not in row:
            row["Teff"] = row["teff"]

        # Extract fid from Access.Reference URL (e.g. '...&fid=42')
        access_ref = row.get("Access.Reference", "")
        if access_ref and "fid" not in row:
            fid_match = re.search(r'fid=(\d+)', access_ref)
            if fid_match:
                row["fid"] = fid_match.group(1)

        rows.append(row)

    return rows


def download_svo_spectrum(base_url, fid, session=None, max_retries=3,
                          delay=0.5):
    """Download + parse a single SVO spectrum by ``fid``.

    Returns (wavelength_angstrom, flux) numpy arrays.
    """
    import requests

    url = f"{base_url}&fid={fid}"
    sess = session or requests.Session()

    for attempt in range(max_retries):
        try:
            resp = sess.get(url, timeout=60)
            resp.raise_for_status()
            break
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = delay * (2 ** attempt)
                logger.debug(f"  Retry {attempt + 1} for fid={fid} in {wait}s: {exc}")
                time.sleep(wait)
            else:
                raise

    # Parse VOTable spectrum
    root = ET.fromstring(resp.content)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    table = root.find(f".//{ns}TABLE")
    if table is None:
        table = root.find(f".//{ns}RESOURCE/{ns}TABLE")

    fields = [f.attrib.get("name", "").lower()
              for f in table.findall(f"{ns}FIELD")]

    wl_idx = None
    fl_idx = None
    for i, name in enumerate(fields):
        if name in ("wavelength", "wave", "lambda"):
            wl_idx = i
        elif name in ("flux", "flam", "sed"):
            fl_idx = i
    if wl_idx is None:
        wl_idx = 0
    if fl_idx is None:
        fl_idx = 1

    wavelengths = []
    fluxes = []
    for tr in table.findall(f".//{ns}TABLEDATA/{ns}TR"):
        tds = tr.findall(f"{ns}TD")
        wavelengths.append(float(tds[wl_idx].text))
        fluxes.append(float(tds[fl_idx].text))

    time.sleep(delay)  # Rate limiting
    return np.array(wavelengths), np.array(fluxes)


# ---------------------------------------------------------------------------
# Argparse helpers
# ---------------------------------------------------------------------------

def add_common_args(parser):
    """Add standard flags shared by all grid download scripts."""
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output grid directory (default: auto)")
    parser.add_argument("--wl-min", type=float, default=DEFAULT_WL_MIN,
                        help=f"Min wavelength in microns (default: {DEFAULT_WL_MIN})")
    parser.add_argument("--wl-max", type=float, default=DEFAULT_WL_MAX,
                        help=f"Max wavelength in microns (default: {DEFAULT_WL_MAX})")
    parser.add_argument("--n-points", type=int, default=DEFAULT_N_POINTS,
                        help=f"Downsampled wavelength points (default: {DEFAULT_N_POINTS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="List models without downloading")
    parser.add_argument("--keep-raw", action="store_true",
                        help="Keep raw downloaded files after processing")
    return parser


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(output_dir, n_ok, n_skip):
    """Print completion stats and disk usage."""
    spectra_dir = os.path.join(output_dir, "spectra")
    index_path = os.path.join(output_dir, "index.csv")

    # Compute disk usage
    total_bytes = 0
    if os.path.isdir(spectra_dir):
        for f in os.listdir(spectra_dir):
            fp = os.path.join(spectra_dir, f)
            if os.path.isfile(fp):
                total_bytes += os.path.getsize(fp)

    print(f"\n{'=' * 60}")
    print(f"Done! Converted {n_ok} models, skipped {n_skip}")
    print(f"Spectra: {spectra_dir}")
    print(f"Index:   {index_path}")
    if total_bytes > 0:
        print(f"Disk:    {total_bytes / 1e6:.1f} MB")
    print(f"\nTo validate:")
    print(f"  python -c \"from model_grids import load_grid_from_directory; "
          f"g = load_grid_from_directory('{output_dir}'); "
          f"print(g['n_models'], g['flux_unit'], len(g['wavelengths']))\"")

    # Cleanup hint
    cache_dir = os.path.join(output_dir, ".cache")
    if os.path.isdir(cache_dir):
        cache_bytes = sum(
            os.path.getsize(os.path.join(cache_dir, f))
            for f in os.listdir(cache_dir)
            if os.path.isfile(os.path.join(cache_dir, f))
        )
        if cache_bytes > 1e6:
            print(f"\nTo free {cache_bytes / 1e6:.1f} MB of cached raw files:")
            print(f"  rm -rf {cache_dir}")

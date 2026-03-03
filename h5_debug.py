#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
h5_debug.py
-----------
Inspect the HDF5 file at the hardcoded path and write a human-readable report of:
- file/group/dataset hierarchy
- attributes at each level
- dataset shapes/dtypes
- small value previews

Also checks for STAMP-expected datasets:
  calibrated_optspec, eureka_wave_1d, time, calibrated_opterr

Output is written as "h5_structure.txt" in the same folder as the .h5 file.
"""

import os
import sys
import numpy as np

try:
    import h5py
except Exception:
    print("ERROR: This script requires the 'h5py' package. Install with: pip install h5py")
    sys.exit(1)

# Hardcoded path to your HDF5 file:
H5_PATH = r"/Users/anthonymunozperez/PycharmProjects/SA3D/VHS1256_spectra_for_niall-August12/VHS1256_PRISM_Aug12.h5"

# Output report path (same directory as the H5 file)
OUT_PATH = os.path.abspath(os.path.join(os.path.dirname(H5_PATH), "h5_structure.txt"))

EXPECTED_KEYS = [
    "calibrated_optspec",   # 2D: (time/integration, wavelength)
    "eureka_wave_1d",       # 1D: wavelength grid
    "time",                 # 1D: time per integration
    "calibrated_opterr",    # 2D: same shape as calibrated_optspec
]

POSSIBLE_ALIASES = [
    "optspec", "spectrum", "flux", "flux_opt", "flux_calibrated",
    "wave", "wavelength", "wlen", "lambda",
    "err", "error", "flux_error", "sigma",
    "t", "mjd", "time_bjd", "time_mjd", "int_time", "bjd", "mjd_utc"
]

def summarize_array(arr, max_elems=12):
    """Return a compact preview of array values without overwhelming the report."""
    try:
        flat = np.ravel(arr)
        n = min(flat.size, max_elems)
        preview = flat[:n]
        with np.printoptions(precision=6, suppress=True, threshold=n):
            return np.array2string(preview, separator=", ")
    except Exception as e:
        return f"<preview failed: {e}>"

def write_line(f, s=""):
    f.write(s + "\n")

def walk_h5(name, obj, f, level=0):
    """Recursively walk groups and datasets, logging structure, attributes, and previews."""
    indent_spaces = "  " * level
    if isinstance(obj, h5py.Group):
        write_line(f, f"{indent_spaces}Group: {name}")
        # Group attributes
        if obj.attrs:
            write_line(f, f"{indent_spaces}  Attributes:")
            for k, v in obj.attrs.items():
                try:
                    vv = v.tolist() if hasattr(v, "tolist") else v
                    write_line(f, f"{indent_spaces}    - {k}: {vv}")
                except Exception as e:
                    write_line(f, f"{indent_spaces}    - {k}: <unprintable attr: {e}>")
        else:
            write_line(f, f"{indent_spaces}  (no attributes)")
        for key in obj.keys():
            try:
                walk_h5(f"{name}/{key}", obj[key], f, level+1)
            except Exception as e:
                write_line(f, f"{indent_spaces}  !! Error accessing {name}/{key}: {e}")
    elif isinstance(obj, h5py.Dataset):
        # Dataset info
        write_line(f, f"{indent_spaces}Dataset: {name}")
        try:
            shape = obj.shape
            dtype = obj.dtype
            write_line(f, f"{indent_spaces}  shape: {shape}")
            write_line(f, f"{indent_spaces}  dtype: {dtype}")
        except Exception as e:
            write_line(f, f"{indent_spaces}  <failed to read shape/dtype: {e}>")

        # Dataset attributes
        if obj.attrs:
            write_line(f, f"{indent_spaces}  Attributes:")
            for k, v in obj.attrs.items():
                try:
                    vv = v.tolist() if hasattr(v, "tolist") else v
                    write_line(f, f"{indent_spaces}    - {k}: {vv}")
                except Exception as e:
                    write_line(f, f"{indent_spaces}    - {k}: <unprintable attr: {e}>")
        else:
            write_line(f, f"{indent_spaces}  (no attributes)")

        # Preview values
        try:
            data = obj[()]
            write_line(f, f"{indent_spaces}  preview: {summarize_array(data)}")
        except Exception as e:
            try:
                idx = tuple(slice(0, 1) for _ in range(len(obj.shape))) if obj.shape else ()
                data = obj[idx]
                write_line(f, f"{indent_spaces}  preview (partial): {summarize_array(data)}")
            except Exception as e2:
                write_line(f, f"{indent_spaces}  <failed to preview values: {e2}>")
    else:
        write_line(f, f"{indent_spaces}{type(obj)}: {name} (unhandled)")

def check_expected_datasets(h5):
    """Return a dict showing presence, shapes, and simple compatibility checks for expected datasets."""
    report = {}
    for key in EXPECTED_KEYS:
        found_path = None
        def finder(name, obj):
            nonlocal found_path
            if isinstance(obj, h5py.Dataset) and name.split("/")[-1] == key:
                found_path = name
        h5.visititems(finder)
        entry = {"exists": bool(found_path), "path": found_path, "shape": None, "dtype": None}
        if found_path:
            ds = h5[found_path]
            entry["shape"] = tuple(ds.shape)
            entry["dtype"] = str(ds.dtype)
        report[key] = entry
    return report

def scan_possible_aliases(h5):
    """List datasets whose terminal names match POSSIBLE_ALIASES (to help spot mismatches)."""
    hits = {}
    aliases = set(POSSIBLE_ALIASES)
    def visitor(name, obj):
        if isinstance(obj, h5py.Dataset):
            base = name.split("/")[-1].lower()
            if base in aliases:
                hits.setdefault(base, []).append(name)
    h5.visititems(visitor)
    return hits

def main():
    if not os.path.isfile(H5_PATH):
        print(f"ERROR: File not found:\n{H5_PATH}")
        sys.exit(1)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    with h5py.File(H5_PATH, "r") as h5, open(OUT_PATH, "w", encoding="utf-8") as f:
        write_line(f, "HDF5 STRUCTURE REPORT")
        write_line(f, f"Source file: {H5_PATH}")
        write_line(f, "")

        # File-level attributes
        write_line(f, "File-level attributes:")
        if h5.attrs:
            for k, v in h5.attrs.items():
                try:
                    vv = v.tolist() if hasattr(v, "tolist") else v
                    write_line(f, f"  - {k}: {vv}")
                except Exception as e:
                    write_line(f, f"  - {k}: <unprintable attr: {e}>")
        else:
            write_line(f, "  (no attributes)")
        write_line(f)

        # Expected datasets section
        write_line(f, "=== Expected datasets check ===")
        exp = check_expected_datasets(h5)
        for key, info in exp.items():
            write_line(f, f"- {key}: exists={info['exists']} path={info['path']} shape={info['shape']} dtype={info['dtype']}")
        write_line(f)

        # Alias scan
        write_line(f, "=== Possible alias datasets (by common names) ===")
        aliases = scan_possible_aliases(h5)
        if aliases:
            for base, paths in aliases.items():
                write_line(f, f"- {base}:")
                for p in paths:
                    write_line(f, f"    {p}")
        else:
            write_line(f, "(none found)")
        write_line(f)

        # Full walk
        write_line(f, "=== Full hierarchy walk ===")
        write_line(f, "(Groups, datasets, attributes, dtypes, shapes, and sample values)")
        write_line(f)
        walk_h5("/", h5["/"], f, level=0)

    # Print the absolute path to the report as requested
    print(OUT_PATH)

if __name__ == "__main__":
    main()

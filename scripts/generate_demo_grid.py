#!/usr/bin/env python3
"""Generate a synthetic blackbody demo grid for SA3D model fitting.

Creates Planck blackbody spectra over a temperature/gravity grid and writes
them as two-column .dat files (wavelength_Angstrom, flux) compatible with
the SA3D model_grids loader.  Produces index.csv + spectra/ in
model_grids/blackbody_demo/.

Usage:
    python scripts/generate_demo_grid.py
"""

import os
import csv
import numpy as np

# ---------------------------------------------------------------------------
# Grid parameters
# ---------------------------------------------------------------------------
TEFF_VALUES = [2500, 3000, 3200, 3500, 3800, 4000, 4500, 5000]  # K
LOGG_VALUES = [4.0, 4.5, 5.0]                                    # log(cm/s^2)
METALLICITY = 0.0                                                 # solar

# Wavelength grid: 0.5 – 5.5 microns in Angstroms, 500 points
WL_MIN_ANGSTROM = 5_000.0   # 0.5 µm
WL_MAX_ANGSTROM = 55_000.0  # 5.5 µm
N_WAVELENGTHS = 500

# Physical constants (CGS)
H = 6.62607015e-27   # erg·s
C = 2.99792458e10     # cm/s
K_B = 1.380649e-16    # erg/K

# Output paths (relative to SA3D project root)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
GRID_DIR = os.path.join(PROJECT_ROOT, "model_grids", "blackbody_demo")
SPECTRA_DIR = os.path.join(GRID_DIR, "spectra")


def planck_flam(wavelength_angstrom, teff):
    """Planck function B_lambda in erg/s/cm^2/Å/sr.

    Parameters
    ----------
    wavelength_angstrom : array-like
        Wavelengths in Angstroms.
    teff : float
        Effective temperature in Kelvin.

    Returns
    -------
    numpy.ndarray
        Spectral radiance in erg/s/cm^2/Å/sr.
    """
    lam_cm = np.asarray(wavelength_angstrom, dtype=float) * 1e-8  # Å → cm
    exponent = H * C / (lam_cm * K_B * teff)
    # Clip exponent to avoid overflow
    exponent = np.clip(exponent, 0, 500)
    B_lam = (2.0 * H * C**2 / lam_cm**5) / (np.exp(exponent) - 1.0)
    # Convert from per-cm to per-Å: divide by 1e8
    B_lam_angstrom = B_lam * 1e-8
    return B_lam_angstrom


def main():
    os.makedirs(SPECTRA_DIR, exist_ok=True)

    wavelengths = np.linspace(WL_MIN_ANGSTROM, WL_MAX_ANGSTROM, N_WAVELENGTHS)

    rows = []
    for teff in TEFF_VALUES:
        for logg in LOGG_VALUES:
            filename = f"bb_T{teff}_g{logg:.1f}.dat"
            filepath = os.path.join(SPECTRA_DIR, filename)

            flux = planck_flam(wavelengths, teff)

            # Scale by a logg-dependent dilution factor (purely cosmetic —
            # higher gravity → slightly lower flux normalisation)
            scale = 10.0 ** (-(logg - 4.5) * 0.3)
            flux *= scale

            data = np.column_stack([wavelengths, flux])
            np.savetxt(filepath, data, fmt="%.6e",
                       header="wavelength_Angstrom  flux_erg_s_cm2_A")

            rows.append({
                "filename": filename,
                "Teff": teff,
                "logg": logg,
                "metallicity": METALLICITY,
            })

    # Write index.csv
    index_path = os.path.join(GRID_DIR, "index.csv")
    with open(index_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "Teff", "logg", "metallicity"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} blackbody spectra in {SPECTRA_DIR}")
    print(f"Index written to {index_path}")


if __name__ == "__main__":
    main()

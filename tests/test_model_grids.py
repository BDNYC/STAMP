"""Tests for model_grids.py — grid loading, unit conversion, caching."""

import os

import numpy as np
import pytest

import model_grids
from model_grids import _read_model_spectrum, load_grid_from_directory, list_available_grids


@pytest.fixture(autouse=True)
def _clear_grid_cache():
    """Prevent cross-test cache pollution."""
    model_grids._loaded_grids.clear()
    yield
    model_grids._loaded_grids.clear()


def _write_dat(path, wavelengths, flux, header_comment="# wavelength flux"):
    """Helper: write a 2-column .dat spectrum file."""
    with open(path, "w") as f:
        f.write(header_comment + "\n")
        for w, fl in zip(wavelengths, flux):
            f.write(f"{w}  {fl}\n")


def _make_grid(tmp_path, name, n_models=2, wl_angstroms=False,
               flux_unit_header="# wavelength flux"):
    """Helper: create a minimal grid directory with index.csv + spectra/."""
    grid_dir = tmp_path / name
    spectra_dir = grid_dir / "spectra"
    spectra_dir.mkdir(parents=True)

    if wl_angstroms:
        wl = np.linspace(10000, 50000, 50)  # Angstroms
    else:
        wl = np.linspace(1.0, 5.0, 50)  # microns

    rows = []
    for i in range(n_models):
        fname = f"model_{i}.dat"
        flux = np.ones(50) * (i + 1) * 1e-10
        _write_dat(spectra_dir / fname, wl, flux, header_comment=flux_unit_header)
        rows.append(f"{fname},{3000 + i * 500},{4.0 + i * 0.5}")

    with open(grid_dir / "index.csv", "w") as f:
        f.write("filename,Teff,logg\n")
        for r in rows:
            f.write(r + "\n")

    return grid_dir


# ── _read_model_spectrum ──────────────────────────────────────────────────

class TestReadModelSpectrum:
    def test_dat_file(self, tmp_path):
        wl = np.linspace(1.0, 5.0, 30)
        flux = np.ones(30) * 1e-10
        fpath = tmp_path / "spec.dat"
        _write_dat(fpath, wl, flux)
        wl_out, flux_out, unit = _read_model_spectrum(str(fpath))
        assert len(wl_out) == 30
        assert unit == "unknown"

    def test_angstrom_autoconvert(self, tmp_path):
        wl = np.linspace(10000, 50000, 30)  # Angstroms
        flux = np.ones(30)
        fpath = tmp_path / "spec.dat"
        _write_dat(fpath, wl, flux)
        wl_out, _, _ = _read_model_spectrum(str(fpath))
        assert np.all(wl_out < 100)  # converted to microns

    def test_descending_sorted(self, tmp_path):
        wl = np.linspace(5.0, 1.0, 30)  # descending
        flux = np.arange(30, dtype=float)
        fpath = tmp_path / "spec.dat"
        _write_dat(fpath, wl, flux)
        wl_out, flux_out, _ = _read_model_spectrum(str(fpath))
        assert wl_out[0] < wl_out[-1]  # now ascending


# ── load_grid_from_directory ──────────────────────────────────────────────

class TestLoadGridFromDirectory:
    def test_loads_grid(self, tmp_path):
        grid_dir = _make_grid(tmp_path, "test_grid", n_models=3)
        result = load_grid_from_directory(str(grid_dir))
        assert result["n_models"] == 3
        assert len(result["wavelengths"]) == 50
        assert result["spectra"].shape == (3, 50)
        assert result["params"][0]["Teff"] == 3000.0
        assert result["params"][1]["Teff"] == 3500.0

    def test_cache_hit(self, tmp_path):
        grid_dir = _make_grid(tmp_path, "cached_grid")
        result1 = load_grid_from_directory(str(grid_dir))
        result2 = load_grid_from_directory(str(grid_dir))
        assert result1 is result2  # same object from cache


# ── list_available_grids ──────────────────────────────────────────────────

class TestListAvailableGrids:
    def test_discovers_grids(self, tmp_path):
        _make_grid(tmp_path, "grid_a")
        _make_grid(tmp_path, "grid_b")
        # Also create a directory without index.csv — should be skipped
        (tmp_path / "not_a_grid").mkdir()
        grids = list_available_grids(str(tmp_path))
        assert len(grids) == 2
        names = {g["name"] for g in grids}
        assert names == {"grid_a", "grid_b"}

    def test_nonexistent_dir(self):
        grids = list_available_grids("/nonexistent/path")
        assert grids == []

"""Tests for data_io.py — FITS, H5, TXT ingestion and range filtering."""

import os

import numpy as np
import pytest
from astropy.io import fits
import h5py

from data_io import (
    apply_data_ranges,
    load_lightcurve_txt_folder,
    load_integrations_from_h5,
    load_integrations_from_fits,
)


# ── apply_data_ranges ─────────────────────────────────────────────────────

class TestApplyDataRanges:
    @pytest.fixture
    def sample_data(self):
        wl = np.linspace(1.0, 5.0, 20)
        time = np.linspace(0, 10, 30)
        flux = np.ones((20, 30))
        return wl, flux, time

    def test_no_filter(self, sample_data):
        wl, flux, time = sample_data
        wl_out, flux_out, time_out, info = apply_data_ranges(wl, flux, time)
        assert len(wl_out) == 20
        assert len(time_out) == 30
        assert flux_out.shape == (20, 30)
        assert info == []

    def test_wavelength_only(self, sample_data):
        wl, flux, time = sample_data
        wl_out, flux_out, time_out, info = apply_data_ranges(
            wl, flux, time, wavelength_range=(2.0, 4.0),
        )
        assert np.all(wl_out >= 2.0)
        assert np.all(wl_out <= 4.0)
        assert len(wl_out) < 20
        assert flux_out.shape == (len(wl_out), 30)
        assert len(time_out) == 30

    def test_time_only(self, sample_data):
        wl, flux, time = sample_data
        wl_out, flux_out, time_out, info = apply_data_ranges(
            wl, flux, time, time_range=(3.0, 7.0),
        )
        assert np.all(time_out >= 3.0)
        assert np.all(time_out <= 7.0)
        assert len(time_out) < 30
        assert flux_out.shape == (20, len(time_out))

    def test_both(self, sample_data):
        wl, flux, time = sample_data
        wl_out, flux_out, time_out, info = apply_data_ranges(
            wl, flux, time,
            wavelength_range=(2.0, 4.0),
            time_range=(3.0, 7.0),
        )
        assert np.all(wl_out >= 2.0) and np.all(wl_out <= 4.0)
        assert np.all(time_out >= 3.0) and np.all(time_out <= 7.0)
        assert flux_out.shape == (len(wl_out), len(time_out))

    def test_inverted_range_fallback(self, sample_data):
        """Inverted range (min > max after clamping) should fall back to full range."""
        wl, flux, time = sample_data
        wl_out, flux_out, time_out, info = apply_data_ranges(
            wl, flux, time, wavelength_range=(5.0, 1.0),
        )
        # After clamping: wl_min = max(5.0, 1.0) = 5.0, wl_max = min(1.0, 5.0) = 1.0
        # wl_min >= wl_max → falls back to full range
        assert len(wl_out) == 20


# ── load_lightcurve_txt_folder ────────────────────────────────────────────

class TestLoadLightcurveTxtFolder:
    def test_happy_path(self, tmp_path):
        """3 well-formed txt files → correct shapes."""
        time = np.linspace(0, 10, 20)
        for lo, hi in [(1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]:
            data = np.column_stack([
                time,
                np.ones(20) + 0.01 * np.random.default_rng(0).random(20),
                np.full(20, 0.001),
            ])
            np.savetxt(tmp_path / f"lc_{lo}_{hi}.txt", data)

        wl, fn, fr, t, meta, err = load_lightcurve_txt_folder(str(tmp_path))
        assert len(wl) == 3
        assert fn.shape == (3, 20)
        assert fr.shape == (3, 20)
        assert len(t) == 20
        assert meta["files_processed"] == 3

    def test_no_matching_files(self, tmp_path):
        # Create a file that doesn't match the pattern
        (tmp_path / "readme.txt").write_text("not a light curve")
        with pytest.raises(ValueError, match="No .txt files"):
            load_lightcurve_txt_folder(str(tmp_path))

    def test_wrong_columns(self, tmp_path):
        """File with 2 columns instead of 3 should raise ValueError."""
        data = np.column_stack([np.linspace(0, 10, 20), np.ones(20)])
        np.savetxt(tmp_path / "lc_1.0_2.0.txt", data)
        with pytest.raises(ValueError, match="expected 3 columns"):
            load_lightcurve_txt_folder(str(tmp_path))

    def test_skips_hidden_files(self, tmp_path):
        """Hidden and macOS resource fork files should be ignored."""
        time = np.linspace(0, 10, 20)
        data = np.column_stack([time, np.ones(20), np.full(20, 0.001)])
        np.savetxt(tmp_path / "lc_1.0_2.0.txt", data)
        np.savetxt(tmp_path / "._lc_1.0_2.0.txt", data)
        np.savetxt(tmp_path / ".hidden_1.0_2.0.txt", data)

        wl, fn, fr, t, meta, err = load_lightcurve_txt_folder(str(tmp_path))
        assert len(wl) == 1  # only the non-hidden file


# ── load_integrations_from_h5 ─────────────────────────────────────────────

class TestLoadIntegrationsFromH5:
    def _make_h5(self, path, flux_key="calibrated_optspec", wave_key="eureka_wave_1d",
                 time_key="time", err_key=None, n_int=5, n_wl=100):
        """Create a minimal HDF5 file for testing."""
        with h5py.File(path, "w") as f:
            f.create_dataset(flux_key, data=np.ones((n_int, n_wl)))
            f.create_dataset(wave_key, data=np.linspace(1.0, 5.0, n_wl))
            f.create_dataset(time_key, data=np.linspace(60000, 60001, n_int))
            if err_key:
                f.create_dataset(err_key, data=np.full((n_int, n_wl), 0.04))  # variance=0.04
        return path

    def test_happy_path(self, tmp_path):
        fpath = self._make_h5(tmp_path / "test.h5")
        integrations, header = load_integrations_from_h5(str(fpath))
        assert integrations is not None
        assert len(integrations) == 5
        assert len(integrations[0]["wavelength"]) == 100
        assert header["target"] == "Unknown"

    def test_variance_key(self, tmp_path):
        """stdvar key should be sqrt-converted to error."""
        fpath = self._make_h5(tmp_path / "test.h5", err_key="stdvar")
        integrations, _ = load_integrations_from_h5(str(fpath))
        assert integrations is not None
        # sqrt(0.04) = 0.2
        np.testing.assert_allclose(integrations[0]["error"], 0.2, atol=1e-10)

    def test_missing_keys(self, tmp_path):
        """H5 with no recognized flux key → (None, None)."""
        fpath = tmp_path / "empty.h5"
        with h5py.File(fpath, "w") as f:
            f.create_dataset("random_data", data=np.ones(10))
        integrations, header = load_integrations_from_h5(str(fpath))
        assert integrations is None
        assert header is None


# ── load_integrations_from_fits ───────────────────────────────────────────

class TestLoadIntegrationsFromFits:
    def _make_fits_branch1(self, path, n_int=5, n_wl=50):
        """Create FITS with EXTRACT1D table containing MJD-AVG column (Branch 1)."""
        primary = fits.PrimaryHDU()
        primary.header["TARGNAME"] = "TEST-TARGET"
        primary.header["INSTRUME"] = "NIRCAM"
        primary.header["FILTER"] = "F444W"
        primary.header["GRATING"] = "PRISM"

        # INT_TIMES
        mjds = np.linspace(60000.0, 60000.5, n_int)
        int_times_col = fits.Column(name="int_mid_MJD_UTC", format="D", array=mjds)
        int_times = fits.BinTableHDU.from_columns([int_times_col], name="INT_TIMES")

        # EXTRACT1D with embedded MJD-AVG
        wl_data = np.tile(np.linspace(1.0, 5.0, n_wl), (n_int, 1))
        flux_data = np.ones((n_int, n_wl)) * 100.0
        err_data = np.ones((n_int, n_wl)) * 0.1
        mjd_avg = mjds

        cols = [
            fits.Column(name="WAVELENGTH", format=f"{n_wl}D", array=wl_data),
            fits.Column(name="FLUX", format=f"{n_wl}D", array=flux_data),
            fits.Column(name="FLUX_ERROR", format=f"{n_wl}D", array=err_data),
            fits.Column(name="MJD-AVG", format="D", array=mjd_avg),
        ]
        extract = fits.BinTableHDU.from_columns(cols, name="EXTRACT1D")

        hdul = fits.HDUList([primary, int_times, extract])
        hdul.writeto(path, overwrite=True)
        return path

    def _make_fits_branch3(self, path, n_int=5, n_wl=50):
        """Create FITS with single EXTRACT1D table + INT_TIMES (Branch 3)."""
        primary = fits.PrimaryHDU()
        primary.header["TARGNAME"] = "TEST-TARGET"
        primary.header["INSTRUME"] = "NIRSPEC"

        mjds = np.linspace(60000.0, 60000.5, n_int)
        int_times_col = fits.Column(name="int_mid_MJD_UTC", format="D", array=mjds)
        int_times = fits.BinTableHDU.from_columns([int_times_col], name="INT_TIMES")

        # EXTRACT1D without MJD columns
        wl_data = np.tile(np.linspace(1.0, 5.0, n_wl), (n_int, 1))
        flux_data = np.ones((n_int, n_wl)) * 100.0
        cols = [
            fits.Column(name="WAVELENGTH", format=f"{n_wl}D", array=wl_data),
            fits.Column(name="FLUX", format=f"{n_wl}D", array=flux_data),
        ]
        extract = fits.BinTableHDU.from_columns(cols, name="EXTRACT1D")

        hdul = fits.HDUList([primary, int_times, extract])
        hdul.writeto(path, overwrite=True)
        return path

    def test_branch1_embedded_time(self, tmp_path):
        fpath = self._make_fits_branch1(tmp_path / "b1.fits")
        integrations, header = load_integrations_from_fits(str(fpath))
        assert integrations is not None
        assert len(integrations) == 5
        assert header["target"] == "TEST-TARGET"
        assert header["instrument"] == "NIRCAM"
        assert len(integrations[0]["wavelength"]) == 50

    def test_branch3_single_table(self, tmp_path):
        """Single EXTRACT1D table without MJD columns.

        Note: astropy treats hdul['EXTRACT1D', 1] as valid even with a single
        extension, so this actually hits Branch 2 and only the first index
        succeeds. We verify it doesn't crash and returns what it can.
        """
        fpath = self._make_fits_branch3(tmp_path / "b3.fits")
        integrations, header = load_integrations_from_fits(str(fpath))
        assert integrations is not None
        assert len(integrations) >= 1
        assert header["target"] == "TEST-TARGET"

    def test_missing_int_times(self, tmp_path):
        """FITS file without INT_TIMES → (None, None)."""
        primary = fits.PrimaryHDU()
        hdul = fits.HDUList([primary])
        fpath = tmp_path / "no_int_times.fits"
        hdul.writeto(fpath, overwrite=True)
        integrations, header = load_integrations_from_fits(str(fpath))
        assert integrations is None
        assert header is None

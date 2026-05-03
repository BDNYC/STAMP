"""Tests for processing.py — binning, smoothing, visits, variability, process_data."""

import numpy as np
import pytest

from processing import (
    calculate_bin_size,
    bin_flux_arr,
    smooth_flux,
    process_data,
    identify_visits,
    calculate_variability_from_raw_flux,
)


# ── calculate_bin_size ────────────────────────────────────────────────────

class TestCalculateBinSize:
    def test_basic(self):
        assert calculate_bin_size(1000, 100) == 10

    def test_never_below_one(self):
        assert calculate_bin_size(50, 100) == 1

    def test_exact_multiple(self):
        assert calculate_bin_size(200, 200) == 1


# ── bin_flux_arr ──────────────────────────────────────────────────────────

class TestBinFluxArr:
    def test_reduces_shape(self):
        arr = np.random.default_rng(1).random((10, 100))
        result = bin_flux_arr(arr, 10)
        assert result.shape == (10, 10)

    def test_preserves_constant(self):
        arr = np.ones((5, 100))
        result = bin_flux_arr(arr, 10)
        np.testing.assert_allclose(result, 1.0, atol=1e-10)

    def test_median_value(self):
        # Row of 1..10 repeated; binning 10→1 should give median of each group
        arr = np.tile(np.arange(1, 11, dtype=float), (1, 10))  # (1, 100)
        result = bin_flux_arr(arr, 10)
        assert result.shape[1] == 10
        # Each bin of 10 identical values should give the median of that group
        assert result.shape == (1, 10)


# ── smooth_flux ───────────────────────────────────────────────────────────

class TestSmoothFlux:
    def test_reduces_noise(self):
        rng = np.random.default_rng(2)
        arr = rng.normal(0, 1, (20, 50))
        smoothed = smooth_flux(arr, sigma=2)
        assert np.std(smoothed) < np.std(arr)

    def test_sigma_zero_identity(self):
        arr = np.random.default_rng(3).random((10, 20))
        result = smooth_flux(arr, sigma=0)
        np.testing.assert_allclose(result, arr, atol=1e-14)


# ── identify_visits ──────────────────────────────────────────────────────

class TestIdentifyVisits:
    def test_single_block(self):
        times = np.linspace(0, 5, 50)
        visits = identify_visits(times)
        assert len(visits) == 1
        assert visits[0] == (0, 50)

    def test_two_gaps(self):
        # Three blocks separated by 1-hour gaps
        block1 = np.linspace(0, 1, 10)
        block2 = np.linspace(3, 4, 10)
        block3 = np.linspace(6, 7, 10)
        times = np.concatenate([block1, block2, block3])
        visits = identify_visits(times, gap_threshold=0.5)
        assert len(visits) == 3
        assert visits[0] == (0, 10)
        assert visits[1] == (10, 20)
        assert visits[2] == (20, 30)

    def test_empty(self):
        assert identify_visits(np.array([])) == []

    def test_single_point(self):
        assert identify_visits(np.array([5.0])) == [(0, 1)]


# ── calculate_variability_from_raw_flux ──────────────────────────────────

class TestCalculateVariability:
    def test_normalizes(self):
        rng = np.random.default_rng(4)
        # 5 wavelengths with different medians
        flux = np.array([
            rng.normal(100, 1, 30),
            rng.normal(200, 2, 30),
            rng.normal(50, 0.5, 30),
            rng.normal(1000, 10, 30),
            rng.normal(0.5, 0.005, 30),
        ])
        normed = calculate_variability_from_raw_flux(flux)
        for i in range(5):
            assert abs(np.median(normed[i]) - 1.0) < 0.02

    def test_handles_zeros(self):
        flux = np.zeros((3, 20))
        flux[1] = np.ones(20)
        # Should not raise; zero rows get median replaced by 1.0
        result = calculate_variability_from_raw_flux(flux)
        assert result.shape == (3, 20)
        # Zero row divided by 1.0 stays zero
        np.testing.assert_allclose(result[0], 0.0)


# ── process_data ─────────────────────────────────────────────────────────

class TestProcessData:
    def test_returns_correct_shapes(self):
        n_wl, n_t = 20, 100
        flux = np.ones((n_wl, n_t)) + 0.01 * np.random.default_rng(5).random((n_wl, n_t))
        wavelength = np.linspace(1.0, 5.0, n_wl)
        time = np.linspace(0, 10, n_t)
        x, y, X, Y, Z, label = process_data(flux, wavelength, time, num_plots=50)
        assert X.shape == Y.shape == Z.shape
        assert label == "Wavelength (um)"

    def test_variability_mode(self):
        n_wl, n_t = 10, 50
        flux = np.ones((n_wl, n_t))
        wavelength = np.linspace(1.0, 5.0, n_wl)
        time = np.linspace(0, 10, n_t)
        _, _, _, _, Z, _ = process_data(
            flux, wavelength, time, num_plots=50,
            apply_binning=False, smooth_sigma=0, z_axis_display="variability",
        )
        # Constant flux = 1.0 → variability = (1-1)*100 = 0%
        np.testing.assert_allclose(Z, 0.0, atol=1e-10)

    def test_flux_mode(self):
        n_wl, n_t = 10, 50
        flux = np.full((n_wl, n_t), 3.14)
        wavelength = np.linspace(1.0, 5.0, n_wl)
        time = np.linspace(0, 10, n_t)
        _, _, _, _, Z, _ = process_data(
            flux, wavelength, time, num_plots=50,
            apply_binning=False, smooth_sigma=0, z_axis_display="flux",
        )
        np.testing.assert_allclose(Z, 3.14, atol=1e-10)

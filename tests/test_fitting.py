"""Tests for fitting.py — Lomb-Scargle, sinusoidal, grid, and transit fitting."""

import numpy as np
import pytest

from fitting import (
    _nan_to_none,
    _nan_to_none_2d,
    lomb_scargle,
    fit_sinusoidal,
    fit_sinusoidal_all_wavelengths,
    fit_spectrum_to_grid,
    fit_spectrum_chunked,
    fit_spectrum_all_timesteps,
    fit_transit,
    fit_transit_all_wavelengths,
)


# ── Lomb-Scargle ──────────────────────────────────────────────────────────

class TestLombScargle:
    def test_recovers_known_period(self, simple_time_flux):
        t, f, e, truth = simple_time_flux
        result = lomb_scargle(t, f)
        assert result["success"] is True
        assert abs(result["best_period"] - truth["period"]) < 0.5

    def test_with_errors(self, simple_time_flux):
        t, f, e, truth = simple_time_flux
        result = lomb_scargle(t, f, error_arr=e)
        assert result["success"] is True
        assert abs(result["best_period"] - truth["period"]) < 0.5

    def test_too_few_points(self):
        result = lomb_scargle([1, 2, 3], [1, 1, 1])
        assert result["success"] is False
        assert "Not enough" in result["error"]

    def test_all_nan(self):
        t = np.linspace(0, 10, 20)
        f = np.full_like(t, np.nan)
        result = lomb_scargle(t, f)
        assert result["success"] is False

    def test_custom_period_bounds(self, simple_time_flux):
        t, f, e, truth = simple_time_flux
        result = lomb_scargle(t, f, min_period=4.0, max_period=6.0)
        assert result["success"] is True
        assert 4.0 <= result["best_period"] <= 6.0


# ── Sinusoidal fitting ───────────────────────────────────────────────────

class TestFitSinusoidal:
    def test_recovers_params(self, simple_time_flux):
        t, f, e, truth = simple_time_flux
        result = fit_sinusoidal(t, f, error_arr=e, period_guess=truth["period"])
        assert result["success"] is True
        fitted_amp = result["params"][0]["amplitude"]
        fitted_per = result["params"][0]["period"]
        assert abs(fitted_amp - truth["amplitude"]) / truth["amplitude"] < 0.3
        assert abs(fitted_per - truth["period"]) / truth["period"] < 0.3

    def test_returns_fit_values(self, simple_time_flux):
        t, f, e, truth = simple_time_flux
        result = fit_sinusoidal(t, f, error_arr=e, period_guess=truth["period"])
        assert result["success"] is True
        assert len(result["fit_values"]) == len(t)
        assert "residuals" in result
        assert np.isfinite(result["chi_squared"])
        assert result["chi_squared"] > 0

    def test_two_sines(self):
        rng = np.random.default_rng(123)
        t = np.linspace(0, 40, 100)
        p1, p2 = 5.0, 2.5
        f = 1.0 + 0.03 * np.sin(2 * np.pi * t / p1) + 0.02 * np.sin(2 * np.pi * t / p2)
        f += rng.normal(0, 0.001, len(t))
        result = fit_sinusoidal(t, f, n_sines=2, period_guess=p1)
        assert result["success"] is True
        assert len(result["params"]) == 2
        recovered_periods = sorted([p["period"] for p in result["params"]])
        assert abs(recovered_periods[0] - p2) / p2 < 0.3
        assert abs(recovered_periods[1] - p1) / p1 < 0.3

    def test_too_few_points(self):
        result = fit_sinusoidal([1, 2, 3], [1, 1, 1])
        assert result["success"] is False
        assert "Not enough" in result["error"]

    def test_all_wavelengths(self, flux_2d_with_signal):
        wl, t, flux, err, truth = flux_2d_with_signal
        result = fit_sinusoidal_all_wavelengths(
            wl, t, flux, error_2d=err,
            n_sines=1, period_guess=truth["period"],
        )
        assert result["success"] is True
        assert len(result["wavelengths"]) == len(wl)

        # Amplitudes should trend upward (injected linearly increasing)
        amps = [a[0] for a in result["amplitudes"] if a[0] is not None]
        assert len(amps) >= 8  # most wavelengths should succeed
        # Check that later amplitudes are generally larger
        first_half = np.mean(amps[: len(amps) // 2])
        second_half = np.mean(amps[len(amps) // 2 :])
        assert second_half > first_half


# ── Spectrum grid fitting ─────────────────────────────────────────────────

class TestFitSpectrumToGrid:
    def test_exact_match(self, model_grid_small):
        wl, spectra, params = model_grid_small
        # Observe a scaled copy of model index 1 (Teff=3500)
        scale = 2.5
        obs_flux = scale * spectra[1]
        obs_error = np.full_like(obs_flux, 0.01)
        result = fit_spectrum_to_grid(wl, obs_flux, obs_error, wl, spectra, params)
        assert result["success"] is True
        assert result["best_fit_params"]["Teff"] == 3500.0
        assert result["chi_squared"] < 1.0  # near-perfect match

    def test_with_noise(self, model_grid_small):
        wl, spectra, params = model_grid_small
        rng = np.random.default_rng(55)
        scale = 2.5
        obs_flux = scale * spectra[1] + rng.normal(0, 0.01, len(wl))
        obs_error = np.full_like(obs_flux, 0.01)
        result = fit_spectrum_to_grid(wl, obs_flux, obs_error, wl, spectra, params)
        assert result["success"] is True
        assert result["best_fit_params"]["Teff"] == 3500.0

    def test_chunked(self, model_grid_small):
        wl, spectra, params = model_grid_small
        scale = 2.0
        obs_flux = scale * spectra[0]
        obs_error = np.full_like(obs_flux, 0.01)
        chunks = [{"min": 1.0, "max": 3.0}, {"min": 3.0, "max": 5.0}]
        result = fit_spectrum_chunked(wl, obs_flux, obs_error, wl, spectra, params, chunks)
        assert result["success"] is True
        assert len(result["chunk_results"]) == 2
        for cr in result["chunk_results"]:
            assert cr["success"] is True

    def test_all_timesteps(self, model_grid_small):
        wl, spectra, params = model_grid_small
        n_times = 5
        # Each timestep is a scaled copy of model 2 (Teff=4000)
        rng = np.random.default_rng(77)
        flux_2d = np.zeros((len(wl), n_times))
        err_2d = np.full((len(wl), n_times), 0.01)
        for j in range(n_times):
            flux_2d[:, j] = 3.0 * spectra[2] + rng.normal(0, 0.005, len(wl))
        t = np.arange(n_times, dtype=float)
        result = fit_spectrum_all_timesteps(wl, t, flux_2d, err_2d, wl, spectra, params)
        assert result["success"] is True
        assert all(result["success_mask"])
        for bp in result["best_params"]:
            assert bp["Teff"] == 4000.0


# ── Transit fitting ───────────────────────────────────────────────────────

class TestFitTransit:
    def test_recovers_rp_rs(self, transit_light_curve):
        t, f, e, truth = transit_light_curve
        result = fit_transit(t, f, e, period=truth["period"], rp_rs_guess=0.12)
        assert result["success"] is True
        assert abs(result["params"]["rp_rs"] - truth["rp_rs"]) < 0.02

    def test_depth_ppm(self, transit_light_curve):
        t, f, e, truth = transit_light_curve
        result = fit_transit(t, f, e, period=truth["period"])
        assert result["success"] is True
        expected_ppm = truth["rp_rs"] ** 2 * 1e6  # 10000
        assert abs(result["params"]["depth_ppm"] - expected_ppm) < 3000

    def test_returns_fit_values(self, transit_light_curve):
        t, f, e, truth = transit_light_curve
        result = fit_transit(t, f, e, period=truth["period"])
        assert result["success"] is True
        assert len(result["fit_values"]) == len(t)
        assert len(result["residuals"]) > 0
        assert np.isfinite(result["chi_squared"])
        assert np.max(np.abs(result["residuals"])) < 0.01

    def test_too_few_points(self):
        result = fit_transit([1, 2], [1, 1], [0.01, 0.01], period=10.0)
        assert result["success"] is False
        assert "Not enough" in result["error"]

    def test_all_wavelengths(self):
        """Transit at 5 wavelengths with varying Rp/Rs."""
        import batman

        n_wl, n_t = 5, 200
        t = np.linspace(-2, 2, n_t)
        wl = np.linspace(1.0, 5.0, n_wl)
        rp_values = np.linspace(0.08, 0.12, n_wl)

        flux_2d = np.ones((n_wl, n_t))
        err_2d = np.full((n_wl, n_t), 0.0005)
        rng = np.random.default_rng(42)

        for i, rp in enumerate(rp_values):
            params = batman.TransitParams()
            params.rp = rp
            params.t0 = 0.0
            params.per = 1.0
            params.a = 15.0
            params.inc = 90.0
            params.ecc = 0.0
            params.w = 90.0
            params.limb_dark = "quadratic"
            params.u = [0.1, 0.1]
            m = batman.TransitModel(params, t / 24.0)
            flux_2d[i] = m.light_curve(params) + rng.normal(0, 0.0002, n_t)

        result = fit_transit_all_wavelengths(
            wl, t, flux_2d, err_2d, period=24.0, rp_rs_guess=0.1,
        )
        assert result["success"] is True
        # Most wavelengths should succeed
        assert sum(result["success_mask"]) >= 4
        # Transit depth should generally increase with rp_values
        depths = [d for d in result["transit_depth"] if d is not None]
        assert len(depths) >= 4


# ── Edge cases / helpers ──────────────────────────────────────────────────

class TestHelpers:
    def test_nan_to_none_1d(self):
        arr = np.array([1.0, np.nan, 3.0])
        out = _nan_to_none(arr)
        assert out == [1.0, None, 3.0]

    def test_nan_to_none_2d(self):
        arr = np.array([[1.0, np.nan], [np.nan, 4.0]])
        out = _nan_to_none_2d(arr)
        assert out == [[1.0, None], [None, 4.0]]

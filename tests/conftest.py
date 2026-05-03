"""Shared pytest fixtures for SA3D/STAMP test suite."""

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# State cleanup — runs automatically for every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_state():
    """Clear shared mutable state between tests."""
    import state
    state.PROGRESS.clear()
    state.RESULTS.clear()
    state.latest_surface_figure = None
    state.latest_heatmap_figure = None
    state.last_surface_plot_html = None
    state.last_heatmap_plot_html = None
    state.last_surface_fig_json = None
    state.last_heatmap_fig_json = None
    state.last_custom_bands = []
    state.latest_spectrum_mp4_path = None
    yield
    state.PROGRESS.clear()
    state.RESULTS.clear()


# ---------------------------------------------------------------------------
# Synthetic time-series data
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_time_flux():
    """50-point sinusoidal light curve with known period=5h, amplitude=0.02."""
    rng = np.random.default_rng(42)
    t = np.linspace(0, 20, 50)
    period, amp, offset = 5.0, 0.02, 1.0
    f = offset + amp * np.sin(2 * np.pi * t / period)
    e = np.full_like(t, 0.001)
    f += rng.normal(0, 0.001, size=len(t))
    return t, f, e, {"period": period, "amplitude": amp, "offset": offset}


@pytest.fixture
def flux_2d_with_signal():
    """(10 wavelengths x 50 times) 2D flux with per-wavelength sinusoid.

    Amplitudes increase linearly from 0.01 to 0.05 across wavelengths.
    """
    rng = np.random.default_rng(99)
    n_wl, n_t = 10, 50
    t = np.linspace(0, 20, n_t)
    wl = np.linspace(1.0, 5.0, n_wl)
    period = 5.0
    amps = np.linspace(0.01, 0.05, n_wl)
    flux = np.ones((n_wl, n_t))
    for i in range(n_wl):
        flux[i] += amps[i] * np.sin(2 * np.pi * t / period)
        flux[i] += rng.normal(0, 0.001, n_t)
    err = np.full((n_wl, n_t), 0.001)
    return wl, t, flux, err, {"period": period, "amplitudes": amps}


@pytest.fixture
def transit_light_curve():
    """Synthetic transit light curve using batman (Rp/Rs=0.1, period=24h)."""
    import batman

    t = np.linspace(-2, 2, 200)  # hours around mid-transit
    params = batman.TransitParams()
    params.rp = 0.1
    params.t0 = 0.0          # mid-transit at t=0 (days)
    params.per = 1.0          # 24 hours = 1 day
    params.a = 15.0
    params.inc = 90.0
    params.ecc = 0.0
    params.w = 90.0
    params.limb_dark = "quadratic"
    params.u = [0.1, 0.1]

    m = batman.TransitModel(params, t / 24.0)  # convert hours to days
    flux = m.light_curve(params)

    rng = np.random.default_rng(7)
    flux += rng.normal(0, 0.0002, len(flux))
    err = np.full_like(flux, 0.0005)

    return t, flux, err, {"rp_rs": 0.1, "period": 24.0, "t0": 0.0}


# ---------------------------------------------------------------------------
# Model grid for spectrum fitting
# ---------------------------------------------------------------------------

@pytest.fixture
def model_grid_small():
    """Tiny 3-model grid for spectrum fitting tests."""
    wl = np.linspace(1.0, 5.0, 100)
    spectra = np.array([
        np.exp(-0.5 * ((wl - 2.5) / 0.5) ** 2),  # Gaussian at 2.5 um
        np.exp(-0.5 * ((wl - 3.0) / 0.5) ** 2),  # Gaussian at 3.0 um
        np.exp(-0.5 * ((wl - 3.5) / 0.5) ** 2),  # Gaussian at 3.5 um
    ])
    params = [
        {"Teff": 3000.0, "logg": 4.0},
        {"Teff": 3500.0, "logg": 4.5},
        {"Teff": 4000.0, "logg": 5.0},
    ]
    return wl, spectra, params


# ---------------------------------------------------------------------------
# Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture
def flask_app():
    """Flask test app with all blueprints registered."""
    from app import app
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()

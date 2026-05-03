"""Tests for plotting.py — surface and heatmap Plotly figure builders."""

import numpy as np
import plotly.graph_objs as go
import pytest

from plotting import create_surface_plot_with_visits, create_heatmap_plot


@pytest.fixture
def plot_data():
    """Standard (20 wl x 50 time) flux array for plotting tests."""
    n_wl, n_t = 20, 50
    rng = np.random.default_rng(10)
    flux = np.ones((n_wl, n_t)) + 0.01 * rng.random((n_wl, n_t))
    wavelength = np.linspace(1.0, 5.0, n_wl)
    time = np.linspace(0, 5, n_t)
    return flux, wavelength, time


@pytest.fixture
def gapped_time():
    """Time array with a gap for multi-visit testing."""
    block1 = np.linspace(0, 2, 25)
    block2 = np.linspace(4, 6, 25)
    return np.concatenate([block1, block2])


# ── Surface plot ──────────────────────────────────────────────────────────

class TestSurfacePlot:
    def test_returns_figure(self, plot_data):
        flux, wl, time = plot_data
        fig = create_surface_plot_with_visits(
            flux, wl, time, "Test", num_plots=50,
            smooth_sigma=0,
        )
        assert isinstance(fig, go.Figure)
        surfaces = [t for t in fig.data if isinstance(t, go.Surface)]
        assert len(surfaces) >= 1

    def test_multiple_visits(self, plot_data, gapped_time):
        flux, wl, _ = plot_data
        fig = create_surface_plot_with_visits(
            flux, wl, gapped_time, "Test", num_plots=50,
            smooth_sigma=0, gap_threshold=0.5,
        )
        surfaces = [t for t in fig.data if isinstance(t, go.Surface)]
        assert len(surfaces) == 2  # two blocks separated by 2h gap

    def test_flux_mode_z_label(self, plot_data):
        flux, wl, time = plot_data
        fig = create_surface_plot_with_visits(
            flux, wl, time, "Test", num_plots=50,
            smooth_sigma=0, z_axis_display="flux",
        )
        z_title = fig.layout.scene.zaxis.title
        # title can be a string or a dict with 'text'
        z_text = z_title if isinstance(z_title, str) else z_title.text
        assert "Raw Flux" in z_text

    def test_variability_mode_z_label(self, plot_data):
        flux, wl, time = plot_data
        fig = create_surface_plot_with_visits(
            flux, wl, time, "Test", num_plots=50,
            smooth_sigma=0, z_axis_display="variability",
        )
        z_title = fig.layout.scene.zaxis.title
        z_text = z_title if isinstance(z_title, str) else z_title.text
        assert "Variability" in z_text


# ── Heatmap plot ──────────────────────────────────────────────────────────

class TestHeatmapPlot:
    def test_returns_figure(self, plot_data):
        flux, wl, time = plot_data
        fig = create_heatmap_plot(
            flux, wl, time, "Test", num_plots=50,
            smooth_sigma=0,
        )
        assert isinstance(fig, go.Figure)
        heatmaps = [t for t in fig.data if isinstance(t, go.Heatmap)]
        assert len(heatmaps) == 1

    def test_z_range_tuple(self, plot_data):
        flux, wl, time = plot_data
        fig = create_heatmap_plot(
            flux, wl, time, "Test", num_plots=50,
            smooth_sigma=0, z_range=(-1.0, 1.0),
        )
        hm = fig.data[0]
        assert hm.zmin == -1.0
        assert hm.zmax == 1.0

    def test_z_range_scalar_variability(self, plot_data):
        flux, wl, time = plot_data
        fig = create_heatmap_plot(
            flux, wl, time, "Test", num_plots=50,
            smooth_sigma=0, z_range=2.0, z_axis_display="variability",
        )
        hm = fig.data[0]
        assert hm.zmin == -2.0
        assert hm.zmax == 2.0

    def test_flux_mode_colorbar(self, plot_data):
        flux, wl, time = plot_data
        fig = create_heatmap_plot(
            flux, wl, time, "Test", num_plots=50,
            smooth_sigma=0, z_axis_display="flux", flux_unit="MJy",
        )
        hm = fig.data[0]
        cb_title = hm.colorbar.title
        cb_text = cb_title if isinstance(cb_title, str) else cb_title.text
        assert "Flux" in cb_text

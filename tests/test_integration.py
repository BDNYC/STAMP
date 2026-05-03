"""Integration tests — end-to-end with real demo data and model grids.

All tests are marked @pytest.mark.slow. Run with:
    pytest -m slow -v
Skip with:
    pytest -m "not slow"
"""

import os
import time
import json
import zipfile
import tempfile

import numpy as np
import pytest

from config import DEMO_DATA_DIR, GRIDS_DIR

DEMO_ZIP = os.path.join(DEMO_DATA_DIR, "demo_jwst_timeseries.zip")
_has_demo = os.path.exists(DEMO_ZIP) and os.path.getsize(DEMO_ZIP) > 1000
_has_grids = os.path.isdir(GRIDS_DIR) and any(
    os.path.exists(os.path.join(GRIDS_DIR, d, "index.csv"))
    for d in os.listdir(GRIDS_DIR)
    if os.path.isdir(os.path.join(GRIDS_DIR, d))
)

skip_no_demo = pytest.mark.skipif(not _has_demo, reason="Demo dataset not available")
skip_no_grids = pytest.mark.skipif(not _has_grids, reason="Model grids not available")


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.slow
@skip_no_demo
class TestDemoPipeline:
    """End-to-end processing of the real demo dataset."""

    def test_full_pipeline(self):
        """Extract demo → process → plot → verify shapes."""
        from processing import process_mast_files_with_gaps
        from plotting import create_surface_plot_with_visits, create_heatmap_plot
        from fitting import lomb_scargle
        import plotly.graph_objs as go

        # Extract
        tmp = tempfile.mkdtemp()
        with zipfile.ZipFile(DEMO_ZIP, "r") as z:
            z.extractall(tmp)

        fits_files = []
        for root, dirs, files in os.walk(tmp):
            for f in files:
                if f.endswith(".fits"):
                    fits_files.append(os.path.join(root, f))

        assert len(fits_files) >= 1

        # Process
        wl, flux_norm, flux_raw, times, meta, errors = process_mast_files_with_gaps(fits_files)
        assert wl.shape[0] > 10
        assert flux_norm.shape[0] == wl.shape[0]
        assert flux_norm.shape[1] == times.shape[0]
        assert meta["total_integrations"] > 0

        # Plot
        fig_s = create_surface_plot_with_visits(
            flux_norm, wl, times, "Test", num_plots=100, smooth_sigma=1,
        )
        fig_h = create_heatmap_plot(
            flux_norm, wl, times, "Test", num_plots=100, smooth_sigma=1,
        )
        assert isinstance(fig_s, go.Figure)
        assert isinstance(fig_h, go.Figure)

        # Lomb-Scargle on median light curve
        median_lc = np.nanmedian(flux_norm, axis=0)
        ls_result = lomb_scargle(times, median_lc)
        assert ls_result["success"] is True
        assert ls_result["best_period"] > 0

    def test_flask_round_trip(self, client):
        """POST /start_mast demo → poll progress → GET results."""
        resp = client.post("/start_mast", data={"use_demo": "true"})
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]

        # Poll until done (max 30s)
        deadline = time.time() + 30
        status = "running"
        while time.time() < deadline:
            prog = client.get(f"/progress/{job_id}").get_json()
            status = prog.get("status", "running")
            if status in ("done", "error"):
                break
            time.sleep(0.5)

        assert status == "done", f"Job ended with status={status}"

        # Fetch results
        result = client.get(f"/results/{job_id}")
        assert result.status_code == 200
        payload = result.get_json()
        assert "surface_plot" in payload
        assert "heatmap_plot" in payload
        assert "metadata" in payload
        assert payload["metadata"]["total_integrations"] > 0


@pytest.mark.slow
@skip_no_grids
class TestModelGridIntegration:
    """Tests against real model grids on disk."""

    def _find_first_grid(self):
        for d in sorted(os.listdir(GRIDS_DIR)):
            grid_dir = os.path.join(GRIDS_DIR, d)
            if os.path.isdir(grid_dir) and os.path.exists(os.path.join(grid_dir, "index.csv")):
                return grid_dir, d
        pytest.skip("No valid grid found")

    def test_real_grid_loading(self):
        """Load a real model grid and verify structure."""
        from model_grids import load_grid_from_directory
        import model_grids
        model_grids._loaded_grids.clear()

        grid_dir, name = self._find_first_grid()
        result = load_grid_from_directory(grid_dir)
        assert result["n_models"] > 0
        assert len(result["wavelengths"]) > 0
        assert result["spectra"].shape[0] == result["n_models"]

    def test_fit_against_real_grid(self):
        """Create synthetic observation matching a real grid model and recover it."""
        from model_grids import load_grid_from_directory
        from fitting import fit_spectrum_to_grid
        import model_grids
        model_grids._loaded_grids.clear()

        grid_dir, name = self._find_first_grid()
        grid = load_grid_from_directory(grid_dir)

        # Pick the middle model as "truth"
        mid = grid["n_models"] // 2
        wl = np.array(grid["wavelengths"])
        true_spectrum = grid["spectra"][mid]
        true_params = grid["params"][mid]

        # Observe it with noise
        rng = np.random.default_rng(12)
        scale = 2.0
        obs_flux = scale * true_spectrum + rng.normal(0, 0.01 * np.nanmax(true_spectrum), len(wl))
        obs_error = np.full_like(obs_flux, 0.01 * np.nanmax(true_spectrum))

        result = fit_spectrum_to_grid(
            wl, obs_flux, obs_error,
            grid["wavelengths"], grid["spectra"], grid["params"],
        )
        assert result["success"] is True
        # Best fit should match the true model's Teff (if present)
        if "Teff" in true_params:
            assert result["best_fit_params"]["Teff"] == true_params["Teff"]


@pytest.mark.slow
@skip_no_demo
class TestTxtFormatIntegration:
    """Test the TXT light curve format end-to-end."""

    def test_txt_upload_round_trip(self, client):
        """Create synthetic TXT light curves, zip them, upload via /start_mast."""
        import io

        rng = np.random.default_rng(88)
        time_arr = np.linspace(0, 10, 30)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for lo, hi in [(1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]:
                data = np.column_stack([
                    time_arr,
                    np.ones(30) + rng.normal(0, 0.01, 30),
                    np.full(30, 0.001),
                ])
                lines = "\n".join(f"{r[0]} {r[1]} {r[2]}" for r in data)
                zf.writestr(f"lc_{lo}_{hi}.txt", lines)
        buf.seek(0)

        resp = client.post("/start_mast", data={
            "mast_zip": (buf, "test_lc.zip"),
        }, content_type="multipart/form-data")
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]

        # Poll until done (max 15s)
        deadline = time.time() + 15
        status = "running"
        while time.time() < deadline:
            prog = client.get(f"/progress/{job_id}").get_json()
            status = prog.get("status", "running")
            if status in ("done", "error"):
                break
            time.sleep(0.3)

        assert status == "done", f"Job ended with status={status}"

        result = client.get(f"/results/{job_id}")
        assert result.status_code == 200
        payload = result.get_json()
        assert "surface_plot" in payload
        assert payload["metadata"]["files_processed"] == 3

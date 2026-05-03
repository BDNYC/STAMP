"""Tests for routes/fitting.py — fitting endpoint request/response validation."""

import json
import os

import numpy as np
import pytest


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def _sine_payload():
    """Minimal valid payload for sinusoidal/lombscargle endpoints."""
    rng = np.random.default_rng(42)
    t = np.linspace(0, 20, 50).tolist()
    f = (1.0 + 0.02 * np.sin(2 * np.pi * np.array(t) / 5.0)
         + rng.normal(0, 0.001, 50)).tolist()
    return {"time": t, "flux": f}


def _transit_payload():
    """Minimal valid payload for transit endpoint."""
    import batman
    t = np.linspace(-2, 2, 100)
    params = batman.TransitParams()
    params.rp, params.t0, params.per = 0.1, 0.0, 1.0
    params.a, params.inc, params.ecc, params.w = 15.0, 90.0, 0.0, 90.0
    params.limb_dark, params.u = "quadratic", [0.1, 0.1]
    m = batman.TransitModel(params, t / 24.0)
    flux = m.light_curve(params)
    return {
        "time": t.tolist(),
        "flux": flux.tolist(),
        "error": [0.001] * len(t),
        "period": 24.0,
    }


# ── Lomb-Scargle ──────────────────────────────────────────────────────────

class TestLombScargleRoute:
    def test_success(self, client):
        resp = client.post("/fit/lombscargle",
                           data=json.dumps(_sine_payload()),
                           content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_with_period_bounds(self, client):
        payload = _sine_payload()
        payload["min_period"] = 4.0
        payload["max_period"] = 6.0
        resp = client.post("/fit/lombscargle",
                           data=json.dumps(payload),
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_missing_field(self, client):
        resp = client.post("/fit/lombscargle",
                           data=json.dumps({"flux": [1, 2, 3]}),
                           content_type="application/json")
        assert resp.status_code == 400


# ── Sinusoidal ────────────────────────────────────────────────────────────

class TestSinusoidalRoute:
    def test_success(self, client):
        resp = client.post("/fit/sinusoidal",
                           data=json.dumps(_sine_payload()),
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_with_error(self, client):
        payload = _sine_payload()
        payload["error"] = [0.001] * 50
        resp = client.post("/fit/sinusoidal",
                           data=json.dumps(payload),
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_all_wavelengths_returns_202(self, client):
        rng = np.random.default_rng(1)
        payload = {
            "wavelengths": np.linspace(1, 5, 5).tolist(),
            "time": np.linspace(0, 20, 30).tolist(),
            "flux_2d": (np.ones((5, 30)) + rng.normal(0, 0.01, (5, 30))).tolist(),
            "n_sines": 1,
        }
        resp = client.post("/fit/sinusoidal_all_wavelengths",
                           data=json.dumps(payload),
                           content_type="application/json")
        assert resp.status_code == 202
        assert "job_id" in resp.get_json()


# ── Transit ───────────────────────────────────────────────────────────────

class TestTransitRoute:
    def test_success(self, client):
        resp = client.post("/fit/transit",
                           data=json.dumps(_transit_payload()),
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_missing_period(self, client):
        payload = {"time": [1, 2, 3], "flux": [1, 1, 1]}
        resp = client.post("/fit/transit",
                           data=json.dumps(payload),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_all_wavelengths_returns_202(self, client):
        import batman
        n_wl, n_t = 3, 50
        t = np.linspace(-2, 2, n_t)
        flux_2d = np.ones((n_wl, n_t))
        for i in range(n_wl):
            params = batman.TransitParams()
            params.rp, params.t0, params.per = 0.1, 0.0, 1.0
            params.a, params.inc, params.ecc, params.w = 15.0, 90.0, 0.0, 90.0
            params.limb_dark, params.u = "quadratic", [0.1, 0.1]
            m = batman.TransitModel(params, t / 24.0)
            flux_2d[i] = m.light_curve(params)

        payload = {
            "wavelengths": np.linspace(1, 5, n_wl).tolist(),
            "time": t.tolist(),
            "flux_2d": flux_2d.tolist(),
            "error_2d": (np.full((n_wl, n_t), 0.001)).tolist(),
            "period": 24.0,
        }
        resp = client.post("/fit/transit_all_wavelengths",
                           data=json.dumps(payload),
                           content_type="application/json")
        assert resp.status_code == 202
        assert "job_id" in resp.get_json()


# ── Spectrum grid ─────────────────────────────────────────────────────────

class TestSpectrumRoute:
    def test_grid_not_found(self, client):
        payload = {
            "wavelengths": [1, 2, 3, 4, 5],
            "flux": [1, 1, 1, 1, 1],
            "error": [0.1] * 5,
            "grid_name": "nonexistent_grid_12345",
        }
        resp = client.post("/fit/spectrum",
                           data=json.dumps(payload),
                           content_type="application/json")
        assert resp.status_code == 404

    def test_grid_list(self, client):
        resp = client.get("/fit/grid_list")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "grids" in data

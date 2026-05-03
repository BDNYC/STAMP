"""Tests for routes/exomast.py — target lookup endpoints (mocked HTTP)."""

import json

import pytest
import responses

from routes.exomast import (
    EXOMAST_BASE,
    SIMBAD_TAP,
    EXOPLANET_EU_TAP,
    _merge_results,
)


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


# ── Merge helper ──────────────────────────────────────────────────────────

class TestMergeResults:
    def test_priority_order(self):
        r1 = ({"teff": 5000, "orbital_period": 3.5}, "WASP-39 b")
        r2 = ({"teff": 4800, "metallicity": 0.1}, "WASP-39b")
        r3 = ({"spectral_type": "G8V"}, "WASP-39")
        merged, sources, resolved = _merge_results(r1, r2, r3)
        assert merged["teff"] == 5000  # ExoMAST wins
        assert merged["metallicity"] == 0.1  # filled by exoplanet.eu
        assert merged["spectral_type"] == "G8V"  # filled by SIMBAD
        assert resolved == "WASP-39 b"

    def test_all_none(self):
        merged, sources, resolved = _merge_results(
            (None, None), (None, None), (None, None),
        )
        assert merged == {}
        assert sources == []


# ── Lookup endpoint ───────────────────────────────────────────────────────

class TestLookupRoute:
    @responses.activate
    def test_exomast_found(self, client):
        responses.add(
            responses.GET,
            f"{EXOMAST_BASE}/WASP-39 b/properties/",
            json=[{
                "planet_name": "WASP-39 b",
                "orbital_period": 4.055,
                "Rp/Rs": 0.146,
                "a/Rs": 11.55,
                "inclination": 87.83,
                "eccentricity": 0.0,
                "omega": None,
                "Teff": 5485,
                "stellar_gravity": 4.4,
                "Fe/H": -0.03,
                "Rs": 0.895,
                "Rp": 1.279,
            }],
            status=200,
        )
        # SIMBAD and exoplanet.eu return nothing
        responses.add(responses.GET, SIMBAD_TAP, json={"metadata": [], "data": []}, status=200)
        responses.add(responses.GET, EXOPLANET_EU_TAP, json={"metadata": [], "data": []}, status=200)

        resp = client.get("/exomast/lookup/WASP-39 b")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"] is True
        assert data["params"]["orbital_period"] == 4.055
        assert data["params"]["rp_rs"] == 0.146
        assert "ExoMAST" in data["sources"]

    @responses.activate
    def test_not_found(self, client):
        responses.add(responses.GET, f"{EXOMAST_BASE}/FAKE-PLANET/properties/", json=[], status=200)
        responses.add(responses.GET, f"{EXOMAST_BASE}/FAKE-PLANET b/properties/", json=[], status=200)
        responses.add(responses.GET, SIMBAD_TAP, json={"metadata": [], "data": []}, status=200)
        responses.add(responses.GET, EXOPLANET_EU_TAP, json={"metadata": [], "data": []}, status=200)

        resp = client.get("/exomast/lookup/FAKE-PLANET")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"] is False

    @responses.activate
    def test_simbad_fallback(self, client):
        """ExoMAST empty, SIMBAD provides spectral type."""
        responses.add(responses.GET, f"{EXOMAST_BASE}/TRAPPIST-1/properties/", json=[], status=200)
        responses.add(responses.GET, f"{EXOMAST_BASE}/TRAPPIST-1 b/properties/", json=[], status=200)
        responses.add(responses.GET, EXOPLANET_EU_TAP, json={"metadata": [], "data": []}, status=200)
        responses.add(
            responses.GET, SIMBAD_TAP,
            json={
                "metadata": [
                    {"name": "main_id"}, {"name": "sp_type"}, {"name": "plx_value"},
                    {"name": "rvz_radvel"}, {"name": "vsini"}, {"name": "period"},
                ],
                "data": [["TRAPPIST-1", "M8V", 80.451, -56.3, None, 3.295]],
            },
            status=200,
        )

        resp = client.get("/exomast/lookup/TRAPPIST-1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"] is True
        assert data["params"]["spectral_type"] == "M8V"
        assert "SIMBAD" in data["sources"]


# ── Autocomplete ──────────────────────────────────────────────────────────

class TestAutocomplete:
    @responses.activate
    def test_returns_suggestions(self, client):
        responses.add(
            responses.GET,
            f"{EXOMAST_BASE}/autocomplete/",
            json=["WASP-39 b", "WASP-39 c"],
            status=200,
        )
        resp = client.get("/exomast/autocomplete?term=WASP-39")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_short_term(self, client):
        resp = client.get("/exomast/autocomplete?term=W")
        assert resp.status_code == 200
        assert resp.get_json() == []

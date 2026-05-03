"""Tests for routes/jobs.py — async job management endpoints."""

import io
import json

import pytest


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


class TestProgressEndpoint:
    def test_unknown_job(self, client):
        resp = client.get("/progress/nonexistent_id")
        assert resp.status_code == 404

    def test_known_job(self, client):
        """Manually insert a progress record and verify it's returned."""
        from state import PROGRESS, PROG_LOCK
        with PROG_LOCK:
            PROGRESS["test_job"] = {
                "status": "running",
                "percent": 42.0,
                "message": "Testing",
                "started_at": 0,
                "stage": "read",
                "processed_integrations": 10,
                "total_integrations": 100,
            }
        resp = client.get("/progress/test_job")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["percent"] == 42.0
        assert data["stage"] == "read"


class TestResultsEndpoint:
    def test_unknown_job(self, client):
        resp = client.get("/results/nonexistent_id")
        assert resp.status_code == 404

    def test_not_ready(self, client):
        from state import PROGRESS, PROG_LOCK
        with PROG_LOCK:
            PROGRESS["running_job"] = {
                "status": "running",
                "percent": 50.0,
                "message": "Working",
                "started_at": 0,
                "stage": "read",
                "processed_integrations": 0,
                "total_integrations": 0,
            }
        resp = client.get("/results/running_job")
        assert resp.status_code == 202

    def test_error_status(self, client):
        from state import PROGRESS, PROG_LOCK
        with PROG_LOCK:
            PROGRESS["error_job"] = {
                "status": "error",
                "percent": 0,
                "message": "Something broke",
                "started_at": 0,
                "stage": "error",
                "processed_integrations": 0,
                "total_integrations": 0,
            }
        resp = client.get("/results/error_job")
        assert resp.status_code == 500
        assert "Something broke" in resp.get_json()["error"]

    def test_done_with_payload(self, client):
        from state import PROGRESS, RESULTS, PROG_LOCK
        with PROG_LOCK:
            PROGRESS["done_job"] = {
                "status": "done",
                "percent": 100.0,
                "message": "Done",
                "started_at": 0,
                "stage": "done",
                "processed_integrations": 0,
                "total_integrations": 0,
            }
            RESULTS["done_job"] = {"surface_plot": "test", "heatmap_plot": "test"}
        resp = client.get("/results/done_job")
        assert resp.status_code == 200
        assert resp.get_json()["surface_plot"] == "test"


class TestStartMast:
    def test_no_file_no_demo(self, client):
        resp = client.post("/start_mast", data={})
        assert resp.status_code == 400

    def test_demo_missing(self, client, monkeypatch):
        """use_demo=true but demo file doesn't exist → 404."""
        import config
        monkeypatch.setattr(config, "DEMO_DATA_DIR", "/tmp/nonexistent_demo_dir_12345")
        # Need to also patch the imported reference in routes.jobs
        import routes.jobs
        monkeypatch.setattr(routes.jobs, "DEMO_DATA_DIR", "/tmp/nonexistent_demo_dir_12345")
        resp = client.post("/start_mast", data={"use_demo": "true"})
        assert resp.status_code == 404

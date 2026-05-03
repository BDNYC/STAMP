"""Tests for state.py — thread-safe progress tracking."""

import time as _time

import pytest

from state import PROGRESS, RESULTS, _progress_set, _cleanup_old_jobs, PROG_LOCK


class TestProgressSet:
    def test_creates_record(self):
        rec = _progress_set("job1", reset=True)
        assert rec["status"] == "running"
        assert rec["percent"] == 0.0
        assert rec["message"] == "Starting"
        assert "job1" in PROGRESS

    def test_updates_fields(self):
        _progress_set("job2", reset=True)
        rec = _progress_set("job2", percent=50.0, message="Halfway", stage="read")
        assert rec["percent"] == 50.0
        assert rec["message"] == "Halfway"
        assert rec["stage"] == "read"

    def test_clamps_percent_to_99(self):
        _progress_set("job3", reset=True)
        rec = _progress_set("job3", percent=150.0)
        assert rec["percent"] == 99.0

    def test_done_allows_100(self):
        _progress_set("job4", reset=True)
        rec = _progress_set("job4", percent=100.0, status="done")
        assert rec["percent"] == 100.0
        assert rec["status"] == "done"

    def test_cleanup_removes_old_jobs(self):
        # Insert a job that looks old
        _progress_set("old_job", reset=True, status="done")
        PROGRESS["old_job"]["started_at"] = _time.time() - 7200  # 2 hours ago

        # Trigger cleanup by completing another job
        _progress_set("new_job", reset=True, status="done")
        assert "old_job" not in PROGRESS

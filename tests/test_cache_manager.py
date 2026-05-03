"""Tests for cache_manager.py — DatasetCache disk-based LRU cache."""

import json
import os
import time
import threading

import numpy as np
import pytest

from cache_manager import DatasetCache


@pytest.fixture
def cache(tmp_path):
    """Fresh DatasetCache in a temp directory."""
    return DatasetCache(cache_dir=str(tmp_path / "cache"), ttl_hours=24, max_cache_size_gb=10)


@pytest.fixture
def sample_file(tmp_path):
    """Create a small file to use as cache key source."""
    fpath = tmp_path / "sample_data.bin"
    fpath.write_bytes(os.urandom(1024))
    return str(fpath)


@pytest.fixture
def sample_data():
    """Typical cached payload."""
    return {
        "wavelength_1d": np.linspace(1, 5, 100).tolist(),
        "time_1d": np.linspace(0, 10, 50).tolist(),
        "flux": "placeholder",
        "metadata": {"total_integrations": 50},
    }


# ── Core operations ──────────────────────────────────────────────────────

class TestCacheOperations:
    def test_set_and_get_roundtrip(self, cache, sample_file, sample_data):
        cache.set(sample_file, False, sample_data)
        result = cache.get(sample_file, False)
        assert result is not None
        assert result["flux"] == "placeholder"
        assert len(result["wavelength_1d"]) == 100

    def test_cache_miss(self, cache, sample_file):
        result = cache.get(sample_file, False)
        assert result is None

    def test_ttl_expiration(self, tmp_path, sample_file, sample_data):
        cache = DatasetCache(
            cache_dir=str(tmp_path / "ttl_cache"),
            ttl_hours=0.0001,  # ~0.36 seconds
        )
        cache.set(sample_file, False, sample_data)
        time.sleep(0.5)
        result = cache.get(sample_file, False)
        assert result is None

    def test_clear(self, cache, sample_file, sample_data):
        cache.set(sample_file, False, sample_data)
        cache.set(sample_file, True, sample_data)
        removed = cache.clear()
        assert removed >= 2  # at least 2 .pkl + 2 _meta.json = 4
        stats = cache.get_stats()
        assert stats["num_entries"] == 0


# ── Hash behavior ─────────────────────────────────────────────────────────

class TestCacheHash:
    def test_hash_stability(self, cache, sample_file):
        h1 = cache._compute_hash(sample_file, False)
        h2 = cache._compute_hash(sample_file, False)
        assert h1 == h2

    def test_interpolation_flag_changes_hash(self, cache, sample_file):
        h_no = cache._compute_hash(sample_file, False)
        h_yes = cache._compute_hash(sample_file, True)
        assert h_no != h_yes


# ── Stats ─────────────────────────────────────────────────────────────────

class TestCacheStats:
    def test_get_stats_structure(self, cache, sample_file, sample_data):
        cache.set(sample_file, False, sample_data)
        stats = cache.get_stats()
        assert "num_entries" in stats
        assert "total_size_mb" in stats
        assert "total_size_gb" in stats
        assert "max_size_gb" in stats
        assert "ttl_hours" in stats
        assert "cache_dir" in stats
        assert "entries" in stats
        assert stats["num_entries"] == 1

    def test_empty_stats(self, cache):
        stats = cache.get_stats()
        assert stats["num_entries"] == 0
        assert stats["total_size_mb"] == 0


# ── Edge cases ────────────────────────────────────────────────────────────

class TestCacheEdgeCases:
    def test_corrupted_metadata(self, cache, sample_file, sample_data):
        """Corrupted _meta.json should not crash get()."""
        cache.set(sample_file, False, sample_data)
        # Corrupt the metadata file
        cache_key = cache._compute_hash(sample_file, False)
        meta_path = cache._get_metadata_path(cache_key)
        with open(meta_path, "w") as f:
            f.write("NOT VALID JSON {{{")
        result = cache.get(sample_file, False)
        assert result is None  # graceful failure

    def test_concurrent_access(self, cache, tmp_path, sample_data):
        """Multiple threads setting/getting simultaneously shouldn't crash."""
        errors = []

        def worker(i):
            try:
                fpath = tmp_path / f"file_{i}.bin"
                fpath.write_bytes(os.urandom(512))
                cache.set(str(fpath), False, sample_data)
                result = cache.get(str(fpath), False)
                assert result is not None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

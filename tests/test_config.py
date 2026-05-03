"""Tests for config.py — YAML loading and constants."""

import os

import pytest

from config import load_config, COLOR_SCALES


class TestLoadConfig:
    def test_missing_file(self):
        result = load_config("nonexistent_file_12345.yaml")
        assert result == {}

    def test_valid_yaml(self, tmp_path):
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text("data_dir: TestData\nsome_key: 42\n")
        result = load_config(str(cfg_file))
        assert result["data_dir"] == "TestData"
        assert result["some_key"] == 42


class TestConstants:
    def test_color_scales_not_empty(self):
        assert len(COLOR_SCALES) >= 5
        assert "Viridis" in COLOR_SCALES

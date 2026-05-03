"""Tests for routes/upload.py — file upload and download endpoints."""

import io

import pytest
from unittest.mock import patch


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


class TestUploadMast:
    def test_no_file(self, client):
        resp = client.post("/upload_mast")
        assert resp.status_code == 400
        assert "No MAST zip" in resp.get_json()["error"]


class TestDownloadPlots:
    def test_no_data(self, client):
        resp = client.get("/download_plots")
        assert resp.status_code == 400

    def test_with_data(self, client):
        """When state has plot HTML, should return a ZIP."""
        import state
        state.last_surface_plot_html = "<html>surface</html>"
        state.last_heatmap_plot_html = "<html>heatmap</html>"
        resp = client.get("/download_plots")
        assert resp.status_code == 200
        assert resp.content_type == "application/zip"


class TestUploadSpectrumFrames:
    def test_no_frames(self, client):
        resp = client.post("/upload_spectrum_frames")
        assert resp.status_code == 400

    def test_no_ffmpeg(self, client):
        """When ffmpeg is not on PATH, should return warning instead of error."""
        # Create a minimal PNG (1x1 pixel)
        import struct, zlib
        def make_png():
            sig = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            raw = b'\x00\x00\x00\x00'
            idat_data = zlib.compress(raw)
            idat_crc = zlib.crc32(b'IDAT' + idat_data) & 0xffffffff
            idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + struct.pack('>I', idat_crc)
            iend_crc = zlib.crc32(b'IEND') & 0xffffffff
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            return sig + ihdr + idat + iend

        png = make_png()
        data = {
            "frames": (io.BytesIO(png), "frame_00000.png"),
            "fps": "10",
            "crf": "22",
        }
        with patch("shutil.which", return_value=None):
            resp = client.post("/upload_spectrum_frames",
                               data=data,
                               content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "warning" in body
        assert body["video_token"] is None

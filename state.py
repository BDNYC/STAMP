"""
Thread-safe shared mutable state for STAMP.

All mutable global state lives here so that dependencies are explicit.
Other modules read/write through this module's attributes.
"""

import threading
import time as _time

from cache_manager import DatasetCache

# Background-job tracking
PROGRESS = {}          # job_id -> progress record dict
RESULTS = {}           # job_id -> completed result payload dict
PROG_LOCK = threading.Lock()

# Dataset cache (disk-backed, LRU, 24-hour TTL, 10 GB cap)
cache = DatasetCache(ttl_hours=24, max_cache_size_gb=10)

# Latest plot objects shared between route handlers
latest_surface_figure = None
latest_heatmap_figure = None
latest_spectrum_video_path = None

last_surface_plot_html = None
last_heatmap_plot_html = None
last_surface_fig_json = None
last_heatmap_fig_json = None
last_custom_bands = []
latest_spectrum_mp4_path = None

# Per-token video temp paths
video_tmp_paths = {}


def _progress_set(job_id, *, percent=None, message=None, status=None,
                  reset=False, stage=None, processed_integrations=None,
                  total_integrations=None, throughput=None, eta_seconds=None):
    """Create or update a background-job progress record (thread-safe).
    Returns a snapshot copy of the record.
    """
    with PROG_LOCK:
        rec = PROGRESS.get(job_id)
        if reset or rec is None:
            rec = {
                "status": "running",
                "percent": 0.0,
                "eta_seconds": None,
                "message": "Starting",
                "started_at": _time.time(),
                "stage": "queued",
                "processed_integrations": 0,
                "total_integrations": None,
                "throughput": None,
            }
            PROGRESS[job_id] = rec

        if percent is not None:
            p = float(percent)
            if status != "done":
                p = max(0.0, min(99.0, p))
            rec["percent"] = p

            frac = p / 100.0
            if eta_seconds is not None:
                rec["eta_seconds"] = int(eta_seconds)
            else:
                if 0.0 < frac < 1.0:
                    elapsed = _time.time() - rec["started_at"]
                    rec["eta_seconds"] = int(
                        max(0.0, elapsed * (1.0 - frac) / max(1e-6, frac))
                    )
                else:
                    rec["eta_seconds"] = None

        if message is not None:
            rec["message"] = message
        if status is not None:
            rec["status"] = status
        if stage is not None:
            rec["stage"] = stage
        if processed_integrations is not None:
            rec["processed_integrations"] = int(processed_integrations)
        if total_integrations is not None:
            rec["total_integrations"] = int(total_integrations)
        if throughput is not None:
            rec["throughput"] = float(throughput)

        return rec.copy()

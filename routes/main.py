"""
routes/main.py
Core page routes: index page, static plot serving, and the before-request
hook that resolves video tokens into file paths.
"""

import os
import tempfile

from flask import Blueprint, render_template, send_from_directory, request

import state

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Serve the main single-page application."""
    return render_template('index.html')


@main_bp.route('/plots/<path:filename>')
def serve_plots(filename):
    """Serve static plot files from the ``plots/`` directory."""
    return send_from_directory('plots', filename)


@main_bp.before_app_request
def _attach_video_token():
    """Resolve a ``video_token`` query/form parameter to a temp-file path.

    The ``/upload_spectrum_frames`` endpoint generates an MP4 file and
    returns a unique token.  When a subsequent request includes that token,
    this hook looks up the token file, reads the MP4 path it contains, and
    stores it in ``state.latest_spectrum_mp4_path`` so that
    ``/download_plots`` can include the video in the export ZIP.
    """
    token = request.args.get('video_token') or (
        request.form.get('video_token') if request.method == 'POST' else None
    )
    if not token:
        return
    p = os.path.join(tempfile.gettempdir(), f"spectrum_token_{token}.txt")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fp:
                path = fp.read().strip()
            if path and os.path.exists(path):
                state.latest_spectrum_mp4_path = path
        except Exception:
            pass

"""
routes/main.py
Core page routes: index page and static plot serving.
"""

from flask import Blueprint, render_template, send_from_directory

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Serve the main single-page application."""
    return render_template('index.html')


@main_bp.route('/plots/<path:filename>')
def serve_plots(filename):
    """Serve static plot files from the ``plots/`` directory."""
    return send_from_directory('plots', filename)

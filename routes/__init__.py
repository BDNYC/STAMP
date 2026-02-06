"""
routes/
Flask Blueprint registration for SA3D (STAMP).

Each sub-module defines a Blueprint containing related route handlers:

- **main** — Index page, static plot serving, video-token hook.
- **upload** — Synchronous file upload, spectrum-frame video, plot download.
- **jobs** — Asynchronous background processing, progress, and results.
"""

from routes.main import main_bp
from routes.upload import upload_bp
from routes.jobs import jobs_bp


def register_blueprints(app):
    """Attach all route Blueprints to the Flask application instance."""
    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(jobs_bp)

import sys
sys.stderr.write(f"WSGI USING: {sys.executable}\n"); sys.stderr.flush()

# Load server environment variables (GRIDS_DIR, DEMO_DATA_DIR) if deployed
try:
    sys.path.insert(0, "/var/www/webroot")
    import env  # noqa: F401
except ImportError:
    pass

from app import app as application

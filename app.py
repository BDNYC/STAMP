"""
app.py
Flask application factory for SA3D — JWST Spectral Analysis in 3D (STAMP).

This file creates the Flask instance and registers all route blueprints.
All business logic lives in dedicated modules:

- config.py        Configuration, constants, YAML loading
- state.py         Shared mutable state (progress, results, plot cache)
- data_io.py       FITS and HDF5 file readers
- processing.py    Numerical pipeline (binning, smoothing, regridding)
- plotting.py      Plotly figure construction
- routes/          Flask route Blueprints
- cache_manager.py Disk-based dataset cache
- apod_service.py  NASA APOD integration
"""

from flask import Flask
from routes import register_blueprints

app = Flask(__name__)
register_blueprints(app)

if __name__ == '__main__':
    app.run(debug=True)

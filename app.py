"""
Flask application factory for STAMP (Spectral Time-series Analysis and Mapping Program).
"""

from flask import Flask
from routes import register_blueprints

app = Flask(__name__)
register_blueprints(app)

if __name__ == '__main__':
    app.run(debug=True)

"""
config.py
Application configuration, constants, and YAML config loader for SA3D (STAMP).

This module contains all static configuration and constants used across the
application. It has no dependencies on Flask, numpy, or any other heavy
libraries, so every other module can safely import from here.
"""

import os
import logging
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plotly colorscale options presented in the UI dropdown
# ---------------------------------------------------------------------------
COLOR_SCALES = [
    'Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis',
    'Turbo', 'Viridis', 'Spectral', 'RdYlBu', 'Picnic',
]


# ---------------------------------------------------------------------------
# YAML config loader
# ---------------------------------------------------------------------------
def load_config(config_file='config.yaml'):
    """Load application settings from a YAML config file.

    Parameters
    ----------
    config_file : str
        Path to the YAML file. Relative paths are resolved against BASE_DIR.

    Returns
    -------
    dict
        Parsed configuration, or an empty dict if the file is missing or invalid.
    """
    try:
        cfg_path = (
            config_file
            if os.path.isabs(config_file)
            else os.path.join(BASE_DIR, config_file)
        )
        with open(cfg_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Error loading configuration: {str(e)}.Using default values.")
        return {}


CONFIG = load_config()
DATA_DIR = CONFIG.get('data_dir', 'Data')

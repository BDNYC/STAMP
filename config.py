"""
Configuration, constants, and YAML config loader for STAMP.
"""

import os
import logging
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

COLOR_SCALES = [
    'Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis',
    'Turbo', 'Viridis', 'Spectral', 'RdYlBu', 'Picnic',
]


def load_config(config_file='config.yaml'):
    """Load settings from a YAML config file. Returns {} on failure."""
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

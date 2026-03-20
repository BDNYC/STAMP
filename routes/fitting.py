"""Model fitting routes for STAMP — sinusoidal and spectral grid fitting."""

import os
import json
import threading
import uuid
import logging

import numpy as np
from flask import Blueprint, request, jsonify

from config import GRIDS_DIR
from state import _progress_set, RESULTS, PROG_LOCK
from fitting import (
    fit_sinusoidal,
    fit_sinusoidal_all_wavelengths,
    fit_spectrum_to_grid,
    fit_spectrum_chunked,
    fit_spectrum_all_timesteps,
)
from model_grids import load_grid_from_directory, list_available_grids

logger = logging.getLogger(__name__)

fitting_bp = Blueprint('fitting', __name__)


@fitting_bp.route('/fit/sinusoidal', methods=['POST'])
def fit_sine():
    """Fit sine(s) to a single 1D light curve (synchronous)."""
    try:
        data = request.get_json(force=True)
        time_arr = data['time']
        flux_arr = data['flux']
        error_arr = data.get('error')
        n_sines = int(data.get('n_sines', 1))
        period_guess = data.get('period_guess')
        if period_guess is not None:
            period_guess = float(period_guess)

        result = fit_sinusoidal(time_arr, flux_arr, error_arr,
                                n_sines=n_sines, period_guess=period_guess)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Sinusoidal fit error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 400


@fitting_bp.route('/fit/sinusoidal_all_wavelengths', methods=['POST'])
def fit_sine_sweep():
    """Fit sinusoidal model across all wavelengths (async, returns job_id)."""
    try:
        data = request.get_json(force=True)
        wavelength_arr = data['wavelengths']
        time_arr = data['time']
        flux_2d = data['flux_2d']
        error_2d = data.get('error_2d')
        n_sines = int(data.get('n_sines', 1))
        period_guess = data.get('period_guess')
        if period_guess is not None:
            period_guess = float(period_guess)

        job_id = uuid.uuid4().hex
        _progress_set(job_id, reset=True, percent=1.0,
                       message="Starting amplitude sweep...", stage="fitting")

        def _worker():
            try:
                def cb(pct):
                    _progress_set(job_id, percent=min(95.0, pct),
                                   message=f"Fitting wavelengths... {pct:.0f}%")

                result = fit_sinusoidal_all_wavelengths(
                    wavelength_arr, time_arr, flux_2d, error_2d,
                    n_sines=n_sines, period_guess=period_guess,
                    progress_cb=cb,
                )

                with PROG_LOCK:
                    RESULTS[job_id] = result

                _progress_set(job_id, percent=100.0, message="Done",
                               status="done", stage="done")

            except Exception as exc:
                logger.exception(f"Sine sweep job {job_id[:8]} failed")
                _progress_set(job_id, message=str(exc), status="error", stage="error")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return jsonify({"job_id": job_id}), 202

    except Exception as e:
        logger.error(f"Sine sweep start error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 400


@fitting_bp.route('/fit/spectrum', methods=['POST'])
def fit_grid():
    """Fit one observed spectrum against a model grid (synchronous)."""
    try:
        data = request.get_json(force=True)
        obs_wl = data['wavelengths']
        obs_flux = data['flux']
        obs_error = data['error']
        grid_name = data['grid_name']

        grid_dir = os.path.join(GRIDS_DIR, grid_name)
        if not os.path.isdir(grid_dir):
            return jsonify({"success": False, "error": f"Grid '{grid_name}' not found"}), 404

        grid = load_grid_from_directory(grid_dir)
        result = fit_spectrum_to_grid(
            obs_wl, obs_flux, obs_error,
            grid["wavelengths"], grid["spectra"], grid["params"],
        )
        return jsonify(result)

    except Exception as e:
        logger.error(f"Spectrum fit error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 400


@fitting_bp.route('/fit/spectrum_chunked', methods=['POST'])
def fit_grid_chunked():
    """Fit observed spectrum in wavelength chunks against a model grid."""
    try:
        data = request.get_json(force=True)
        obs_wl = data['wavelengths']
        obs_flux = data['flux']
        obs_error = data['error']
        grid_name = data['grid_name']
        chunks = data['chunks']

        grid_dir = os.path.join(GRIDS_DIR, grid_name)
        if not os.path.isdir(grid_dir):
            return jsonify({"success": False, "error": f"Grid '{grid_name}' not found"}), 404

        grid = load_grid_from_directory(grid_dir)
        result = fit_spectrum_chunked(
            obs_wl, obs_flux, obs_error,
            grid["wavelengths"], grid["spectra"], grid["params"],
            chunks,
        )
        return jsonify(result)

    except Exception as e:
        logger.error(f"Chunked spectrum fit error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 400


@fitting_bp.route('/fit/spectrum_all_timesteps', methods=['POST'])
def fit_grid_sweep():
    """Fit each time-step spectrum against a model grid (async, returns job_id)."""
    try:
        data = request.get_json(force=True)
        wavelength_arr = data['wavelengths']
        time_arr = data['time']
        flux_2d = data['flux_2d']
        error_2d = data['error_2d']
        grid_name = data['grid_name']

        grid_dir = os.path.join(GRIDS_DIR, grid_name)
        if not os.path.isdir(grid_dir):
            return jsonify({"success": False, "error": f"Grid '{grid_name}' not found"}), 404

        grid = load_grid_from_directory(grid_dir)

        job_id = uuid.uuid4().hex
        _progress_set(job_id, reset=True, percent=1.0,
                       message="Starting parameter sweep...", stage="fitting")

        def _worker():
            try:
                def cb(pct):
                    _progress_set(job_id, percent=min(95.0, pct),
                                   message=f"Fitting timesteps... {pct:.0f}%")

                result = fit_spectrum_all_timesteps(
                    wavelength_arr, time_arr, flux_2d, error_2d,
                    grid["wavelengths"], grid["spectra"], grid["params"],
                    progress_cb=cb,
                )

                with PROG_LOCK:
                    RESULTS[job_id] = result

                _progress_set(job_id, percent=100.0, message="Done",
                               status="done", stage="done")

            except Exception as exc:
                logger.exception(f"Grid sweep job {job_id[:8]} failed")
                _progress_set(job_id, message=str(exc), status="error", stage="error")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return jsonify({"job_id": job_id}), 202

    except Exception as e:
        logger.error(f"Grid sweep start error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 400


@fitting_bp.route('/fit/grid_list', methods=['GET'])
def get_grid_list():
    """List available model grids."""
    try:
        grids = list_available_grids(GRIDS_DIR)
        return jsonify({"grids": grids})
    except Exception as e:
        logger.error(f"Grid list error: {e}", exc_info=True)
        return jsonify({"grids": [], "error": str(e)})

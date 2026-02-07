"""Background job management routes for async MAST data processing."""

import os
import json
import copy
import shutil
import zipfile
import tempfile
import threading
import uuid
import logging

import numpy as np
import plotly.io as pio
from flask import Blueprint, request, jsonify
from astropy.io import fits
import h5py

import state
from state import _progress_set, PROGRESS, RESULTS, PROG_LOCK, cache
from config import BASE_DIR
from data_io import apply_data_ranges, _first_key
from processing import process_mast_files_with_gaps
from plotting import create_surface_plot_with_visits, create_heatmap_plot

logger = logging.getLogger(__name__)

jobs_bp = Blueprint('jobs', __name__)


def _extract_and_sort(zip_path, work_dir):
    """Extract a ZIP archive and return FITS/H5 paths sorted by observation time."""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(work_dir)

    fits_files = []
    for root, _, files in os.walk(work_dir):
        for f in files:
            if f.lower().endswith(('.fits', '.h5')):
                fits_files.append(os.path.join(root, f))

    file_times = []
    for fp in fits_files:
        try:
            if fp.endswith('.fits'):
                with fits.open(fp) as hdul:
                    t = hdul['INT_TIMES'].data['int_mid_MJD_UTC'][0]
            elif fp.endswith('.h5'):
                with h5py.File(fp, 'r') as h:
                    t = float(h['time'][0]) if 'time' in h else None
            else:
                t = None
            if t is not None:
                file_times.append((fp, t))
        except Exception:
            continue
    return [fp for fp, _ in sorted(file_times, key=lambda x: x[1])]


def _run_mast_job(job_id, zip_path, form_args):
    """Background worker: process a MAST zip through the full pipeline and store results."""
    _progress_set(job_id, reset=True, percent=1.0, message="Queued…", stage="queued")
    temp_dir = tempfile.mkdtemp(prefix=f"mast_job_{job_id[:8]}_")
    is_demo = form_args.get("is_demo", False)

    try:
        use_interpolation = form_args["use_interpolation"]
        num_integrations = form_args["num_integrations"]

        # Stage 1: Cache check
        _progress_set(job_id, percent=2.0, message="Checking cache…", stage="scan")

        cache_key_path = zip_path

        logger.info(f"Job {job_id[:8]}: Cache lookup parameters:")
        logger.info(f"   zip_path: {os.path.basename(zip_path)}")
        logger.info(f"   cache_key_path: {os.path.basename(cache_key_path)}")
        logger.info(f"   interpolation: {use_interpolation}")
        logger.info(f"   num_integrations: {num_integrations}")

        cached_data = cache.get(cache_key_path, use_interpolation)

        if cached_data:
            logger.info(f"Job {job_id[:8]}: Cache HIT!")
            logger.info(f"   Cached metadata total_integrations:   {cached_data['metadata'].get('total_integrations', 'unknown')}")
            logger.info(f"   Cached metadata plotted_integrations: {cached_data['metadata'].get('plotted_integrations', 'unknown')}")
            logger.info(f"   Cached time_1d length: {len(cached_data['time_1d'])}")
            logger.info(f"   Cached wavelength_1d length: {len(cached_data['wavelength_1d'])}")
            logger.info(f"   Cached flux_raw_2d shape: {cached_data['flux_raw_2d'].shape}")

            _progress_set(job_id, percent=60.0, message="Loaded from cache", stage="read")

            # Deep-copy so mutations don't corrupt the cache
            wavelength_1d = cached_data['wavelength_1d'].copy()
            flux_norm_2d = cached_data['flux_norm_2d'].copy()
            flux_raw_2d = cached_data['flux_raw_2d'].copy()
            time_1d = cached_data['time_1d'].copy()
            metadata = copy.deepcopy(cached_data['metadata'])
            error_raw_2d = cached_data['error_raw_2d'].copy()

            logger.info(f"   Data copied from cache")

        else:
            logger.info(f"Job {job_id[:8]}: Cache MISS - processing from scratch")

            # Stage 2: Extract & sort
            work_dir = os.path.join(temp_dir, "unzipped")
            os.makedirs(work_dir, exist_ok=True)
            _progress_set(job_id, percent=3.0, message="Extracting archive…", stage="scan")
            fits_files_sorted = _extract_and_sort(zip_path, work_dir)

            if not fits_files_sorted:
                raise ValueError("No valid FITS/H5 files found in archive.")

            logger.info(f"   Found {len(fits_files_sorted)} FITS/H5 files")

            # Stage 3: Process
            def cb(pct, msg=None, **kw):
                _progress_set(job_id, percent=pct, message=msg, **kw)

            wavelength_1d, flux_norm_2d, flux_raw_2d, time_1d, metadata, error_raw_2d = (
                process_mast_files_with_gaps(
                    fits_files_sorted,
                    use_interpolation,
                    max_integrations=None,
                    progress_cb=cb,
                )
            )

            logger.info(f"   Processed total_integrations: {metadata.get('total_integrations', 'unknown')}")
            logger.info(f"   Processed plotted_integrations: {metadata.get('plotted_integrations', 'unknown')}")
            logger.info(f"   Processed time_1d length: {len(time_1d)}")
            logger.info(f"   Processed wavelength_1d length:  {len(wavelength_1d)}")
            logger.info(f"   Processed flux_raw_2d shape: {flux_raw_2d.shape}")

            # Stage 4: Cache store
            _progress_set(job_id, percent=93.0, message="Caching processed data…", stage="finalize")

            cache_data = {
                'wavelength_1d': wavelength_1d,
                'flux_norm_2d': flux_norm_2d,
                'flux_raw_2d': flux_raw_2d,
                'time_1d': time_1d,
                'metadata': metadata,
                'error_raw_2d': error_raw_2d,
            }

            cache.set(cache_key_path, use_interpolation, cache_data)
            logger.info(f"Data cached successfully")

        logger.info(f"Job {job_id[:8]}: Data state after cache retrieval:")
        logger.info(f"   metadata total_integrations: {metadata.get('total_integrations', 'unknown')}")
        logger.info(f"   metadata plotted_integrations:   {metadata.get('plotted_integrations', 'unknown')}")
        logger.info(f"   time_1d length:  {len(time_1d)}")
        logger.info(f"   time_1d range: {time_1d.min():.2f} to {time_1d.max():.2f} hours")

        # Stage 5: Sample (optional)
        if num_integrations and num_integrations > 0 and num_integrations < len(time_1d):
            _progress_set(
                job_id, percent=94.0,
                message=f"Sampling to {num_integrations} integrations…",
                stage="finalize",
            )
            logger.info(f"Sampling from {len(time_1d)} to {num_integrations} integrations")

            step = len(time_1d) / num_integrations
            indices = [int(i * step) for i in range(num_integrations)]

            flux_norm_2d = flux_norm_2d[:, indices]
            flux_raw_2d = flux_raw_2d[:, indices]
            error_raw_2d = error_raw_2d[:, indices]
            time_1d = time_1d[indices]

            metadata['plotted_integrations'] = num_integrations

            logger.info(f"   Sampled to {len(time_1d)} integrations")
            logger.info(f"   New flux shape: {flux_raw_2d.shape}")

        # Stage 6: Filter — apply user-specified ranges
        _progress_set(job_id, percent=95.0, message="Applying filters…", stage="finalize")

        custom_bands = form_args["custom_bands"]
        colorscale = form_args["colorscale"]
        z_axis_display = form_args["z_axis_display"]
        time_range = form_args["time_range"]
        wavelength_range = form_args["wavelength_range"]
        variability_range = form_args["variability_range"]

        range_info = []
        if wavelength_range or time_range:
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm, range_info = apply_data_ranges(
                wavelength_1d, flux_norm_2d, time_1d, wavelength_range, time_range,
            )
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw, _ = apply_data_ranges(
                wavelength_1d, flux_raw_2d, time_1d, wavelength_range, time_range,
            )
            wavelength_1d_err, error_raw_2d_filtered, time_1d_err, _ = apply_data_ranges(
                wavelength_1d, error_raw_2d, time_1d, wavelength_range, time_range,
            )
            logger.info(f"   Ranges applied: {'; '.join(range_info)}")
        else:
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm = wavelength_1d, flux_norm_2d, time_1d
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw = wavelength_1d, flux_raw_2d, time_1d
            wavelength_1d_err, error_raw_2d_filtered, time_1d_err = wavelength_1d, error_raw_2d, time_1d
            logger.info(f"   No range filtering applied")

        metadata['user_ranges'] = '; '.join(range_info) if range_info else None

        logger.info(f"Job {job_id[:8]}: Final data for plotting:")
        logger.info(f"   time_1d_norm length: {len(time_1d_norm)}")
        logger.info(f"   time_1d_norm range: {time_1d_norm.min():.2f} to {time_1d_norm.max():.2f} hours")
        logger.info(f"   flux shape: {flux_norm_2d_filtered.shape}")

        # Choose Z data based on display mode
        if z_axis_display == 'flux':
            z_data = flux_raw_2d_filtered
            errors_for_plot = error_raw_2d_filtered
        else:
            z_data = flux_norm_2d_filtered
            median_per_wl = np.nanmedian(flux_raw_2d_filtered, axis=1, keepdims=True)
            median_per_wl[median_per_wl == 0] = 1.0
            errors_for_plot = (error_raw_2d_filtered / median_per_wl) * 100

        ref_spec = np.nanmedian(np.asarray(flux_raw_2d_filtered), axis=1)

        # Stage 7: Plot
        _progress_set(
            job_id, percent=96.0, message="Rendering plots…", stage="finalize",
            processed_integrations=_progress_set(job_id)["processed_integrations"],
            total_integrations=_progress_set(job_id)["total_integrations"],
        )

        surface_plot = create_surface_plot_with_visits(
            z_data,
            wavelength_1d_norm if z_axis_display != 'flux' else wavelength_1d_raw,
            time_1d_norm if z_axis_display != 'flux' else time_1d_raw,
            '3D Surface Plot',
            num_plots=1000,
            smooth_sigma=2,
            wavelength_unit='um',
            custom_bands=custom_bands,
            colorscale=colorscale,
            z_range=variability_range,
            z_axis_display=z_axis_display,
            flux_unit=metadata.get('flux_unit', 'Unknown'),
            errors_2d=errors_for_plot,
        )

        heatmap_plot = create_heatmap_plot(
            z_data,
            wavelength_1d_norm if z_axis_display != 'flux' else wavelength_1d_raw,
            time_1d_norm if z_axis_display != 'flux' else time_1d_raw,
            'Heatmap',
            num_plots=1000,
            smooth_sigma=2,
            wavelength_unit='um',
            custom_bands=custom_bands,
            colorscale=colorscale,
            z_range=variability_range,
            z_axis_display=z_axis_display,
            flux_unit=metadata.get('flux_unit', 'Unknown'),
            errors_2d=error_raw_2d_filtered,
        )

        # Store plot data in shared state for /download_plots
        state.last_surface_plot_html = pio.to_html(surface_plot, include_plotlyjs='cdn', full_html=True)
        state.last_heatmap_plot_html = pio.to_html(heatmap_plot, include_plotlyjs='cdn', full_html=True)
        state.last_surface_fig_json = surface_plot.to_plotly_json()
        state.last_heatmap_fig_json = heatmap_plot.to_plotly_json()
        state.last_custom_bands = custom_bands

        # Stage 8: Store results
        payload = {
            'surface_plot': surface_plot.to_json(),
            'heatmap_plot': heatmap_plot.to_json(),
            'metadata': metadata,
            'reference_spectrum': json.dumps(ref_spec.tolist()),
        }

        with PROG_LOCK:
            RESULTS[job_id] = payload

        logger.info(f"Job {job_id[:8]}: Completed successfully")
        _progress_set(job_id, percent=100.0, message="Done", status="done", stage="done")

    except Exception as e:
        logger.exception(f"Job {job_id[:8]}: Background job failed")
        _progress_set(job_id, message=str(e), status="error", stage="error")
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        if not is_demo:
            try:
                os.remove(zip_path)
            except Exception:
                pass


@jobs_bp.route('/start_mast', methods=['POST'])
def start_mast():
    """Start an async MAST processing job; returns a job_id (HTTP 202)."""
    try:
        use_demo = request.form.get('use_demo', 'false').lower() == 'true'

        if use_demo:
            demo_zip = os.path.join(BASE_DIR, 'static', 'demo_data', 'demo_jwst_timeseries.zip')
            if not os.path.exists(demo_zip):
                return jsonify({'error': 'Demo dataset not found. Please upload your own data.'}), 404
            tmp_zip = demo_zip
            logger.info(f"Using demo dataset at {demo_zip}")
        else:
            mast_file = request.files.get('mast_zip')
            if not mast_file or mast_file.filename == '':
                return jsonify({'error': 'No MAST zip file provided'}), 400
            tmp_zip = os.path.join(tempfile.gettempdir(), f"mast_job_{uuid.uuid4().hex}.zip")
            mast_file.save(tmp_zip)
            logger.info(f"Processing uploaded file: {mast_file.filename}")

        # Parse form parameters
        custom_bands_json = request.form.get('custom_bands', '[]')
        try:
            custom_bands = json.loads(custom_bands_json)
        except json.JSONDecodeError:
            custom_bands = []

        use_interpolation = request.form.get('use_interpolation', 'false').lower() == 'true'
        colorscale = request.form.get('colorscale', 'Viridis')
        num_integrations = int(request.form.get('num_integrations', '0') or 0)
        z_axis_display = request.form.get('z_axis_display', 'variability')

        time_range_min = request.form.get('time_range_min', '')
        time_range_max = request.form.get('time_range_max', '')
        wavelength_range_min = request.form.get('wavelength_range_min', '')
        wavelength_range_max = request.form.get('wavelength_range_max', '')
        variability_range_min = request.form.get('variability_range_min', '')
        variability_range_max = request.form.get('variability_range_max', '')

        time_range = None
        wavelength_range = None
        variability_range = None
        if time_range_min or time_range_max:
            t_min = float(time_range_min) if time_range_min else None
            t_max = float(time_range_max) if time_range_max else None
            time_range = (t_min, t_max)
        if wavelength_range_min or wavelength_range_max:
            wl_min = float(wavelength_range_min) if wavelength_range_min else None
            wl_max = float(wavelength_range_max) if wavelength_range_max else None
            wavelength_range = (wl_min, wl_max)
        if variability_range_min or variability_range_max:
            v_min = float(variability_range_min) if variability_range_min else None
            v_max = float(variability_range_max) if variability_range_max else None
            variability_range = (v_min, v_max)

        # Spawn background thread
        job_id = uuid.uuid4().hex
        _progress_set(job_id, reset=True, percent=1.0, message="Queued…", stage="queued")
        form_args = {
            "custom_bands": custom_bands,
            "use_interpolation": use_interpolation,
            "colorscale": colorscale,
            "num_integrations": num_integrations,
            "z_axis_display": z_axis_display,
            "time_range": time_range,
            "wavelength_range": wavelength_range,
            "variability_range": variability_range,
            "is_demo": use_demo,
        }
        t = threading.Thread(target=_run_mast_job, args=(job_id, tmp_zip, form_args), daemon=True)
        t.start()
        return jsonify({"job_id": job_id}), 202

    except Exception as e:
        logger.error(f"Error starting job: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 400


@jobs_bp.route('/progress/<job_id>')
def get_progress(job_id):
    """Return the current progress record for a background job."""
    rec = PROGRESS.get(job_id)
    if not rec:
        return jsonify({"error": "unknown job"}), 404
    with PROG_LOCK:
        out = dict(PROGRESS[job_id])
    return jsonify(out)


@jobs_bp.route('/results/<job_id>')
def get_results(job_id):
    """Return the final result payload once a background job has completed."""
    rec = PROGRESS.get(job_id)
    if not rec:
        return jsonify({"error": "unknown job"}), 404
    if rec.get("status") == "error":
        return jsonify({"error": rec.get("message", "processing error")}), 500
    if rec.get("status") != "done":
        return jsonify({"error": "not ready"}), 202
    payload = RESULTS.get(job_id)
    if not payload:
        return jsonify({"error": "no payload"}), 500
    return jsonify(payload)

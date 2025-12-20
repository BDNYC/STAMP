from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from astropy.io import fits
import numpy as np
import json
import plotly.graph_objs as go
from scipy.stats import binned_statistic
from scipy.ndimage import gaussian_filter
from concurrent.futures import ThreadPoolExecutor
import logging
from io import BytesIO
import yaml
import os
import zipfile
import tempfile
import shutil
import base64
from astropy.time import Time
from astropy.stats import sigma_clip
from scipy import interpolate
import plotly.io as pio
from datetime import datetime
import h5py
import os
import threading
import time as _time
import uuid


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)




logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

latest_surface_figure = None
latest_heatmap_figure = None
latest_spectrum_video_path = None


PROGRESS = {}
RESULTS  = {}
PROG_LOCK = threading.Lock()

def _progress_set(job_id, *, percent=None, message=None, status=None, reset=False, stage=None, processed_integrations=None, total_integrations=None, throughput=None, eta_seconds=None):
    with PROG_LOCK:
        rec = PROGRESS.get(job_id)
        if reset or rec is None:
            rec = {"status": "running", "percent": 0.0, "eta_seconds": None, "message": "Starting", "started_at": _time.time(), "stage": "queued", "processed_integrations": 0, "total_integrations": None, "throughput": None}
            PROGRESS[job_id] = rec
        if percent is not None:
            p = float(percent)
            if status != "done":
                p = max(0.0, min(99.0, p))
            rec["percent"] = p
            frac = p / 100.0
            if eta_seconds is not None:
                rec["eta_seconds"] = int(eta_seconds)
            else:
                if 0.0 < frac < 1.0:
                    elapsed = _time.time() - rec["started_at"]
                    rec["eta_seconds"] = int(max(0.0, elapsed * (1.0 - frac) / max(1e-6, frac)))
                else:
                    rec["eta_seconds"] = None
        if message is not None:
            rec["message"] = message
        if status is not None:
            rec["status"] = status
        if stage is not None:
            rec["stage"] = stage
        if processed_integrations is not None:
            rec["processed_integrations"] = int(processed_integrations)
        if total_integrations is not None:
            rec["total_integrations"] = int(total_integrations)
        if throughput is not None:
            rec["throughput"] = float(throughput)
        return rec.copy()

COLOR_SCALES = ['Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis', 'Turbo', 'Viridis', 'Spectral', 'RdYlBu', 'Picnic']


def load_config(config_file='config.yaml'):
    try:
        cfg_path = config_file if os.path.isabs(config_file) else os.path.join(BASE_DIR, config_file)
        with open(cfg_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Error loading configuration: {str(e)}. Using default values.")
        return {}


CONFIG = load_config()
DATA_DIR = CONFIG.get('data_dir', 'Data')


def apply_data_ranges(wavelength, flux, time, wavelength_range=None, time_range=None):
    range_info = []
    original_wl_range = (wavelength.min(), wavelength.max())
    original_time_range = (time.min(), time.max())
    if wavelength_range and (wavelength_range[0] is not None or wavelength_range[1] is not None):
        wl_min = wavelength_range[0] if wavelength_range[0] is not None else original_wl_range[0]
        wl_max = wavelength_range[1] if wavelength_range[1] is not None else original_wl_range[1]
        wl_min = max(wl_min, original_wl_range[0])
        wl_max = min(wl_max, original_wl_range[1])
        if wl_min >= wl_max:
            logger.warning(f"Invalid wavelength range: {wl_min} to {wl_max}. Using full range.")
            wl_mask = np.ones(len(wavelength), dtype=bool)
        else:
            wl_mask = (wavelength >= wl_min) & (wavelength <= wl_max)
            range_info.append(f"Wavelength: {wl_min:.3f} - {wl_max:.3f} µm")
    else:
        wl_mask = np.ones(len(wavelength), dtype=bool)
    if time_range and (time_range[0] is not None or time_range[1] is not None):
        time_min = time_range[0] if time_range[0] is not None else original_time_range[0]
        time_max = time_range[1] if time_range[1] is not None else original_time_range[1]
        time_min = max(time_min, original_time_range[0])
        time_max = min(time_max, original_time_range[1])
        if time_min >= time_max:
            logger.warning(f"Invalid time range: {time_min} to {time_max}. Using full range.")
            time_mask = np.ones(len(time), dtype=bool)
        else:
            time_mask = (time >= time_min) & (time <= time_max)
            range_info.append(f"Time: {time_min:.2f} - {time_max:.2f} hours")
    else:
        time_mask = np.ones(len(time), dtype=bool)
    filtered_wavelength = wavelength[wl_mask]
    filtered_flux = flux[wl_mask, :][:, time_mask]
    filtered_time = time[time_mask]
    logger.info(f"Wavelength filtering: {len(wavelength)} -> {len(filtered_wavelength)} points")
    logger.info(f"Time filtering: {len(time)} -> {len(filtered_time)} points")
    return filtered_wavelength, filtered_flux, filtered_time, range_info


def _first_key(group, *candidates):
    for k in candidates:
        if k in group:
            return k
    return None


def load_integrations_from_h5(file_path, per_integ_cb=None, total_in_file=None):
    with h5py.File(file_path, 'r') as f:
        flux_k = _first_key(f, "calibrated_optspec", "stdspec", "optspec")
        wave_k = _first_key(f, "eureka_wave_1d", "wave_1d", "wavelength", "wave")
        time_k = _first_key(f, "time", "bmjd", "mjd", "bjd", "time_bjd", "time_mjd")
        err_k  = _first_key(f, "calibrated_opterr", "stdvar", "error", "flux_error", "sigma")
        if not (flux_k and wave_k and time_k):
            return None, None
        flux = f[flux_k][:]
        wl   = f[wave_k][:]
        t    = f[time_k][:]
        err = None
        if err_k:
            err_data = f[err_k][:]
            if err_k.endswith("stdvar"):
                err = np.sqrt(err_data)
            else:
                err = err_data
        integrations = []
        nint = flux.shape[0]
        for i in range(flux.shape[0]):
            integrations.append({
                "wavelength": wl,
                "flux": flux[i, :],
                "error": (err[i, :] if err is not None else np.full(flux.shape[1], np.nan)),
                "time": t[i]
            })
            if per_integ_cb:
                per_integ_cb(i + 1, total_in_file or nint)
        header_info = {
            "filename": os.path.basename(file_path),
            "target": "Unknown",
            "instrument": "Unknown",
            "filter": "Unknown",
            "grating": "Unknown",
            "obs_date": "Unknown",
            "exposure_time": "Unknown",
            "flux_unit": "Unknown"
        }
        return integrations, header_info



def load_integrations_from_fits(file_path, per_integ_cb=None, total_in_file=None):
    try:
        with fits.open(file_path) as hdul:
            mids = hdul['INT_TIMES'].data['int_mid_MJD_UTC']
            header_info = {
                'filename': os.path.basename(file_path),
                'target': hdul[0].header.get('TARGNAME', 'Unknown'),
                'instrument': hdul[0].header.get('INSTRUME', 'Unknown'),
                'filter': hdul[0].header.get('FILTER', 'Unknown'),
                'grating': hdul[0].header.get('GRATING', 'Unknown'),
                'obs_date': hdul[0].header.get('DATE-OBS', 'Unknown'),
                'exposure_time': hdul[0].header.get('EXPTIME', 'Unknown'),
            }
            flux_unit = hdul[0].header.get('BUNIT', None)
            if flux_unit is None and 'EXTRACT1D' in hdul:
                flux_unit = hdul['EXTRACT1D'].header.get('BUNIT', None)
            if flux_unit is None:
                for i in range(1, 10):
                    unit = hdul['EXTRACT1D'].header.get(f'TUNIT{i}', None)
                    if unit and 'flux' in hdul['EXTRACT1D'].header.get(f'TTYPE{i}', '').lower():
                        flux_unit = unit
                        break
            if flux_unit is None:
                flux_unit = 'MJy'
            header_info['flux_unit'] = flux_unit
            integrations = []
            extract = hdul['EXTRACT1D'].data if 'EXTRACT1D' in hdul else None
            nint = len(extract) if extract is not None else len(mids)
            for idx, mjd in enumerate(mids[:nint], start=1):
                try:
                    data = hdul['EXTRACT1D', idx].data
                    w = data['WAVELENGTH']
                    f = data['FLUX']
                    e = data['FLUX_ERROR'] if 'FLUX_ERROR' in data.names else np.full_like(f, np.nan)
                except Exception:
                    if extract is None or (idx - 1) >= len(extract):
                        raise
                    row = extract[idx - 1]
                    w = row['WAVELENGTH']
                    f = row['FLUX']
                    e = row['FLUX_ERROR'] if 'FLUX_ERROR' in extract.names else np.full_like(f, np.nan)
                mask = ~np.isnan(f)
                integrations.append({
                    'wavelength': w[mask],
                    'flux': f[mask],
                    'error': e[mask] if e is not None else np.full(np.sum(mask), np.nan),
                    'time': Time(mjd, format='mjd', scale='utc')
                })
                if per_integ_cb:
                    per_integ_cb(idx, total_in_file or nint)
            return integrations, header_info
    except Exception as e:
        logger.error(f"Error reading FITS file {file_path}: {e}")
        return None, None


def calculate_bin_size(data_length, num_plots):
    return max(1, data_length // num_plots)


def bin_flux_arr(fluxarr, bin_size):
    try:
        n_bins = fluxarr.shape[1] // bin_size
        bin_edges = np.linspace(0, fluxarr.shape[1], n_bins + 1)
        def bin_row(row):
            return binned_statistic(np.arange(len(row)), row, statistic='median', bins=bin_edges)[0]
        with ThreadPoolExecutor() as executor:
            fluxarrbin = np.array(list(executor.map(bin_row, fluxarr)))
        return fluxarrbin
    except Exception as e:
        logger.error(f"Error in bin_flux_arr: {str(e)}")
        raise


def smooth_flux(flux, sigma=2):
    try:
        return gaussian_filter(flux, sigma=sigma)
    except Exception as e:
        logger.error(f"Error in smooth_flux: {str(e)}")
        raise


def process_data(flux, wavelength, time, num_plots, apply_binning=True,
                 smooth_sigma=2, wavelength_unit='um', z_axis_display='variability'):
    try:
        logger.info('Shape before processing: %s', flux.shape)
        logger.info(f'Time array shape: {time.shape if hasattr(time, "shape") else len(time)}')
        logger.info(f'Z-axis display mode: {z_axis_display}')
        min_length = min(flux.shape[0], len(wavelength))
        flux = flux[:min_length]
        wavelength = np.asarray(wavelength[:min_length], dtype=float)
        finite_mask = np.isfinite(wavelength)
        if not np.all(finite_mask):
            logger.info(f"Removing {np.count_nonzero(~finite_mask)} non-finite wavelength rows")
        wavelength = wavelength[finite_mask]
        flux = flux[finite_mask, :]
        sort_idx = np.argsort(wavelength)
        if not np.all(sort_idx == np.arange(len(sort_idx))):
            logger.info("Sorting wavelengths to be strictly increasing")
        wavelength = wavelength[sort_idx]
        flux = flux[sort_idx, :]
        if not isinstance(time, np.ndarray):
            time = np.array(time, dtype=float)
        else:
            time = time.astype(float)
        bin_size = calculate_bin_size(flux.shape[1], num_plots)
        logger.info(f'Calculated bin size: {bin_size}')
        if bin_size > 1 and apply_binning:
            flux = bin_flux_arr(flux, bin_size)
            time = time[::bin_size]
            logger.info('Shape after binning: %s', flux.shape)
        flux = smooth_flux(flux, sigma=smooth_sigma)
        logger.info('Shape after smoothing: %s', flux.shape)
        if wavelength_unit == 'nm':
            wavelength = wavelength / 1000.0
            wavelength_label = 'Wavelength (nm)'
        elif wavelength_unit == 'A':
            wavelength = wavelength / 10000.0
            wavelength_label = 'Wavelength (Å)'
        else:
            wavelength_label = 'Wavelength (µm)'
        x = time
        logger.info(f'Time array after processing: min={np.nanmin(x):.4f}, max={np.nanmax(x):.4f}, shape={x.shape}')
        y = wavelength
        X, Y = np.meshgrid(x, y)
        if z_axis_display == 'flux':
            Z = flux
            logger.info(f'Raw flux range: {np.nanmin(Z):.4e} to {np.nanmax(Z):.4e}')
        else:
            Z = (flux - 1) * 100
            logger.info(f'Variability range: {np.nanmin(Z):.2f}% to {np.nanmax(Z):.2f}%')
        return x, y, X, Y, Z, wavelength_label
    except Exception as e:
        logger.error(f"Error in process_data: {str(e)}")
        raise



def identify_visits(times_hours, gap_threshold=0.5):
    if len(times_hours) == 0:
        return []
    visits = []
    start_idx = 0
    if len(times_hours) == 1:
        return [(0, 1)]
    for i in range(1, len(times_hours)):
        time_gap = times_hours[i] - times_hours[i - 1]
        if time_gap > gap_threshold:
            visits.append((start_idx, i))
            start_idx = i
    visits.append((start_idx, len(times_hours)))
    logger.info(f"Identified {len(visits)} visits with gaps > {gap_threshold} hours")
    for i, (start, end) in enumerate(visits):
        duration = times_hours[end - 1] - times_hours[start] if end > start else 0
        logger.info(
            f"Visit {i + 1}: {end - start} integrations, time range: {times_hours[start]:.2f} to {times_hours[end - 1]:.2f} hours (duration: {duration:.2f} hours)")
    return visits



def create_surface_plot_with_visits(flux, wavelength, time, title, num_plots,
                                    smooth_sigma=2, wavelength_unit='um', custom_bands=None, colorscale='Viridis',
                                    gap_threshold=0.5, use_interpolation=False, z_range=None,
                                    z_axis_display='variability',
                                    flux_unit='Unknown', errors_2d=None):
    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, False,
        smooth_sigma, wavelength_unit, z_axis_display
    )
    if z_axis_display == 'flux':
        Z_adjusted = Z
        colorbar_title = f'Flux ({flux_unit})'
        hover_z_label = 'Flux'
        flux_max = np.nanmax(np.abs(Z_adjusted))
        if flux_max < 0.01 or flux_max > 1000:
            hover_z_format = '.2e'
            colorbar_tickformat = '.2e'
        else:
            hover_z_format = '.4f'
            colorbar_tickformat = None
        hover_z_suffix = ''
    else:
        Z_adjusted = Z
        colorbar_title = 'Variability (%)'
        hover_z_label = 'Variability'
        hover_z_format = '.4f'
        hover_z_suffix = ' %'
        colorbar_tickformat = None
    if isinstance(z_range, tuple) or isinstance(z_range, list):
        if z_axis_display == 'variability':
            z_min_range = -z_range[1] if z_range[0] is None else z_range[0]
            z_max_range = z_range[1] if z_range[1] is not None else Z_adjusted.max()
        else:
            z_min_range = z_range[0] if z_range[0] is not None else Z_adjusted.min()
            z_max_range = z_range[1] if z_range[1] is not None else Z_adjusted.max()
        Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
        z_min = z_min_range
        z_max = z_max_range
    elif isinstance(z_range, (int, float)):
        if z_axis_display == 'variability':
            z_min_range = -z_range
            z_max_range = z_range
        else:
            z_min_range = Z_adjusted.min()
            z_max_range = Z_adjusted.max()
        Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
        z_min = z_min_range
        z_max = z_max_range
    else:
        Z_clipped = Z_adjusted
        z_min = Z_adjusted.min()
        z_max = Z_adjusted.max()
    if use_interpolation:
        visits = [(0, len(x))]
    else:
        visits = identify_visits(x, gap_threshold)
    data = []
    for visit_idx, (start, end) in enumerate(visits):
        X_visit = X[:, start:end]
        Y_visit = Y[:, start:end]
        Z_visit = Z_clipped[:, start:end]
        cd = errors_2d[:, start:end] if errors_2d is not None else None
        surface = go.Surface(
            x=X_visit,
            y=Y_visit,
            z=Z_visit,
            surfacecolor=Z_visit,
            colorscale=colorscale,
            cmin=z_min,
            cmax=z_max,
            showscale=(visit_idx == 0),
            colorbar=dict(
                title=colorbar_title,
                titlefont=dict(color='#ffffff'),
                tickfont=dict(color='#ffffff'),
                thickness=15,
                len=0.8,
                lenmode='fraction',
                x=1.02,
                y=0.5
            ),
            hovertemplate='Time: %{x:.2f}<br>' + wavelength_label + ': %{y:.4f}<br>' + hover_z_label + ': %{z:' + hover_z_format + '}' + hover_z_suffix + '<extra></extra>',
            opacity=1.0,
            customdata=cd
        )
        data.append(surface)
    title_text = title
    layout = go.Layout(
        template='plotly_dark',
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#ffffff'),
        title=dict(text=title_text, x=0.5),
        scene=dict(
            xaxis=dict(title='Time (hours)', backgroundcolor='rgba(0,0,0,0)', gridcolor='#555555', zeroline=False, showspikes=False),
            yaxis=dict(title=wavelength_label, backgroundcolor='rgba(0,0,0,0)', gridcolor='#555555', zeroline=False, showspikes=False),
            zaxis=dict(title='Raw Flux' if z_axis_display == 'flux' else 'Variability (%)', backgroundcolor='rgba(0,0,0,0)', gridcolor='#555555', zeroline=False, showspikes=False),
            aspectmode='cube'
        ),
        margin=dict(l=20, r=20, b=20, t=60),
        autosize=True,
        hovermode='closest',
        showlegend=False
    )
    fig = go.Figure(data=data, layout=layout)
    return fig



def create_heatmap_plot(flux, wavelength, time, title, num_plots,
                        smooth_sigma=2, wavelength_unit='um', custom_bands=None, colorscale='Viridis', z_range=None,
                        z_axis_display='variability', flux_unit='Unknown', errors_2d=None):
    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, False,
        smooth_sigma, wavelength_unit, z_axis_display
    )
    if Z.shape != (len(y), len(x)):
        raise ValueError(f"Heatmap Z shape {Z.shape} does not match (len(y), len(x)) = {(len(y), len(x))}")
    if z_axis_display == 'flux':
        Z_adjusted = Z
        colorbar_title = f'Flux ({flux_unit})'
        hover_z_label = 'Flux'
        flux_max = np.nanmax(np.abs(Z_adjusted))
        if (flux_max < 0.01) or (flux_max > 1000):
            hover_z_format = '.2e'
            colorbar_tickformat = '.2e'
        else:
            hover_z_format = '.4f'
            colorbar_tickformat = None
        hover_z_suffix = ''
    else:
        Z_adjusted = Z
        colorbar_title = 'Variability (%)'
        hover_z_label = 'Variability'
        hover_z_format = '.4f'
        hover_z_suffix = ' %'
        colorbar_tickformat = None
    if isinstance(z_range, tuple) or isinstance(z_range, list):
        if z_axis_display == 'variability':
            z_min_range = -z_range[1] if z_range[0] is None else z_range[0]
            z_max_range = z_range[1] if z_range[1] is not None else np.nanmax(Z_adjusted)
        else:
            z_min_range = z_range[0] if z_range[0] is not None else np.nanmin(Z_adjusted)
            z_max_range = z_range[1] if z_range[1] is not None else np.nanmax(Z_adjusted)
        Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
        z_min = z_min_range
        z_max = z_max_range
    elif isinstance(z_range, (int, float)):
        if z_axis_display == 'variability':
            z_min_range = -z_range
            z_max_range = z_range
        else:
            z_min_range = np.nanmin(Z_adjusted)
            z_max_range = np.nanmax(Z_adjusted)
        Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
        z_min = z_min_range
        z_max = z_max_range
    else:
        Z_clipped = Z_adjusted
        z_min = np.nanmin(Z_adjusted)
        z_max = np.nanmax(Z_adjusted)
    heatmap = go.Heatmap(
        x=x,
        y=y,
        z=Z_clipped,
        colorscale=colorscale,
        zmin=z_min,
        zmax=z_max,
        colorbar=dict(
            title=colorbar_title,
            titlefont=dict(color='#ffffff'),
            tickfont=dict(color='#ffffff'),
            thickness=15,
            len=0.8,
            lenmode='fraction',
            x=1.02,
            y=0.5,
            tickformat=colorbar_tickformat
        ),
        hovertemplate='Time: %{x:.2f}<br>' + wavelength_label + ': %{y:.4f}<br>' + hover_z_label + ': %{z:' + hover_z_format + '}' + hover_z_suffix + '<extra></extra>',
        customdata=errors_2d
    )
    data = [heatmap]
    y_min, y_max = float(np.nanmin(y)), float(np.nanmax(y))
    layout = go.Layout(
        template='plotly_dark',
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#ffffff'),
        title=dict(text=title, x=0.5),
        xaxis=dict(title='Time (hours)', showspikes=False, gridcolor='#555555', linecolor='#555555', zeroline=False),
        yaxis=dict(title=wavelength_label, showspikes=False, gridcolor='#555555', linecolor='#555555', zeroline=False, range=[y_min, y_max]),
        margin=dict(l=20, r=20, b=60, t=60),
        hovermode='closest',
        showlegend=False
    )
    fig = go.Figure(data=data, layout=layout)
    return fig





def calculate_variability_from_raw_flux(flux_raw_2d):
    median_flux_per_wavelength = np.nanmedian(flux_raw_2d, axis=1, keepdims=True)
    median_flux_per_wavelength[median_flux_per_wavelength == 0] = 1.0
    flux_norm_2d = flux_raw_2d / median_flux_per_wavelength
    logger.info(f"Median flux per wavelength shape: {median_flux_per_wavelength.shape}")
    logger.info(f"Normalized flux range: {np.nanmin(flux_norm_2d):.4f} to {np.nanmax(flux_norm_2d):.4f}")
    return flux_norm_2d



def process_mast_files_with_gaps(file_paths, use_interpolation=False, max_integrations=None, progress_cb=None):
    if progress_cb:
        progress_cb(2.0, "Scanning files…", stage="scan")
    scans = []
    for fp in file_paths or []:
        try:
            if fp.endswith('.fits'):
                with fits.open(fp, memmap=True) as hdul:
                    mids = hdul['INT_TIMES'].data['int_mid_MJD_UTC']
                    if 'EXTRACT1D' in hdul:
                        extract = hdul['EXTRACT1D'].data
                        count = min(len(mids), len(extract))
                    else:
                        count = len(mids)
                    first_t = float(mids[0])
            elif fp.endswith('.h5'):
                with h5py.File(fp, 'r') as h:
                    fk = _first_key(h, "calibrated_optspec", "stdspec", "optspec")
                    count = h[fk].shape[0] if fk else 0
                    if 'time' in h:
                        first_t = float(h['time'][0])
                    else:
                        first_t = None
            else:
                continue
            scans.append({"path": fp, "count": int(count), "first_t": first_t})
        except Exception:
            scans.append({"path": fp, "count": 0, "first_t": None})
    scans = [s for s in scans if s["count"] > 0]
    scans.sort(key=lambda d: (float('inf') if d["first_t"] is None else d["first_t"]))
    total_files = len(scans)
    total_est_integrations = sum(s["count"] for s in scans) if scans else 0
    if progress_cb:
        progress_cb(10.0, f"Found {total_est_integrations} integrations in {total_files} files", stage="scan", processed_integrations=0, total_integrations=total_est_integrations)
    all_integrations = []
    all_headers = []
    processed_count = 0
    read_start, read_end = 10.0, 60.0
    def pct_for_read(processed):
        if total_est_integrations == 0:
            return read_start
        frac = processed / total_est_integrations
        return read_start + (read_end - read_start) * min(1.0, max(0.0, frac))
    for i, s in enumerate(scans):
        fp = s["path"]
        file_total = s["count"]
        def per_integ_cb(done_local, total_local):
            nonlocal processed_count
            processed_count += 1
            if progress_cb:
                progress_cb(
                    pct_for_read(processed_count),
                    f"Reading {i+1}/{total_files} • {done_local}/{file_total} integrations",
                    stage="read",
                    processed_integrations=processed_count,
                    total_integrations=total_est_integrations
                )
        if fp.endswith('.fits'):
            integrations, header_info = load_integrations_from_fits(fp, per_integ_cb=per_integ_cb, total_in_file=file_total)
        elif fp.endswith('.h5'):
            integrations, header_info = load_integrations_from_h5(fp, per_integ_cb=per_integ_cb, total_in_file=file_total)
        else:
            integrations, header_info = (None, None)
        if integrations:
            all_integrations.extend(integrations)
            all_headers.append(header_info)
        if progress_cb:
            progress_cb(
                pct_for_read(processed_count),
                f"Loaded {i+1}/{total_files} files",
                stage="read",
                processed_integrations=processed_count,
                total_integrations=total_est_integrations
            )
    if not all_integrations:
        raise ValueError("No valid integrations found in files")
    all_integrations.sort(key=lambda x: x['time'] if not hasattr(x['time'], 'mjd') else x['time'].mjd)
    original_count = len(all_integrations)
    if max_integrations and max_integrations < len(all_integrations):
        step = len(all_integrations) / max_integrations
        indices = [int(i * step) for i in range(max_integrations)]
        sampled_integrations = [all_integrations[i] for i in indices]
        all_integrations = sampled_integrations
    min_wl = max(np.min(integ['wavelength']) for integ in all_integrations)
    max_wl = min(np.max(integ['wavelength']) for integ in all_integrations)
    n_wave = 1000
    common_wl = np.linspace(min_wl, max_wl, n_wave)
    flux_raw_list = []
    error_raw_list = []
    times = []
    total_integ = len(all_integrations)
    regrid_start, regrid_end = 60.0, 88.0
    def pct_for_regrid(done):
        if total_integ == 0:
            return regrid_start
        frac = done / total_integ
        return regrid_start + (regrid_end - regrid_start) * min(1.0, max(0.0, frac))
    if progress_cb:
        progress_cb(regrid_start, "Regridding integrations…", stage="regrid", processed_integrations=processed_count, total_integrations=total_est_integrations)
    t_start = _time.time()
    for k, integ in enumerate(all_integrations):
        f_interp = interpolate.interp1d(
            integ['wavelength'],
            integ['flux'],
            kind='linear',
            bounds_error=False,
            fill_value=np.nan
        )
        flux_raw_list.append(f_interp(common_wl))
        if 'error' in integ and integ['error'] is not None:
            e_interp = interpolate.interp1d(
                integ['wavelength'],
                integ['error'],
                kind='linear',
                bounds_error=False,
                fill_value=np.nan
            )
            error_raw_list.append(e_interp(common_wl))
        else:
            error_raw_list.append(np.full_like(common_wl, np.nan))
        t = integ['time'].mjd if hasattr(integ['time'], 'mjd') else integ['time']
        times.append(t)
        if progress_cb:
            elapsed = _time.time() - t_start
            done_total = processed_count + (k + 1)
            tp = done_total / elapsed if elapsed > 0 else None
            progress_cb(pct_for_regrid(k + 1), f"Regridding {k+1}/{total_integ} integrations", stage="regrid", processed_integrations=done_total, total_integrations=total_est_integrations, throughput=(tp if tp is not None else None))
    flux_raw_2d = np.array(flux_raw_list).T
    error_raw_2d = np.array(error_raw_list).T
    times_arr = np.array(times)
    t0 = times_arr.min()
    times_hours = (times_arr - t0) * 24.0
    if use_interpolation:
        if progress_cb:
            progress_cb(88.0, "Interpolating across time…", stage="interpolate")
        time_grid = np.linspace(times_hours.min(), times_hours.max(), len(times_hours))
        flux_raw_interpolated = np.zeros((flux_raw_2d.shape[0], len(time_grid)))
        error_raw_interpolated = np.zeros((error_raw_2d.shape[0], len(time_grid)))
        for i in range(flux_raw_2d.shape[0]):
            f_raw_interp = interpolate.interp1d(times_hours, flux_raw_2d[i, :], kind='linear',
                                                bounds_error=False, fill_value='extrapolate')
            e_raw_interp = interpolate.interp1d(times_hours, error_raw_2d[i, :], kind='linear',
                                                bounds_error=False, fill_value='extrapolate')
            flux_raw_interpolated[i, :] = f_raw_interp(time_grid)
            error_raw_interpolated[i, :] = e_raw_interp(time_grid)
            if progress_cb and i % 50 == 0:
                progress_cb(88.0 + 4.0 * (i / max(1, flux_raw_2d.shape[0])), "Interpolating across time…", stage="interpolate")
        flux_raw_2d = flux_raw_interpolated
        error_raw_2d = error_raw_interpolated
        times_hours = time_grid
    if progress_cb:
        progress_cb(92.0, "Computing variability & metadata…", stage="finalize", processed_integrations=processed_count + total_integ, total_integrations=total_est_integrations)
    flux_norm_2d = calculate_variability_from_raw_flux(flux_raw_2d)
    metadata = {
        'total_integrations': original_count,
        'plotted_integrations': len(all_integrations),
        'files_processed': len(file_paths),
        'wavelength_range': f"{common_wl.min():.3f}–{common_wl.max():.3f} µm",
        'time_range': f"{times_hours.min():.2f}–{times_hours.max():.2f} hours",
        'targets': list(set(h['target'] for h in all_headers if h)),
        'instruments': list(set(h['instrument'] for h in all_headers if h)),
        'filters': list(set(h['filter'] for h in all_headers if h)),
        'gratings': list(set(h['grating'] for h in all_headers if h)),
        'flux_unit': all_headers[0]['flux_unit'] if all_headers else 'Unknown',
    }
    return common_wl, flux_norm_2d, flux_raw_2d, times_hours, metadata, error_raw_2d

@app.route('/plots/<path:filename>')
def serve_plots(filename):
    return send_from_directory('plots', filename)


@app.route('/')
def index():
    return render_template('index.html')

@app.before_request
def _attach_video_token():
    from flask import request
    import os, tempfile
    token = request.args.get('video_token') or (request.form.get('video_token') if request.method == 'POST' else None)
    if not token:
        return
    p = os.path.join(tempfile.gettempdir(), f"spectrum_token_{token}.txt")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fp:
                path = fp.read().strip()
            if path and os.path.exists(path):
                globals()['latest_spectrum_mp4_path'] = path
        except Exception:
            pass


@app.route('/download_plots')
def download_plots():
    import io, os, time, base64, zipfile, json
    from flask import send_file
    from plotly.utils import PlotlyJSONEncoder
    surface_html = globals().get('last_surface_plot_html')
    heatmap_html = globals().get('last_heatmap_plot_html')
    surface_json = globals().get('last_surface_fig_json')
    heatmap_json = globals().get('last_heatmap_fig_json')
    bands = globals().get('last_custom_bands') or []
    if not surface_html or not heatmap_html:
        return 'No plots available to download.', 400
    mp4_path = globals().get('latest_spectrum_mp4_path')
    mp4_bytes = None
    mp4_name = None
    video_html = '<div id="videoBox" style="min-height:120px;display:flex;align-items:center;justify-content:flex-start;color:#cbd5e1">No video available in this session.</div>'
    if (mp4_path and os.path.exists(mp4_path)):
        with open(mp4_path, 'rb') as f:
            mp4_bytes = f.read()
        mp4_name = "2d_spectrum_" + time.strftime('%Y%m%d_%H%M%S') + ".mp4"
        b64 = base64.b64encode(mp4_bytes).decode('ascii')
        video_html = '<video controls muted style="width:100%;max-width:1600px;display:block;margin:0 auto;border-radius:8px"><source src="data:video/mp4;base64,' + b64 + '" type="video/mp4"></video>'
    def make_single_plot_html(fig_json, title, bands_list):
        d = json.dumps(fig_json["data"], cls=PlotlyJSONEncoder)
        l = json.dumps(fig_json.get("layout", {}), cls=PlotlyJSONEncoder)
        b = json.dumps(bands_list)
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>" + title + "</title>"
            "<link rel=\"preconnect\" href=\"https://cdn.plot.ly\"><script src=\"https://cdn.plot.ly/plotly-latest.min.js\"></script>"
            "<style>"
            "body{background:#0f172a;color:#e5e7eb;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif}"
            ".wrapper{max-width:1600px;margin:24px auto;padding:16px}"
            ".controls{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}"
            ".controls button{background:#374151;color:#e5e7eb;border:1px solid #4b5563;border-radius:8px;padding:6px 10px;cursor:pointer}"
            ".controls button.active{outline:2px solid #3b82f6}"
            ".card{background:#111827;border:1px solid #374151;border-radius:12px;padding:16px}"
            "</style></head><body><div class=\"wrapper\">"
            "<h2 style=\"text-align:center;margin:6px 0 16px\">" + title + "</h2>"
            "<div class=\"card\"><div class=\"controls\" id=\"bandBtns\"></div><div id=\"plot\" style=\"width:100%;height:800px\"></div></div>"
            "</div>"
            "<script>"
            "const figData=" + d + ";"
            "const figLayout=" + l + ";"
            "const bands=" + b + ";"
            "const originalData=JSON.parse(JSON.stringify(figData));"
            "function markActive(id){document.querySelectorAll('#bandBtns button').forEach(x=>{if(x.dataset.id===id)x.classList.add('active');else x.classList.remove('active');});}"
            "function applyBand(b){if(!b){Plotly.react('plot',originalData,figLayout);markActive('__full__');return;}const nd=[];"
            "for(const tr of originalData){if(tr.type==='surface'||tr.type==='heatmap'){let yv=tr.y;if(Array.isArray(yv[0])) yv=yv.map(r=>r[0]);"
            "const z=tr.z;const inZ=[],outZ=[];for(let i=0;i<z.length;i++){const ok=yv[i]>=b.start&&yv[i]<=b.end;const row=z[i];"
            "inZ[i]=ok?row.slice():new Array(row.length).fill(NaN);outZ[i]=ok?new Array(row.length).fill(NaN):row.slice();}"
            "const base={};for(const k in tr) if(k!=='z') base[k]=tr[k];"
            "nd.push(Object.assign({},base,{z:inZ}));"
            "nd.push(Object.assign({},base,{z:outZ,showscale:false,opacity:0.35,colorscale:[[0,'#888'],[1,'#888']]}));}"
            "else{nd.push(tr);}}"
            "Plotly.react('plot',nd,figLayout);markActive(b.__id);}"
            "function renderBtns(){const c=document.getElementById('bandBtns');c.innerHTML='';"
            "const full=document.createElement('button');full.textContent='Full Spectrum';full.dataset.id='__full__';full.onclick=()=>applyBand(null);c.appendChild(full);"
            "bands.forEach((b,i)=>{const btn=document.createElement('button');b.__id=(b.name||'Band')+'-'+i;btn.dataset.id=b.__id;btn.textContent=b.name||('Band '+(i+1));btn.onclick=()=>applyBand(b);c.appendChild(btn);});"
            "markActive('__full__');}"
            "Plotly.newPlot('plot',originalData,figLayout,{responsive:true,displayModeBar:true,displaylogo:false}).then(renderBtns);"
            "</script></body></html>"
        )
    if surface_json and heatmap_json:
        s_data = json.dumps(surface_json["data"], cls=PlotlyJSONEncoder)
        s_layout = json.dumps(surface_json.get("layout", {}), cls=PlotlyJSONEncoder)
        h_data = json.dumps(heatmap_json["data"], cls=PlotlyJSONEncoder)
        h_layout = json.dumps(heatmap_json.get("layout", {}), cls=PlotlyJSONEncoder)
        bands_js = json.dumps(bands)
        combined_html = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>Combined Plots</title>"
            "<link rel=\"preconnect\" href=\"https://cdn.plot.ly\"><script src=\"https://cdn.plot.ly/plotly-latest.min.js\"></script>"
            "<style>"
            "body{background:#0f172a;color:#e5e7eb;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif}"
            ".wrapper{max-width:1600px;margin:24px auto;padding:16px}"
            ".card{background:#111827;border:1px solid #374151;border-radius:12px;padding:16px;margin-bottom:24px}"
            ".controls{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}"
            ".controls button{background:#374151;color:#e5e7eb;border:1px solid #4b5563;border-radius:8px;padding:6px 10px;cursor:pointer}"
            ".controls button.active{outline:2px solid #3b82f6}"
            "</style></head><body><div class=\"wrapper\">"
            "<div class=\"card\"><h2 style=\"text-align:center;margin:6px 0 16px\">3D Surface Plot (MAST Data)</h2>"
            "<div class=\"controls\" id=\"bandBtns_surface\"></div>"
            "<div id=\"plot_surface\" style=\"width:100%;height:800px\"></div></div>"
            "<div class=\"card\"><h2 style=\"text-align:center;margin:6px 0 16px\">Heatmap (MAST Data)</h2>"
            "<div class=\"controls\" id=\"bandBtns_heatmap\"></div>"
            "<div id=\"plot_heatmap\" style=\"width:100%;height:800px\"></div></div>"
            "<div class=\"card\"><h2 style=\"text-align:center;margin:6px 0 16px\">2D Spectrum Video</h2>" + video_html + "</div>"
            "</div>"
            "<script>"
            "const bands=" + bands_js + ";"
            "const surfData=" + s_data + ";"
            "const surfLayout=" + s_layout + ";"
            "const heatData=" + h_data + ";"
            "const heatLayout=" + h_layout + ";"
            "const originals={};const layouts={};"
            "function markActive(containerId,id){document.querySelectorAll('#'+containerId+' button').forEach(b=>{if(b.dataset.id===id)b.classList.add('active');else b.classList.remove('active');});}"
            "function applyBand(plotId,btnContainerId,band){const originalData=originals[plotId];const layout=layouts[plotId];if(!band){Plotly.react(plotId,originalData,layout);markActive(btnContainerId,'__full__');return;}const newData=[];"
            "for(const tr of originalData){if(tr.type==='surface'||tr.type==='heatmap'){let yvec=tr.y;if(Array.isArray(yvec[0]))yvec=yvec.map(r=>r[0]);const z=tr.z;const inZ=[],outZ=[];"
            "for(let i=0;i<z.length;i++){const inBand=yvec[i]>=band.start&&yvec[i]<=band.end;const row=z[i];inZ[i]=inBand?row.slice():new Array(row.length).fill(NaN);outZ[i]=inBand?new Array(row.length).fill(NaN):row.slice();}"
            "const base={};for(const k in tr)if(k!=='z')base[k]=tr[k];newData.push(Object.assign({},base,{z:inZ}));newData.push(Object.assign({},base,{z:outZ,showscale:false,opacity:0.35,colorscale:[[0,'#888'],[1,'#888']]}));}"
            "else{newData.push(tr);}}"
            "Plotly.react(plotId,newData,layout);markActive(btnContainerId,band.__id);}"
            "function renderButtons(plotId,btnContainerId){const c=document.getElementById(btnContainerId);c.innerHTML='';const full=document.createElement('button');full.textContent='Full Spectrum';full.dataset.id='__full__';full.onclick=()=>applyBand(plotId,btnContainerId,null);c.appendChild(full);"
            "bands.forEach((b,i)=>{const btn=document.createElement('button');b.__id=(b.name||'Band')+'-'+i;btn.dataset.id=b.__id;btn.textContent=b.name||('Band '+(i+1));btn.onclick=()=>applyBand(plotId,btnContainerId,b);c.appendChild(btn);});"
            "markActive(btnContainerId,'__full__');}"
            "originals['plot_surface']=JSON.parse(JSON.stringify(surfData));layouts['plot_surface']=surfLayout;"
            "originals['plot_heatmap']=JSON.parse(JSON.stringify(heatData));layouts['plot_heatmap']=heatLayout;"
            "Plotly.newPlot('plot_surface',originals['plot_surface'],layouts['plot_surface'],{responsive:true,displayModeBar:true,displaylogo:false}).then(()=>renderButtons('plot_surface','bandBtns_surface'));"
            "Plotly.newPlot('plot_heatmap',originals['plot_heatmap'],layouts['plot_heatmap'],{responsive:true,displayModeBar:true,displaylogo:false}).then(()=>renderButtons('plot_heatmap','bandBtns_heatmap'));"
            "</script></body></html>"
        )
    else:
        combined_html = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>Combined Plots</title></head>"
            "<body style=\"background:#111;color:#eee;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif\">"
            "<div style=\"max-width:1600px;margin:24px auto;padding:12px;border:1px solid #333;border-radius:12px\">" + surface_html + "</div>"
            "<div style=\"max-width:1600px;margin:24px auto;padding:12px;border:1px solid #333;border-radius:12px\">" + heatmap_html + "</div>"
            "<div style=\"max-width:1600px;margin:24px auto;padding:12px;border:1px solid #333;border-radius:12px\"><h2 style=\"text-align:center;margin:0 0 16px\">2D Spectrum Video</h2>" + video_html + "</div>"
            "</body></html>"
        )
    ts = time.strftime('%Y%m%d_%H%M%S')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        if surface_json and heatmap_json:
            z.writestr('surface_plot_' + ts + '.html', make_single_plot_html(surface_json, '3D Surface Plot (MAST Data)', bands))
            z.writestr('heatmap_plot_' + ts + '.html', make_single_plot_html(heatmap_json, 'Heatmap (MAST Data)', bands))
        else:
            z.writestr('surface_plot_' + ts + '.html', surface_html)
            z.writestr('heatmap_plot_' + ts + '.html', heatmap_html)
        z.writestr('combined_plots_' + ts + '.html', combined_html)
        if mp4_bytes and mp4_name:
            z.writestr(mp4_name, mp4_bytes)
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name='jwst_plots_' + ts + '.zip')


@app.route('/upload_spectrum_frames', methods=['POST'])
def upload_spectrum_frames():
    import subprocess, tempfile, os, shutil, time, uuid, json
    from flask import jsonify, request
    fps = int(request.form.get('fps', 10))
    crf = int(request.form.get('crf', 22))
    files = request.files.getlist('frames')
    if not files:
        return jsonify({"error": "no frames provided"}), 400
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return jsonify({"error": "ffmpeg not found on server PATH"}), 500
    tmpdir = tempfile.mkdtemp(prefix='spectrum_frames_')
    try:
        for i, f in enumerate(files):
            f.save(os.path.join(tmpdir, f"frame_{i:05d}.png"))
        ts = time.strftime("%Y%m%d_%H%M%S")
        outpath = os.path.join(tempfile.gettempdir(), f"spectrum_{ts}.mp4")
        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", os.path.join(tmpdir, "frame_%05d.png"),
            "-c:v", "libx264",
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            outpath
        ]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            return jsonify({"error": r.stderr.decode("utf-8", "ignore")[:2000]}), 500
        token = uuid.uuid4().hex
        token_path = os.path.join(tempfile.gettempdir(), f"spectrum_token_{token}.txt")
        with open(token_path, "w", encoding="utf-8") as fp:
            fp.write(outpath)
        return jsonify({"ok": True, "token": token})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route('/upload_mast', methods=['POST'])
def upload_mast():
    global latest_surface_figure, latest_heatmap_figure
    try:
        mast_file = request.files.get('mast_zip')
        if not mast_file or mast_file.filename == '':
            return jsonify({'error': 'No MAST zip file provided.'}), 400
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
        temp_dir = tempfile.mkdtemp()
        try:
            zip_path = os.path.join(temp_dir, 'mast.zip')
            mast_file.save(zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            fits_files = []
            for root, _, files in os.walk(temp_dir):
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
            fits_files_sorted = [fp for fp, _ in sorted(file_times, key=lambda x: x[1])]
        except Exception as e:
            shutil.rmtree(temp_dir)
            return jsonify({'error': 'Error sorting files by observation time.'}), 400
        wavelength_1d, flux_norm_2d, flux_raw_2d, time_1d, metadata, error_raw_2d = process_mast_files_with_gaps(
            fits_files_sorted,
            use_interpolation,
            max_integrations=num_integrations if num_integrations > 0 else None
        )
        range_info = []
        if wavelength_range or time_range:
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm, range_info = apply_data_ranges(
                wavelength_1d, flux_norm_2d, time_1d, wavelength_range, time_range
            )
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw, _ = apply_data_ranges(
                wavelength_1d, flux_raw_2d, time_1d, wavelength_range, time_range
            )
            wavelength_1d_err, error_raw_2d_filtered, time_1d_err, _ = apply_data_ranges(
                wavelength_1d, error_raw_2d, time_1d, wavelength_range, time_range
            )
        else:
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm = wavelength_1d, flux_norm_2d, time_1d
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw = wavelength_1d, flux_raw_2d, time_1d
            wavelength_1d_err, error_raw_2d_filtered, time_1d_err = wavelength_1d, error_raw_2d, time_1d
        metadata['user_ranges'] = '; '.join(range_info) if range_info else None
        if z_axis_display == 'flux':
            z_data = flux_raw_2d_filtered
            errors_for_plot = error_raw_2d_filtered
        else:
            z_data = flux_norm_2d_filtered
            # Convert errors to variability percentage
            median_per_wl = np.nanmedian(flux_raw_2d_filtered, axis=1, keepdims=True)
            median_per_wl[median_per_wl == 0] = 1.0
            errors_for_plot = (error_raw_2d_filtered / median_per_wl) * 100
        ref_spec = np.nanmedian(np.asarray(flux_raw_2d_filtered), axis=1)
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
            errors_2d=errors_for_plot
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
            errors_2d=error_raw_2d_filtered
        )
        latest_surface_figure = surface_plot
        latest_heatmap_figure = heatmap_plot
        globals()['last_surface_plot_html'] = pio.to_html(surface_plot, include_plotlyjs='cdn', full_html=True)
        globals()['last_heatmap_plot_html'] = pio.to_html(heatmap_plot, include_plotlyjs='cdn', full_html=True)
        globals()['last_surface_fig_json'] = surface_plot.to_plotly_json()
        globals()['last_heatmap_fig_json'] = heatmap_plot.to_plotly_json()
        globals()['last_custom_bands'] = json.loads(request.form.get('custom_bands', '[]'))
        shutil.rmtree(temp_dir)
        return jsonify({
            'surface_plot': surface_plot.to_json(),
            'heatmap_plot': heatmap_plot.to_json(),
            'metadata': metadata,
            'reference_spectrum': json.dumps(ref_spec.tolist())
        })
    except Exception as e:
        logger.error(f"Error in upload_mast: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


def _extract_and_sort(zip_path, work_dir):
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
    _progress_set(job_id, reset=True, percent=1.0, message="Queued…", stage="queued")
    temp_dir = tempfile.mkdtemp(prefix=f"mast_job_{job_id[:8]}_")
    try:
        work_dir = os.path.join(temp_dir, "unzipped")
        os.makedirs(work_dir, exist_ok=True)
        _progress_set(job_id, percent=3.0, message="Extracting archive…", stage="scan")
        fits_files_sorted = _extract_and_sort(zip_path, work_dir)
        if not fits_files_sorted:
            raise ValueError("No valid FITS/H5 files found in archive.")
        custom_bands = form_args["custom_bands"]
        use_interpolation = form_args["use_interpolation"]
        colorscale = form_args["colorscale"]
        num_integrations = form_args["num_integrations"]
        z_axis_display = form_args["z_axis_display"]
        time_range = form_args["time_range"]
        wavelength_range = form_args["wavelength_range"]
        variability_range = form_args["variability_range"]
        def cb(pct, msg=None, **kw):
            _progress_set(job_id, percent=pct, message=msg, **kw)
        wavelength_1d, flux_norm_2d, flux_raw_2d, time_1d, metadata, error_raw_2d = process_mast_files_with_gaps(
            fits_files_sorted,
            use_interpolation,
            max_integrations=(num_integrations if num_integrations and num_integrations > 0 else None),
            progress_cb=cb
        )
        range_info = []
        if wavelength_range or time_range:
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm, range_info = apply_data_ranges(
                wavelength_1d, flux_norm_2d, time_1d, wavelength_range, time_range
            )
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw, _ = apply_data_ranges(
                wavelength_1d, flux_raw_2d, time_1d, wavelength_range, time_range
            )
            wavelength_1d_err, error_raw_2d_filtered, time_1d_err, _ = apply_data_ranges(
                wavelength_1d, error_raw_2d, time_1d, wavelength_range, time_range
            )
        else:
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm = wavelength_1d, flux_norm_2d, time_1d
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw = wavelength_1d, flux_raw_2d, time_1d
            wavelength_1d_err, error_raw_2d_filtered, time_1d_err = wavelength_1d, error_raw_2d, time_1d
        metadata['user_ranges'] = '; '.join(range_info) if range_info else None
        if z_axis_display == 'flux':
            z_data = flux_raw_2d_filtered
            errors_for_plot = error_raw_2d_filtered
        else:
            z_data = flux_norm_2d_filtered
            # Convert errors to variability percentage
            median_per_wl = np.nanmedian(flux_raw_2d_filtered, axis=1, keepdims=True)
            median_per_wl[median_per_wl == 0] = 1.0
            errors_for_plot = (error_raw_2d_filtered / median_per_wl) * 100
        ref_spec = np.nanmedian(np.asarray(flux_raw_2d_filtered), axis=1)
        _progress_set(job_id, percent=95.0, message="Rendering plots…", stage="finalize",
                      processed_integrations=_progress_set(job_id)["processed_integrations"],
                      total_integrations=_progress_set(job_id)["total_integrations"])
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
            errors_2d=errors_for_plot
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
            errors_2d=errors_for_plot
        )
        globals()['last_surface_plot_html'] = pio.to_html(surface_plot, include_plotlyjs='cdn', full_html=True)
        globals()['last_heatmap_plot_html'] = pio.to_html(heatmap_plot, include_plotlyjs='cdn', full_html=True)
        globals()['last_surface_fig_json'] = surface_plot.to_plotly_json()
        globals()['last_heatmap_fig_json'] = heatmap_plot.to_plotly_json()
        globals()['last_custom_bands'] = custom_bands
        payload = {
            'surface_plot': surface_plot.to_json(),
            'heatmap_plot': heatmap_plot.to_json(),
            'metadata': metadata,
            'reference_spectrum': json.dumps(ref_spec.tolist())
        }
        with PROG_LOCK:
            RESULTS[job_id] = payload
        _progress_set(job_id, percent=100.0, message="Done", status="done", stage="done")
    except Exception as e:
        logger.exception("Background job failed")
        _progress_set(job_id, message=str(e), status="error", stage="error")
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            os.remove(zip_path)
        except Exception:
            pass


@app.route('/start_mast', methods=['POST'])
def start_mast():
    try:
        # Check if demo data is requested
        use_demo = request.form.get('use_demo', 'false').lower() == 'true'

        if use_demo:
            # Use demo dataset
            demo_zip = os.path.join(BASE_DIR, 'static', 'demo_data', 'demo_jwst_timeseries.zip')

            if not os.path.exists(demo_zip):
                return jsonify({'error': 'Demo dataset not found.  Please upload your own data.'}), 404


            tmp_zip = os.path.join(tempfile.gettempdir(), f"mast_demo_{uuid.uuid4().hex}.zip")
            shutil.copy2(demo_zip, tmp_zip)
            logger.info(f"Using demo dataset:  {demo_zip}")
        else:
            # Use uploaded file
            mast_file = request.files.get('mast_zip')
            if not mast_file or mast_file.filename == '':
                return jsonify({'error': 'No MAST zip file provided. '}), 400

            tmp_zip = os.path.join(tempfile.gettempdir(), f"mast_job_{uuid.uuid4().hex}.zip")
            mast_file.save(tmp_zip)
            logger.info(f"Processing uploaded file: {mast_file.filename}")

        # Parse form parameters (same for both demo and uploaded)
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

        # Start background job (same for both demo and uploaded)
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
            "variability_range": variability_range
        }
        t = threading.Thread(target=_run_mast_job, args=(job_id, tmp_zip, form_args), daemon=True)
        t.start()
        return jsonify({"job_id": job_id}), 202
    except Exception as e:
        logger.error(f"Error starting job: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 400



@app.route('/progress/<job_id>')
def get_progress(job_id):
    rec = PROGRESS.get(job_id)
    if not rec:
        return jsonify({"error": "unknown job"}), 404
    with PROG_LOCK:
        out = dict(PROGRESS[job_id])
    return jsonify(out)



@app.route('/results/<job_id>')
def get_results(job_id):
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


if __name__ == '__main__':
    app.run(debug=True)

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
from astropy.time import Time
from astropy.stats import sigma_clip
from scipy import interpolate
import plotly.io as pio
from datetime import datetime

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global variables for download feature
latest_surface_figure = None
latest_heatmap_figure = None

# Color scales
COLOR_SCALES = ['Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis', 'Turbo', 'Viridis', 'Spectral', 'RdYlBu', 'Picnic']


def load_config(config_file='config.yaml'):
    """Load configuration from YAML file."""
    try:
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Error loading configuration: {str(e)}. Using default values.")
        return {}


CONFIG = load_config()
DATA_DIR = CONFIG.get('data_dir', 'Data')


def apply_data_ranges(wavelength, flux, time, wavelength_range=None, time_range=None):
    """Apply user-specified wavelength and time ranges to the data.

    Args:
        wavelength: 1D array of wavelengths
        flux: 2D array of flux values (wavelength x time)
        time: 1D array of time values
        wavelength_range: tuple of (min, max) wavelength values or None
        time_range: tuple of (min, max) time values or None

    Returns:
        Filtered wavelength, flux, time arrays and info about applied ranges
    """
    range_info = []

    # Store original ranges for reporting
    original_wl_range = (wavelength.min(), wavelength.max())
    original_time_range = (time.min(), time.max())

    # Apply wavelength range
    if wavelength_range and (wavelength_range[0] is not None or wavelength_range[1] is not None):
        wl_min = wavelength_range[0] if wavelength_range[0] is not None else original_wl_range[0]
        wl_max = wavelength_range[1] if wavelength_range[1] is not None else original_wl_range[1]

        # Clamp to actual data range
        wl_min = max(wl_min, original_wl_range[0])
        wl_max = min(wl_max, original_wl_range[1])

        # Ensure min < max
        if wl_min >= wl_max:
            logger.warning(f"Invalid wavelength range: {wl_min} to {wl_max}. Using full range.")
            wl_mask = np.ones(len(wavelength), dtype=bool)
        else:
            wl_mask = (wavelength >= wl_min) & (wavelength <= wl_max)
            range_info.append(f"Wavelength: {wl_min:.3f} - {wl_max:.3f} µm")
    else:
        wl_mask = np.ones(len(wavelength), dtype=bool)

    # Apply time range
    if time_range and (time_range[0] is not None or time_range[1] is not None):
        time_min = time_range[0] if time_range[0] is not None else original_time_range[0]
        time_max = time_range[1] if time_range[1] is not None else original_time_range[1]

        # Clamp to actual data range
        time_min = max(time_min, original_time_range[0])
        time_max = min(time_max, original_time_range[1])

        # Ensure min < max
        if time_min >= time_max:
            logger.warning(f"Invalid time range: {time_min} to {time_max}. Using full range.")
            time_mask = np.ones(len(time), dtype=bool)
        else:
            time_mask = (time >= time_min) & (time <= time_max)
            range_info.append(f"Time: {time_min:.2f} - {time_max:.2f} hours")
    else:
        time_mask = np.ones(len(time), dtype=bool)

    # Apply masks
    filtered_wavelength = wavelength[wl_mask]
    filtered_flux = flux[wl_mask, :][:, time_mask]
    filtered_time = time[time_mask]

    # Log the filtering results
    logger.info(f"Wavelength filtering: {len(wavelength)} -> {len(filtered_wavelength)} points")
    logger.info(f"Time filtering: {len(time)} -> {len(filtered_time)} points")

    return filtered_wavelength, filtered_flux, filtered_time, range_info


def load_integrations_from_fits(file_path):
    """Load all integrations from a JWST x1dints FITS file."""
    try:
        with fits.open(file_path) as hdul:
            mids = hdul['INT_TIMES'].data['int_mid_MJD_UTC']

            # Extract header information
            header_info = {
                'filename': os.path.basename(file_path),
                'target': hdul[0].header.get('TARGNAME', 'Unknown'),
                'instrument': hdul[0].header.get('INSTRUME', 'Unknown'),
                'filter': hdul[0].header.get('FILTER', 'Unknown'),
                'grating': hdul[0].header.get('GRATING', 'Unknown'),
                'obs_date': hdul[0].header.get('DATE-OBS', 'Unknown'),
                'exposure_time': hdul[0].header.get('EXPTIME', 'Unknown'),
            }

            # Try to extract flux units from FITS header or table
            flux_unit = None
            try:
                # Check for BUNIT in primary header
                flux_unit = hdul[0].header.get('BUNIT', None)

                # If not found, check EXTRACT1D extension
                if flux_unit is None and 'EXTRACT1D' in hdul:
                    flux_unit = hdul['EXTRACT1D'].header.get('BUNIT', None)

                # Check for TUNITn keywords in the table
                if flux_unit is None:
                    for i in range(1, 10):
                        unit = hdul['EXTRACT1D'].header.get(f'TUNIT{i}', None)
                        if unit and 'flux' in hdul['EXTRACT1D'].header.get(f'TTYPE{i}', '').lower():
                            flux_unit = unit
                            break

                # Common JWST flux units if not found
                if flux_unit is None:
                    flux_unit = 'MJy'  # Default for JWST
                    logger.info("Flux unit not found in FITS header, assuming MJy")
                else:
                    logger.info(f"Found flux unit: {flux_unit}")

            except Exception as e:
                logger.warning(f"Error extracting flux unit: {e}")
                flux_unit = 'MJy'

            header_info['flux_unit'] = flux_unit

            logger.info(f"File {os.path.basename(file_path)} contains {len(mids)} integrations")
            logger.info(
                f"Time span: {mids.min():.4f} to {mids.max():.4f} MJD ({(mids.max() - mids.min()) * 24:.2f} hours)")

            integrations = []
            for idx, mjd in enumerate(mids, start=1):
                data = hdul['EXTRACT1D', idx].data
                w = data['WAVELENGTH']
                f = data['FLUX']

                mask = ~np.isnan(f)

                integrations.append({
                    'wavelength': w[mask],
                    'flux': f[mask],
                    'time': Time(mjd, format='mjd', scale='utc')
                })

            return integrations, header_info

    except Exception as e:
        logger.error(f"Error reading FITS file {file_path}: {e}")
        return None, None


def calculate_bin_size(data_length, num_plots):
    """Calculate bin size based on data length."""
    return max(1, data_length // num_plots)


def bin_flux_arr(fluxarr, bin_size):
    """Bin the flux array."""
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
    """Apply Gaussian smoothing to flux data."""
    try:
        return gaussian_filter(flux, sigma=sigma)
    except Exception as e:
        logger.error(f"Error in smooth_flux: {str(e)}")
        raise


def process_data(flux, wavelength, time, num_plots, remove_first_60=True, apply_binning=True,
                 smooth_sigma=2, wavelength_unit='um', z_axis_display='variability'):
    """Process flux, wavelength, and time data for plotting.

    Note: When z_axis_display='flux', the input flux should be raw flux values.
          When z_axis_display='variability', the input flux should be normalized flux values.
    """
    try:
        logger.info('Shape before processing: %s', flux.shape)
        logger.info(f'Time array shape: {time.shape if hasattr(time, "shape") else len(time)}')
        logger.info(f'Z-axis display mode: {z_axis_display}')

        min_length = min(flux.shape[0], len(wavelength))
        flux = flux[:min_length]
        wavelength = wavelength[:min_length]

        if not isinstance(time, np.ndarray):
            time = np.array(time)

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
        logger.info(f'Time array after processing: min={x.min():.4f}, max={x.max():.4f}, shape={x.shape}')

        y = wavelength[60:] if remove_first_60 else wavelength
        X, Y = np.meshgrid(x, y)

        # Calculate Z based on display option
        if z_axis_display == 'flux':
            # Use raw flux values directly
            Z = flux[60:] if remove_first_60 else flux
            logger.info(f'Raw flux range: {Z.min():.4e} to {Z.max():.4e}')
        else:
            # Calculate variability percentage from normalized flux
            # Assumes flux is normalized where 1.0 = median
            Z = (flux[60:] - 1) * 100 if remove_first_60 else (flux - 1) * 100
            logger.info(f'Variability range: {Z.min():.2f}% to {Z.max():.2f}%')

        return x, y, X, Y, Z, wavelength_label

    except Exception as e:
        logger.error(f"Error in process_data: {str(e)}")
        raise


def identify_visits(times_hours, gap_threshold=0.5):
    """Identify separate visits based on time gaps."""
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


def create_surface_plot_with_visits(flux, wavelength, time, title, num_plots, remove_first_60=True,
                                    smooth_sigma=2, wavelength_unit='um', custom_bands=None, colorscale='Viridis',
                                    gap_threshold=0.5, use_interpolation=False, z_range=None,
                                    z_axis_display='variability',
                                    flux_unit='Unknown'):
    """Create 3D surface plot with separate surfaces for each visit."""
    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, remove_first_60, False,
        smooth_sigma, wavelength_unit, z_axis_display
    )

    # If interpolation is requested, don't separate visits
    if use_interpolation:
        visits = [(0, len(x))]
        logger.info("Linear interpolation enabled - creating continuous surface")
    else:
        visits = identify_visits(x, gap_threshold)
        if len(visits) == 1:
            logger.info("Single continuous observation detected - creating one surface")

    # Adjust Z based on display type
    if z_axis_display == 'flux':
        Z_adjusted = Z  # Raw flux, no adjustment
        z_axis_title = f'Flux ({flux_unit})'
        hover_z_label = 'Flux'

        # Determine appropriate format based on flux scale
        flux_max = np.nanmax(np.abs(Z_adjusted))
        if flux_max < 0.01 or flux_max > 1000:
            hover_z_format = '.2e'  # Scientific notation
        else:
            hover_z_format = '.4f'  # Regular notation
    else:
        Z_adjusted = Z  # No division by 10 for variability percentage
        z_axis_title = 'Variability %'
        hover_z_label = 'Variability'
        hover_z_format = '.2f'

    # Apply Z-range clipping if specified
    if z_range:
        # Handle tuple format (min, max)
        if isinstance(z_range, tuple):
            if z_axis_display == 'variability':
                # For variability, interpret as percentage
                z_min_range = z_range[0] if z_range[0] is not None else Z_adjusted.min()
                z_max_range = z_range[1] if z_range[1] is not None else Z_adjusted.max()
                Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
                z_min = z_min_range
                z_max = z_max_range
                logger.info(f"Clipping Z values to range: {z_min_range}% to {z_max_range}%")
            else:
                # For flux, use raw values
                z_min_range = z_range[0] if z_range[0] is not None else Z_adjusted.min()
                z_max_range = z_range[1] if z_range[1] is not None else Z_adjusted.max()
                Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
                z_min = z_min_range
                z_max = z_max_range
                logger.info(f"Clipping flux values to range: {z_min_range:.2e} to {z_max_range:.2e}")
        else:
            # Backward compatibility with single value (for variability only)
            if z_axis_display == 'variability':
                z_min_range = -z_range
                z_max_range = z_range
                Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
                z_min = z_min_range
                z_max = z_max_range
            else:
                Z_clipped = Z_adjusted
                z_min = Z_adjusted.min()
                z_max = Z_adjusted.max()
    else:
        Z_clipped = Z_adjusted
        z_min = Z_adjusted.min()
        z_max = Z_adjusted.max()

    data = []

    # Create main surfaces for each visit
    for visit_idx, (start, end) in enumerate(visits):
        X_visit = X[:, start:end]
        Y_visit = Y[:, start:end]
        Z_visit = Z_adjusted[:, start:end]

        # Full spectrum surface
        surface = go.Surface(
            x=X_visit,
            y=Y_visit,
            z=Z_clipped[:, start:end],
            surfacecolor=Z_clipped[:, start:end],  # Explicitly set surface color to Z values
            colorscale=colorscale,
            cmin=z_min,  # Set color scale min
            cmax=z_max,  # Set color scale max
            showscale=(visit_idx == 0),
            name=f'Visit {visit_idx + 1}' if len(visits) > 1 and not use_interpolation else 'Full Observation',
            colorbar=dict(
                title=z_axis_title,
                titleside='right',
                titlefont=dict(size=12, color='#ffffff'),
                tickfont=dict(size=10, color='#ffffff'),
                len=0.8,
                thickness=15,
                x=1.0,
                tickformat='.2e' if z_axis_display == 'flux' and (flux_max < 0.01 or flux_max > 1000) else None
            ) if visit_idx == 0 else None,
            hovertemplate=(
                    'Time: %{x:.2f} hours<br>' +
                    wavelength_label + ': %{y:.4f}<br>' +
                    hover_z_label + ': %{z:.2f}%<br>' +
                    '<extra></extra>'
            )
        )
        data.append(surface)

        # Gray mask surface for when bands are selected
        gray_surface = go.Surface(
            x=X_visit,
            y=Y_visit,
            z=Z_clipped[:, start:end],
            colorscale=[[0, 'rgba(200, 200, 200, 0.3)'], [1, 'rgba(220, 220, 220, 0.3)']],
            showscale=False,
            name=f'Gray Visit {visit_idx + 1}',
            hoverinfo='skip',
            visible=False
        )
        data.append(gray_surface)

    # Add band surfaces overlaid on full spectrum
    if custom_bands:
        for band_idx, band in enumerate(custom_bands):
            for visit_idx, (start, end) in enumerate(visits):
                # Create mask for this band
                band_mask = (Y[:, start:end] >= band['start']) & (Y[:, start:end] <= band['end'])
                X_visit = X[:, start:end]
                Y_visit = Y[:, start:end]
                Z_visit = Z_adjusted[:, start:end]

                # Apply mask
                Z_band = np.where(band_mask, Z_clipped[:, start:end], np.nan)

                band_surface = go.Surface(
                    x=X_visit,
                    y=Y_visit,
                    z=Z_band,
                    surfacecolor=np.where(band_mask, Z_clipped[:, start:end], np.nan),  # Use clipped Z values for color
                    colorscale=colorscale,  # Use same colorscale as main surface
                    cmin=z_min,  # Set color scale min
                    cmax=z_max,  # Set color scale max
                    showscale=False,
                    name=band['name'] + (
                        f" - Visit {visit_idx + 1}" if len(visits) > 1 and not use_interpolation else ""),
                    legendgroup=band['name'],
                    showlegend=(visit_idx == 0),
                    hovertemplate=(
                            band['name'] + '<br>' +
                            'Time: %{x:.2f} hours<br>' +
                            wavelength_label + ': %{y:.4f}<br>' +
                            hover_z_label + ': %{z:.2f}%<br>' +
                            '<extra></extra>'
                    ),
                    visible=False
                )
                data.append(band_surface)

    if use_interpolation:
        title_text = f"{title} (Linear Interpolation)"
    elif len(visits) == 1:
        title_text = f"{title} (Continuous observation)"
    else:
        title_text = f"{title} ({len(visits)} visits)"

    layout = go.Layout(
        template="plotly_dark",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#ffffff'),
        title=dict(
            text=title_text,
            x=0.5,
            y=0.95,
            xanchor='center',
            yanchor='top',
            font=dict(size=18, color='#ffffff')
        ),
        scene=dict(
            xaxis=dict(
                title='Time (hours)',
                gridcolor='#555555',
                linecolor='#555555',
                showbackground=True,
                backgroundcolor='rgba(0,0,0,0.5)',
                tickfont=dict(size=10, color='#ffffff')
            ),
            yaxis=dict(
                title=wavelength_label,
                gridcolor='#555555',
                linecolor='#555555',
                showbackground=True,
                backgroundcolor='rgba(0,0,0,0.5)'
            ),
            zaxis=dict(
                title=z_axis_title,
                gridcolor='#555555',
                linecolor='#555555',
                showbackground=True,
                backgroundcolor='rgba(0,0,0,0.5)',
                range=[z_min, z_max] if z_range else None,
                tickformat='.2e' if z_axis_display == 'flux' and 'flux_max' in locals() and (
                            flux_max < 0.01 or flux_max > 1000) else None,
                exponentformat='e'
            ),
            aspectmode='manual',
            aspectratio=dict(x=1.4, y=1.2, z=0.8),
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.3))
        ),
        margin=dict(l=20, r=20, b=20, t=60),
        autosize=True,
        hovermode='closest',
        showlegend=False
    )

    # Update menus for band selection and camera views
    updatemenus = [
        # Band selection buttons
        dict(
            type="buttons",
            direction="right",
            x=0.1,
            y=-0.05,
            xanchor="center",
            yanchor="top",
            buttons=[
                        dict(
                            # Show only main surfaces, hide gray masks and bands
                            args=[
                                {'visible': [True, False] * len(visits) + [False] * (len(custom_bands) * len(visits))}],
                            label="Full Spectrum",
                            method="update"
                        )
                    ] + [
                        dict(
                            # Show main surfaces, gray masks, and selected band
                            args=[{'visible':
                                       [False, True] * len(visits) +  # Hide main, show gray
                                       [(j // len(visits)) == i for j in range(len(custom_bands) * len(visits))]}],
                            # Show only selected band
                            label=band['name'],
                            method="update"
                        ) for i, band in enumerate(custom_bands or [])
                    ],
            pad={"r": 10, "t": 10},
            showactive=True,
            active=0
        ),
        # Camera view buttons
        dict(
            type="buttons",
            direction="right",
            x=0.1,
            y=-0.15,
            xanchor="center",
            yanchor="top",
            buttons=[
                dict(args=[{'scene.camera.eye': {'x': 1.5, 'y': 1.5, 'z': 1.3}}],
                     label="Default View",
                     method="relayout"),
                dict(args=[{'scene.camera.eye': {'x': 0, 'y': 0, 'z': 2.8}}],
                     label="Top View",
                     method="relayout"),
                dict(args=[{'scene.camera.eye': {'x': 2.5, 'y': 0, 'z': 0}}],
                     label="Side View",
                     method="relayout")
            ],
            pad={"r": 10, "t": 10},
            showactive=True
        )
    ]

    layout.updatemenus = updatemenus

    fig = go.Figure(data=data, layout=layout)
    return fig


def create_heatmap_plot(flux, wavelength, time, title, num_plots, remove_first_60=True,
                        smooth_sigma=2, wavelength_unit='um', custom_bands=None, colorscale='Viridis', z_range=None,
                        z_axis_display='variability', flux_unit='Unknown'):
    """Create 2D heatmap plot with support for band overlays."""

    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, remove_first_60, False,
        smooth_sigma, wavelength_unit, z_axis_display
    )

    if z_axis_display == 'flux':
        Z_adjusted = Z  # Raw flux, no adjustment
        colorbar_title = f'Flux ({flux_unit})'
        hover_z_label = 'Flux'
        flux_max = np.nanmax(np.abs(Z_adjusted))
        if flux_max < 0.01 or flux_max > 1000:
            hover_z_format = '.2e'
            colorbar_tickformat = '.2e'
        else:
            hover_z_format = '.4f'
            colorbar_tickformat = None
    else:
        Z_adjusted = Z  # No division by 10 for variability percentage
        colorbar_title = 'Variability %'
        hover_z_label = 'Variability'
        hover_z_format = '.4f'
        colorbar_tickformat = None

    # Handle Z range
    if z_range:
        if isinstance(z_range, tuple):
            if z_axis_display == 'variability':
                z_min_range = z_range[0] if z_range[0] is not None else Z_adjusted.min()
                z_max_range = z_range[1] if z_range[1] is not None else Z_adjusted.max()
                Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
                z_min = z_min_range
                z_max = z_max_range
            else:
                z_min_range = z_range[0] if z_range[0] is not None else Z_adjusted.min()
                z_max_range = z_range[1] if z_range[1] is not None else Z_adjusted.max()
                Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
                z_min = z_min_range
                z_max = z_max_range
        else:
            if z_axis_display == 'variability':
                z_min_range = -z_range
                z_max_range = z_range
                Z_clipped = np.clip(Z_adjusted, z_min_range, z_max_range)
                z_min = z_min_range
                z_max = z_max_range
            else:
                Z_clipped = Z_adjusted
                z_min = Z_adjusted.min()
                z_max = Z_adjusted.max()
    else:
        Z_clipped = Z_adjusted
        z_min = Z_adjusted.min()
        z_max = Z_adjusted.max()

    hovertemplate = (
        'Time: %{x:.2f} hours<br>' +
        wavelength_label + ': %{y:.4f}<br>' +
        hover_z_label + ': %{z:' + hover_z_format + '}<br>' +
        '<extra></extra>'
    )

    x = np.array(x, dtype=np.float64)
    y = np.array(y, dtype=np.float64)
    Z_clipped = np.array(Z_clipped, dtype=np.float64)

    data = []
    # Full spectrum
    heatmap_full = go.Heatmap(
        x=x,
        y=y,
        z=Z_clipped,
        colorscale=colorscale,
        hovertemplate=hovertemplate,
        colorbar=dict(
            title=colorbar_title,
            titleside='right',
            titlefont=dict(size=12, color='#ffffff'),
            tickfont=dict(size=10, color='#ffffff'),
            thickness=15,
            len=0.8,
            tickformat=colorbar_tickformat,
        ),
        name='Full Spectrum',
        visible=True,
        zmin=z_min,
        zmax=z_max,
    )
    data.append(heatmap_full)
    # Gray mask for band overlays (matches the 3D plot logic)
    gray_mask = go.Heatmap(
        x=x,
        y=y,
        z=Z_clipped,
        colorscale=[[0, 'rgba(200, 200, 200, 0.3)'], [1, 'rgba(220, 220, 220, 0.3)']],
        showscale=False,
        name='Gray Mask',
        hoverinfo='skip',
        visible=False
    )
    data.append(gray_mask)

    # Add custom bands as overlays (as additional heatmaps, only band values shown, rest NaN)
    if custom_bands:
        for band in custom_bands:
            band_mask = (y >= band['start']) & (y <= band['end'])
            Z_band = np.where(band_mask[:, None], Z_clipped, np.nan)
            band_heatmap = go.Heatmap(
                x=x,
                y=y,
                z=Z_band,
                colorscale=colorscale,
                hovertemplate=hovertemplate,
                colorbar=None,
                name=band['name'],
                visible=False,
                zmin=z_min,
                zmax=z_max,
            )
            data.append(band_heatmap)

    # Create updatemenus for toggling full spectrum and bands
    updatemenus = [
        dict(
            type="buttons",
            direction="right",
            x=0.1,
            y=-0.07,
            xanchor="center",
            yanchor="top",
            buttons=[
                dict(
                    args=[{'visible': [True, False] + [False] * (len(custom_bands) if custom_bands else 0)}],
                    label="Full Spectrum",
                    method="update"
                )
            ] + [
                dict(
                    args=[{'visible': [False, True] + [i == j for j in range(len(custom_bands) if custom_bands else 0)]}],
                    label=band['name'],
                    method="update"
                ) for i, band in enumerate(custom_bands or [])
            ],
            pad={"r": 10, "t": 10},
            showactive=True,
            active=0
        )
    ]

    layout = go.Layout(
        template="plotly_dark",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#ffffff'),
        title=dict(
            text=title,
            x=0.5,
            y=0.95,
            xanchor='center',
            yanchor='top',
            font=dict(size=18, color='#ffffff')
        ),
        xaxis=dict(
            title='Time (hours)',
            gridcolor='#555555',
            linecolor='#555555'
        ),
        yaxis=dict(
            title=wavelength_label,
            gridcolor='#555555',
            linecolor='#555555'
        ),
        margin=dict(l=50, r=50, t=80, b=50),
        hovermode='closest',
        updatemenus=updatemenus
    )

    fig = go.Figure(data=data, layout=layout)
    return fig


def calculate_variability_from_raw_flux(flux_raw_2d):
    """Calculate variability as percentage deviation from median at each wavelength.

    Args:
        flux_raw_2d: 2D array of raw flux values (wavelength x time)

    Returns:
        flux_norm_2d: Normalized flux for variability calculation
    """
    # Calculate median flux at each wavelength across all time points
    median_flux_per_wavelength = np.nanmedian(flux_raw_2d, axis=1, keepdims=True)

    # Avoid division by zero
    median_flux_per_wavelength[median_flux_per_wavelength == 0] = 1.0

    # Normalize flux by the median at each wavelength
    flux_norm_2d = flux_raw_2d / median_flux_per_wavelength

    logger.info(f"Median flux per wavelength shape: {median_flux_per_wavelength.shape}")
    logger.info(f"Normalized flux range: {np.nanmin(flux_norm_2d):.4f} to {np.nanmax(flux_norm_2d):.4f}")

    return flux_norm_2d


def process_mast_files_with_gaps(file_paths, use_interpolation=False, max_integrations=None):
    """Process JWST x1dints.fits files preserving gaps between visits."""
    all_integrations = []
    all_headers = []

    for fp in file_paths:
        integrations, header_info = load_integrations_from_fits(fp)
        if integrations:
            all_integrations.extend(integrations)
            all_headers.append(header_info)

    if not all_integrations:
        raise ValueError("No valid integrations found in FITS files")

    all_integrations.sort(key=lambda x: x['time'].mjd)

    # Sample integrations if max_integrations is specified
    original_count = len(all_integrations)
    if max_integrations and max_integrations < len(all_integrations):
        # Calculate step size for even sampling
        step = len(all_integrations) / max_integrations
        indices = [int(i * step) for i in range(max_integrations)]
        sampled_integrations = [all_integrations[i] for i in indices]
        all_integrations = sampled_integrations
        logger.info(f"Sampled {len(all_integrations)} integrations from {original_count} total")

    min_wl = max(np.min(integ['wavelength']) for integ in all_integrations)
    max_wl = min(np.max(integ['wavelength']) for integ in all_integrations)
    n_wave = 1000
    common_wl = np.linspace(min_wl, max_wl, n_wave)

    flux_raw_list = []  # Store raw flux values
    times = []

    for integ in all_integrations:
        f_interp = interpolate.interp1d(
            integ['wavelength'],
            integ['flux'],
            kind='linear',
            bounds_error=False,
            fill_value=np.nan
        )
        flux_interp = f_interp(common_wl)

        # Store raw flux directly
        flux_raw_list.append(flux_interp)
        times.append(integ['time'].mjd)

    flux_raw_2d = np.array(flux_raw_list).T
    times_mjd = np.array(times)

    t0 = times_mjd.min()
    times_hours = (times_mjd - t0) * 24.0

    # If interpolation is requested, fill gaps
    if use_interpolation:
        # Create evenly spaced time grid
        time_grid = np.linspace(times_hours.min(), times_hours.max(), len(times_hours))

        # Interpolate raw flux for each wavelength
        flux_raw_interpolated = np.zeros((flux_raw_2d.shape[0], len(time_grid)))

        for i in range(flux_raw_2d.shape[0]):
            # Interpolate raw flux
            f_raw_interp = interpolate.interp1d(times_hours, flux_raw_2d[i, :], kind='linear',
                                                bounds_error=False, fill_value='extrapolate')
            flux_raw_interpolated[i, :] = f_raw_interp(time_grid)

        flux_raw_2d = flux_raw_interpolated
        times_hours = time_grid
        logger.info("Applied linear interpolation to fill gaps")

    # Calculate normalized flux for variability
    flux_norm_2d = calculate_variability_from_raw_flux(flux_raw_2d)

    logger.info(f"Processed {len(all_integrations)} integrations")
    logger.info(f"Time range: {times_hours.min():.2f} to {times_hours.max():.2f} hours")
    if not use_interpolation:
        if len(times_hours) > 1:
            logger.info(f"Time gaps: {np.diff(times_hours).max():.2f} hours max gap")

    # Compile metadata
    metadata = {
        'total_integrations': original_count,
        'plotted_integrations': len(all_integrations),
        'wavelength_range': f"{min_wl:.3f} - {max_wl:.3f} µm",
        'time_range': f"{times_hours.min():.2f} - {times_hours.max():.2f} hours",
        'files_processed': len(file_paths),
        'targets': list(set(h['target'] for h in all_headers if h)),
        'instruments': list(set(h['instrument'] for h in all_headers if h)),
        'filters': list(set(h['filter'] for h in all_headers if h)),
        'gratings': list(set(h['grating'] for h in all_headers if h)),
        'flux_unit': all_headers[0]['flux_unit'] if all_headers else 'Unknown',
    }

    return common_wl, flux_norm_2d, flux_raw_2d, times_hours, metadata


@app.route('/plots/<path:filename>')
def serve_plots(filename):
    """Serve static Plotly HTML files."""
    return send_from_directory('plots', filename)


@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')


@app.route('/download_plots', methods=['GET'])
def download_plots():
    """Download the last-generated plots as HTML."""
    global latest_surface_figure, latest_heatmap_figure

    if latest_surface_figure is None or latest_heatmap_figure is None:
        return jsonify({"error": "No plots available to download. Please upload files first."}), 400

    # Create standalone HTML files with Plotly JS included
    html_surface = pio.to_html(
        latest_surface_figure,
        include_plotlyjs='cdn',  # Include Plotly from CDN
        config={'responsive': True, 'displayModeBar': True}
    )
    html_heatmap = pio.to_html(
        latest_heatmap_figure,
        include_plotlyjs='cdn',  # Include Plotly from CDN
        config={'responsive': True, 'displayModeBar': True}
    )

    # Create a timestamp for the filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create a zip file in memory
    import io
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add surface plot
        zip_file.writestr(f'surface_plot_{timestamp}.html', html_surface)
        # Add heatmap
        zip_file.writestr(f'heatmap_plot_{timestamp}.html', html_heatmap)
        # Add combined view
        combined_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <title>JWST Spectral Analysis Plots - {timestamp}</title>
            <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
            <style>
                body {{
                    background-color: #1a1a1a;
                    color: #ffffff;
                    font-family: Arial, sans-serif;
                    padding: 20px;
                }}
                .plot-container {{
                    margin-bottom: 40px;
                    border: 1px solid #444;
                    border-radius: 8px;
                    padding: 20px;
                    background-color: #2a2a2a;
                }}
                h1, h2 {{
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <h1>JWST Spectral Analysis</h1>
            <p style="text-align: center;">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

            <div class="plot-container">
                <h2>3D Surface Plot</h2>
                {pio.to_html(latest_surface_figure, include_plotlyjs=False, full_html=False)}
            </div>

            <div class="plot-container">
                <h2>2D Heatmap</h2>
                {pio.to_html(latest_heatmap_figure, include_plotlyjs=False, full_html=False)}
            </div>
        </body>
        </html>
        """
        zip_file.writestr(f'combined_plots_{timestamp}.html', combined_html)

    zip_buffer.seek(0)

    return Response(
        zip_buffer.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f"attachment;filename=jwst_plots_{timestamp}.zip"}
    )


@app.route('/upload_mast', methods=['POST'])
def upload_mast():
    """Process uploaded MAST zip file."""
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
        num_integrations = int(request.form.get('num_integrations', '0'))
        z_axis_display = request.form.get('z_axis_display', 'variability')

        # Get range values
        time_range_min = request.form.get('time_range_min', '')
        time_range_max = request.form.get('time_range_max', '')
        wavelength_range_min = request.form.get('wavelength_range_min', '')
        wavelength_range_max = request.form.get('wavelength_range_max', '')
        variability_range_min = request.form.get('variability_range_min', '')
        variability_range_max = request.form.get('variability_range_max', '')

        # Parse ranges
        time_range = None
        wavelength_range = None
        variability_range = None

        # Time range
        if time_range_min or time_range_max:
            try:
                t_min = float(time_range_min) if time_range_min else None
                t_max = float(time_range_max) if time_range_max else None
                time_range = (t_min, t_max)
                logger.info(f"Time range specified: {t_min} to {t_max} hours")
            except ValueError:
                logger.warning("Invalid time range values provided")

        # Wavelength range
        if wavelength_range_min or wavelength_range_max:
            try:
                wl_min = float(wavelength_range_min) if wavelength_range_min else None
                wl_max = float(wavelength_range_max) if wavelength_range_max else None
                wavelength_range = (wl_min, wl_max)
                logger.info(f"Wavelength range specified: {wl_min} to {wl_max} µm")
            except ValueError:
                logger.warning("Invalid wavelength range values provided")

        # Variability range
        if variability_range_min or variability_range_max:
            try:
                v_min = float(variability_range_min) if variability_range_min else None
                v_max = float(variability_range_max) if variability_range_max else None
                variability_range = (v_min, v_max)
                logger.info(f"Variability range specified: {v_min}% to {v_max}%")
            except ValueError:
                logger.warning("Invalid variability range values provided")

        logger.info(f"Received custom bands for MAST: {custom_bands}")
        logger.info(f"Linear interpolation: {use_interpolation}")
        logger.info(f"Colorscale: {colorscale}")
        logger.info(f"Max integrations: {num_integrations if num_integrations > 0 else 'All'}")
        logger.info(f"Z-axis display: {z_axis_display}")

        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, 'mast.zip')
        mast_file.save(zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        fits_files = []
        for root, dirs, files in os.walk(temp_dir):
            if '__MACOSX' in root:
                continue
            for file in files:
                if file.endswith('x1dints.fits') and not file.startswith('._'):
                    fits_files.append(os.path.join(root, file))

        if not fits_files:
            shutil.rmtree(temp_dir)
            return jsonify({'error': 'No x1dints.fits files found in the uploaded directory.'}), 400

        logger.info(f"Found {len(fits_files)} x1dints.fits files")

        try:
            file_times = []
            for fp in fits_files:
                integrations, _ = load_integrations_from_fits(fp)
                if integrations:
                    file_times.append((fp, integrations[0]['time'].mjd))

            fits_files_sorted = [fp for fp, _ in sorted(file_times, key=lambda x: x[1])]
        except Exception as e:
            logger.error(f"Error sorting files: {e}")
            shutil.rmtree(temp_dir)
            return jsonify({'error': 'Error sorting FITS files by observation time.'}), 400

        wavelength_1d, flux_norm_2d, flux_raw_2d, time_1d, metadata = process_mast_files_with_gaps(
            fits_files_sorted,
            use_interpolation,
            max_integrations=num_integrations if num_integrations > 0 else None
        )

        logger.info(
            f"Final data shapes - Wavelength: {wavelength_1d.shape}, Flux: {flux_norm_2d.shape}, Time: {time_1d.shape}")
        logger.info(f"Time range: {time_1d.min():.2f} to {time_1d.max():.2f} hours")

        # Apply user-specified ranges
        range_info = []
        if wavelength_range or time_range:
            # Log data shape before filtering
            logger.info(f"Data shape before range filtering - Wavelength: {wavelength_1d.shape}, Time: {time_1d.shape}")

            # Apply ranges to both normalized and raw flux
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm, range_info = apply_data_ranges(
                wavelength_1d, flux_norm_2d, time_1d, wavelength_range, time_range
            )
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw, _ = apply_data_ranges(
                wavelength_1d, flux_raw_2d, time_1d, wavelength_range, time_range
            )

            # Use the filtered data
            wavelength_1d = wavelength_1d_norm
            flux_norm_2d = flux_norm_2d_filtered
            flux_raw_2d = flux_raw_2d_filtered
            time_1d = time_1d_norm

            # Log data shape after filtering
            logger.info(f"Data shape after range filtering - Wavelength: {wavelength_1d.shape}, Time: {time_1d.shape}")

            # Update metadata with applied ranges
            if range_info:
                metadata['user_ranges'] = ', '.join(range_info)
                metadata['wavelength_range'] = f"{wavelength_1d.min():.3f} - {wavelength_1d.max():.3f} µm"
                metadata['time_range'] = f"{time_1d.min():.2f} - {time_1d.max():.2f} hours"

        # Smooth the appropriate flux based on z_axis_display
        if z_axis_display == 'flux':
            flux_for_plot = smooth_flux(flux_raw_2d, sigma=2)
        else:
            flux_for_plot = smooth_flux(flux_norm_2d, sigma=2)

        surface_plot = create_surface_plot_with_visits(
            flux=flux_for_plot,
            wavelength=wavelength_1d,
            time=time_1d,
            title="3D Surface Plot (MAST Data)",
            num_plots=1000,
            remove_first_60=True,
            smooth_sigma=2,
            wavelength_unit='um',
            custom_bands=custom_bands,
            colorscale=colorscale,
            use_interpolation=use_interpolation,
            z_range=variability_range,
            z_axis_display=z_axis_display,
            flux_unit=metadata.get('flux_unit', 'Unknown')
        )

        heatmap_plot = create_heatmap_plot(
            flux=flux_for_plot,
            wavelength=wavelength_1d,
            time=time_1d,
            title="Heatmap (MAST Data)",
            num_plots=1000,
            remove_first_60=True,
            smooth_sigma=2,
            wavelength_unit='um',
            custom_bands=custom_bands,
            colorscale=colorscale,
            z_range=variability_range,
            z_axis_display=z_axis_display,
            flux_unit=metadata.get('flux_unit', 'Unknown')
        )

        latest_surface_figure = surface_plot
        latest_heatmap_figure = heatmap_plot

        shutil.rmtree(temp_dir)

        return jsonify({
            'surface_plot': surface_plot.to_json(),
            'heatmap_plot': heatmap_plot.to_json(),
            'metadata': metadata
        })

    except Exception as e:
        logger.error(f"Error in upload_mast: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


if __name__ == '__main__':
    app.run(debug=True)
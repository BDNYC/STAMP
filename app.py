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

from datetime import datetime  # <-- for timestamping saved plot files.

app = Flask(__name__)

# ===================================
# Logging Configuration
# ===================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===================================
# Global Variables (for Download Feature)
# ===================================
"""
Stores the last-generated Plotly figures in global variables (latest_surface_figure and latest_heatmap_figure).
After the user uploads files and the plots are generated at /upload, they can go to /download_plots to get the HTML.
If multiple users use the service simultaneously, they'll overwrite each other's "latest" plots.
For multi-user or production scenarios, you'd want a more robust approach (session, DB, or ID-based storage).
"""
latest_surface_figure = None
latest_heatmap_figure = None

# ===================================
# Constants and Configuration
# ===================================
# Updated color scales to match CSS
COLOR_SCALES = ['Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis', 'Turbo', 'Viridis', 'Spectral', 'RdYlBu', 'Picnic']

def load_config(config_file='config.yaml'):
    """Load configuration from a YAML file."""
    try:
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Error loading configuration: {str(e)}. Using default values.")
        return {}

CONFIG = load_config()
DATA_DIR = CONFIG.get('data_dir', 'Data')


# ===================================
# FITS File Utilities
# ===================================
def load_fits(file, memmap=True):
    """Load a FITS file from a file-like object."""
    try:
        file_content = file.read()
        file_like = BytesIO(file_content)
        with fits.open(file_like, memmap=memmap, mode='readonly') as hdul:
            if memmap:
                # If memmapping, return a copy of the data to ensure it's fully in memory
                return np.array(hdul[0].data)
            else:
                return hdul[0].data
    except Exception as e:
        logger.error(f"Error loading FITS file: {str(e)}")
        raise


def load_and_process_fits(file_path):
    """Load and extract wavelength, flux, and observation time from a JWST FITS file."""
    try:
        with fits.open(file_path) as hdul:
            data = hdul['EXTRACT1D', 1].data
            wavelength = data['WAVELENGTH']
            flux = data['FLUX']

            # Filter out NaN values
            valid_indices = ~np.isnan(flux)
            wavelength = wavelength[valid_indices]
            flux = flux[valid_indices]

            obs_time = Time(hdul[0].header['DATE-OBS'], format='isot', scale='utc')
    except Exception as e:
        logger.error(f"Error reading FITS file {file_path}: {e}")
        return None, None, None

    return wavelength, flux, obs_time


# ===================================
# Data Processing Utilities
# ===================================
def calculate_bin_size(data_length, num_plots):
    """Calculate the bin size based on data length and desired number of plots."""
    return max(1, data_length // num_plots)


def bin_flux_arr(fluxarr, bin_size):
    """Bin the flux array using a specified bin size."""
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
    """Apply Gaussian smoothing to the flux data."""
    try:
        return gaussian_filter(flux, sigma=sigma)
    except Exception as e:
        logger.error(f"Error in smooth_flux: {str(e)}")
        raise


def process_data(flux, wavelength, time, num_plots, remove_first_60=True, apply_binning=True,
                 smooth_sigma=2, wavelength_unit='um'):
    """
    Process the flux, wavelength, and time data for plotting:
    - Apply binning (optional)
    - Smooth the flux data
    - Convert wavelength units
    - Generate X, Y, Z arrays for plotting
    """
    try:
        logger.info('Shape before processing: %s', flux.shape)

        # Ensure wavelength and flux are compatible
        min_length = min(flux.shape[0], len(wavelength))
        flux = flux[:min_length]
        wavelength = wavelength[:min_length]

        # Calculate bin size
        bin_size = calculate_bin_size(flux.shape[1], num_plots)
        logger.info(f'Calculated bin size: {bin_size}')

        if bin_size > 1 and apply_binning:
            flux = bin_flux_arr(flux, bin_size)
            logger.info('Shape after binning: %s', flux.shape)

        flux = smooth_flux(flux, sigma=smooth_sigma)
        logger.info('Shape after smoothing: %s', flux.shape)

        # Wavelength unit conversion
        if wavelength_unit == 'nm':
            wavelength = wavelength / 1000.0
            wavelength_label = 'Wavelength (nm)'
        elif wavelength_unit == 'A':
            wavelength = wavelength / 10000.0
            wavelength_label = 'Wavelength (Å)'
        else:
            wavelength_label = 'Wavelength (µm)'

        # Convert time to hours difference
        x = np.linspace(0, 1, flux.shape[1]) * ((np.nanmax(time) - np.nanmin(time)) * 24.)
        # Optionally remove the first 60 wavelength points
        y = wavelength[60:] if remove_first_60 else wavelength
        X, Y = np.meshgrid(x, y)
        Z = (flux[60:] - 1) * 100 if remove_first_60 else (flux - 1) * 100

        return x, y, X, Y, Z, wavelength_label

    except Exception as e:
        logger.error(f"Error in process_data: {str(e)}")
        raise


def create_surface_plot(flux, wavelength, time, title, num_plots, remove_first_60=True, apply_binning=True,
                        smooth_sigma=2, wavelength_unit='um', custom_bands=None, colorscale='Viridis'):
    """
    Create a 3D surface plot with optional band masking and dark styling.
    """
    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, remove_first_60, apply_binning,
        smooth_sigma, wavelength_unit
    )

    # Adjust Z values for hover (divide by 10)
    Z_adjusted = Z / 10

    # Adjust X values for hover (divide by 24)
    X_adjusted = X / 24

    hovertemplate = (
        'Time: %{x:.2f} hours<br>' +
        wavelength_label + ': %{y:.4f}<br>' +
        'Variability: %{z:.4f}%<br>' +
        '<extra></extra>'
    )

    # Full spectrum surface
    surface_full = go.Surface(
        x=X_adjusted, y=Y, z=Z_adjusted,  # Use X_adjusted and Z_adjusted for hover values
        colorscale=colorscale,
        opacity=1,
        name='Full Spectrum',
        colorbar=dict(
            title='Variability %',
            titleside='right',
            titlefont=dict(size=12, color='#ffffff'),
            tickfont=dict(size=10, color='#ffffff'),
            len=0.8,
            thickness=15,
            x=1.0
        ),
        hoverinfo='x+y+z',
        hovertemplate=hovertemplate
    )

    # Gray mask surface
    gray_surface = go.Surface(
        x=X_adjusted, y=Y, z=Z_adjusted,
        colorscale=[[0, 'rgba(200, 200, 200, 0.3)'], [1, 'rgba(200, 200, 200, 0.3)']],
        opacity=0.3,
        showscale=False,
        hoverinfo='skip'
    )

    data = [surface_full, gray_surface]

    # If custom_bands are defined, create separate surfaces for them
    if custom_bands:
        for band in custom_bands:
            band_mask = (Y >= band['start']) & (Y <= band['end'])
            band_surface = go.Surface(
                x=X_adjusted, y=Y, z=np.where(band_mask, Z_adjusted, np.nan),
                colorscale=colorscale,
                opacity=0.9,
                showscale=False,
                name=band['name'],
                hoverinfo='x+y+z',
                hovertemplate=hovertemplate
            )
            data.append(band_surface)

    # Update the x-axis tick values and labels
    tickvals = np.linspace(X.min(), X.max(), num=6)  # Generate original tick positions
    ticktext = [f"{val / 24:.2f}" for val in tickvals]  # Convert to divided values for labels

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
        scene=dict(
            xaxis=dict(
                title='Time (hours)',
                gridcolor='#555555',
                linecolor='#555555',
                showbackground=True,
                backgroundcolor='rgba(0,0,0,0.5)',
                tickvals=tickvals,
                ticktext=ticktext,
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
                title='Variability %',
                gridcolor='#555555',
                linecolor='#555555',
                showbackground=True,
                backgroundcolor='rgba(0,0,0,0.5)'
            ),
            aspectmode='manual',
            aspectratio=dict(x=1.4, y=1.2, z=0.8),
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.3))
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        autosize=True,
        hovermode='closest',
        showlegend=True,
        legend=dict(
            x=0.02,
            y=0.98,
            bgcolor='rgba(0,0,0,0.5)',
            font=dict(color='#ffffff', size=10)
        )
    )

    # Update menus for band selection and camera views
    updatemenus = [
        dict(
            type="buttons",
            direction="right",
            x=0.1,
            y=-0.05,
            xanchor="center",
            yanchor="top",
            buttons=[
                dict(args=[{'visible': [True, False] + [False] * len(custom_bands)}],
                     label="Full Spectrum",
                     method="update")
            ] + [
                dict(args=[{'visible': [False, True] + [i == j for j in range(len(custom_bands))]}],
                     label=band['name'],
                     method="update") for i, band in enumerate(custom_bands or [])
            ],
            pad={"r": 10, "t": 10},
            showactive=True
        ),
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


import numpy as np
import plotly.graph_objects as go

def create_heatmap_plot(flux, wavelength, time, title, num_plots, remove_first_60=True, apply_binning=True,
                        smooth_sigma=2, wavelength_unit='um', custom_bands=None, colorscale='Viridis'):
    """
    Create a 2D heatmap plot with optional band masking and dark styling.
    """
    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, remove_first_60, apply_binning,
        smooth_sigma, wavelength_unit
    )

    # Adjust Z values for hover (divide by 10)
    Z_adjusted = Z / 10

    # Adjust X values for hover and axis (divide by 24)
    x_adjusted = x / 24

    hovertemplate = (
        'Time: %{x:.2f} hours<br>' +
        wavelength_label + ': %{y:.4f}<br>' +
        'Variability: %{z:.4f}%<br>' +
        '<extra></extra>'
    )

    # Full spectrum heatmap
    heatmap_full = go.Heatmap(
        x=x_adjusted,
        y=y,
        z=Z_adjusted,
        colorscale=colorscale,
        colorbar=dict(
            title='Variability %',
            titleside='right',
            titlefont=dict(size=12, color='#ffffff'),
            tickfont=dict(size=10, color='#ffffff'),
            len=0.8,
            thickness=15,
            x=1.0
        ),
        hoverinfo='x+y+z',
        hovertemplate=hovertemplate,
        name='Full Spectrum'
    )

    # Gray mask layer
    gray_heatmap = go.Heatmap(
        x=x_adjusted,
        y=y,
        z=Z_adjusted,
        colorscale=[[0, 'black'], [1, 'white']],
        opacity=0.3,
        showscale=False,
        hoverinfo='skip',
        name='Gray Mask'
    )

    data = [heatmap_full, gray_heatmap]

    # Add custom band layers if provided
    if custom_bands:
        for band in custom_bands:
            band_mask = (y >= band['start']) & (y <= band['end'])
            band_z = np.where(band_mask[:, None], Z_adjusted, np.nan)
            band_heatmap = go.Heatmap(
                x=x_adjusted,
                y=y,
                z=band_z,
                colorscale=colorscale,
                showscale=False,
                hoverinfo='x+y+z',
                hovertemplate=hovertemplate,
                name=band['name']
            )
            data.append(band_heatmap)

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
            linecolor='#555555',
            tickvals=np.linspace(x.min() / 24, x.max() / 24, num=6),
            ticktext=[f"{val:.2f}" for val in np.linspace(x.min() / 24, x.max() / 24, num=6)],
            tickfont=dict(size=10, color='#ffffff')
        ),
        yaxis=dict(
            title=wavelength_label,
            gridcolor='#555555',
            linecolor='#555555',
            tickfont=dict(size=10, color='#ffffff')
        ),
        margin=dict(l=50, r=50, t=80, b=180),
        autosize=True,
        hovermode='closest',
    )

    # Buttons for switching between full spectrum and bands
    buttons = [
        dict(
            args=[{'visible': [True, False] + [False] * len(custom_bands)}],
            label="Full Spectrum",
            method="update"
        )
    ]

    for i, band in enumerate(custom_bands):
        buttons.append(dict(
            args=[{'visible': [False, True] + [j == i for j in range(len(custom_bands))]}],
            label=band['name'],
            method="update"
        ))

    updatemenus = [
        dict(
            type="buttons",
            direction="right",
            x=0.5,
            y=-0.5,
            xanchor="center",
            yanchor="top",
            buttons=buttons,
            pad={"r": 10, "t": 10},
            showactive=True,
            active=0,
            bgcolor='rgba(30, 40, 70, 0.8)',
            bordercolor='#ffffff',
            font=dict(color='#ffffff')
        )
    ]

    layout.updatemenus = updatemenus

    fig = go.Figure(data=data, layout=layout)
    fig.update_xaxes(rangeslider_visible=True)
    return fig


# ===================================
# MAST Directory Processing Utilities
# ===================================
def sigma_clip_flux(interpolated_fluxes, sigma=3, maxiters=5):
    """Apply sigma clipping to remove outliers from flux arrays."""
    cleaned_fluxes = []
    for flux in interpolated_fluxes:
        clipped_flux = sigma_clip(flux, sigma=sigma, maxiters=maxiters, cenfunc='median', stdfunc='mad_std')
        if np.all(clipped_flux.mask):
            # If everything got masked, fallback to an array of ones
            flux_cleaned = np.ones_like(flux)
        else:
            median_flux = np.median(flux[~clipped_flux.mask])
            flux_cleaned = np.where(clipped_flux.mask, median_flux, flux)
        cleaned_fluxes.append(flux_cleaned)
    return cleaned_fluxes


def smooth_flux_spectrum(interpolated_fluxes, sigma=1):
    """Apply Gaussian smoothing along the wavelength axis for each spectrum."""
    smoothed_fluxes = []
    for flux in interpolated_fluxes:
        smoothed_flux = gaussian_filter(flux, sigma=sigma)
        smoothed_fluxes.append(smoothed_flux)
    return smoothed_fluxes


def calculate_variance(interpolated_fluxes):
    """Calculate variance across time for each wavelength."""
    return np.var(interpolated_fluxes, axis=0)


def handle_variance_outliers(variance_flux, sigma=3, maxiters=3):
    """Apply sigma clipping to variance array to handle outliers."""
    clipped_variance = sigma_clip(variance_flux, sigma=sigma, maxiters=maxiters, cenfunc='median', stdfunc='mad_std')
    variance_cleaned = np.where(clipped_variance.mask, np.nan, variance_flux)
    return variance_cleaned


def process_mast_files(file_paths):
    """
    Process JWST x1dints.fits files from a MAST directory:
    - Interpolate onto common wavelength grid
    - Normalize flux
    - Sigma clip and smooth flux
    """
    all_wavelengths = []
    all_fluxes = []
    all_times = []

    for file_path in sorted(file_paths):
        w, f, t = load_and_process_fits(file_path)
        if w is None or f is None or t is None:
            continue
        all_wavelengths.append(w)
        all_fluxes.append(f)
        all_times.append(t)

    if not all_wavelengths:
        raise ValueError("No valid FITS files were processed from MAST data.")

    min_wavelength = max(np.min(w) for w in all_wavelengths)
    max_wavelength = min(np.max(w) for w in all_wavelengths)
    common_wavelength = np.linspace(min_wavelength, max_wavelength, 1000)

    interpolated_fluxes = []
    for wavelength, flux in zip(all_wavelengths, all_fluxes):
        f_interp = interpolate.interp1d(wavelength, flux, kind='linear', bounds_error=False, fill_value='extrapolate')
        interpolated_flux = f_interp(common_wavelength)
        median_flux = np.median(interpolated_flux)
        if median_flux == 0:
            normalized_flux = np.ones_like(interpolated_flux)
        else:
            normalized_flux = interpolated_flux / median_flux
        interpolated_fluxes.append(normalized_flux)

    cleaned_fluxes = sigma_clip_flux(interpolated_fluxes, sigma=3, maxiters=5)
    smoothed_fluxes = smooth_flux_spectrum(cleaned_fluxes, sigma=1)

    return common_wavelength, np.array(smoothed_fluxes), all_times


# ===================================
# Routes
# ===================================

@app.route('/plots/<path:filename>')
def serve_plots(filename):
    """
    Serve static Plotly HTML files directly from the 'plots' directory.
    """
    return send_from_directory('plots', filename)

@app.route('/')
def index():
    """
    Render the main index page.
    NOTE: We'll pass two example preloaded plot filenames to the template so it can embed them as iframes.
    """
    # If you have specific "preloaded" HTML files you want to show by default, list them here:
    preloaded_surface = "surface_plot_20250128_173435.html"
    preloaded_heatmap = "heatmap_plot_20250128_173435.html"

    # Render 'index.html', passing the filenames so you can use them in iframes or links
    return render_template('index.html',
                           preloaded_surface=preloaded_surface,
                           preloaded_heatmap=preloaded_heatmap)


@app.route('/upload', methods=['POST'])
def upload_files():
    """
    Handle file uploads for flux, wavelength, and time FITS files.
    Generate and return the surface and heatmap plots as JSON.
    Also store the figures in global variables for download.
    Save each plot as an HTML file in a 'plots' folder.
    """
    global latest_surface_figure, latest_heatmap_figure

    try:
        flux_file = request.files['flux']
        wavelength_file = request.files['wavelength']
        time_file = request.files['time']
        num_plots = int(request.form.get('num_plots', 1000))
        colorscale = request.form.get('colorscale', 'Viridis')
        custom_bands = json.loads(request.form.get('custom_bands', '[]'))
        remove_first_60 = request.form.get('remove_first_60', 'true').lower() == 'true'
        apply_binning = request.form.get('apply_binning', 'true').lower() == 'true'
        smooth_sigma = float(request.form.get('smooth_sigma', 2))
        wavelength_unit = request.form.get('wavelength_unit', 'um')

        logger.info(f"Received files: {flux_file.filename}, {wavelength_file.filename}, {time_file.filename}")
        logger.info(f"Number of plots: {num_plots}, Colorscale: {colorscale}")
        logger.info(f"Remove first 60: {remove_first_60}, Apply binning: {apply_binning}, Smooth sigma: {smooth_sigma}")
        logger.info(f"Wavelength unit: {wavelength_unit}")
        logger.info(f"Custom bands: {custom_bands}")

        # Load FITS data arrays
        flux_data = load_fits(flux_file)
        wavelength_data = load_fits(wavelength_file)
        time_data = load_fits(time_file)

        logger.info(
            f"Data shapes - Flux: {flux_data.shape}, Wavelength: {wavelength_data.shape}, Time: {time_data.shape}")

        # Ensure CH4 and CO bands are included if not present
        ch4_band = {'name': 'CH₄ Band', 'start': 2.14, 'end': 2.5}
        co_band = {'name': 'CO Band', 'start': 4.5, 'end': 5.05}
        if not any(band['name'] == 'CH₄ Band' for band in custom_bands):
            custom_bands.append(ch4_band)
        if not any(band['name'] == 'CO Band' for band in custom_bands):
            custom_bands.append(co_band)

        # Generate plots in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            surface_future = executor.submit(
                create_surface_plot,
                flux_data, wavelength_data, time_data,
                title="3D Surface Plot",
                num_plots=num_plots,
                remove_first_60=remove_first_60,
                apply_binning=apply_binning,
                smooth_sigma=smooth_sigma,
                wavelength_unit=wavelength_unit,
                custom_bands=custom_bands,
                colorscale=colorscale
            )

            heatmap_future = executor.submit(
                create_heatmap_plot,
                flux_data, wavelength_data, time_data,
                title="Heatmap",
                num_plots=num_plots,
                remove_first_60=remove_first_60,
                apply_binning=apply_binning,
                smooth_sigma=smooth_sigma,
                wavelength_unit=wavelength_unit,
                custom_bands=custom_bands,
                colorscale=colorscale
            )

            surface_plot = surface_future.result()
            heatmap_plot = heatmap_future.result()

        # Store figures in global variables (for download)
        latest_surface_figure = surface_plot
        latest_heatmap_figure = heatmap_plot

        # ============ SAVE PLOTS TO 'plots' FOLDER ============
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not os.path.exists('plots'):
            os.makedirs('plots')

        surface_html_path = f'plots/surface_plot_{timestamp}.html'
        heatmap_html_path = f'plots/heatmap_plot_{timestamp}.html'

        surface_plot.write_html(surface_html_path)
        heatmap_plot.write_html(heatmap_html_path)

        logger.info(f"Surface plot saved to {surface_html_path}")
        logger.info(f"Heatmap plot saved to {heatmap_html_path}")
        # ======================================================

        return jsonify({
            'surface_plot': surface_plot.to_json(),
            'heatmap_plot': heatmap_plot.to_json()
        })

    except Exception as e:
        logger.error(f"Error in upload_files: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


@app.route('/download_plots', methods=['GET'])
def download_plots():
    """
    Download the last-generated Surface and Heatmap plots as a single HTML file.
    """
    global latest_surface_figure, latest_heatmap_figure

    if latest_surface_figure is None or latest_heatmap_figure is None:
        return jsonify({"error": "No plots available to download. Please upload files first."}), 400

    # Convert each figure to partial HTML (no <html> or <head> tags),
    # but do NOT include plotly.js multiple times.
    html_surface = pio.to_html(
        latest_surface_figure, include_plotlyjs=False, full_html=False, div_id='surface_plot_div'
    )
    html_heatmap = pio.to_html(
        latest_heatmap_figure, include_plotlyjs=False, full_html=False, div_id='heatmap_plot_div'
    )

    # Combine them into one HTML file, loading Plotly from CDN
    combined_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <title>Downloaded Plots</title>
        <!-- Load Plotly from CDN -->
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    </head>
    <body style="background-color: #333; color: #eee;">
        <h1>3D Surface Plot</h1>
        {html_surface}

        <h1>Heatmap</h1>
        {html_heatmap}
    </body>
    </html>
    """

    # Return as an attachment for download
    return Response(
        combined_html,
        mimetype="text/html",
        headers={"Content-Disposition": "attachment;filename=plots.html"}
    )


@app.route('/upload_mast', methods=['POST'])
def upload_mast():
    """
    Handle uploading a zipped MAST directory. Extracts the zip, finds all x1dints.fits files,
    sorts them by observation time, processes them, and returns surface/heatmap plots
    *including custom bands* provided by the front end.
    """
    global latest_surface_figure, latest_heatmap_figure

    try:
        # 1. Get the MAST zip file
        mast_file = request.files.get('mast_zip')
        if not mast_file or mast_file.filename == '':
            return jsonify({'error': 'No MAST zip file provided.'}), 400

        # 2. Get custom bands JSON (array of { name, start, end }) from the form
        custom_bands_json = request.form.get('custom_bands', '[]')
        try:
            custom_bands = json.loads(custom_bands_json)
        except json.JSONDecodeError:
            custom_bands = []
        logger.info(f"Received custom bands for MAST: {custom_bands}")

        # Create a temporary directory
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, 'mast.zip')
        mast_file.save(zip_path)

        # Extract the uploaded .zip
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        # Find all x1dints.fits files
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

        # Sort files by observation time
        try:
            fits_files_sorted = sorted(
                fits_files, key=lambda x: load_and_process_fits(x)[2]
            )
        except TypeError:
            shutil.rmtree(temp_dir)
            return jsonify({'error': 'Error sorting FITS files by observation time.'}), 400

        # Process MAST files
        common_wavelength, interpolated_fluxes, all_times = process_mast_files(fits_files_sorted)

        # Convert times to hours from earliest observation
        reference_time = min(all_times)
        times_hours = np.array([(t - reference_time).to('hour').value for t in all_times])

        # Transpose flux to match shape (num_wavelengths, num_times)
        flux_2d = interpolated_fluxes.T
        wavelength_1d = common_wavelength
        time_1d = times_hours

        # Create the plots using the same create_*_plot functions
        surface_plot = create_surface_plot(
            flux=flux_2d,
            wavelength=wavelength_1d,
            time=time_1d,
            title="3D Surface Plot (MAST Data)",
            num_plots=1000,      # or read from a form field if desired
            remove_first_60=True,
            apply_binning=True,
            smooth_sigma=2,
            wavelength_unit='um',
            custom_bands=custom_bands,
            colorscale='Viridis'
        )

        heatmap_plot = create_heatmap_plot(
            flux=flux_2d,
            wavelength=wavelength_1d,
            time=time_1d,
            title="Heatmap (MAST Data)",
            num_plots=1000,
            remove_first_60=True,
            apply_binning=True,
            smooth_sigma=2,
            wavelength_unit='um',
            custom_bands=custom_bands,
            colorscale='Viridis'
        )

        # Store in global variables for /download_plots
        latest_surface_figure = surface_plot
        latest_heatmap_figure = heatmap_plot

        # Save each plot as an HTML file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not os.path.exists('plots'):
            os.makedirs('plots')

        surface_html_path = f'plots/mast_surface_plot_{timestamp}.html'
        heatmap_html_path = f'plots/mast_heatmap_plot_{timestamp}.html'
        surface_plot.write_html(surface_html_path)
        heatmap_plot.write_html(heatmap_html_path)

        logger.info(f"MAST Surface plot saved to {surface_html_path}")
        logger.info(f"MAST Heatmap plot saved to {heatmap_html_path}")

        # Clean up temp directory
        shutil.rmtree(temp_dir)

        # Return figures as JSON
        return jsonify({
            'surface_plot': surface_plot.to_json(),
            'heatmap_plot': heatmap_plot.to_json()
        })

    except Exception as e:
        logger.error(f"Error in upload_mast: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


if __name__ == '__main__':
    # In production, consider using a WSGI server (e.g., gunicorn) and disable debug mode.
    app.run(debug=True)

"""
Plotly figure builders for JWST spectral visualisations.
"""

import logging

import numpy as np
import plotly.graph_objs as go

from processing import process_data, identify_visits

logger = logging.getLogger(__name__)


def create_surface_plot_with_visits(flux, wavelength, time, title, num_plots,
                                    smooth_sigma=2, wavelength_unit='um',
                                    custom_bands=None, colorscale='Viridis',
                                    gap_threshold=0.5, use_interpolation=False,
                                    z_range=None, z_axis_display='variability',
                                    flux_unit='Unknown', errors_2d=None):
    """Create an interactive 3-D Plotly surface plot, one trace per visit."""
    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, False,
        smooth_sigma, wavelength_unit, z_axis_display,
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

    # Z-range clipping
    if isinstance(z_range, (tuple, list)):
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

    # One surface trace per visit
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
                y=0.5,
            ),
            hovertemplate=(
                'Time: %{x:.2f}<br>'
                + wavelength_label + ': %{y:.4f}<br>'
                + hover_z_label + ': %{z:' + hover_z_format + '}'
                + hover_z_suffix + '<extra></extra>'
            ),
            opacity=1.0,
            customdata=cd,
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
            xaxis=dict(title='Time (hours)', backgroundcolor='rgba(0,0,0,0)',
                       gridcolor='#555555', zeroline=False, showspikes=False),
            yaxis=dict(title=wavelength_label, backgroundcolor='rgba(0,0,0,0)',
                       gridcolor='#555555', zeroline=False, showspikes=False),
            zaxis=dict(
                title='Raw Flux' if z_axis_display == 'flux' else 'Variability (%)',
                backgroundcolor='rgba(0,0,0,0)',
                gridcolor='#555555', zeroline=False, showspikes=False,
            ),
            aspectmode='cube',
        ),
        margin=dict(l=20, r=20, b=20, t=60),
        autosize=True,
        hovermode='closest',
        showlegend=False,
    )
    fig = go.Figure(data=data, layout=layout)
    return fig


def create_heatmap_plot(flux, wavelength, time, title, num_plots,
                        smooth_sigma=2, wavelength_unit='um',
                        custom_bands=None, colorscale='Viridis',
                        z_range=None, z_axis_display='variability',
                        flux_unit='Unknown', errors_2d=None):
    """Create an interactive 2-D Plotly heatmap."""
    x, y, X, Y, Z, wavelength_label = process_data(
        flux, wavelength, time, num_plots, False,
        smooth_sigma, wavelength_unit, z_axis_display,
    )

    if Z.shape != (len(y), len(x)):
        raise ValueError(
            f"Heatmap Z shape {Z.shape} does not match "
            f"(len(y), len(x)) = {(len(y), len(x))}"
        )

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

    if isinstance(z_range, (tuple, list)):
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
            tickformat=colorbar_tickformat,
        ),
        hovertemplate=(
            'Time: %{x:.2f}<br>'
            + wavelength_label + ': %{y:.4f}<br>'
            + hover_z_label + ': %{z:' + hover_z_format + '}'
            + hover_z_suffix + '<extra></extra>'
        ),
        customdata=errors_2d,
    )
    data = [heatmap]

    y_min, y_max = float(np.nanmin(y)), float(np.nanmax(y))
    layout = go.Layout(
        template='plotly_dark',
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#ffffff'),
        title=dict(text=title, x=0.5),
        xaxis=dict(title='Time (hours)', showspikes=False,
                   gridcolor='#555555', linecolor='#555555', zeroline=False),
        yaxis=dict(title=wavelength_label, showspikes=False,
                   gridcolor='#555555', linecolor='#555555', zeroline=False,
                   range=[y_min, y_max]),
        margin=dict(l=20, r=20, b=60, t=60),
        hovermode='closest',
        showlegend=False,
    )
    fig = go.Figure(data=data, layout=layout)
    return fig

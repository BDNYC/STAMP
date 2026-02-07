"""File upload and download routes for MAST data, spectrum frames, and plot exports."""

import io
import os
import json
import time
import uuid
import base64
import shutil
import zipfile
import tempfile
import subprocess
import logging

import numpy as np
import plotly.io as pio
from plotly.utils import PlotlyJSONEncoder
from flask import Blueprint, request, jsonify, send_file
from astropy.io import fits
import h5py

import state
from config import COLOR_SCALES, BASE_DIR
from data_io import apply_data_ranges
from processing import process_mast_files_with_gaps
from plotting import create_surface_plot_with_visits, create_heatmap_plot

logger = logging.getLogger(__name__)

upload_bp = Blueprint('upload', __name__)


@upload_bp.route('/download_plots')
def download_plots():
    """Package the latest surface plot, heatmap, and video into a ZIP file.

    Reads plot data from ``state.*`` attributes that were set by the most
    recent ``/upload_mast`` or ``/start_mast`` job.  Generates standalone
    HTML files with embedded Plotly + band-filter buttons, plus a combined
    view with all plots and the spectrum video.
    """
    surface_html = state.last_surface_plot_html
    heatmap_html = state.last_heatmap_plot_html
    surface_json = state.last_surface_fig_json
    heatmap_json = state.last_heatmap_fig_json
    bands = state.last_custom_bands or []

    if not surface_html or not heatmap_html:
        return 'No plots available to download.', 400

    # Resolve video path
    mp4_path = state.latest_spectrum_mp4_path
    mp4_bytes = None
    mp4_name = None
    video_html = (
        '<div id="videoBox" style="min-height:120px;display:flex;'
        'align-items:center;justify-content:flex-start;color:#cbd5e1">'
        'No video available in this session.</div>'
    )
    if mp4_path and os.path.exists(mp4_path):
        with open(mp4_path, 'rb') as f:
            mp4_bytes = f.read()
        mp4_name = "2d_spectrum_" + time.strftime('%Y%m%d_%H%M%S') + ".mp4"
        b64 = base64.b64encode(mp4_bytes).decode('ascii')
        video_html = (
            '<video controls muted style="width:100%;max-width:1600px;'
            'display:block;margin:0 auto;border-radius:8px">'
            '<source src="data:video/mp4;base64,' + b64 + '" type="video/mp4">'
            '</video>'
        )

    # Build a standalone HTML page for a single plot
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

    # Build combined HTML with both plots + video
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

    # Write ZIP to memory buffer and send
    ts = time.strftime('%Y%m%d_%H%M%S')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        if surface_json and heatmap_json:
            z.writestr(
                'surface_plot_' + ts + '.html',
                make_single_plot_html(surface_json, '3D Surface Plot (MAST Data)', bands),
            )
            z.writestr(
                'heatmap_plot_' + ts + '.html',
                make_single_plot_html(heatmap_json, 'Heatmap (MAST Data)', bands),
            )
        else:
            z.writestr('surface_plot_' + ts + '.html', surface_html)
            z.writestr('heatmap_plot_' + ts + '.html', heatmap_html)
        z.writestr('combined_plots_' + ts + '.html', combined_html)
        if mp4_bytes and mp4_name:
            z.writestr(mp4_name, mp4_bytes)
    buf.seek(0)
    return send_file(
        buf, mimetype='application/zip', as_attachment=True,
        download_name='jwst_plots_' + ts + '.zip',
    )


@upload_bp.route('/upload_spectrum_frames', methods=['POST'])
def upload_spectrum_frames():
    """Receive PNG frames from the client and encode them into an MP4 video.

    Uses ffmpeg (must be available on PATH).  Returns a ``video_token``
    that the client can later pass to ``/download_plots`` so the video
    is included in the export ZIP.
    """
    fps = int(request.form.get('fps', 10))
    crf = int(request.form.get('crf', 22))
    files = request.files.getlist('frames')

    if not files:
        return jsonify({"error": "no frames provided"}), 400

    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return jsonify({
            "warning": "ffmpeg not available on server - video generation skipped",
            "video_token": None,
            "success": True,
        }), 200

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
            outpath,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return jsonify({"error": f"ffmpeg failed: {result.stderr}"}), 500

        if not os.path.exists(outpath):
            return jsonify({"error": "output file not created"}), 500

        # Store the video path so /download_plots can find it
        token = str(uuid.uuid4())
        state.video_tmp_paths[token] = outpath
        state.latest_spectrum_mp4_path = outpath

        return jsonify({"video_token": token, "success": True})

    except subprocess.TimeoutExpired:
        return jsonify({"error": "ffmpeg timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@upload_bp.route('/upload_mast', methods=['POST'])
def upload_mast():
    """Process an uploaded MAST zip file synchronously and return plots.

    This is the original upload endpoint.  For large datasets, prefer
    ``/start_mast`` which processes asynchronously with progress tracking.
    """
    try:
        mast_file = request.files.get('mast_zip')
        if not mast_file or mast_file.filename == '':
            return jsonify({'error': 'No MAST zip file provided.'}), 400

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

        # Extract and sort files
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

        # Run processing pipeline
        wavelength_1d, flux_norm_2d, flux_raw_2d, time_1d, metadata, error_raw_2d = (
            process_mast_files_with_gaps(
                fits_files_sorted,
                use_interpolation,
                max_integrations=num_integrations if num_integrations > 0 else None,
            )
        )

        # Apply user-specified data ranges
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
        else:
            wavelength_1d_norm, flux_norm_2d_filtered, time_1d_norm = wavelength_1d, flux_norm_2d, time_1d
            wavelength_1d_raw, flux_raw_2d_filtered, time_1d_raw = wavelength_1d, flux_raw_2d, time_1d
            wavelength_1d_err, error_raw_2d_filtered, time_1d_err = wavelength_1d, error_raw_2d, time_1d

        metadata['user_ranges'] = '; '.join(range_info) if range_info else None

        # Choose Z data and error data based on display mode
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

        # Create plots
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

        # Store in shared state for /download_plots
        state.latest_surface_figure = surface_plot
        state.latest_heatmap_figure = heatmap_plot
        state.last_surface_plot_html = pio.to_html(surface_plot, include_plotlyjs='cdn', full_html=True)
        state.last_heatmap_plot_html = pio.to_html(heatmap_plot, include_plotlyjs='cdn', full_html=True)
        state.last_surface_fig_json = surface_plot.to_plotly_json()
        state.last_heatmap_fig_json = heatmap_plot.to_plotly_json()
        state.last_custom_bands = json.loads(request.form.get('custom_bands', '[]'))

        shutil.rmtree(temp_dir)
        return jsonify({
            'surface_plot': surface_plot.to_json(),
            'heatmap_plot': heatmap_plot.to_json(),
            'metadata': metadata,
            'reference_spectrum': json.dumps(ref_spec.tolist()),
        })
    except Exception as e:
        logger.error(f"Error in upload_mast: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400

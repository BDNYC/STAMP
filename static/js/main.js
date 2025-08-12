// Animation state variables
let isAnimating = false;
let animationInterval = null;
let animationSpeed = 5;
let activeBand = null;
const plotOriginal = { surfacePlot: null, heatmapPlot: null };

// Video export configuration
const VIDEO_FPS = 12;           // frames per second
const VIDEO_MAX_FRAMES = 600;   // cap total frames
const VIDEO_WIDTH = 1600;       // exported width in pixels
const VIDEO_HEIGHT = 400;       // exported height in pixels
const VIDEO_CRF = 20;           // quality for server-side ffmpeg

function collectBands() {
  return Array.from(document.getElementById('customBands').children).map((band, idx) => {
    const inputs = band.querySelectorAll('input');
    const name = inputs[0].value.trim();
    const start = parseFloat(inputs[1].value);
    const end = parseFloat(inputs[2].value);
    if (!name || isNaN(start) || isNaN(end)) return null;
    return { id: `${name}-${start}-${end}-${idx}`, name, start, end };
  }).filter(Boolean);
}

function updateBandButtonStates() {
  const activeId = activeBand ? activeBand.id : '__full__';
  document.querySelectorAll('#surfaceBandButtons [data-band-id], #heatmapBandButtons [data-band-id]').forEach(btn => {
    if (btn.dataset.bandId === activeId) {
      btn.classList.add('ring-2', 'ring-blue-500');
    } else {
      btn.classList.remove('ring-2', 'ring-blue-500');
    }
  });
}

function renderBandButtons() {
  const bands = collectBands();
  ['surfaceBandButtons', 'heatmapBandButtons'].forEach(cid => {
    const c = document.getElementById(cid);
    if (!c) return;
    c.innerHTML = '';
    const fullBtn = document.createElement('button');
    fullBtn.textContent = 'Full Spectrum';
    fullBtn.className = 'px-3 py-2 bg-gray-600 text-gray-100 rounded-md hover:bg-gray-700 transition duration-200';
    fullBtn.dataset.bandId = '__full__';
    fullBtn.addEventListener('click', () => setActiveBand(null));
    c.appendChild(fullBtn);
    bands.forEach(b => {
      const btn = document.createElement('button');
      btn.textContent = b.name;
      btn.className = 'px-3 py-2 bg-gray-700 text-gray-100 rounded-md hover:bg-gray-600 transition duration-200';
      btn.dataset.bandId = b.id;
      btn.addEventListener('click', () => setActiveBand(b));
      c.appendChild(btn);
    });
  });
  updateBandButtonStates();
}

function setActiveBand(band) {
  activeBand = band;
  applyBandToPlot('surfacePlot', band);
  applyBandToPlot('heatmapPlot', band);
  if (currentSpectrumData && document.getElementById('toggleErrorBars') && document.getElementById('toggleErrorBars').checked) {
    currentSpectrumData.lockedRibbonRange = computeLockedRibbonRange(currentSpectrumData, activeBand);
  }
  if (currentSpectrumData) updateSpectrumPlot();
  updateBandButtonStates();
}


function applyBandToPlot(plotId, band) {
  const div = document.getElementById(plotId);
  if (!div || !div.data) return;
  if (!plotOriginal[plotId]) plotOriginal[plotId] = JSON.parse(JSON.stringify(div.data));
  if (!band) {
    Plotly.react(div, plotOriginal[plotId], div.layout);
    setupPlotClickHandler(div);
    return;
  }
  const orig = plotOriginal[plotId];
  const newData = [];
  for (const trace of orig) {
    const isSurface = plotId === 'surfacePlot' && trace.type === 'surface';
    const isHeatmap = plotId === 'heatmapPlot' && trace.type === 'heatmap';
    if (isSurface || isHeatmap) {
      let yvec = trace.y;
      if (Array.isArray(yvec[0])) yvec = yvec.map(row => row[0]);
      const z = trace.z;
      const inZ = [];
      const outZ = [];
      for (let i = 0; i < z.length; i++) {
        const inBand = yvec[i] >= band.start && yvec[i] <= band.end;
        const row = z[i];
        inZ[i] = inBand ? row.slice() : new Array(row.length).fill(NaN);
        outZ[i] = inBand ? new Array(row.length).fill(NaN) : row.slice();
      }
      const base = {};
      for (const k in trace) if (k !== 'z') base[k] = trace[k];
      newData.push({ ...base, z: inZ, name: trace.name });
      newData.push({ ...base, z: outZ, name: (trace.name || '') + ' Gray', showscale: false, opacity: 0.35, colorscale: [[0,'#888'],[1,'#888']] });
    } else {
      newData.push(trace);
    }
  }
  Plotly.react(div, newData, div.layout);
  setupPlotClickHandler(div);
}

// plot creation
function createPlot(plotId, data, layout, config) {
  const div = document.getElementById(plotId);
  const enhancedConfig = {
    ...config,
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
    toImageButtonOptions: {
      format: 'png',
      width: 1200,
      height: plotId === "spectrumPlot" ? 400 : 800,
      scale: 2
    }
  };
  return Plotly.newPlot(div, data, layout, enhancedConfig).then(() => {
    plotOriginal[plotId] = JSON.parse(JSON.stringify(div.data));
    if (plotId === 'surfacePlot' && div.layout && div.layout.scene) {
      const cam = div.layout.scene.camera || { up:{x:0,y:0,z:1}, center:{x:0,y:0,z:0}, eye:{x:1.25,y:1.25,z:1.25} };
      div._initialCamera = JSON.parse(JSON.stringify(cam));
    }
    if (plotId === 'surfacePlot' || plotId === 'heatmapPlot') {
      setupPlotClickHandler(div);
    }
    const mbc = div.querySelector('.modebar-container');
    if (mbc) { mbc.style.left = ''; mbc.style.right = '0px'; }

    let titleText = '';
    try {
      const t0 = Array.isArray(div.data) && div.data.length ? div.data[0] : null;
      const cbTitle = t0 && t0.colorbar && t0.colorbar.title && (t0.colorbar.title.text || t0.colorbar.title);
      titleText = (typeof cbTitle === 'string' ? cbTitle : '').trim();
    } catch(e) {}
    const isVariability = /%|variability/i.test(titleText);
    const tickFmt = isVariability ? '.4~f' : '.2e';

    if (plotId === 'surfacePlot') {
      Plotly.relayout(div, {
        'scene.zaxis.tickformat': tickFmt,
        'scene.zaxis.title.text': titleText || (isVariability ? 'Variability (%)' : 'Flux')
      });
    } else if (plotId === 'heatmapPlot') {
      const idxs = [];
      for (let i = 0; i < div.data.length; i++) {
        if (div.data[i] && div.data[i].type === 'heatmap') idxs.push(i);
      }
      if (idxs.length) {
        Plotly.restyle(div, { 'colorbar.tickformat': tickFmt }, idxs);
      }
    }
  });
}

function resetPlotView(plotId) {
  const div = document.getElementById(plotId);
  if (!div) return;
  if (plotId === 'surfacePlot') {
    const cam = div._initialCamera || { up:{x:0,y:0,z:1}, center:{x:0,y:0,z:0}, eye:{x:1.25,y:1.25,z:1.25} };
    Plotly.relayout(div, { 'scene.camera': cam });
  } else if (plotId === 'heatmapPlot') {
    Plotly.relayout(div, { 'xaxis.autorange': true, 'yaxis.autorange': true });
  }
}


function addCustomBandsToSpectrumPlot() {
  const spectrumPlotDiv = document.getElementById('spectrumPlot');
  const traces = spectrumPlotDiv.data;
  const yaxis = spectrumPlotDiv.layout.yaxis;
  const xaxis = spectrumPlotDiv.layout.xaxis;
  const bands = Array.from(document.getElementById('customBands').children).map(band => {
    const inputs = band.querySelectorAll('input');
    return {
      name:  inputs[0].value.trim(),
      start: parseFloat(inputs[1].value),
      end:   parseFloat(inputs[2].value)
    };
  }).filter(b => b.name && !isNaN(b.start) && !isNaN(b.end));
  let shapes = [];
  for (const band of bands) {
    shapes.push({
      type: 'rect',
      xref: 'x',
      yref: 'paper',
      x0: band.start,
      x1: band.end,
      y0: 0,
      y1: 1,
      fillcolor: 'rgba(255,255,0,0.15)',
      line: { width: 0 },
      layer: 'below'
    });
  }
  Plotly.relayout('spectrumPlot', { shapes: shapes });
}

function onToggleErrorBars() {
  const teb = document.getElementById('toggleErrorBars');
  if (!currentSpectrumData) { updateSpectrumPlot(); return; }
  if (teb && teb.checked) {
    currentSpectrumData.lockedRibbonRange = computeLockedRibbonRange(currentSpectrumData, activeBand);
  } else {
    currentSpectrumData.lockedRibbonRange = null;
  }
  updateSpectrumPlot();
}

function computeLockedRibbonRange(spec, band) {
  const wl = spec.wavelengthData || [];
  const Z = spec.fluxData || [];
  const E = spec.errorData || [];
  const ref = spec.referenceSpectrum || null;
  if (!Z.length || !E.length) return null;
  let minV = Infinity, maxV = -Infinity;
  for (let i = 0; i < wl.length; i++) {
    if (band && (wl[i] < band.start || wl[i] > band.end)) continue;
    for (let j = 0; j < spec.timeData.length; j++) {
      const v = Z[i] && Z[i][j];
      const e = E[i] && E[i][j];
      if (v == null || e == null || isNaN(v) || isNaN(e)) continue;
      let s = e;
      if (spec.zAxisDisplay === 'variability') {
        const r = ref && ref[i];
        if (!r || !isFinite(r) || r === 0) continue;
        s = 100 * e / r;
      }
      const up = v + s;
      const lo = v - s;
      if (isFinite(up) && up > maxV) maxV = up;
      if (isFinite(lo) && lo < minV) minV = lo;
    }
  }
  if (!isFinite(minV) || !isFinite(maxV)) return null;
  const pad = (maxV - minV) * 0.03 || 1e-6;
  return [minV - pad, maxV + pad];
}


document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('addBandBtn').addEventListener('click', () => addCustomBand());
  document.getElementById('uploadMastBtn').addEventListener('click', uploadMastDirectory);
  document.getElementById('resetSurfaceViewBtn').addEventListener('click', () => resetPlotView('surfacePlot'));
  document.getElementById('resetHeatmapViewBtn').addEventListener('click', () => resetPlotView('heatmapPlot'));
  document.getElementById('closeSpectrumBtn').addEventListener('click', closeSpectrumViewer);
  document.getElementById('prevSpectrumBtn').addEventListener('click', () => navigateSpectrum(-1));
  document.getElementById('nextSpectrumBtn').addEventListener('click', () => navigateSpectrum(1));
  document.getElementById('playAnimationBtn').addEventListener('click', toggleAnimation);
  document.getElementById('animationSpeed').addEventListener('input', (e) => updateAnimationSpeed(e.target.value));
  const teb = document.getElementById('toggleErrorBars');
  if (teb) teb.addEventListener('change', onToggleErrorBars);
  initializeColorScales();
  addCustomBand('CH₄ Band', 2.14, 2.50);
  addCustomBand('CO Band', 4.50, 5.05);
  renderBandButtons();

  const dl = document.querySelector('a[href="/download_plots"]');
  if (dl) dl.addEventListener('click', downloadAllWithVideo);

})


// Available color scales
const colorScales = [
  { name: 'Viridis',   class: 'viridis' },
  { name: 'Plasma',    class: 'plasma' },
  { name: 'Inferno',   class: 'inferno' },
  { name: 'Magma',     class: 'magma' },
  { name: 'Cividis',   class: 'cividis' },
  { name: 'Turbo',     class: 'turbo' },
  { name: 'Coolwarm',  class: 'coolwarm' },
  { name: 'Spectral',  class: 'spectral' },
  { name: 'RdYlBu',    class: 'rdylbu' },
  { name: 'Picnic',    class: 'picnic' }
];

function initializeColorScales() {
  const container = document.getElementById('colorscaleSelector');
  colorScales.forEach((scale, index) => {
    const option = document.createElement('div');
    option.className = `colorscale-option ${scale.class}`;
    option.setAttribute('data-colorscale', scale.name);
    option.title = scale.name;

    option.addEventListener('click', () => selectColorScale(option));
    container.appendChild(option);

    if (index === 0) selectColorScale(option);
  });
}

function selectColorScale(selectedOption) {
  document.querySelectorAll('.colorscale-option').forEach(option => {
    option.classList.remove('selected');
  });
  selectedOption.classList.add('selected');
}

function addCustomBand(name = '', start = '', end = '') {
  const bandContainer = document.createElement('div');
  bandContainer.className = 'flex items-center space-x-2 mb-2';
  bandContainer.innerHTML = `
    <input type="text" placeholder="Band Name" value="${name}"
           class="flex-grow px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
    <input type="number" step="0.01" placeholder="Start" value="${start}"
           class="w-24 px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
    <input type="number" step="0.01" placeholder="End" value="${end}"
           class="w-24 px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
    <button class="px-3 py-2 bg-red-600 text-gray-100 rounded-md hover:bg-red-700 transition duration-200">Remove</button>
  `;
  document.getElementById('customBands').appendChild(bandContainer);
  bandContainer.querySelector('button').addEventListener('click', () => {
    bandContainer.remove();
    renderBandButtons();
  });
  bandContainer.querySelectorAll('input').forEach(inp => {
    inp.addEventListener('input', renderBandButtons);
  });
  renderBandButtons();
}


function displayMetadata(metadata) {
  const metadataDiv = document.getElementById('metadataInfo');

  let metadataHTML = `
    <h3 class="text-lg font-medium mb-3 text-blue-300">Data Information</h3>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <p class="text-sm text-gray-400">Total Integrations:</p>
        <p class="text-lg font-semibold">${metadata.total_integrations}</p>
      </div>
      <div>
        <p class="text-sm text-gray-400">Files Processed:</p>
        <p class="text-lg font-semibold">${metadata.files_processed}</p>
      </div>
      <div>
        <p class="text-sm text-gray-400">Wavelength Range:</p>
        <p class="text-lg font-semibold">${metadata.wavelength_range}</p>
      </div>
      <div>
        <p class="text-sm text-gray-400">Time Range:</p>
        <p class="text-lg font-semibold">${metadata.time_range}</p>
      </div>
  `;

  if (metadata.targets && metadata.targets.length > 0) {
    metadataHTML += `
      <div>
        <p class="text-sm text-gray-400">Target(s):</p>
        <p class="text-lg font-semibold">${metadata.targets.join(', ')}</p>
      </div>
    `;
  }

  if (metadata.plotted_integrations && metadata.plotted_integrations < metadata.total_integrations) {
    metadataHTML += `
      <div class="col-span-2 border-t border-gray-600 pt-2 mt-2">
        <p class="text-sm text-yellow-400">⚠️ Showing ${metadata.plotted_integrations} of ${metadata.total_integrations} integrations (evenly sampled)</p>
      </div>
    `;
  }

  if (metadata.user_ranges) {
    metadataHTML += `
      <div class="col-span-2 border-t border-gray-600 pt-2 mt-2">
        <p class="text-sm text-blue-400">📊 User-specified ranges applied:</p>
        <p class="text-sm text-gray-300">${metadata.user_ranges}</p>
      </div>
    `;
  }

  if (metadata.instruments && metadata.instruments.length > 0) {
    metadataHTML += `
      <div>
        <p class="text-sm text-gray-400">Instrument(s):</p>
        <p class="text-lg font-semibold">${metadata.instruments.join(', ')}</p>
      </div>
    `;
  }

  if (metadata.filters && metadata.filters.length > 0) {
    metadataHTML += `
      <div>
        <p class="text-sm text-gray-400">Filter(s):</p>
        <p class="text-lg font-semibold">${metadata.filters.join(', ')}</p>
      </div>
    `;
  }

  if (metadata.gratings && metadata.gratings.length > 0) {
    metadataHTML += `
      <div>
        <p class="text-sm text-gray-400">Grating(s):</p>
        <p class="text-lg font-semibold">${metadata.gratings.join(', ')}</p>
      </div>
    `;
  }

  metadataHTML += '</div>';
  metadataDiv.innerHTML = metadataHTML;
  metadataDiv.classList.remove('hidden');
}

async function uploadMastDirectory() {
  const mastZipFile = document.getElementById('mastZipFile').files[0];
  if (!mastZipFile) { alert('Please select a MAST ZIP file before processing.'); return; }
  const formData = new FormData();
  formData.append('mast_zip', mastZipFile);
  const selectedColorscale = document.querySelector('.colorscale-option.selected');
  if (!selectedColorscale) { alert('Please select a color scale.'); return; }
  formData.append('colorscale', selectedColorscale.getAttribute('data-colorscale'));
  const useInterpolation = document.getElementById('linearInterpolation').checked;
  formData.append('use_interpolation', useInterpolation);
  const numIntegrations = document.getElementById('numIntegrations').value;
  formData.append('num_integrations', numIntegrations || '0');
  const timeRangeMin = document.getElementById('timeRangeMin').value;
  const timeRangeMax = document.getElementById('timeRangeMax').value;
  const wavelengthRangeMin = document.getElementById('wavelengthRangeMin').value;
  const wavelengthRangeMax = document.getElementById('wavelengthRangeMax').value;
  const variabilityRangeMin = document.getElementById('variabilityRangeMin').value;
  const variabilityRangeMax = document.getElementById('variabilityRangeMax').value;
  const zAxisDisplay = document.querySelector('input[name="zAxisDisplay"]:checked').value;
  formData.append('time_range_min', timeRangeMin || '');
  formData.append('time_range_max', timeRangeMax || '');
  formData.append('wavelength_range_min', wavelengthRangeMin || '');
  formData.append('wavelength_range_max', wavelengthRangeMax || '');
  formData.append('variability_range_min', variabilityRangeMin || '');
  formData.append('variability_range_max', variabilityRangeMax || '');
  formData.append('z_axis_display', zAxisDisplay);
  const customBands = Array.from(document.getElementById('customBands').children).map(band => {
    const inputs = band.querySelectorAll('input');
    return { name: inputs[0].value.trim(), start: parseFloat(inputs[1].value), end: parseFloat(inputs[2].value) };
  }).filter(b => b.name && !isNaN(b.start) && !isNaN(b.end));
  formData.append('custom_bands', JSON.stringify(customBands));

  activeBand = null;
  plotOriginal.surfacePlot = null;
  plotOriginal.heatmapPlot = null;
  window.__referenceSpectrum = null;

  // Store user ranges for spectrum viewer
  window.__userRanges = {
    timeRangeMin: timeRangeMin || null,
    timeRangeMax: timeRangeMax || null,
    wavelengthRangeMin: wavelengthRangeMin || null,
    wavelengthRangeMax: wavelengthRangeMax || null
  };

  const uploadBtn = document.getElementById('uploadMastBtn');
  const originalText = uploadBtn.textContent;
  uploadBtn.textContent = 'Processing...';
  uploadBtn.disabled = true;
  try {
    const response = await fetch('/upload_mast', { method: 'POST', body: formData });
    if (!response.ok) { const errorText = await response.text(); throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`); }
    const data = await response.json();
    if (data.error) { throw new Error(data.error); }

    if (data.metadata) displayMetadata(data.metadata);
    if (data.reference_spectrum) { try { window.__referenceSpectrum = JSON.parse(data.reference_spectrum); } catch(_) { window.__referenceSpectrum = null; } }

    const surfaceData = JSON.parse(data.surface_plot);
    const heatmapData = JSON.parse(data.heatmap_plot);

    function centerPlot(fig) {
      const m = { l: 120, r: 120, t: 60, b: 50 };
      fig.layout = fig.layout || {};
      fig.layout.margin = { l: m.l, r: m.r, t: m.t, b: m.b };
      if (fig.layout.scene) { fig.layout.scene.domain = { x: [0,1], y: [0,1] }; }
      if (fig.layout.xaxis || fig.layout.yaxis) {
        fig.layout.xaxis = { ...(fig.layout.xaxis || {}), domain: [0,1] };
        fig.layout.yaxis = { ...(fig.layout.yaxis || {}), domain: [0,1] };
      }
      Object.keys(fig.layout).forEach(k => {
        if (k.startsWith('coloraxis')) {
          const cb = ((fig.layout[k] || {}).colorbar) || {};
          fig.layout[k] = { ...(fig.layout[k] || {}), colorbar: { ...cb, x: 1, xanchor: 'left', xpad: m.r - 40, y: 0.5, yanchor: 'middle', len: 0.85 } };
        }
      });
      if (Array.isArray(fig.data)) {
        fig.data.forEach(t => {
          if (!t.coloraxis && (t.type === 'surface' || t.type === 'heatmap')) {
            t.colorbar = { ...(t.colorbar || {}), x: 1, xanchor: 'left', xpad: m.r - 40, y: 0.5, yanchor: 'middle', len: 0.85 };
          }
        });
      }
    }
    centerPlot(surfaceData);
    centerPlot(heatmapData);

    document.getElementById('plotsContainer').classList.remove('hidden');

    await Promise.all([
      createPlot('surfacePlot', surfaceData.data, surfaceData.layout, { responsive: true }),
      createPlot('heatmapPlot', heatmapData.data, heatmapData.layout, { responsive: true })
    ]);

    Plotly.Plots.resize(document.getElementById('surfacePlot'));
    Plotly.Plots.resize(document.getElementById('heatmapPlot'));

    document.getElementById('plotsContainer').scrollIntoView({ behavior: 'smooth' });

    renderBandButtons();
    setActiveBand(null);
  } catch (error) {
    console.error('Error processing MAST folder:', error);
    alert('Error processing MAST folder: ' + error.message);
  } finally {
    uploadBtn.textContent = originalText;
    uploadBtn.disabled = false;
  }
}

// Animation functions
function toggleAnimation() {
  if (isAnimating) {
    // Stop animation
    clearInterval(animationInterval);
    isAnimating = false;
    document.getElementById('playAnimationBtn').innerHTML = '▶ Play';
    // Re-enable manual navigation
    document.getElementById('prevSpectrumBtn').disabled = currentTimeIndex <= 0;
    document.getElementById('nextSpectrumBtn').disabled = currentTimeIndex >= totalTimePoints - 1;
  } else {
    // Start animation
    isAnimating = true;
    document.getElementById('playAnimationBtn').innerHTML = '⏸ Pause';
    // Disable manual navigation during animation
    document.getElementById('prevSpectrumBtn').disabled = true;
    document.getElementById('nextSpectrumBtn').disabled = true;

    // Calculate interval based on speed (higher speed = shorter interval)
    const intervalMs = 1000 / animationSpeed; // 1-10 fps

    animationInterval = setInterval(() => {
      // Move to next frame
      currentTimeIndex++;

      // Loop back to beginning
      if (currentTimeIndex >= totalTimePoints) {
        currentTimeIndex = 0;
      }

      // Update the plot
      updateSpectrumPlot();
    }, intervalMs);
  }
}

function updateAnimationSpeed(newSpeed) {
  animationSpeed = parseInt(newSpeed);
  document.getElementById('speedValue').textContent = newSpeed;

  // If currently animating, restart with new speed
  if (isAnimating) {
    clearInterval(animationInterval);
    isAnimating = false;
    toggleAnimation(); // Restart with new speed
  }
}

// Global variables for spectrum viewer
let currentSpectrumData = null;
let currentTimeIndex = 0;
let totalTimePoints = 0;

// Function to show spectrum at a specific time
function showSpectrumAtTime(clickData, plotDiv) {
  const plotData = (plotDiv && plotDiv.data) ? plotDiv.data : [];
  let mainTrace = null;
  let allVisitTraces = [];

  for (let i = 0; i < plotData.length; i++) {
    const trace = plotData[i];
    if (!trace || trace.visible === false) continue;
    const name = (typeof trace.name === 'string') ? trace.name : '';
    const isGray = name.indexOf('Gray') !== -1;
    if (isGray) continue;

    if (plotDiv.id === 'surfacePlot' && trace.type === 'surface') {
      allVisitTraces.push({ trace, index: i });
    } else if (plotDiv.id === 'heatmapPlot' && trace.type === 'heatmap') {
      mainTrace = trace;
      break;
    }
  }

  if (plotDiv.id === 'surfacePlot' && allVisitTraces.length > 0) {
    const firstTrace = allVisitTraces[0].trace;
    let wavelengthData = firstTrace.y;
    if (Array.isArray(wavelengthData[0])) wavelengthData = wavelengthData.map(row => row[0]);

    let combinedTimeData = [];
    let combinedFluxData = [];
    let combinedErrData = [];

    for (let k = 0; k < allVisitTraces.length; k++) {
      const t = allVisitTraces[k].trace;
      let tx = t.x;
      if (Array.isArray(tx[0])) tx = tx[0];
      combinedTimeData = combinedTimeData.concat(tx);

      if (combinedFluxData.length === 0) {
        combinedFluxData = t.z.map(row => row.slice());
      } else {
        for (let r = 0; r < t.z.length; r++) {
          combinedFluxData[r] = combinedFluxData[r].concat(t.z[r]);
        }
      }

      const cd = t.customdata;
      if (cd && Array.isArray(cd) && cd.length) {
        if (combinedErrData.length === 0) {
          combinedErrData = cd.map(row => row.slice());
        } else {
          for (let r = 0; r < cd.length; r++) {
            combinedErrData[r] = combinedErrData[r].concat(cd[r]);
          }
        }
      }
    }

    mainTrace = { type: 'surface', x: combinedTimeData, y: wavelengthData, z: combinedFluxData, customdata: combinedErrData.length ? combinedErrData : null };
  } else if (!mainTrace && plotDiv.id === 'surfacePlot' && allVisitTraces.length > 0) {
    mainTrace = allVisitTraces[0].trace;
  }

  if (!mainTrace) return;

  const clickX = clickData.x;

  let wavelengthData = mainTrace.y;
  let timeData = mainTrace.x;
  let fluxData = mainTrace.z;
  let errData = mainTrace.customdata || null;

  if (mainTrace.type === 'surface') {
    if (Array.isArray(wavelengthData[0])) wavelengthData = wavelengthData.map(row => row[0]);
    if (Array.isArray(timeData[0])) timeData = timeData[0];
  }

  // Apply user-defined ranges to spectrum data
  const ranges = window.__userRanges || {};

  // Apply wavelength filtering
  if (ranges.wavelengthRangeMin || ranges.wavelengthRangeMax) {
    const wlMin = ranges.wavelengthRangeMin ? parseFloat(ranges.wavelengthRangeMin) : -Infinity;
    const wlMax = ranges.wavelengthRangeMax ? parseFloat(ranges.wavelengthRangeMax) : Infinity;

    const wlIndices = [];
    for (let i = 0; i < wavelengthData.length; i++) {
      if (wavelengthData[i] >= wlMin && wavelengthData[i] <= wlMax) {
        wlIndices.push(i);
      }
    }

    if (wlIndices.length > 0) {
      wavelengthData = wlIndices.map(i => wavelengthData[i]);
      fluxData = wlIndices.map(i => fluxData[i]);
      if (errData) errData = wlIndices.map(i => errData[i]);
    }
  }

  // Apply time filtering
  if (ranges.timeRangeMin || ranges.timeRangeMax) {
    const timeMin = ranges.timeRangeMin ? parseFloat(ranges.timeRangeMin) : -Infinity;
    const timeMax = ranges.timeRangeMax ? parseFloat(ranges.timeRangeMax) : Infinity;

    const timeIndices = [];
    for (let i = 0; i < timeData.length; i++) {
      if (timeData[i] >= timeMin && timeData[i] <= timeMax) {
        timeIndices.push(i);
      }
    }

    if (timeIndices.length > 0) {
      timeData = timeIndices.map(i => timeData[i]);
      fluxData = fluxData.map(row => timeIndices.map(i => row[i]));
      if (errData) errData = errData.map(row => timeIndices.map(i => row[i]));
    }
  }

  let timeIndex = 0;
  let minDiff = Infinity;
  for (let i = 0; i < timeData.length; i++) {
    const d = Math.abs(timeData[i] - clickX);
    if (d < minDiff) { minDiff = d; timeIndex = i; }
  }

  totalTimePoints = timeData.length;
  currentTimeIndex = timeIndex;

  let globalMin = Infinity;
  let globalMax = -Infinity;
  for (let i = 0; i < fluxData.length; i++) {
    const row = fluxData[i];
    for (let j = 0; j < row.length; j++) {
      const v = row[j];
      if (v !== null && !isNaN(v)) {
        if (v < globalMin) globalMin = v;
        if (v > globalMax) globalMax = v;
      }
    }
  }

  const zAxisDisplay = document.querySelector('input[name="zAxisDisplay"]:checked').value;

  currentSpectrumData = {
    wavelengthData,
    timeData,
    fluxData,
    errorData: errData,
    plotType: mainTrace.type,
    clickedTime: timeData[timeIndex],
    useInterpolation: document.getElementById('linearInterpolation').checked,
    globalMin,
    globalMax,
    zAxisDisplay,
    referenceSpectrum: Array.isArray(window.__referenceSpectrum) ? window.__referenceSpectrum : null,
    lockedRibbonRange: null
  };

  document.getElementById('spectrumContainer').classList.remove('hidden');
  updateSpectrumPlot();
  document.getElementById('spectrumContainer').scrollIntoView({ behavior: 'smooth', block: 'center' });
}
// Function to update spectrum plot
function updateSpectrumPlot() {
  if (!currentSpectrumData) { return; }
  const wavelengths = currentSpectrumData.wavelengthData;
  const fluxData = currentSpectrumData.fluxData;
  const errData = currentSpectrumData.errorData;
  const currentTime = currentSpectrumData.timeData[currentTimeIndex];
  let values = [];
  let errors = [];
  for (let i = 0; i < wavelengths.length; i++) {
    if (fluxData[i] && fluxData[i][currentTimeIndex] !== undefined) {
      values.push(fluxData[i][currentTimeIndex]);
    } else {
      values.push(NaN);
    }
    if (errData && errData[i] && errData[i][currentTimeIndex] !== undefined) {
      errors.push(errData[i][currentTimeIndex]);
    } else {
      errors.push(NaN);
    }
  }
  const validValues = values.filter(v => !isNaN(v) && v !== null);
  if (validValues.length === 0) { return; }
  let yAxisLabel, hoverFormat;
  if (currentSpectrumData.zAxisDisplay === 'flux') {
    yAxisLabel = 'Flux';
    const flux_max = Math.max(...validValues.map(v => Math.abs(v)));
    hoverFormat = (flux_max < 0.01 || flux_max > 1000) ? '.2e' : '.4f';
  } else {
    yAxisLabel = 'Variability (%)';
    hoverFormat = '.4f';
  }
  const layout = {
    template: "plotly_dark",
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: 'Wavelength (µm)', gridcolor: '#555555', linecolor: '#555555', zeroline: false },
    yaxis: {
      title: yAxisLabel,
      gridcolor: '#555555',
      linecolor: '#555555',
      zeroline: false,
      range: currentSpectrumData.lockedRibbonRange ? currentSpectrumData.lockedRibbonRange : [currentSpectrumData.globalMin, currentSpectrumData.globalMax],
      tickformat: currentSpectrumData.zAxisDisplay === 'flux' && hoverFormat === '.2e' ? '.2e' : undefined
    },
    margin: { l: 60, r: 40, t: 40, b: 60 },
    showlegend: false
  };
  const showErrors = !!document.getElementById('toggleErrorBars') && document.getElementById('toggleErrorBars').checked === true;
  if (activeBand) {
    const inMask = wavelengths.map((_, i) => wavelengths[i] >= activeBand.start && wavelengths[i] <= activeBand.end);
    const inY = values.map((v, i) => inMask[i] ? v : NaN);
    const outY = values.map((v, i) => inMask[i] ? NaN : v);
    const spectrumIn = {
      x: wavelengths,
      y: inY,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#3B82F6', width: 2 },
      name: 'In',
      hovertemplate: `Wavelength: %{x:.4f} µm<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
    };
    const spectrumOut = {
      x: wavelengths,
      y: outY,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#9CA3AF', width: 2 },
      name: 'Out',
      hovertemplate: `Wavelength: %{x:.4f} µm<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
    };
    const traces = [spectrumOut, spectrumIn];
    if (showErrors) {
      const ref = currentSpectrumData.referenceSpectrum;
      const sigma = currentSpectrumData.zAxisDisplay === 'variability' && Array.isArray(ref)
        ? errors.map((e, i) => (ref[i] && isFinite(ref[i]) && ref[i] !== 0) ? (e / ref[i]) * 100 : NaN)
        : errors;
      const upper = inY.map((v, i) => (isNaN(v) || isNaN(sigma[i])) ? NaN : v + sigma[i]);
      const lower = inY.map((v, i) => (isNaN(v) || isNaN(sigma[i])) ? NaN : v - sigma[i]);
      const ribbonTop = { x: wavelengths, y: upper, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false };
      const ribbonBottom = { x: wavelengths, y: lower, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.2)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false };
      traces.push(ribbonTop, ribbonBottom);
    }
    Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
  } else {
    const spectrumTrace = {
      x: wavelengths,
      y: values,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#3B82F6', width: 2 },
      name: 'Spectrum',
      hovertemplate: `Wavelength: %{x:.4f} µm<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
    };
    const traces = [spectrumTrace];
    if (showErrors) {
      const ref = currentSpectrumData.referenceSpectrum;
      const sigma = currentSpectrumData.zAxisDisplay === 'variability' && Array.isArray(ref)
        ? errors.map((e, i) => (ref[i] && isFinite(ref[i]) && ref[i] !== 0) ? (e / ref[i]) * 100 : NaN)
        : errors;
      const upper = values.map((v, i) => (isNaN(v) || isNaN(sigma[i])) ? NaN : v + sigma[i]);
      const lower = values.map((v, i) => (isNaN(v) || isNaN(sigma[i])) ? NaN : v - sigma[i]);
      const ribbonTop = { x: wavelengths, y: upper, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false };
      const ribbonBottom = { x: wavelengths, y: lower, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.2)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false };
      traces.push(ribbonTop, ribbonBottom);
    }
    Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
  }
  document.getElementById('spectrumTitle').textContent = `Spectrum at Time: ${currentTime.toFixed(2)} hours`;
  document.getElementById('spectrumInfo').textContent = `Time point ${currentTimeIndex + 1} of ${totalTimePoints}`;
  document.getElementById('prevSpectrumBtn').disabled = currentTimeIndex <= 0;
  document.getElementById('nextSpectrumBtn').disabled = currentTimeIndex >= totalTimePoints - 1;
}

// Function to close spectrum viewer
function closeSpectrumViewer() {
  // Stop animation if running
  if (isAnimating) {
    toggleAnimation();
  }

  document.getElementById('spectrumContainer').classList.add('hidden');
  currentSpectrumData = null;
}

// Function to setup click handler on a specific plot
function setupPlotClickHandler(plotDiv) {
  // Remove any existing handlers first
  plotDiv.removeAllListeners('plotly_click');

  // Add simple click handler
  plotDiv.on('plotly_click', function(eventData) {
    // Check if the corresponding checkbox is checked
    let isEnabled = false;
    if (plotDiv.id === 'surfacePlot') {
      isEnabled = document.getElementById('enableSurfaceClick').checked;
    } else if (plotDiv.id === 'heatmapPlot') {
      isEnabled = document.getElementById('enableHeatmapClick').checked;
    }

    if (isEnabled && eventData && eventData.points && eventData.points.length > 0) {
      console.log('Click detected on', plotDiv.id);
      const point = eventData.points[0];
      console.log('Point data:', point);

      // Pass both the point and the plot div
      showSpectrumAtTime(point, plotDiv);
    }
  });

  console.log('Click handler setup complete for', plotDiv.id);
}

function nextAnimationFrame() {
  return new Promise(resolve => requestAnimationFrame(() => resolve()));
}


async function ensureSpectrumInitialized() {
  if (currentSpectrumData) return;

  const heatmapDiv = document.getElementById('heatmapPlot');
  const surfaceDiv = document.getElementById('surfacePlot');
  const sourceDiv = (heatmapDiv && heatmapDiv.data && heatmapDiv.data.length) ? heatmapDiv
                   : (surfaceDiv && surfaceDiv.data && surfaceDiv.data.length) ? surfaceDiv
                   : null;
  if (!sourceDiv) throw new Error('Plots are not ready; process MAST data first.');

  // Synthesize a click at the first time point
  let timeArray = null;
  // Try to deduce time array from the source plot traces
  for (let i = 0; i < sourceDiv.data.length; i++) {
    const tr = sourceDiv.data[i];
    if (tr.visible === false) continue;
    if (sourceDiv.id === 'heatmapPlot' && tr.type === 'heatmap') { timeArray = tr.x; break; }
    if (sourceDiv.id === 'surfacePlot' && tr.type === 'surface') { timeArray = Array.isArray(tr.x) ? tr.x[0] : tr.x; break; }
  }
  const firstTime = (timeArray && timeArray.length) ? timeArray[0] : 0;
  const fakeClick = { points: [{ x: firstTime }] };
  showSpectrumAtTime(fakeClick, sourceDiv);
  await nextAnimationFrame();
}

function dataURLtoBlob(dataurl) {
  const arr = dataurl.split(',');
  const mime = arr[0].match(/:(.*?);/)[1];
  const bstr = atob(arr[1]);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  for (let i = 0; i < n; i++) { u8arr[i] = bstr.charCodeAt(i); }
  return new Blob([u8arr], { type: mime });
}

async function captureSpectrumFrames() {
  await ensureSpectrumInitialized();
  const spDiv = document.getElementById('spectrumPlot');

  // Determine indices to sample
  const N = totalTimePoints;
  if (!N || N <= 0) throw new Error('No spectrum time points available.');
  const target = Math.min(N, VIDEO_MAX_FRAMES);
  const step = Math.max(1, Math.floor(N / target));
  const indices = [];
  for (let i = 0; i < N; i += step) indices.push(i);
  if (indices[indices.length - 1] !== N - 1) indices.push(N - 1);

  const frames = [];
  for (let idx of indices) {
    currentTimeIndex = idx;
    updateSpectrumPlot();
    await nextAnimationFrame();
    const dataUrl = await Plotly.toImage(spDiv, { format: 'png', width: VIDEO_WIDTH, height: VIDEO_HEIGHT, scale: 1 });
    frames.push(dataURLtoBlob(dataUrl));
  }
  return frames;
}

async function uploadFramesAndEncode(frames) {
  const fd = new FormData();
  fd.append('fps', String(VIDEO_FPS));
  fd.append('crf', String(VIDEO_CRF));
  for (let i = 0; i < frames.length; i++) {
    fd.append('frames', frames[i], `frame_${String(i).padStart(5, '0')}.png`);
  }
  const res = await fetch('/upload_spectrum_frames', { method: 'POST', body: fd });
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) {
    const msg = ct.includes('application/json') ? (await res.json()).error || 'encode failed' : await res.text();
    throw new Error(`Video upload/encode failed: ${msg}`);
  }
  const data = ct.includes('application/json') ? await res.json() : {};
  if (!data.ok) throw new Error(`Video upload/encode failed: ${data.error || 'unknown error'}`);
  window.__lastVideoToken = data.token || null;
}


async function downloadAllWithVideo(e) {
  if (e) e.preventDefault();
  const link = document.querySelector('a[href="/download_plots"]');
  const originalText = link ? link.textContent : null;
  if (link) { link.textContent = 'Preparing video…'; link.classList.add('opacity-70'); }

  try {
    const frames = await captureSpectrumFrames();
    await uploadFramesAndEncode(frames);

    const token = window.__lastVideoToken ? `?video_token=${encodeURIComponent(window.__lastVideoToken)}` : '';
    const resp = await fetch('/download_plots' + token);
    if (!resp.ok) {
      const et = await resp.text();
      throw new Error(`Download failed: ${et}`);
    }
    const blob = await resp.blob();
    let filename = 'jwst_plots.zip';
    const cd = resp.headers.get('Content-Disposition');
    if (cd) {
      const m = cd.match(/filename="?([^"]+)"?/);
      if (m && m[1]) filename = m[1];
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error(err);
    alert(err.message || 'Failed to prepare video download.');
  } finally {
    if (link && originalText) { link.textContent = originalText; link.classList.remove('opacity-70'); }
  }
}

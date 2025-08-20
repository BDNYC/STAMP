// Animation state variables
let isAnimating = false;
let animationInterval = null;
let animationSpeed = 5;
let activeBands = [];
const plotOriginal = { surfacePlot: null, heatmapPlot: null };

const VIDEO_FPS = 12;
const VIDEO_MAX_FRAMES = 600;
const VIDEO_WIDTH = 1600;
const VIDEO_HEIGHT = 400;
const VIDEO_CRF = 20;

let __progressTimer = null;
let __currentJobId = null;

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
  const activeIds = activeBands.map(b => b.id);
  document.querySelectorAll('#surfaceBandButtons [data-band-id], #heatmapBandButtons [data-band-id], #spectrumBandButtons [data-band-id]').forEach(btn => {
    const isActive = activeIds.includes(btn.dataset.bandId) || (btn.dataset.bandId === '__full__' && activeBands.length === 0);
    if (isActive) {
      btn.classList.add('ring-2', 'ring-blue-500');
    } else {
      btn.classList.remove('ring-2', 'ring-blue-500');
    }
  });
}

function renderBandButtons() {
  const bands = collectBands();
  ['surfaceBandButtons', 'heatmapBandButtons', 'spectrumBandButtons'].forEach(cid => {
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
  if (band === null) {
    activeBands = [];
  } else {
    const i = activeBands.findIndex(x => x.id === band.id);
    if (i >= 0) activeBands.splice(i, 1);
    else activeBands.push({ id: band.id, name: band.name, start: band.start, end: band.end });
  }
  applyBandToPlot('surfacePlot', activeBands);
  applyBandToPlot('heatmapPlot', activeBands);
  if (currentSpectrumData && document.getElementById('toggleErrorBars') && document.getElementById('toggleErrorBars').checked) {
    currentSpectrumData.lockedRibbonRange = computeLockedRibbonRange(currentSpectrumData, null);
  }
  if (currentSpectrumData) {
    if (spectrumMode === 'vs_time') {
      const wls = currentSpectrumData.wavelengthData || [];
      const eligible = getEligibleWavelengthIndices(wls);
      if (eligible.length) {
        if (!eligible.includes(currentWavelengthIndex)) {
          currentWavelengthIndex = eligible[0];
        }
      }
    }
    updateSpectrumPlot();
  }
  updateBandButtonStates();
}

function applyBandToPlot(plotId, bands) {
  const div = document.getElementById(plotId);
  if (!div || !div.data) return;
  if (!plotOriginal[plotId]) plotOriginal[plotId] = JSON.parse(JSON.stringify(div.data));
  if (!bands || bands.length === 0) {
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
        const inBand = bands.some(b => yvec[i] >= b.start && yvec[i] <= b.end);
        const row = z[i];
        inZ[i] = inBand ? row.slice() : new Array(row.length).fill(NaN);
        outZ[i] = inBand ? new Array(row.length).fill(NaN) : row.slice();
      }
      const base = {};
      for (const k in trace) if (k !== 'z') base[k] = trace[k];
      newData.push({ ...base, z: inZ, name: trace.name });
      newData.push({ ...base, z: outZ, name: (trace.name || '') + ' Gray', showscale: false, opacity: 0.35, colorscale: [[0,'#888'],[1,'#888']], hoverinfo: 'skip' });
    } else {
      newData.push(trace);
    }
  }
  Plotly.react(div, newData, div.layout);
  setupPlotClickHandler(div);
}

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
        'scene.zaxis.title.text': titleText || (isVariability ? 'Variability (%)' : 'Flux'),
        'scene.aspectmode': 'cube'
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
    const desiredHeight = plotId === 'spectrumPlot' ? 480 : 640;
    div.style.aspectRatio = '';
    div.style.height = desiredHeight + 'px';
    Plotly.relayout(div, { height: desiredHeight });
    if (plotId === 'heatmapPlot') {
      try {
        let ys = [];
        for (let i = 0; i < div.data.length; i++) {
          const tr = div.data[i];
          if (tr && tr.type === 'heatmap' && tr.y) {
            if (Array.isArray(tr.y[0])) {
              for (let r = 0; r < tr.y.length; r++) ys.push(tr.y[r][0]);
            } else {
              ys = ys.concat(tr.y);
            }
          }
        }
        const yf = ys.filter(v => Number.isFinite(v));
        if (yf.length) {
          const ymin = Math.min(...yf);
          const ymax = Math.max(...yf);
          if (ymin < ymax) {
            Plotly.relayout(div, { 'yaxis.range': [ymin, ymax] });
          }
        }
      } catch(e) {}
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
    if (!currentSpectrumData.lockedRibbonRange) currentSpectrumData.lockedRibbonRange = computeLockedRibbonRange(currentSpectrumData, null);
  }
  updateSpectrumPlot();
}

function computeLockedRibbonRange(spec, bands) {
  const wl = spec.wavelengthData || [];
  const Z = spec.fluxData || [];
  const E = spec.errorData || [];
  const ref = spec.referenceSpectrum || null;
  if (!Z.length || !E.length) return null;
  let minV = Infinity, maxV = -Infinity;
  for (let i = 0; i < wl.length; i++) {
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

let spectrumMode = 'vs_wavelength';
let currentSpectrumData = null;
let currentTimeIndex = 0;
let totalTimePoints = 0;
let currentWavelengthIndex = 0;
let totalWavelengthPoints = 0;

function getEligibleWavelengthIndices(wavelengths) {
  if (!activeBands || activeBands.length === 0) return wavelengths.map((_, i) => i);
  const inds = [];
  for (let i = 0; i < wavelengths.length; i++) {
    const w = wavelengths[i];
    if (activeBands.some(b => w >= b.start && w <= b.end)) inds.push(i);
  }
  return inds;
}

function toggleSpectrumMode() {
  spectrumMode = (spectrumMode === 'vs_wavelength') ? 'vs_time' : 'vs_wavelength';
  const btn = document.getElementById('toggleSpectrumModeBtn');
  if (btn) btn.textContent = (spectrumMode === 'vs_wavelength') ? 'X-axis: Wavelength' : 'X-axis: Time';
  if (currentSpectrumData) {
    if (spectrumMode === 'vs_time') {
      totalWavelengthPoints = (currentSpectrumData.wavelengthData || []).length;
      const eligible = getEligibleWavelengthIndices(currentSpectrumData.wavelengthData || []);
      if (eligible.length) {
        if (!eligible.includes(currentWavelengthIndex)) currentWavelengthIndex = eligible[0];
      } else {
        currentWavelengthIndex = 0;
      }
    }
    updateSpectrumPlot();
  }
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
  const tsm = document.getElementById('toggleSpectrumModeBtn');
  if (tsm) tsm.addEventListener('click', toggleSpectrumMode);
});

const colorScales = [
  { name: 'Viridis',   class: 'viridis' },
  { name: 'Plasma',    class: 'plasma' },
  { name: 'Inferno',   class: 'inferno' },
  { name: 'Magma',     class: 'magma' },
  { name: 'Cividis',   class: 'cividis' },
  { name: 'Turbo',     class: 'turbo' },
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
        <p class="text-sm text-yellow-400"> Showing ${metadata.plotted_integrations} of ${metadata.total_integrations} integrations (evenly sampled)</p>
      </div>
    `;
  }
  if (metadata.user_ranges) {
    metadataHTML += `
      <div class="col-span-2 border-t border-gray-600 pt-2 mt-2">
        <p class="text-sm text-blue-400"> User-specified ranges applied:</p>
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

function showProgress(message) {
  const btn = document.getElementById('uploadMastBtn');
  let wrap = document.getElementById('progressWrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'progressWrap';
    wrap.className = 'mt-4';
    wrap.innerHTML = `
      <div class="w-full h-2 bg-gray-700 rounded overflow-hidden">
        <div id="progressInner" class="h-2 bg-blue-500" style="width:0%"></div>
      </div>
      <div class="flex justify-between mt-1">
        <p id="progressMsg" class="text-xs text-gray-300"></p>
        <p id="progressPct" class="text-xs text-gray-400"></p>
      </div>
      <p id="progressStats" class="text-[11px] mt-1 text-gray-400"></p>
    `;
    btn.parentElement.appendChild(wrap);
  }
  const msg = wrap.querySelector('#progressMsg');
  if (msg) msg.textContent = message || 'Queued…';
  const inner = wrap.querySelector('#progressInner');
  if (inner) inner.style.width = '0%';
  const pct = wrap.querySelector('#progressPct');
  if (pct) pct.textContent = '0%';
  const stats = wrap.querySelector('#progressStats');
  if (stats) stats.textContent = '';
  wrap.style.display = 'block';
}
function updateProgress(pct, message, statsText) {
  const wrap = document.getElementById('progressWrap');
  if (!wrap) return;
  const inner = wrap.querySelector('#progressInner');
  const pctVal = Math.max(0, Math.min(100, Math.round(pct || 0)));
  if (inner) inner.style.width = `${pctVal}%`;
  const msg = wrap.querySelector('#progressMsg');
  if (msg && message != null) msg.textContent = message;
  const pctEl = wrap.querySelector('#progressPct');
  if (pctEl) pctEl.textContent = `${pctVal}%`;
  const stats = wrap.querySelector('#progressStats');
  if (stats) stats.textContent = statsText || '';
}
function hideProgress() {
  const wrap = document.getElementById('progressWrap');
  if (wrap) wrap.style.display = 'none';
}

function fmtETA(s) {
  if (!(s >= 0)) return '';
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2,'0')} ETA`;
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

  activeBands = [];
  plotOriginal.surfacePlot = null;
  plotOriginal.heatmapPlot = null;
  window.__referenceSpectrum = null;

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
  showProgress('Queued…');

  try {
    const startRes = await fetch('/start_mast', { method: 'POST', body: formData });
    if (!startRes.ok) { const t = await startRes.text(); throw new Error(`HTTP ${startRes.status}: ${t}`); }
    const startData = await startRes.json();
    if (!startData.job_id) throw new Error('No job id returned');
    __currentJobId = startData.job_id;

    await new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          const r = await fetch(`/progress/${__currentJobId}`);
          if (!r.ok) { const et = await r.text(); throw new Error(et || 'progress error'); }
          const p = await r.json();
          const stageMap = { queued:'Queued', scan:'Scanning files', read:'Reading integrations', regrid:'Regridding', interpolate:'Interpolating', finalize:'Finalizing', done:'Done', error:'Error' };
          const stageLabel = stageMap[p.stage] || (p.stage || '');
          const proc = typeof p.processed_integrations === 'number' ? p.processed_integrations : null;
          const tot = typeof p.total_integrations === 'number' ? p.total_integrations : null;
          const baseMsg = p.message || '';
          let main = stageLabel ? `${stageLabel} — ${baseMsg}` : baseMsg;
          let stats = '';
          if (tot && proc != null) stats += `${proc}/${tot} integrations`;
          if (p.throughput && isFinite(p.throughput)) stats += (stats ? ' • ' : '') + `${p.throughput.toFixed(1)}/s`;
          if (p.eta_seconds != null) stats += (stats ? ' • ' : '') + fmtETA(p.eta_seconds);
          updateProgress(p.percent || 0, main, stats);
          if (p.status === 'done') {
            updateProgress(100, 'Finalizing…', stats);
            clearInterval(__progressTimer);
            __progressTimer = null;
            resolve();
          } else if (p.status === 'error') {
            clearInterval(__progressTimer);
            __progressTimer = null;
            reject(new Error(p.message || 'Processing failed'));
          }
        } catch (e) {
          clearInterval(__progressTimer);
          __progressTimer = null;
          reject(e);
        }
      };
      __progressTimer = setInterval(poll, 800);
      poll();
    });

    const res = await fetch(`/results/${__currentJobId}`);
    if (!res.ok) { const t = await res.text(); throw new Error(`HTTP ${res.status}: ${t}`); }
    const data = await res.json();
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
    if (__progressTimer) { clearInterval(__progressTimer); __progressTimer = null; }
    hideProgress();
    uploadBtn.textContent = originalText;
    uploadBtn.disabled = false;
  }
}

function toggleAnimation() {
  if (spectrumMode === 'vs_time' && activeBands.length > 0) {
    return;
  }
  if (isAnimating) {
    clearInterval(animationInterval);
    isAnimating = false;
    document.getElementById('playAnimationBtn').innerHTML = '▶ Play';
    if (spectrumMode === 'vs_wavelength') {
      document.getElementById('prevSpectrumBtn').disabled = currentTimeIndex <= 0;
      document.getElementById('nextSpectrumBtn').disabled = currentTimeIndex >= totalTimePoints - 1;
    } else {
      document.getElementById('prevSpectrumBtn').disabled = currentWavelengthIndex <= 0;
      document.getElementById('nextSpectrumBtn').disabled = currentWavelengthIndex >= totalWavelengthPoints - 1;
    }
  } else {
    isAnimating = true;
    document.getElementById('playAnimationBtn').innerHTML = '⏸ Pause';
    document.getElementById('prevSpectrumBtn').disabled = true;
    document.getElementById('nextSpectrumBtn').disabled = true;
    const intervalMs = 1000 / animationSpeed;
    animationInterval = setInterval(() => {
      if (spectrumMode === 'vs_wavelength') {
        currentTimeIndex++;
        if (currentTimeIndex >= totalTimePoints) {
          currentTimeIndex = 0;
        }
      } else {
        currentWavelengthIndex++;
        if (currentWavelengthIndex >= totalWavelengthPoints) {
          currentWavelengthIndex = 0;
        }
      }
      updateSpectrumPlot();
    }, intervalMs);
  }
}

function updateAnimationSpeed(newSpeed) {
  animationSpeed = parseInt(newSpeed);
  document.getElementById('speedValue').textContent = newSpeed;
  if (isAnimating) {
    clearInterval(animationInterval);
    isAnimating = false;
    toggleAnimation();
  }
}

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
  const clickY = clickData.y;

  let wavelengthData = mainTrace.y;
  let timeData = mainTrace.x;
  let fluxData = mainTrace.z;
  let errData = mainTrace.customdata || null;

  if (mainTrace.type === 'surface') {
    if (Array.isArray(wavelengthData[0])) wavelengthData = wavelengthData.map(row => row[0]);
    if (Array.isArray(timeData[0])) timeData = timeData[0];
  }

  const ranges = window.__userRanges || {};

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

  totalWavelengthPoints = wavelengthData.length;
  if (typeof clickY === 'number' && isFinite(clickY)) {
    let wlIdx = 0;
    let wMin = Infinity;
    for (let i = 0; i < wavelengthData.length; i++) {
      const d = Math.abs(wavelengthData[i] - clickY);
      if (d < wMin) { wMin = d; wlIdx = i; }
    }
    currentWavelengthIndex = wlIdx;
  } else {
    currentWavelengthIndex = 0;
  }
  const eligible = getEligibleWavelengthIndices(wavelengthData);
  if (eligible.length && !eligible.includes(currentWavelengthIndex)) currentWavelengthIndex = eligible[0];

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

  currentSpectrumData.lockedRibbonRange = computeLockedRibbonRange(currentSpectrumData, null);

  document.getElementById('spectrumContainer').classList.remove('hidden');
  updateSpectrumPlot();
  document.getElementById('spectrumContainer').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function updateSpectrumPlot() {
  if (!currentSpectrumData) { return; }
  const wavelengths = currentSpectrumData.wavelengthData;
  const fluxData = currentSpectrumData.fluxData;
  const errData = currentSpectrumData.errorData;

  let values = [];
  let errors = [];
  let xAxisTitle = 'Wavelength (µm)';
  let xValues = wavelengths;
  let infoPrimary = '';
  let infoIndex = 0;
  let infoTotal = 0;

  currentSpectrumData.bandAveraged = false;

  if (spectrumMode === 'vs_wavelength') {
    const currentTime = currentSpectrumData.timeData[currentTimeIndex];
    for (let i = 0; i < wavelengths.length; i++) {
      values.push((fluxData[i] && fluxData[i][currentTimeIndex] !== undefined) ? fluxData[i][currentTimeIndex] : NaN);
      errors.push((errData && errData[i] && errData[i][currentTimeIndex] !== undefined) ? errData[i][currentTimeIndex] : NaN);
    }
    xAxisTitle = 'Wavelength (µm)';
    xValues = wavelengths;
    infoPrimary = `Spectrum at Time: ${currentTime.toFixed(2)} hours`;
    infoIndex = currentTimeIndex + 1;
    infoTotal = totalTimePoints;
  } else {
    const timeArray = currentSpectrumData.timeData || [];
    if (activeBands && activeBands.length >= 1) {
      const b0 = activeBands[0];
      for (let j = 0; j < timeArray.length; j++) {
        let sum = 0, cnt = 0, esum = 0, ecnt = 0;
        for (let i = 0; i < wavelengths.length; i++) {
          const w = wavelengths[i];
          if (w >= b0.start && w <= b0.end) {
            const v = (fluxData[i] && fluxData[i][j] !== undefined) ? fluxData[i][j] : NaN;
            if (isFinite(v)) { sum += v; cnt++; }
            const e = (errData && errData[i] && errData[i][j] !== undefined) ? errData[i][j] : NaN;
            if (isFinite(e)) { esum += e; ecnt++; }
          }
        }
        values.push(cnt ? (sum / cnt) : NaN);
        errors.push(ecnt ? (esum / ecnt) : NaN);
      }
      xAxisTitle = 'Time (hours)';
      xValues = timeArray;
      infoPrimary = activeBands.length === 1 ? `Band-integrated series: ${b0.name} (${b0.start.toFixed(2)}–${b0.end.toFixed(2)} µm)` : `Band-integrated series (${activeBands.length} bands)`;
      infoIndex = 1;
      infoTotal = 1;
      currentSpectrumData.bandAveraged = true;
    } else {
      const wlIdx = Math.max(0, Math.min(currentWavelengthIndex, wavelengths.length - 1));
      for (let j = 0; j < timeArray.length; j++) {
        values.push((fluxData[wlIdx] && fluxData[wlIdx][j] !== undefined) ? fluxData[wlIdx][j] : NaN);
        errors.push((errData && errData[wlIdx] && errData[wlIdx][j] !== undefined) ? errData[wlIdx][j] : NaN);
      }
      xAxisTitle = 'Time (hours)';
      xValues = timeArray;
      infoPrimary = `Series at Wavelength: ${wavelengths[wlIdx].toFixed(4)} µm`;
      infoIndex = wlIdx + 1;
      infoTotal = totalWavelengthPoints;
    }
  }

  const validValues = values.filter(v => !isNaN(v) && v !== null);
  if (validValues.length === 0) { return; }

  let yAxisLabel, hoverFormat, yTickFormat;
  if (currentSpectrumData.zAxisDisplay === 'flux') {
    yAxisLabel = 'Flux';
    hoverFormat = '.2e';
    yTickFormat = '.2e';
  } else {
    yAxisLabel = 'Variability (%)';
    hoverFormat = '.4f';
    yTickFormat = '.4~f';
  }

  const layout = {
    template: "plotly_dark",
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: xAxisTitle, gridcolor: '#555555', linecolor: '#555555', zeroline: false },
    yaxis: {
      title: yAxisLabel,
      gridcolor: '#555555',
      linecolor: '#555555',
      zeroline: false,
      range: currentSpectrumData.lockedRibbonRange ? currentSpectrumData.lockedRibbonRange : [currentSpectrumData.globalMin, currentSpectrumData.globalMax],
      tickformat: yTickFormat
    },
    margin: { l: 60, r: 40, t: 40, b: 60 },
    showlegend: false
  };

  const showErrors = !!document.getElementById('toggleErrorBars') && document.getElementById('toggleErrorBars').checked === true;

  function sigmaFor(valuesArr, errsArr, wlIndexForTimeSeries = null) {
    if (!Array.isArray(errsArr) || !errsArr.length) return errsArr;
    if (currentSpectrumData.bandAveraged && currentSpectrumData.zAxisDisplay === 'variability') {
      return errsArr;
    }
    if (currentSpectrumData.zAxisDisplay === 'variability') {
      const ref = currentSpectrumData.referenceSpectrum;
      if (Array.isArray(ref)) {
        if (spectrumMode === 'vs_wavelength') {
          return errsArr.map((e, i) => {
            const r = ref[i];
            return (r && isFinite(r) && r !== 0) ? (e / r) * 100 : NaN;
          });
        } else {
          const r = ref[wlIndexForTimeSeries];
          return errsArr.map(e => (r && isFinite(r) && r !== 0) ? (e / r) * 100 : NaN);
        }
      }
      return errsArr.map(() => NaN);
    }
    return errsArr;
  }

  if (spectrumMode === 'vs_wavelength') {
    if (activeBands && activeBands.length > 0) {
      const inMask = xValues.map((w) => activeBands.some(b => w >= b.start && w <= b.end));
      const inY = values.map((v, i) => inMask[i] ? v : NaN);

      const baseTrace = {
        x: xValues,
        y: values,
        type: 'scatter',
        mode: 'lines',
        line: { color: '#9CA3AF', width: 2 },
        opacity: 0.35,
        name: 'Spectrum',
        hoverinfo: 'skip'
      };

      const spectrumIn = {
        x: xValues,
        y: inY,
        type: 'scatter',
        mode: 'lines',
        line: { color: '#3B82F6', width: 2 },
        name: 'In',
        hovertemplate: `Wavelength: %{x:.4f} µm<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
      };

      const traces = [baseTrace, spectrumIn];

      if (showErrors) {
        const sigmaRaw = sigmaFor(inY, errors);
        let i = 0;
        while (i < xValues.length) {
          const ok = inMask[i] && isFinite(inY[i]) && isFinite(sigmaRaw[i]);
          if (!ok) { i++; continue; }
          const start = i;
          i++;
          while (i < xValues.length && inMask[i] && isFinite(inY[i]) && isFinite(sigmaRaw[i])) i++;
          const end = i - 1;

          const xSeg = xValues.slice(start, end + 1);
          const upperSeg = [];
          const lowerSeg = [];
          for (let k = start; k <= end; k++) {
            upperSeg.push(inY[k] + sigmaRaw[k]);
            lowerSeg.push(inY[k] - sigmaRaw[k]);
          }
          traces.push(
            { x: xSeg, y: upperSeg, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
            { x: xSeg, y: lowerSeg, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false }
          );
        }
      }

      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
    } else {
      const spectrumTrace = {
        x: xValues,
        y: values,
        type: 'scatter',
        mode: 'lines',
        line: { color: '#3B82F6', width: 2 },
        name: 'Spectrum',
        hovertemplate: `Wavelength: %{x:.4f} µm<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
      };

      const traces = [spectrumTrace];

      if (showErrors) {
        const sigma = sigmaFor(values, errors);
        const upper = values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v + sigma[i] : null);
        const lower = values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v - sigma[i] : null);
        traces.push(
          { x: xValues, y: upper, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
          { x: xValues, y: lower, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false }
        );
      }

      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
    }
  } else {
    if (activeBands && activeBands.length >= 1) {
      const timeArray = xValues;
      const traces = [];
      const gapThresholdHours = 0.5;
      const segs = [];
      if (!currentSpectrumData.useInterpolation) {
        let s = 0;
        for (let i = 1; i < timeArray.length; i++) {
          if ((timeArray[i] - timeArray[i - 1]) > gapThresholdHours) {
            segs.push([s, i - 1]);
            s = i;
          }
        }
        segs.push([s, timeArray.length - 1]);
      }
      const bandColors = ['#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', '#06B6D4', '#E11D48', '#22C55E', '#A855F7', '#F97316'];
      function hexToRgba(hex, a) {
        const h = hex.replace('#', '');
        const r = parseInt(h.substring(0, 2), 16);
        const g = parseInt(h.substring(2, 4), 16);
        const b = parseInt(h.substring(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${a})`;
      }
      for (let bi = 0; bi < activeBands.length; bi++) {
        const b = activeBands[bi];
        const col = bandColors[bi % bandColors.length];
        const fillCol = hexToRgba(col, 0.2);
        const y = [];
        const eArr = [];
        const hasErr = Array.isArray(errData) && errData.length;
        for (let j = 0; j < timeArray.length; j++) {
          if (hasErr) {
            let sumw = 0, sumwv = 0;
            for (let i = 0; i < wavelengths.length; i++) {
              const w = wavelengths[i];
              if (w >= b.start && w <= b.end) {
                const v = (fluxData[i] && fluxData[i][j] !== undefined) ? fluxData[i][j] : NaN;
                if (!isFinite(v)) continue;
                let sErr = (errData && errData[i] && errData[i][j] !== undefined) ? errData[i][j] : NaN;
                if (!isFinite(sErr) || sErr <= 0) continue;
                if (currentSpectrumData.zAxisDisplay === 'variability') {
                  const ref = currentSpectrumData.referenceSpectrum;
                  const r = Array.isArray(ref) ? ref[i] : NaN;
                  if (!(r && isFinite(r) && r !== 0)) continue;
                  sErr = (sErr / r) * 100;
                  if (!isFinite(sErr) || sErr <= 0) continue;
                }
                const wgt = 1 / (sErr * sErr);
                sumw += wgt;
                sumwv += wgt * v;
              }
            }
            if (sumw > 0) {
              y.push(sumwv / sumw);
              eArr.push(1 / Math.sqrt(sumw));
            } else {
              y.push(NaN);
              eArr.push(NaN);
            }
          } else {
            let sum = 0, cnt = 0;
            for (let i = 0; i < wavelengths.length; i++) {
              const w = wavelengths[i];
              if (w >= b.start && w <= b.end) {
                const v = (fluxData[i] && fluxData[i][j] !== undefined) ? fluxData[i][j] : NaN;
                if (isFinite(v)) { sum += v; cnt++; }
              }
            }
            y.push(cnt ? (sum / cnt) : NaN);
            eArr.push(NaN);
          }
        }
        if (!currentSpectrumData.useInterpolation) {
          segs.forEach(([a, bb], si) => {
            const xSeg = timeArray.slice(a, bb + 1);
            const ySeg = y.slice(a, bb + 1);
            traces.push({
              x: xSeg,
              y: ySeg,
              type: 'scatter',
              mode: 'lines',
              name: b.name,
              connectgaps: false,
              showlegend: si === 0,
              line: { color: col, width: 2 },
              legendgroup: `band_${bi}`
            });
            if (showErrors && eArr.some(k => isFinite(k))) {
              const eSeg = eArr.slice(a, bb + 1);
              const upperSeg = ySeg.map((v, i) => (isFinite(v) && isFinite(eSeg[i])) ? v + eSeg[i] : null);
              const lowerSeg = ySeg.map((v, i) => (isFinite(v) && isFinite(eSeg[i])) ? v - eSeg[i] : null);
              traces.push(
                { x: xSeg, y: upperSeg, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false, legendgroup: `band_${bi}` },
                { x: xSeg, y: lowerSeg, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: fillCol, line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false, legendgroup: `band_${bi}` }
              );
            }
          });
        } else {
          traces.push({
            x: timeArray,
            y: y,
            type: 'scatter',
            mode: 'lines',
            name: b.name,
            line: { color: col, width: 2 },
            legendgroup: `band_${bi}`
          });
          if (showErrors && eArr.some(k => isFinite(k))) {
            const upper = y.map((v, i) => (isFinite(v) && isFinite(eArr[i])) ? v + eArr[i] : null);
            const lower = y.map((v, i) => (isFinite(v) && isFinite(eArr[i])) ? v - eArr[i] : null);
            traces.push(
              { x: timeArray, y: upper, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false, legendgroup: `band_${bi}` },
              { x: timeArray, y: lower, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: fillCol, line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false, legendgroup: `band_${bi}` }
            );
          }
        }
      }
      layout.showlegend = activeBands.length > 1;
      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
    } else {
      const traces = [];
      const gapThresholdHours = 0.5;
      const xValuesTime = xValues;

      if (!currentSpectrumData.useInterpolation) {
        const segs = [];
        let s = 0;
        for (let i = 1; i < xValuesTime.length; i++) {
          if ((xValuesTime[i] - xValuesTime[i - 1]) > gapThresholdHours) {
            segs.push([s, i - 1]);
            s = i;
          }
        }
        segs.push([s, xValuesTime.length - 1]);

        segs.forEach(([a, b]) => {
          const xSeg = xValuesTime.slice(a, b + 1);
          const ySeg = values.slice(a, b + 1);
          traces.push({
            x: xSeg,
            y: ySeg,
            type: 'scatter',
            mode: 'lines',
            line: { color: '#3B82F6', width: 2 },
            name: 'Series',
            hovertemplate: `Time: %{x:.4f} hr<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`,
            connectgaps: false,
            showlegend: false
          });

          if (showErrors) {
            const sigmaSeg = sigmaFor(ySeg, errors.slice(a, b + 1), currentWavelengthIndex);
            const upperSeg = ySeg.map((v, i) => (isFinite(v) && isFinite(sigmaSeg[i])) ? v + sigmaSeg[i] : null);
            const lowerSeg = ySeg.map((v, i) => (isFinite(v) && isFinite(sigmaSeg[i])) ? v - sigmaSeg[i] : null);
            traces.push(
              { x: xSeg, y: upperSeg, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
              { x: xSeg, y: lowerSeg, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false }
            );
          }
        });
      } else {
        const spectrumTrace = {
          x: xValuesTime,
          y: values,
          type: 'scatter',
          mode: 'lines',
          line: { color: '#3B82F6', width: 2 },
          name: 'Series',
          hovertemplate: `Time: %{x:.4f} hr<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
        };
        traces.push(spectrumTrace);

        if (showErrors) {
          const sigma = sigmaFor(values, errors, currentWavelengthIndex);
          const upper = values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v + sigma[i] : null);
          const lower = values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v - sigma[i] : null);
          traces.push(
            { x: xValuesTime, y: upper, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
            { x: xValuesTime, y: lower, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false }
          );
        }
      }

      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
    }
  }

  const titleEl = document.getElementById('spectrumTitle');
  if (titleEl) titleEl.textContent = infoPrimary;
  const infoEl = document.getElementById('spectrumInfo');
  if (infoEl) {
    if (spectrumMode === 'vs_wavelength') {
      infoEl.textContent = `Time point ${infoIndex} of ${infoTotal}`;
    } else {
      infoEl.textContent = `Wavelength point ${infoIndex} of ${infoTotal}`;
    }
  }

  if (spectrumMode === 'vs_time' && activeBands.length > 0) {
    document.getElementById('prevSpectrumBtn').disabled = true;
    document.getElementById('nextSpectrumBtn').disabled = true;
    document.getElementById('playAnimationBtn').disabled = true;
  } else if (spectrumMode === 'vs_wavelength') {
    document.getElementById('prevSpectrumBtn').disabled = currentTimeIndex <= 0;
    document.getElementById('nextSpectrumBtn').disabled = currentTimeIndex >= totalTimePoints - 1;
    document.getElementById('playAnimationBtn').disabled = false;
  } else {
    document.getElementById('prevSpectrumBtn').disabled = currentWavelengthIndex <= 0;
    document.getElementById('nextSpectrumBtn').disabled = currentWavelengthIndex >= totalWavelengthPoints - 1;
    document.getElementById('playAnimationBtn').disabled = false;
  }
}


function navigateSpectrum(step) {
  if (!currentSpectrumData) return;
  if (spectrumMode === 'vs_time' && activeBands.length > 0) return;
  if (spectrumMode === 'vs_wavelength') {
    if (!totalTimePoints) return;
    currentTimeIndex += step;
    if (currentTimeIndex < 0) currentTimeIndex = 0;
    if (currentTimeIndex >= totalTimePoints) currentTimeIndex = totalTimePoints - 1;
  } else {
    if (!totalWavelengthPoints) return;
    currentWavelengthIndex += step;
    if (currentWavelengthIndex < 0) currentWavelengthIndex = 0;
    if (currentWavelengthIndex >= totalWavelengthPoints) currentWavelengthIndex = totalWavelengthPoints - 1;
    const eligible = getEligibleWavelengthIndices(currentSpectrumData.wavelengthData || []);
    if (eligible.length && !eligible.includes(currentWavelengthIndex)) {
      let next = eligible.find(i => i > currentWavelengthIndex);
      if (step < 0) {
        for (let k = eligible.length - 1; k >= 0; k--) { if (eligible[k] < currentWavelengthIndex) { next = eligible[k]; break; } }
      }
      if (next == null) next = (step < 0 ? eligible[eligible.length - 1] : eligible[0]);
      currentWavelengthIndex = next;
    }
  }
  updateSpectrumPlot();
}

function closeSpectrumViewer() {
  if (isAnimating) {
    toggleAnimation();
  }
  document.getElementById('spectrumContainer').classList.add('hidden');
  currentSpectrumData = null;
}

function setupPlotClickHandler(plotDiv) {
  plotDiv.removeAllListeners('plotly_click');
  plotDiv.on('plotly_click', function(eventData) {
    let isEnabled = false;
    if (plotDiv.id === 'surfacePlot') {
      isEnabled = document.getElementById('enableSurfaceClick').checked;
    } else if (plotDiv.id === 'heatmapPlot') {
      isEnabled = document.getElementById('enableHeatmapClick').checked;
    }
    if (isEnabled && eventData && eventData.points && eventData.points.length > 0) {
      const point = eventData.points[0];
      showSpectrumAtTime(point, plotDiv);
    }
  });
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

  let timeArray = null;
  let wlArray = null;
  for (let i = 0; i < sourceDiv.data.length; i++) {
    const tr = sourceDiv.data[i];
    if (tr.visible === false) continue;
    if (sourceDiv.id === 'heatmapPlot' && tr.type === 'heatmap') { timeArray = tr.x; wlArray = tr.y; break; }
    if (sourceDiv.id === 'surfacePlot' && tr.type === 'surface') { timeArray = Array.isArray(tr.x) ? tr.x[0] : tr.x; wlArray = Array.isArray(tr.y[0]) ? tr.y.map(r => r[0]) : tr.y; break; }
  }
  const firstTime = (timeArray && timeArray.length) ? timeArray[0] : 0;
  const firstWl = (wlArray && wlArray.length) ? wlArray[0] : null;
  const fakeClick = { x: firstTime, y: firstWl };
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

  if (spectrumMode === 'vs_wavelength') {
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
  } else {
    const N = totalWavelengthPoints;
    if (!N || N <= 0) throw new Error('No spectrum wavelength points available.');
    const eligible = getEligibleWavelengthIndices(currentSpectrumData.wavelengthData || []);
    const domain = eligible.length ? eligible : Array.from({length: N}, (_, i) => i);
    const target = Math.min(domain.length, VIDEO_MAX_FRAMES);
    const step = Math.max(1, Math.floor(domain.length / target));
    const indices = [];
    for (let i = 0; i < domain.length; i += step) indices.push(domain[i]);
    if (indices[indices.length - 1] !== domain[domain.length - 1]) indices.push(domain[domain.length - 1]);

    const frames = [];
    for (let idx of indices) {
      currentWavelengthIndex = idx;
      updateSpectrumPlot();
      await nextAnimationFrame();
      const dataUrl = await Plotly.toImage(spDiv, { format: 'png', width: VIDEO_WIDTH, height: VIDEO_HEIGHT, scale: 1 });
      frames.push(dataURLtoBlob(dataUrl));
    }
    return frames;
  }
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

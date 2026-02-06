/*
 * ============================================================================
 * main-upload.js — Upload Pipeline, Progress Bar & Metadata Display
 * ============================================================================
 *
 * Handles the entire MAST file upload workflow: form submission, async job
 * polling with progress updates, result fetching, and plot rendering.
 * Also includes sidebar positioning, metadata display, and progress-bar
 * DOM management.
 *
 * Requires:
 *   main-state.js   (__currentJobId, __progressTimer, activeBands,
 *                    plotOriginal)
 *   main-plots.js   (createPlot, renderBandButtons, setActiveBand)
 *
 * Sets:
 *   window.stampsDataLoaded  — read by tour-core.js to detect when plots
 *                              are ready
 * Reads:
 *   window.tourActive()      — defined in tour-core.js; suppresses
 *                              auto-scroll when the tour is active
 *
 * Load order:
 *   main-state.js → main-plots.js → main-spectrum.js
 *                → main-upload.js → main-export.js
 * ============================================================================
 */

// ---------------------------------------------------------------------------
// Data Requirements Sidebar Positioning
// ---------------------------------------------------------------------------

/**
 * Position the #dataRequirementsContainer absolutely to the left of the
 * main content column. Detaches the element from its original parent on
 * first call so it doesn't affect centering, then uses absolute document
 * coordinates so it doesn't follow scroll.
 */
function positionDataRequirements() {
  const container = document.getElementById('dataRequirementsContainer');
  const mainContent = document.querySelector('.max-w-4xl');
  if (!container || !mainContent) return;

  // Detach so it doesn't affect centering
  if (!container.dataset.detached) {
    document.body.appendChild(container);
    container.dataset.detached = '1';
  }

  const mainRect = mainContent.getBoundingClientRect();
  const containerWidth = container.offsetWidth || 256;

  const GAP = 48;
  const MIN_LEFT = 16;

  // Absolute position in document coordinates (does not follow scroll)
  const OFFSET_Y = 0;
  const docTop = Math.round(window.scrollY + mainRect.top + OFFSET_Y);

  container.style.position = 'absolute';
  container.style.setProperty('top', `${docTop}px`, 'important');
  container.style.setProperty('z-index', '1000', 'important');

  let left = Math.round(mainRect.left + window.scrollX - GAP - containerWidth);

  if (left >= MIN_LEFT) {
    container.style.setProperty('left', `${left}px`, 'important');
    container.style.setProperty('transform', 'none', 'important');
    container.style.setProperty('width', 'auto', 'important');
  } else {
    container.style.setProperty('left', '16px', 'important');
    container.style.setProperty('transform', 'none', 'important');
    container.style.setProperty('width', 'min(90vw, 256px)', 'important');
  }
}

/**
 * Initialize sidebar positioning once the DOM is ready and re-run on
 * window resize.
 */
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(positionDataRequirements, 0);
  window.addEventListener('resize', positionDataRequirements);
});

// ---------------------------------------------------------------------------
// Metadata Display
// ---------------------------------------------------------------------------

/**
 * Render dataset metadata (integrations, wavelength/time range,
 * instruments, filters, gratings) into the #metadataInfo container.
 *
 * @param {Object} metadata - Metadata object returned by the backend.
 * @param {number} metadata.total_integrations
 * @param {number} metadata.files_processed
 * @param {string} metadata.wavelength_range
 * @param {string} metadata.time_range
 * @param {string[]} [metadata.targets]
 * @param {number}   [metadata.plotted_integrations]
 * @param {string}   [metadata.user_ranges]
 * @param {string[]} [metadata.instruments]
 * @param {string[]} [metadata.filters]
 * @param {string[]} [metadata.gratings]
 */
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

// ---------------------------------------------------------------------------
// Progress Bar
// ---------------------------------------------------------------------------

/**
 * Create (or show) the progress bar UI beneath the upload button.
 *
 * @param {string} message - Initial status message (e.g. 'Queued...').
 */
function showProgress(message) {
  const wrap = document.getElementById('progressWrap');
  if (!wrap) return;
  const msg = wrap.querySelector('#progressMsg');
  if (msg) msg.textContent = message || 'Queued…';
  const inner = wrap.querySelector('#progressInner');
  if (inner) inner.style.width = '0%';
  const pct = wrap.querySelector('#progressPct');
  if (pct) pct.textContent = '0%';
  const stats = wrap.querySelector('#progressStats');
  if (stats) stats.textContent = '';
  wrap.classList.remove('hidden');
}

/**
 * Update the progress bar width, message, and stats text.
 *
 * @param {number}      pct       - Progress percentage (0–100).
 * @param {string|null} message   - Status message to display.
 * @param {string}      statsText - Additional stats line (throughput, ETA).
 */
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

/**
 * Hide the progress bar wrapper.
 */
function hideProgress() {
  const wrap = document.getElementById('progressWrap');
  if (wrap) wrap.classList.add('hidden');
}


// ---------------------------------------------------------------------------
// Upload Pipeline
// ---------------------------------------------------------------------------

/**
 * Main upload workflow. Orchestrates the entire data-processing pipeline:
 *
 *   1. Collect form data (file, colorscale, ranges, bands, options).
 *   2. POST to /start_mast to kick off the async backend job.
 *   3. Poll /progress/{jobId} every 200 ms, updating the progress bar.
 *   4. Once done, GET /results/{jobId} for plot JSON and metadata.
 *   5. Render the surface and heatmap plots.
 *   6. Signal to the tour that plots are loaded.
 *   7. Render band buttons and restore the default (full spectrum) view.
 *
 * @returns {Promise<void>}
 */
async function uploadMastDirectory() {
  const formData = new FormData();

  // --- 1. Collect form data ---

  // File selection
  if (window.isDemoDataSelected) {
    formData.append('use_demo', 'true');
  } else {
    if (! window.selectedFile) {
      alert('Please select a file or use the demo dataset.');
      return;
    }
    formData.append('mast_zip', window.selectedFile);
  }

  // Color scale
  const selectedColorscale = document.querySelector('.colorscale-option.selected');
  if (!selectedColorscale) { alert('Please select a color scale.'); return; }
  formData.append('colorscale', selectedColorscale.getAttribute('data-colorscale'));

  // Options
  const useInterpolation = document.getElementById('linearInterpolation').checked;
  formData.append('use_interpolation', useInterpolation);
  const numIntegrations = document.getElementById('numIntegrations').value;
  formData.append('num_integrations', numIntegrations || '0');

  // Range filters
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

  // Custom bands
  const customBands = Array.from(document.getElementById('customBands').children).map(band => {
    const inputs = band.querySelectorAll('input');
    return { name: inputs[0].value.trim(), start: parseFloat(inputs[1].value), end: parseFloat(inputs[2].value) };
  }).filter(b => b.name && ! isNaN(b.start) && !isNaN(b.end));
  formData.append('custom_bands', JSON.stringify(customBands));

  // Reset state for fresh processing
  activeBands = [];
  plotOriginal.surfacePlot = null;
  plotOriginal.heatmapPlot = null;
  window.__referenceSpectrum = null;

  window.__userRanges = {
    timeRangeMin:  timeRangeMin || null,
    timeRangeMax: timeRangeMax || null,
    wavelengthRangeMin: wavelengthRangeMin || null,
    wavelengthRangeMax: wavelengthRangeMax || null
  };

  const uploadBtn = document.getElementById('uploadMastBtn');
  const originalText = uploadBtn.textContent;
  uploadBtn.textContent = 'Processing...';
  uploadBtn.disabled = true;
  showProgress('Queued…');
  if (!window.tourActive || typeof window.tourActive !== 'function' || !window.tourActive()) {
    document.getElementById('progressWrap').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  try {
    // --- 2. Start the async backend job ---
    const startRes = await fetch('/start_mast', { method: 'POST', body:  formData });
    if (!startRes.ok) { const t = await startRes.text(); throw new Error(`HTTP ${startRes.status}: ${t}`); }
    const startData = await startRes.json();
    if (!startData.job_id) throw new Error('No job id returned');
    __currentJobId = startData.job_id;

    // --- 3. Poll progress ---
    await new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          const r = await fetch(`/progress/${__currentJobId}`);
          if (!r.ok) { const et = await r.text(); throw new Error(et || 'progress error'); }
          const p = await r.json();
          const stageMap = { queued:'Queued', scan:'Scanning files', read:'Reading data', regrid:'Regridding wavelengths', interpolate:'Interpolating gaps', finalize:'Finalizing', done:'Done', error:'Error' };
          const stageLabel = stageMap[p.stage] || (p.stage || '');
          const proc = typeof p.processed_integrations === 'number' ? p.processed_integrations : null;
          const tot = typeof p.total_integrations === 'number' ? p.total_integrations : null;
          const baseMsg = p.message || '';
          const isCacheHit = baseMsg.toLowerCase().includes('cache');
          let main = isCacheHit ? 'Loaded from cache' : (stageLabel ? `${stageLabel} — ${baseMsg}` : baseMsg);
          let stats = '';
          if (tot && proc != null) stats += `${proc}/${tot} integrations`;
          if (p.throughput && isFinite(p.throughput)) stats += (stats ? ' • ' : '') + `${p.throughput.toFixed(1)}/s`;
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
      __progressTimer = setInterval(poll, 200);
      poll();
    });

    // --- 4. Fetch results ---
    const res = await fetch(`/results/${__currentJobId}`);
    if (!res.ok) { const t = await res.text(); throw new Error(`HTTP ${res.status}: ${t}`); }
    const data = await res.json();
    if (data.error) { throw new Error(data.error); }

    if (data.metadata) displayMetadata(data.metadata);
    if (data.reference_spectrum) { try { window.__referenceSpectrum = JSON.parse(data.reference_spectrum); } catch(_) { window.__referenceSpectrum = null; } }

    // --- 5. Render plots ---
    const surfaceData = JSON.parse(data.surface_plot);
    const heatmapData = JSON.parse(data.heatmap_plot);

    /** Center a Plotly figure's margins and colorbar positioning. */
    function centerPlot(fig) {
      const m = { l: 120, r: 120, t:  60, b: 50 };
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
          if (! t.coloraxis && (t.type === 'surface' || t.type === 'heatmap')) {
            t.colorbar = { ...(t.colorbar || {}), x: 1, xanchor: 'left', xpad:  m.r - 40, y: 0.5, yanchor: 'middle', len:  0.85 };
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

    // --- 6. Signal tour that plots are loaded ---
    window.stampsDataLoaded = true;

    Plotly.Plots.resize(document.getElementById('surfacePlot'));
    Plotly.Plots.resize(document.getElementById('heatmapPlot'));

    // Only auto-scroll to plots if the tour is NOT active
    if (!window.tourActive || typeof window.tourActive !== 'function' || !window.tourActive()) {
        document.getElementById('plotsContainer').scrollIntoView({ behavior: 'smooth' });
    }

    // --- 7. Render band buttons ---
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

/*
 * ============================================================================
 * main-plots.js — Plot Creation, Band Management & Click Handlers
 * ============================================================================
 *
 * Plotly plot lifecycle (create, reset, resize), spectral band filtering
 * (collect, render, toggle, apply), color-scale picker, custom-band DOM
 * management, and plot-click-to-spectrum wiring.
 *
 * Requires:  main-state.js (activeBands, plotOriginal, spectrumMode,
 *            currentSpectrumData, currentWavelengthIndex, colorScales)
 *
 * Called by:  main-upload.js  (createPlot, renderBandButtons, setActiveBand)
 *            main-spectrum.js (computeLockedRibbonRange, getEligibleWavelengthIndices)
 *
 * Calls at runtime:
 *            main-spectrum.js (updateSpectrumPlot, showSpectrumAtTime)
 *
 * Load order:
 *   main-state.js → main-plots.js → main-spectrum.js
 *                → main-upload.js → main-export.js
 * ============================================================================
 */

// ---------------------------------------------------------------------------
// Band Collection & State
// ---------------------------------------------------------------------------

/**
 * Gather all custom spectral bands from the DOM input rows.
 *
 * Each band row has three inputs: name, start wavelength, end wavelength.
 * Invalid or incomplete rows are filtered out.
 *
 * @returns {Array<{id:string, name:string, start:number, end:number}>}
 */
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

/**
 * Update the visual state (ring highlight) of all band buttons across the
 * surface, heatmap, and spectrum button groups.
 */
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

/**
 * Render band-selection buttons into the surface, heatmap, and spectrum
 * button containers. Creates a "Full Spectrum" button plus one button per
 * valid custom band.
 */
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

/**
 * Toggle a band on or off in the active set, then re-filter all plots
 * and update the spectrum viewer.
 *
 * @param {Object|null} band - Band to toggle, or null to clear all bands
 *                             (show full spectrum).
 */
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

// ---------------------------------------------------------------------------
// Band Filtering on Surface / Heatmap
// ---------------------------------------------------------------------------

/**
 * Filter a surface or heatmap plot to show only wavelengths within the
 * selected bands. Out-of-band data is rendered as a transparent gray layer.
 *
 * If no bands are active, restores the original (unfiltered) plot data.
 *
 * @param {string} plotId - DOM id of the Plotly div ('surfacePlot' or 'heatmapPlot').
 * @param {Array}  bands  - Currently active bands (may be empty).
 */
function applyBandToPlot(plotId, bands) {
  const div = document.getElementById(plotId);
  if (!div || !div.data) return;
  if (!plotOriginal[plotId]) plotOriginal[plotId] = JSON.parse(JSON.stringify(div.data));

  // No bands → restore original
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

      // Split Z data into in-band and out-of-band matrices
      if (z.length === yvec.length) {
        // Rows indexed by wavelength
        for (let i = 0; i < z.length; i++) {
          const inBand = bands.some(b => yvec[i] >= b.start && yvec[i] <= b.end);
          const row = z[i];
          inZ[i] = inBand ? row.slice() : new Array(row.length).fill(NaN);
          outZ[i] = inBand ? new Array(row.length).fill(NaN) : row.slice();
        }
      } else if (z[0] && z[0].length === yvec.length) {
        // Columns indexed by wavelength
        for (let i = 0; i < z.length; i++) {
          inZ[i] = [];
          outZ[i] = [];
          for (let j = 0; j < z[i].length; j++) {
            const inBand = bands.some(b => yvec[j] >= b.start && yvec[j] <= b.end);
            if (inBand) {
              inZ[i][j] = z[i][j];
              outZ[i][j] = NaN;
            } else {
              inZ[i][j] = NaN;
              outZ[i][j] = z[i][j];
            }
          }
        }
      }
      const base = {};
      for (const k in trace) if (k !== 'z') base[k] = trace[k];
      if (isHeatmap) {
        // Heatmap ghost: light grey at full opacity so it looks like faded data
        newData.push({ ...base, z: outZ, showscale: false, colorscale: [[0,'#2a2a2e'],[1,'#3a3a40']], hoverinfo: 'skip', hoverongaps: false });
        newData.push({ ...base, z: inZ, hoverongaps: false });
      } else {
        // Surface ghost: white at low opacity
        newData.push({ ...base, z: outZ, showscale: false, opacity: 0.08, colorscale: [[0,'#fff'],[1,'#fff']], hoverongaps: false });
        newData.push({ ...base, z: inZ, hoverongaps: false });
      }
    } else {
      newData.push(trace);
    }
  }
  Plotly.react(div, newData, div.layout);
  setupPlotClickHandler(div);
}

// ---------------------------------------------------------------------------
// Plot Creation & Reset
// ---------------------------------------------------------------------------

/**
 * Create a Plotly plot with standardized config, aspect ratio, tick
 * formatting, and colorbar positioning.
 *
 * Also caches the original data in `plotOriginal` for band filtering,
 * stores the initial 3-D camera for reset, and attaches the click handler.
 *
 * @param {string} plotId  - DOM id of the target div.
 * @param {Array}  data    - Plotly trace data array.
 * @param {Object} layout  - Plotly layout object.
 * @param {Object} config  - Plotly config object (will be enhanced).
 * @returns {Promise} Resolves when the plot is fully rendered.
 */
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

    plotOriginal[plotId] = JSON.parse(JSON.stringify(data));

    // Remember initial 3-D camera for reset
    if (plotId === 'surfacePlot' && div.layout && div.layout.scene) {
      const cam = div.layout.scene.camera || { up:{x:0,y:0,z:1}, center:{x:0,y:0,z:0}, eye:{x:1.25,y:1.25,z:1.25} };
      div._initialCamera = JSON.parse(JSON.stringify(cam));
    }

    // Enable click-to-slice on the main plots
    if (plotId === 'surfacePlot' || plotId === 'heatmapPlot') {
      setupPlotClickHandler(div);
    }

    // Push modebar to the right
    const mbc = div.querySelector('.modebar-container');
    if (mbc) { mbc.style.left = ''; mbc.style.right = '0px'; }

    // --- Detect variability vs flux for tick formatting ---
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

    // --- Set a stable height ---
    const desiredHeight = plotId === 'spectrumPlot' ? 480 : 640;
    div.style.aspectRatio = '';
    div.style.height = desiredHeight + 'px';
    Plotly.relayout(div, { height: desiredHeight });

    // --- Heatmap: auto-range the Y axis to data bounds ---
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

/**
 * Reset a plot's view to its initial state.
 * For the surface plot, restores the original 3-D camera angle.
 * For the heatmap, resets both axes to autorange.
 *
 * @param {string} plotId - 'surfacePlot' or 'heatmapPlot'.
 */
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

// ---------------------------------------------------------------------------
// Spectrum Plot Helpers (bands overlay, error bars, ribbon range)
// ---------------------------------------------------------------------------

/**
 * Overlay translucent yellow rectangles on the spectrum plot for each
 * custom band, so the user can see band boundaries visually.
 */
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

/**
 * Handle the error-bars checkbox toggle. Recomputes the locked ribbon
 * range if errors are being shown, then re-renders the spectrum.
 */
function onToggleErrorBars() {
  const teb = document.getElementById('toggleErrorBars');
  if (!currentSpectrumData) { updateSpectrumPlot(); return; }
  if (teb && teb.checked) {
    if (!currentSpectrumData.lockedRibbonRange) currentSpectrumData.lockedRibbonRange = computeLockedRibbonRange(currentSpectrumData, null);
  }
  updateSpectrumPlot();
}

/**
 * Calculate the Y-axis min/max that encompasses the full error-bar
 * envelope across all time points, so the Y-range stays stable during
 * animation.
 *
 * Handles two cases:
 *   1. Band-averaged mode: computes averaged flux ± propagated error per band.
 *   2. Full spectrum mode: scans every (wavelength, time) cell.
 *
 * @param {Object}     spec  - The currentSpectrumData object.
 * @param {Array|null} bands - Unused (kept for API compatibility).
 * @returns {[number, number]|null} [yMin, yMax] with 3% padding, or null.
 */
function computeLockedRibbonRange(spec, bands) {
  const wl = spec.wavelengthData || [];
  const Z = spec.fluxData || [];
  const E = spec.errorData || [];
  const ref = spec.referenceSpectrum || null;
  if (!Z.length || !E.length) return null;

  // --- Case 1: Band-averaged mode ---
  if (spec.bandAveraged && activeBands && activeBands.length >= 1) {
    let minV = Infinity, maxV = -Infinity;
    const timeArray = spec.timeData || [];

    for (let bi = 0; bi < activeBands.length; bi++) {
      const b = activeBands[bi];

      for (let j = 0; j < timeArray.length; j++) {
        let sum = 0, cnt = 0, esum = 0;

        for (let i = 0; i < wl.length; i++) {
          const w = wl[i];
          if (w >= b.start && w <= b.end) {
            const v = Z[i] && Z[i][j];
            const e = E[i] && E[i][j];
            if (v == null || e == null || isNaN(v) || isNaN(e)) continue;

            sum += v;
            cnt++;
            esum += e * e;
          }
        }

        if (cnt > 0) {
          const avgFlux = sum / cnt;
          const avgErr = Math.sqrt(esum / cnt) / Math.sqrt(cnt);
          const up = avgFlux + avgErr;
          const lo = avgFlux - avgErr;
          if (isFinite(up) && up > maxV) maxV = up;
          if (isFinite(lo) && lo < minV) minV = lo;
        }
      }
    }

    if (! isFinite(minV) || !isFinite(maxV)) return null;
    const pad = (maxV - minV) * 0.03 || 1e-6;
    return [minV - pad, maxV + pad];
  }

  // --- Case 2: Full spectrum mode ---
  let minV = Infinity, maxV = -Infinity;
  for (let i = 0; i < wl.length; i++) {
    for (let j = 0; j < spec.timeData.length; j++) {
      const v = Z[i] && Z[i][j];
      const e = E[i] && E[i][j];
      if (v == null || e == null || isNaN(v) || isNaN(e)) continue;
      const s = e;
      const up = v + s;
      const lo = v - s;
      if (isFinite(up) && up > maxV) maxV = up;
      if (isFinite(lo) && lo < minV) minV = lo;
    }
  }
  if (! isFinite(minV) || !isFinite(maxV)) return null;
  const pad = (maxV - minV) * 0.03 || 1e-6;
  return [minV - pad, maxV + pad];
}

// ---------------------------------------------------------------------------
// Wavelength Index Filtering & Spectrum Mode Toggle
// ---------------------------------------------------------------------------

/**
 * Return the indices of wavelengths that fall within any active band.
 * If no bands are active, returns all indices.
 *
 * @param {number[]} wavelengths - The wavelength array.
 * @returns {number[]} Array of valid indices.
 */
function getEligibleWavelengthIndices(wavelengths) {
  if (!activeBands || activeBands.length === 0) return wavelengths.map((_, i) => i);
  const inds = [];
  for (let i = 0; i < wavelengths.length; i++) {
    const w = wavelengths[i];
    if (activeBands.some(b => w >= b.start && w <= b.end)) inds.push(i);
  }
  return inds;
}

/**
 * Switch the spectrum X-axis between wavelength and time.
 * Updates the toggle button text and re-renders the spectrum.
 */
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

// ---------------------------------------------------------------------------
// Color Scale Picker
// ---------------------------------------------------------------------------

/**
 * Create DOM elements for each color-scale option and insert them into
 * the #colorscaleSelector container. Selects the first option by default.
 */
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

/**
 * Highlight the selected color-scale option and deselect all others.
 *
 * @param {HTMLElement} selectedOption - The clicked option element.
 */
function selectColorScale(selectedOption) {
  document.querySelectorAll('.colorscale-option').forEach(option => {
    option.classList.remove('selected');
  });
  selectedOption.classList.add('selected');
}

// ---------------------------------------------------------------------------
// Custom Band DOM Management
// ---------------------------------------------------------------------------

/**
 * Add a new custom-band input row to the #customBands container.
 * Each row has name, start wavelength, and end wavelength fields plus
 * a "Remove" button.
 *
 * @param {string}       name  - Pre-filled band name (default '').
 * @param {string|number} start - Pre-filled start wavelength (default '').
 * @param {string|number} end   - Pre-filled end wavelength (default '').
 */
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

// ---------------------------------------------------------------------------
// Plot Click Handler
// ---------------------------------------------------------------------------

/**
 * Attach a Plotly click listener to a plot div. When the user clicks on
 * the surface or heatmap (and the corresponding checkbox is enabled),
 * extracts a spectrum at the clicked point.
 *
 * @param {HTMLElement} plotDiv - The Plotly div element.
 */
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

// main-fitting.js - Model Fitting UI and Overlay Rendering

const CHUNK_COLORS = [
    '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6',
    '#EC4899', '#14B8A6', '#F97316', '#6366F1',
];

let _preFitDisplayMode = null;

function _switchDisplayMode(mode) {
  if (!currentSpectrumData) return;

  const sd = currentSpectrumData;
  const rawFlux = sd.rawFluxData;
  const rawErr  = sd.rawErrorData;
  const ref     = sd.referenceSpectrum;

  if (mode === 'variability') {
    // Need rawFluxData + referenceSpectrum to compute variability
    if (!rawFlux || !ref) return;

    for (let i = 0; i < rawFlux.length; i++) {
      const r = ref[i];
      if (!r || !isFinite(r) || r === 0) {
        // Can't normalise — copy raw values as-is
        for (let j = 0; j < rawFlux[i].length; j++) {
          sd.fluxData[i][j] = rawFlux[i][j];
          if (rawErr && rawErr[i]) sd.errorData[i][j] = rawErr[i][j];
        }
      } else {
        for (let j = 0; j < rawFlux[i].length; j++) {
          sd.fluxData[i][j] = (rawFlux[i][j] / r - 1) * 100;
          if (rawErr && rawErr[i]) sd.errorData[i][j] = (rawErr[i][j] / r) * 100;
        }
      }
    }
  } else {
    // mode === 'flux': copy raw values straight through
    if (!rawFlux) return;

    for (let i = 0; i < rawFlux.length; i++) {
      for (let j = 0; j < rawFlux[i].length; j++) {
        sd.fluxData[i][j] = rawFlux[i][j];
        if (rawErr && rawErr[i]) sd.errorData[i][j] = rawErr[i][j];
      }
    }
  }

  // Recompute globalMin / globalMax from the new fluxData
  let gMin = Infinity, gMax = -Infinity;
  for (let i = 0; i < sd.fluxData.length; i++) {
    const row = sd.fluxData[i];
    for (let j = 0; j < row.length; j++) {
      const v = row[j];
      if (v !== null && !isNaN(v)) {
        if (v < gMin) gMin = v;
        if (v > gMax) gMax = v;
      }
    }
  }
  sd.globalMin = gMin;
  sd.globalMax = gMax;

  // Recompute locked ribbon range
  sd.lockedRibbonRange = computeLockedRibbonRange(sd, null);

  // Update metadata + radio button
  sd.zAxisDisplay = mode;
  const radio = document.querySelector(`input[name="zAxisDisplay"][value="${mode}"]`);
  if (radio) radio.checked = true;
}

/**
 * Extract the current 1D light curve (time series) from spectrum data.
 * Handles both single-wavelength and band-averaged modes.
 * Always uses raw flux data for fitting when available, so results
 * are independent of the display mode (variability % vs raw flux).
 * @returns {{time: number[], flux: number[], error: number[]|null}|null}
 */
function _extractCurrentLightCurve() {
  if (!currentSpectrumData) return null;

  // Use raw (physical flux) data for fitting; fall back to display data
  const timeArray = currentSpectrumData.rawTime || currentSpectrumData.timeData;
  const fluxData = currentSpectrumData.rawFluxData || currentSpectrumData.fluxData;
  const errData = currentSpectrumData.rawErrorData || currentSpectrumData.errorData;
  const wavelengths = currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData;

  if (currentSpectrumData.bandAveraged && activeBands && activeBands.length >= 1) {
    // Band-averaged: compute mean flux across bands at each time step
    const flux = [];
    const error = [];
    for (let j = 0; j < timeArray.length; j++) {
      let sum = 0, cnt = 0, esum = 0, ecnt = 0;
      for (let i = 0; i < wavelengths.length; i++) {
        const inBand = activeBands.some(b => wavelengths[i] >= b.start && wavelengths[i] <= b.end);
        if (!inBand) continue;
        const v = (fluxData[i] && fluxData[i][j] !== undefined) ? fluxData[i][j] : NaN;
        if (!isFinite(v)) continue;
        sum += v;
        cnt++;
        if (errData && errData[i] && errData[i][j] !== undefined) {
          const e = errData[i][j];
          if (isFinite(e)) { esum += e * e; ecnt++; }
        }
      }
      flux.push(cnt ? sum / cnt : NaN);
      error.push(ecnt > 0 ? Math.sqrt(esum / ecnt) / Math.sqrt(ecnt) : NaN);
    }
    return { time: Array.from(timeArray), flux, error };
  } else {
    // Single wavelength
    const wlIdx = Math.max(0, Math.min(currentWavelengthIndex, wavelengths.length - 1));
    const flux = [];
    const error = [];
    for (let j = 0; j < timeArray.length; j++) {
      flux.push((fluxData[wlIdx] && fluxData[wlIdx][j] !== undefined) ? fluxData[wlIdx][j] : NaN);
      error.push((errData && errData[wlIdx] && errData[wlIdx][j] !== undefined) ? errData[wlIdx][j] : NaN);
    }
    return { time: Array.from(timeArray), flux, error };
  }
}

/**
 * Extract the current 1D spectrum (flux vs wavelength) at the current time index.
 * Always uses raw flux data for model fitting when available, so results
 * are independent of the display mode (variability % vs raw flux).
 * @returns {{wavelengths: number[], flux: number[], error: number[]|null}|null}
 */
function _extractCurrentSpectrum() {
  if (!currentSpectrumData) return null;

  // Use raw (physical flux) data for fitting; fall back to display data
  const wavelengths = currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData;
  const fluxData = currentSpectrumData.rawFluxData || currentSpectrumData.fluxData;
  const errData = currentSpectrumData.rawErrorData || currentSpectrumData.errorData;

  const flux = [];
  const error = [];
  for (let i = 0; i < wavelengths.length; i++) {
    flux.push((fluxData[i] && fluxData[i][currentTimeIndex] !== undefined) ? fluxData[i][currentTimeIndex] : NaN);
    error.push((errData && errData[i] && errData[i][currentTimeIndex] !== undefined) ? errData[i][currentTimeIndex] : NaN);
  }
  return { wavelengths: Array.from(wavelengths), flux, error };
}

// Chunk Range UI

/**
 * Build chunk wavelength range input rows for N chunks.
 * @param {number} n - Number of chunks
 */
function buildChunkRangeInputs(n) {
  const container = document.getElementById('chunkRangesContainer');
  if (!container) return;

  const wavelengths = currentSpectrumData
    ? (currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData)
    : null;
  if (!wavelengths || wavelengths.length === 0) {
    container.style.display = 'none';
    return;
  }

  const wlMin = wavelengths[0];
  const wlMax = wavelengths[wavelengths.length - 1];
  const step = (wlMax - wlMin) / n;

  let html = '';
  for (let i = 0; i < n; i++) {
    const color = CHUNK_COLORS[i % CHUNK_COLORS.length];
    const lo = (wlMin + step * i).toFixed(4);
    const hi = (wlMin + step * (i + 1)).toFixed(4);
    html += `<div class="flex items-center gap-2 text-sm" data-chunk="${i}">
      <span style="color: ${color}; font-size: 1.2em;">&bull;</span>
      <span style="color: ${color}; font-weight: 500; min-width: 4.5rem;">Chunk ${i + 1}</span>
      <input type="number" class="stamp-input chunk-wl-min" step="any" value="${lo}"
             style="padding: 2px 6px; width: 6rem; color: ${color}; border-color: ${color}40;">
      <span style="color: var(--text-dim);">&ndash;</span>
      <input type="number" class="stamp-input chunk-wl-max" step="any" value="${hi}"
             style="padding: 2px 6px; width: 6rem; color: ${color}; border-color: ${color}40;">
      <span style="color: var(--text-dim);">&mu;m</span>
    </div>`;
  }
  container.innerHTML = html;
  container.style.display = '';
}

/**
 * Read chunk definitions from the UI.
 * @returns {Array<{min:number, max:number, color:string}>|null} null if single-fit
 */
function getChunkDefinitions() {
  const input = document.getElementById('chunkCountInput');
  if (!input) return null;
  const n = parseInt(input.value);
  if (!n || n <= 1) return null;

  const mins = document.querySelectorAll('.chunk-wl-min');
  const maxs = document.querySelectorAll('.chunk-wl-max');
  if (mins.length === 0) return null;

  const chunks = [];
  for (let i = 0; i < mins.length; i++) {
    chunks.push({
      min: parseFloat(mins[i].value),
      max: parseFloat(maxs[i].value),
      color: CHUNK_COLORS[i % CHUNK_COLORS.length],
    });
  }
  return chunks;
}

// Sinusoidal Fitting

/**
 * Compute a Lomb-Scargle periodogram to detect the dominant period.
 */
async function requestLombScargle() {
  if (spectrumMode !== 'vs_time') {
    alert('Switch to vs_time mode to compute a periodogram.');
    return;
  }

  const curve = _extractCurrentLightCurve();
  if (!curve) { alert('No spectrum data loaded.'); return; }

  const statusEl = document.getElementById('fittingJobStatus');
  if (statusEl) statusEl.textContent = 'Computing periodogram...';

  try {
    const resp = await fetch('/fit/lombscargle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ time: curve.time, flux: curve.flux, error: curve.error }),
    });
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    const result = await resp.json();

    if (!result.success) {
      alert('Periodogram failed: ' + (result.error || 'Unknown error'));
      if (statusEl) statusEl.textContent = '';
      return;
    }

    // Auto-fill period guess
    const periodEl = document.getElementById('fitPeriodGuess');
    if (periodEl) periodEl.value = result.best_period.toFixed(4);

    // Show result text
    const resultEl = document.getElementById('periodogramResult');
    if (resultEl) {
      resultEl.textContent = 'Detected period: ' + result.best_period.toFixed(4) + ' hr (power: ' + result.best_power.toFixed(4) + ')';
      resultEl.classList.remove('hidden');
    }

    // Plot periodogram
    const plotEl = document.getElementById('periodogramPlot');
    if (plotEl && result.periods && result.powers) {
      plotEl.classList.remove('hidden');
      Plotly.newPlot(plotEl, [
        {
          x: result.periods,
          y: result.powers,
          type: 'scatter',
          mode: 'lines',
          line: { color: '#F59E0B', width: 1.5 },
          name: 'Power',
        },
        {
          x: [result.best_period, result.best_period],
          y: [0, result.best_power],
          type: 'scatter',
          mode: 'lines',
          line: { color: '#10b981', width: 2, dash: 'dash' },
          name: 'Best: ' + result.best_period.toFixed(4) + ' hr',
        },
      ], {
        template: 'plotly_dark',
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e5e7eb' },
        xaxis: { title: 'Period (hours)', type: 'log' },
        yaxis: { title: 'Lomb-Scargle Power' },
        margin: { t: 10, b: 40, l: 50, r: 10 },
        showlegend: true,
        legend: { x: 0.7, y: 0.95, font: { size: 10 } },
      }, { responsive: true, displayModeBar: false });
    }

    if (statusEl) statusEl.textContent = '';
  } catch (e) {
    alert('Periodogram request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

/**
 * Request a sinusoidal fit for the current light curve and overlay the result.
 */
async function requestSineFit() {
  if (spectrumMode !== 'vs_time') {
    alert('Switch to vs_time mode to fit a sinusoidal model.');
    return;
  }

  if (currentSpectrumData && currentSpectrumData.zAxisDisplay !== 'variability') {
    _preFitDisplayMode = currentSpectrumData.zAxisDisplay;
    _switchDisplayMode('variability');
  }

  const curve = _extractCurrentLightCurve();
  if (!curve) { alert('No spectrum data loaded.'); return; }

  const nSinesEl = document.getElementById('fitNSines');
  const periodEl = document.getElementById('fitPeriodGuess');
  const n_sines = nSinesEl ? parseInt(nSinesEl.value) || 1 : 1;
  const period_guess = periodEl && periodEl.value ? parseFloat(periodEl.value) : null;

  const statusEl = document.getElementById('fittingJobStatus');
  if (statusEl) statusEl.textContent = 'Fitting...';

  try {
    const body = {
      time: curve.time,
      flux: curve.flux,
      error: curve.error,
      n_sines: n_sines,
      period_guess: period_guess,
    };

    const resp = await fetch('/fit/sinusoidal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    const result = await resp.json();

    if (!result.success) {
      alert('Sine fit failed: ' + (result.error || 'Unknown error'));
      if (statusEl) statusEl.textContent = '';
      return;
    }

    lastSineFitResult = result;
    showSineFitOverlay = true;
    updateFitParameterReadout('sine', result);
    updateSpectrumPlot();
    window.dispatchEvent(new CustomEvent('sineFitComplete'));
    if (statusEl) statusEl.textContent = '';
  } catch (e) {
    alert('Sine fit request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

/**
 * Clear the sinusoidal fit overlay and readout.
 */
function clearSineFit() {
  lastSineFitResult = null;
  showSineFitOverlay = false;
  if (_preFitDisplayMode) {
    _switchDisplayMode(_preFitDisplayMode);
    _preFitDisplayMode = null;
  }
  updateSpectrumPlot();
  const readout = document.getElementById('fittingParamsReadout');
  if (readout) readout.innerHTML = '';
}

// Grid Fitting

/**
 * Request a spectral grid fit for the current spectrum and overlay the result.
 */
async function requestGridFit() {
  if (spectrumMode !== 'vs_wavelength') {
    alert('Switch to vs_wavelength mode to fit against a model grid.');
    return;
  }

  if (currentSpectrumData && currentSpectrumData.zAxisDisplay !== 'flux') {
    _preFitDisplayMode = currentSpectrumData.zAxisDisplay;
    _switchDisplayMode('flux');
  }

  const selectEl = document.getElementById('fitGridSelect');
  if (!selectEl || !selectEl.value) {
    alert('Select a model grid first.');
    return;
  }

  const spectrum = _extractCurrentSpectrum();
  if (!spectrum) { alert('No spectrum data loaded.'); return; }

  const statusEl = document.getElementById('fittingJobStatus');
  if (statusEl) statusEl.textContent = 'Fitting against grid...';

  const chunks = getChunkDefinitions();

  try {
    if (chunks) {
      // ── Chunked fit path ──
      const body = {
        wavelengths: spectrum.wavelengths,
        flux: spectrum.flux,
        error: spectrum.error,
        grid_name: selectEl.value,
        chunks: chunks.map(c => ({ min: c.min, max: c.max })),
      };

      const resp = await fetch('/fit/spectrum_chunked', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
      const result = await resp.json();

      if (!result.success) {
        alert('Chunked grid fit failed: ' + (result.error || 'Unknown error'));
        if (statusEl) statusEl.textContent = '';
        return;
      }

      // Attach color and label to each chunk result
      result.chunk_results.forEach((cr, i) => {
        cr._color = chunks[i].color;
        cr._label = `Chunk ${i + 1}`;
      });

      lastChunkedFitResult = result;
      lastGridFitResult = null;
      showGridFitOverlay = true;
      updateFitParameterReadout('grid_chunked', result);
      updateSpectrumPlot();
      renderChunkedResidualPlot(result);
      if (statusEl) statusEl.textContent = '';
      window.dispatchEvent(new CustomEvent('gridFitComplete'));
    } else {
      // ── Single fit path (unchanged) ──
      const body = {
        wavelengths: spectrum.wavelengths,
        flux: spectrum.flux,
        error: spectrum.error,
        grid_name: selectEl.value,
      };

      const resp = await fetch('/fit/spectrum', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
      const result = await resp.json();

      if (!result.success) {
        alert('Grid fit failed: ' + (result.error || 'Unknown error'));
        if (statusEl) statusEl.textContent = '';
        return;
      }

      lastGridFitResult = result;
      lastChunkedFitResult = null;
      showGridFitOverlay = true;
      updateFitParameterReadout('grid', result);
      updateSpectrumPlot();
      renderResidualPlot(
        result.best_fit_wavelengths,
        result.residuals,
        currentSpectrumData ? currentSpectrumData.zAxisDisplay : null,
        currentSpectrumData ? currentSpectrumData.referenceSpectrum : null,
        currentSpectrumData ? (currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData) : null
      );
      if (statusEl) statusEl.textContent = '';
      window.dispatchEvent(new CustomEvent('gridFitComplete'));
    }
  } catch (e) {
    alert('Grid fit request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

/**
 * Clear the grid fit overlay, residual plot, and readout.
 */
function clearGridFit() {
  lastGridFitResult = null;
  lastChunkedFitResult = null;
  showGridFitOverlay = false;
  if (_preFitDisplayMode) {
    _switchDisplayMode(_preFitDisplayMode);
    _preFitDisplayMode = null;
  }
  updateSpectrumPlot();
  const residualContainer = document.getElementById('residualPlotContainer');
  if (residualContainer) residualContainer.classList.add('hidden');
  const readout = document.getElementById('fittingParamsReadout');
  if (readout) readout.innerHTML = '';
}

// Async Sweep Jobs

/**
 * Poll a fitting job until complete, then invoke callback with results.
 */
function _pollFitJob(jobId, statusEl, onDone) {
  const poll = setInterval(async () => {
    try {
      const resp = await fetch(`/progress/${jobId}`);
      if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
      const prog = await resp.json();

      if (statusEl) statusEl.textContent = prog.message || 'Working...';

      if (prog.status === 'done') {
        clearInterval(poll);
        const resResp = await fetch(`/results/${jobId}`);
        if (!resResp.ok) throw new Error(await resResp.text().catch(() => resResp.statusText) || `Server error (${resResp.status})`);
        const result = await resResp.json();
        if (statusEl) statusEl.textContent = '';
        onDone(result);
      } else if (prog.status === 'error') {
        clearInterval(poll);
        if (statusEl) statusEl.textContent = '';
        alert('Sweep job failed: ' + (prog.message || 'Unknown error'));
      }
    } catch (e) {
      clearInterval(poll);
      if (statusEl) statusEl.textContent = '';
      alert('Polling error: ' + e.message);
    }
  }, 1000);
}

/**
 * Request amplitude vs wavelength sweep (async).
 */
async function requestSineSweep() {
  if (!currentSpectrumData) { alert('No spectrum data loaded.'); return; }

  const nSinesEl = document.getElementById('fitNSines');
  const periodEl = document.getElementById('fitPeriodGuess');
  const n_sines = nSinesEl ? parseInt(nSinesEl.value) || 1 : 1;
  const period_guess = periodEl && periodEl.value ? parseFloat(periodEl.value) : null;

  const statusEl = document.getElementById('fittingJobStatus');
  if (statusEl) statusEl.textContent = 'Starting amplitude sweep...';

  try {
    const body = {
      wavelengths: Array.from(currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData),
      time: Array.from(currentSpectrumData.rawTime || currentSpectrumData.timeData),
      flux_2d: Array.from(currentSpectrumData.rawFluxData || currentSpectrumData.fluxData).map(row => Array.from(row)),
      error_2d: (currentSpectrumData.rawErrorData || currentSpectrumData.errorData)
        ? Array.from(currentSpectrumData.rawErrorData || currentSpectrumData.errorData).map(row => Array.from(row))
        : null,
      n_sines: n_sines,
      period_guess: period_guess,
    };

    const resp = await fetch('/fit/sinusoidal_all_wavelengths', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    const data = await resp.json();

    if (!data.job_id) {
      alert('Failed to start sweep: ' + (data.error || 'Unknown error'));
      if (statusEl) statusEl.textContent = '';
      return;
    }

    sineSweepJobId = data.job_id;
    _pollFitJob(data.job_id, statusEl, (result) => {
      sineSweepJobId = null;
      if (result.success) {
        renderAmplitudeVsWavelengthPlot(result);
        window._sineSweepDone = true;
        window.dispatchEvent(new CustomEvent('sineSweepComplete'));
      } else {
        alert('Sweep failed: ' + (result.error || 'Unknown error'));
      }
    });
  } catch (e) {
    alert('Sweep request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

/**
 * Request parameter time series sweep (async).
 */
async function requestGridSweep() {
  if (!currentSpectrumData) { alert('No spectrum data loaded.'); return; }

  const selectEl = document.getElementById('fitGridSelect');
  if (!selectEl || !selectEl.value) {
    alert('Select a model grid first.');
    return;
  }

  const statusEl = document.getElementById('fittingJobStatus');
  if (statusEl) statusEl.textContent = 'Starting parameter sweep...';

  try {
    const body = {
      wavelengths: Array.from(currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData),
      time: Array.from(currentSpectrumData.rawTime || currentSpectrumData.timeData),
      flux_2d: Array.from(currentSpectrumData.rawFluxData || currentSpectrumData.fluxData).map(row => Array.from(row)),
      error_2d: (currentSpectrumData.rawErrorData || currentSpectrumData.errorData)
        ? Array.from(currentSpectrumData.rawErrorData || currentSpectrumData.errorData).map(row => Array.from(row))
        : null,
      grid_name: selectEl.value,
    };

    const resp = await fetch('/fit/spectrum_all_timesteps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    const data = await resp.json();

    if (!data.job_id) {
      alert('Failed to start sweep: ' + (data.error || 'Unknown error'));
      if (statusEl) statusEl.textContent = '';
      return;
    }

    gridSweepJobId = data.job_id;
    _pollFitJob(data.job_id, statusEl, (result) => {
      gridSweepJobId = null;
      if (result.success) {
        renderParameterTimeSeriesPlot(result);
        window.dispatchEvent(new CustomEvent('gridSweepComplete'));
      } else {
        alert('Sweep failed: ' + (result.error || 'Unknown error'));
      }
    });
  } catch (e) {
    alert('Sweep request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

// Transit Fitting

/**
 * Read all transit UI inputs and validate.
 * @returns {Object|null} Transit params or null if invalid.
 */
function _getTransitParams() {
  const periodEl = document.getElementById('transitPeriod');
  if (!periodEl || !periodEl.value) {
    alert('Period is required for transit fitting.');
    return null;
  }

  const period = parseFloat(periodEl.value);
  if (!isFinite(period) || period <= 0) {
    alert('Period must be a positive number.');
    return null;
  }

  return {
    period: period,
    rp_rs_guess: parseFloat(document.getElementById('transitRpRs').value) || 0.1,
    a_rs: parseFloat(document.getElementById('transitARs').value) || 15.0,
    inc: parseFloat(document.getElementById('transitInc').value) || 90.0,
    ecc: parseFloat(document.getElementById('transitEcc').value) || 0.0,
    omega: parseFloat(document.getElementById('transitOmega').value) || 90.0,
    limb_dark: document.getElementById('transitLimbDark').value || 'quadratic',
    u: [
      parseFloat(document.getElementById('transitU1').value) || 0.1,
      parseFloat(document.getElementById('transitU2').value) || 0.1,
    ],
    fit_limb_dark: !!document.getElementById('transitFitLD').checked,
  };
}

/**
 * Request a transit fit for the current light curve and overlay the result.
 */
async function requestTransitFit() {
  if (spectrumMode !== 'vs_time') {
    alert('Switch to vs_time mode to fit a transit model.');
    return;
  }

  const params = _getTransitParams();
  if (!params) return;

  const curve = _extractCurrentLightCurve();
  if (!curve) { alert('No spectrum data loaded.'); return; }

  // Normalize flux to ~1.0 (batman expects normalized flux)
  const fluxArr = curve.flux.filter(v => isFinite(v));
  if (fluxArr.length === 0) { alert('No valid flux data.'); return; }

  // Sort a copy to find the median
  const sorted = fluxArr.slice().sort((a, b) => a - b);
  const normMedian = sorted[Math.floor(sorted.length / 2)];
  if (!normMedian || normMedian === 0) { alert('Cannot normalize flux (median is zero).'); return; }

  const normFlux = curve.flux.map(v => isFinite(v) ? v / normMedian : NaN);
  const normErr = curve.error ? curve.error.map(v => isFinite(v) ? v / normMedian : NaN) : null;

  const statusEl = document.getElementById('fittingJobStatus');
  if (statusEl) statusEl.textContent = 'Fitting transit...';

  try {
    const body = {
      time: curve.time,
      flux: normFlux,
      error: normErr,
      period: params.period,
      rp_rs_guess: params.rp_rs_guess,
      a_rs: params.a_rs,
      inc: params.inc,
      ecc: params.ecc,
      omega: params.omega,
      limb_dark: params.limb_dark,
      u: params.u,
      fit_limb_dark: params.fit_limb_dark,
    };

    const resp = await fetch('/fit/transit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    const result = await resp.json();

    if (!result.success) {
      alert('Transit fit failed: ' + (result.error || 'Unknown error'));
      if (statusEl) statusEl.textContent = '';
      return;
    }

    // Stash normalization median for de-normalizing the overlay
    result._normMedian = normMedian;

    lastTransitFitResult = result;
    showTransitFitOverlay = true;
    updateFitParameterReadout('transit', result);
    updateSpectrumPlot();
    window.dispatchEvent(new CustomEvent('transitFitComplete'));
    if (statusEl) statusEl.textContent = '';
  } catch (e) {
    alert('Transit fit request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

/**
 * Clear the transit fit overlay and readout.
 */
function clearTransitFit() {
  lastTransitFitResult = null;
  showTransitFitOverlay = false;
  updateSpectrumPlot();
  const readout = document.getElementById('fittingParamsReadout');
  if (readout) readout.innerHTML = '';
}

/**
 * Request transit depth vs wavelength sweep (async).
 */
async function requestTransitSweep() {
  if (!currentSpectrumData) { alert('No spectrum data loaded.'); return; }

  const params = _getTransitParams();
  if (!params) return;

  const statusEl = document.getElementById('fittingJobStatus');
  if (statusEl) statusEl.textContent = 'Starting transmission spectrum...';

  try {
    const rawFlux = currentSpectrumData.rawFluxData || currentSpectrumData.fluxData;
    const rawErr = currentSpectrumData.rawErrorData || currentSpectrumData.errorData;
    const ref = currentSpectrumData.referenceSpectrum;

    // Normalize each wavelength row by its reference spectrum value (or row median)
    const normFlux2d = [];
    const normErr2d = [];
    for (let i = 0; i < rawFlux.length; i++) {
      const row = rawFlux[i];
      // Use reference spectrum value if available, otherwise row median
      let normVal;
      if (ref && ref[i] && isFinite(ref[i]) && ref[i] !== 0) {
        normVal = ref[i];
      } else {
        const validRow = row.filter(v => isFinite(v));
        const s = validRow.slice().sort((a, b) => a - b);
        normVal = s.length > 0 ? s[Math.floor(s.length / 2)] : 1;
      }
      normFlux2d.push(row.map(v => isFinite(v) ? v / normVal : NaN));
      if (rawErr && rawErr[i]) {
        normErr2d.push(rawErr[i].map(v => isFinite(v) ? v / normVal : NaN));
      } else {
        normErr2d.push(row.map(() => NaN));
      }
    }

    const body = {
      wavelengths: Array.from(currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData),
      time: Array.from(currentSpectrumData.rawTime || currentSpectrumData.timeData),
      flux_2d: normFlux2d,
      error_2d: normErr2d,
      period: params.period,
      rp_rs_guess: params.rp_rs_guess,
      a_rs: params.a_rs,
      inc: params.inc,
      ecc: params.ecc,
      omega: params.omega,
      limb_dark: params.limb_dark,
      u: params.u,
      fit_limb_dark: params.fit_limb_dark,
    };

    const resp = await fetch('/fit/transit_all_wavelengths', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    const data = await resp.json();

    if (!data.job_id) {
      alert('Failed to start sweep: ' + (data.error || 'Unknown error'));
      if (statusEl) statusEl.textContent = '';
      return;
    }

    transitSweepJobId = data.job_id;
    _pollFitJob(data.job_id, statusEl, (result) => {
      transitSweepJobId = null;
      if (result.success) {
        renderTransmissionSpectrumPlot(result);
        window.dispatchEvent(new CustomEvent('transitSweepComplete'));
      } else {
        alert('Transit sweep failed: ' + (result.error || 'Unknown error'));
      }
    });
  } catch (e) {
    alert('Transit sweep request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

/**
 * Render transit depth (ppm) vs wavelength (transmission spectrum).
 */
function renderTransmissionSpectrumPlot(result) {
  const container = document.getElementById('derivedPlotContainer');
  if (!container) return;
  container.classList.remove('hidden');

  const wl = result.wavelengths;
  const depth = result.transit_depth;
  const depthErr = result.transit_depth_err;
  const mask = result.success_mask;

  // Filter to successful fits
  const xFilt = [], yFilt = [], eFilt = [];
  for (let i = 0; i < wl.length; i++) {
    if (mask[i] && depth[i] != null && isFinite(depth[i])) {
      xFilt.push(wl[i]);
      yFilt.push(depth[i]);
      eFilt.push(depthErr[i] != null && isFinite(depthErr[i]) ? depthErr[i] : 0);
    }
  }

  const trace = {
    x: xFilt,
    y: yFilt,
    error_y: {
      type: 'data',
      array: eFilt,
      visible: true,
      color: '#06B6D4',
    },
    type: 'scatter',
    mode: 'markers',
    marker: { color: '#06B6D4', size: 5 },
    name: 'Transit Depth',
  };

  const layout = {
    template: 'plotly_dark',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: 'Wavelength (um)', gridcolor: 'rgba(74,144,217,0.12)' },
    yaxis: { title: 'Transit Depth (ppm)', gridcolor: 'rgba(74,144,217,0.12)' },
    margin: { l: 70, r: 40, t: 30, b: 50 },
    height: 400,
    showlegend: false,
    title: { text: 'Transmission Spectrum', font: { size: 14, color: '#06B6D4' } },
  };

  Plotly.newPlot('derivedPlot', [trace], layout, { responsive: true });
}

// Overlay Rendering

/**
 * Get the reference flux for the current sine-fit context.
 * Handles both single-wavelength and band-averaged modes.
 * @returns {number|null}
 */
function _getSineReferenceFlux() {
  if (!currentSpectrumData || !currentSpectrumData.referenceSpectrum) return null;
  const ref = currentSpectrumData.referenceSpectrum;
  const wl = currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData;

  if (currentSpectrumData.bandAveraged && activeBands && activeBands.length >= 1) {
    let sum = 0, cnt = 0;
    for (let i = 0; i < wl.length; i++) {
      if (activeBands.some(b => wl[i] >= b.start && wl[i] <= b.end)) {
        if (isFinite(ref[i]) && ref[i] !== 0) { sum += ref[i]; cnt++; }
      }
    }
    return cnt > 0 ? sum / cnt : null;
  }

  const idx = currentWavelengthIndex;
  if (idx >= 0 && idx < ref.length && isFinite(ref[idx]) && ref[idx] !== 0) {
    return ref[idx];
  }
  return null;
}

/**
 * Re-apply fit overlay traces after Plotly.newPlot completes.
 * Called from the setTimeout(0) hook in updateSpectrumPlot().
 */
function applyFitOverlays() {
  const plotEl = document.getElementById('spectrumPlot');
  if (!plotEl || !plotEl.data) return;

  if (showSineFitOverlay && lastSineFitResult && spectrumMode === 'vs_time') {
    let overlayY = lastSineFitResult.fit_values;

    // Convert from raw Jy to variability (%) when display is not flux
    if (currentSpectrumData && currentSpectrumData.zAxisDisplay !== 'flux') {
      const refFlux = _getSineReferenceFlux();
      if (refFlux) {
        overlayY = lastSineFitResult.fit_values.map(v =>
          isFinite(v) ? (v / refFlux - 1) * 100 : NaN
        );
      }
    }

    Plotly.addTraces('spectrumPlot', {
      x: lastSineFitResult.fit_time,
      y: overlayY,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#F59E0B', width: 2.5 },
      name: 'Sine Fit',
      hoverinfo: 'skip',
    });
  }

  if (showGridFitOverlay && lastGridFitResult && !lastChunkedFitResult && spectrumMode === 'vs_wavelength') {
    const modelWl = lastGridFitResult.best_fit_wavelengths;
    const modelJy = lastGridFitResult.best_fit_spectrum;
    let overlayY = modelJy;

    // Convert model from raw Jy to variability (%) when display is not flux
    if (currentSpectrumData && currentSpectrumData.zAxisDisplay !== 'flux') {
      const ref = currentSpectrumData.referenceSpectrum;
      const rawWl = currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData;
      if (ref && rawWl) {
        overlayY = modelWl.map((wl, i) => {
          // Find closest reference wavelength index
          let bestIdx = 0, bestDist = Math.abs(rawWl[0] - wl);
          for (let k = 1; k < rawWl.length; k++) {
            const d = Math.abs(rawWl[k] - wl);
            if (d < bestDist) { bestDist = d; bestIdx = k; }
          }
          const r = ref[bestIdx];
          return (r && isFinite(r) && r !== 0) ? (modelJy[i] / r - 1) * 100 : NaN;
        });
      }
    }

    Plotly.addTraces('spectrumPlot', {
      x: modelWl,
      y: overlayY,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#EF4444', width: 2.5, dash: 'dash' },
      name: 'Grid Fit',
      hoverinfo: 'skip',
    });
  }

  // Chunked grid fit overlays — one colored dashed trace per successful chunk
  if (showGridFitOverlay && lastChunkedFitResult && spectrumMode === 'vs_wavelength') {
    const traces = [];
    const ref = currentSpectrumData ? currentSpectrumData.referenceSpectrum : null;
    const rawWl = currentSpectrumData ? (currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData) : null;
    const isVariability = currentSpectrumData && currentSpectrumData.zAxisDisplay !== 'flux';

    lastChunkedFitResult.chunk_results.forEach((cr) => {
      if (!cr.success) return;
      const modelWl = cr.best_fit_wavelengths;
      const modelJy = cr.best_fit_spectrum;
      let overlayY = modelJy;

      if (isVariability && ref && rawWl) {
        overlayY = modelWl.map((wl, i) => {
          let bestIdx = 0, bestDist = Math.abs(rawWl[0] - wl);
          for (let k = 1; k < rawWl.length; k++) {
            const d = Math.abs(rawWl[k] - wl);
            if (d < bestDist) { bestDist = d; bestIdx = k; }
          }
          const r = ref[bestIdx];
          return (r && isFinite(r) && r !== 0) ? (modelJy[i] / r - 1) * 100 : NaN;
        });
      }

      traces.push({
        x: modelWl,
        y: overlayY,
        type: 'scatter',
        mode: 'lines',
        line: { color: cr._color || '#3B82F6', width: 2.5, dash: 'dash' },
        name: cr._label || 'Chunk',
        hoverinfo: 'skip',
      });
    });

    if (traces.length > 0) {
      Plotly.addTraces('spectrumPlot', traces);
    }
  }

  // Transit fit overlay
  if (showTransitFitOverlay && lastTransitFitResult && spectrumMode === 'vs_time') {
    const normMedian = lastTransitFitResult._normMedian || 1;
    let overlayY;

    if (currentSpectrumData && currentSpectrumData.zAxisDisplay === 'flux') {
      // De-normalize: multiply batman output (near 1.0) by median to get Jy
      overlayY = lastTransitFitResult.fit_values.map(v =>
        isFinite(v) ? v * normMedian : NaN
      );
    } else {
      // Variability display: (batman_val - 1) * 100
      overlayY = lastTransitFitResult.fit_values.map(v =>
        isFinite(v) ? (v - 1) * 100 : NaN
      );
    }

    Plotly.addTraces('spectrumPlot', {
      x: lastTransitFitResult.fit_time,
      y: overlayY,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#06B6D4', width: 2.5 },
      name: 'Transit Fit',
      hoverinfo: 'skip',
    });
  }

  // Expand y-axis if any overlay trace extends beyond the current range
  const overlayYValues = [];
  for (let i = 0; i < plotEl.data.length; i++) {
    const name = plotEl.data[i].name || '';
    if (name === 'Sine Fit' || name === 'Grid Fit' || name === 'Transit Fit' || name.startsWith('Chunk')) {
      const yArr = plotEl.data[i].y;
      if (yArr) {
        for (let j = 0; j < yArr.length; j++) {
          const v = yArr[j];
          if (isFinite(v)) overlayYValues.push(v);
        }
      }
    }
  }

  if (overlayYValues.length > 0 && plotEl.layout && plotEl.layout.yaxis && plotEl.layout.yaxis.range) {
    const curMin = plotEl.layout.yaxis.range[0];
    const curMax = plotEl.layout.yaxis.range[1];
    let oMin = overlayYValues[0], oMax = overlayYValues[0];
    for (let i = 1; i < overlayYValues.length; i++) {
      if (overlayYValues[i] < oMin) oMin = overlayYValues[i];
      if (overlayYValues[i] > oMax) oMax = overlayYValues[i];
    }

    if (oMin < curMin || oMax > curMax) {
      const newMin = Math.min(curMin, oMin);
      const newMax = Math.max(curMax, oMax);
      const pad = (newMax - newMin) * 0.03 || 1e-6;
      Plotly.relayout('spectrumPlot', {
        'yaxis.range': [
          oMin < curMin ? newMin - pad : curMin,
          oMax > curMax ? newMax + pad : curMax,
        ]
      });
    }
  }
}

// Derived Plots

/**
 * Render residual plot below the main spectrum plot.
 */
function renderResidualPlot(wavelengths, residuals, zAxisDisplay, referenceSpectrum, refWavelengths) {
  const container = document.getElementById('residualPlotContainer');
  if (!container) return;
  container.classList.remove('hidden');

  let plotResiduals = residuals;
  let yLabel = 'Residual (Jy)';

  // Convert residuals from Jy to variability (%) when not in flux mode
  if (zAxisDisplay && zAxisDisplay !== 'flux' && referenceSpectrum && refWavelengths) {
    plotResiduals = wavelengths.map((wl, i) => {
      let bestIdx = 0, bestDist = Math.abs(refWavelengths[0] - wl);
      for (let k = 1; k < refWavelengths.length; k++) {
        const d = Math.abs(refWavelengths[k] - wl);
        if (d < bestDist) { bestDist = d; bestIdx = k; }
      }
      const r = referenceSpectrum[bestIdx];
      return (r && isFinite(r) && r !== 0) ? (residuals[i] / r) * 100 : NaN;
    });
    yLabel = 'Residual (%)';
  }

  const trace = {
    x: wavelengths,
    y: plotResiduals,
    type: 'scatter',
    mode: 'lines',
    line: { color: '#EF4444', width: 1.5 },
    name: 'Residuals',
  };

  const layout = {
    template: 'plotly_dark',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: 'Wavelength (um)', gridcolor: 'rgba(74,144,217,0.12)' },
    yaxis: { title: yLabel, gridcolor: 'rgba(74,144,217,0.12)', zeroline: true, zerolinecolor: 'rgba(255,255,255,0.3)' },
    margin: { l: 60, r: 40, t: 20, b: 40 },
    height: 200,
    showlegend: false,
  };

  Plotly.newPlot('residualPlot', [trace], layout, { responsive: true });
}

/**
 * Render residual plot for chunked fit results — one colored trace per chunk.
 */
function renderChunkedResidualPlot(result) {
  const container = document.getElementById('residualPlotContainer');
  if (!container) return;
  container.classList.remove('hidden');

  const zAxisDisplay = currentSpectrumData ? currentSpectrumData.zAxisDisplay : null;
  const ref = currentSpectrumData ? currentSpectrumData.referenceSpectrum : null;
  const refWl = currentSpectrumData ? (currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData) : null;
  const isVariability = zAxisDisplay && zAxisDisplay !== 'flux' && ref && refWl;
  const yLabel = isVariability ? 'Residual (%)' : 'Residual (Jy)';

  const traces = [];
  result.chunk_results.forEach((cr) => {
    if (!cr.success) return;
    const wl = cr.best_fit_wavelengths;
    let plotResiduals = cr.residuals;

    if (isVariability) {
      plotResiduals = wl.map((w, i) => {
        let bestIdx = 0, bestDist = Math.abs(refWl[0] - w);
        for (let k = 1; k < refWl.length; k++) {
          const d = Math.abs(refWl[k] - w);
          if (d < bestDist) { bestDist = d; bestIdx = k; }
        }
        const r = ref[bestIdx];
        return (r && isFinite(r) && r !== 0) ? (cr.residuals[i] / r) * 100 : NaN;
      });
    }

    traces.push({
      x: wl,
      y: plotResiduals,
      type: 'scatter',
      mode: 'lines',
      line: { color: cr._color || '#3B82F6', width: 1.5 },
      name: cr._label || 'Chunk',
    });
  });

  const layout = {
    template: 'plotly_dark',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: 'Wavelength (um)', gridcolor: 'rgba(74,144,217,0.12)' },
    yaxis: { title: yLabel, gridcolor: 'rgba(74,144,217,0.12)', zeroline: true, zerolinecolor: 'rgba(255,255,255,0.3)' },
    margin: { l: 60, r: 40, t: 20, b: 40 },
    height: 200,
    showlegend: traces.length > 1,
  };

  Plotly.newPlot('residualPlot', traces, layout, { responsive: true });
}

/**
 * Render amplitude vs wavelength derived plot.
 */
function renderAmplitudeVsWavelengthPlot(result) {
  const container = document.getElementById('derivedPlotContainer');
  if (!container) return;
  container.classList.remove('hidden');

  const isVariability = currentSpectrumData && currentSpectrumData.zAxisDisplay !== 'flux';
  const ref = currentSpectrumData ? currentSpectrumData.referenceSpectrum : null;
  const refWl = currentSpectrumData ? (currentSpectrumData.rawWavelengths || currentSpectrumData.wavelengthData) : null;

  const n_sines = result.n_sines || 1;
  const traces = [];
  const colors = ['#F59E0B', '#EF4444', '#10B981'];

  for (let s = 0; s < n_sines; s++) {
    let amps = result.amplitudes.map(row => row[s]);

    // Convert amplitudes from Jy to % using per-wavelength reference spectrum
    if (isVariability && ref && refWl) {
      amps = result.wavelengths.map((wl, i) => {
        // Find closest reference wavelength index
        let bestIdx = 0, bestDist = Math.abs(refWl[0] - wl);
        for (let k = 1; k < refWl.length; k++) {
          const d = Math.abs(refWl[k] - wl);
          if (d < bestDist) { bestDist = d; bestIdx = k; }
        }
        const r = ref[bestIdx];
        return (r && isFinite(r) && r !== 0) ? (result.amplitudes[i][s] / r) * 100 : NaN;
      });
    }

    traces.push({
      x: result.wavelengths,
      y: amps,
      type: 'scatter',
      mode: 'lines+markers',
      line: { color: colors[s % colors.length], width: 2 },
      marker: { size: 3 },
      name: n_sines > 1 ? `Sine ${s + 1}` : 'Amplitude',
    });
  }

  const ampLabel = isVariability ? 'Amplitude (%)' : 'Amplitude (Jy)';

  const layout = {
    template: 'plotly_dark',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: 'Wavelength (um)', gridcolor: 'rgba(74,144,217,0.12)' },
    yaxis: { title: ampLabel, gridcolor: 'rgba(74,144,217,0.12)' },
    margin: { l: 60, r: 40, t: 30, b: 50 },
    height: 400,
    showlegend: n_sines > 1,
    title: { text: 'Amplitude vs Wavelength', font: { size: 14, color: '#F59E0B' } },
  };

  Plotly.newPlot('derivedPlot', traces, layout, { responsive: true });
}

/**
 * Render parameter time series derived plot (Teff + log(g) on secondary y-axis).
 */
function renderParameterTimeSeriesPlot(result) {
  const container = document.getElementById('derivedPlotContainer');
  if (!container) return;
  container.classList.remove('hidden');

  const times = result.times;
  const teff = result.best_params.map(p => p.Teff !== undefined ? p.Teff : NaN);
  const logg = result.best_params.map(p => p.logg !== undefined ? p.logg : NaN);
  const mask = result.success_mask;

  // Filter to successful fits only
  const validTimes = times.filter((_, i) => mask[i]);
  const validTeff = teff.filter((_, i) => mask[i]);
  const validLogg = logg.filter((_, i) => mask[i]);

  const traces = [
    {
      x: validTimes,
      y: validTeff,
      type: 'scatter',
      mode: 'lines+markers',
      line: { color: '#EF4444', width: 2 },
      marker: { size: 4 },
      name: 'T_eff (K)',
      yaxis: 'y',
    },
  ];

  const hasLogg = validLogg.some(v => isFinite(v));
  if (hasLogg) {
    traces.push({
      x: validTimes,
      y: validLogg,
      type: 'scatter',
      mode: 'lines+markers',
      line: { color: '#3B82F6', width: 2, dash: 'dash' },
      marker: { size: 4 },
      name: 'log(g)',
      yaxis: 'y2',
    });
  }

  const layout = {
    template: 'plotly_dark',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: 'Time (hours)', gridcolor: 'rgba(74,144,217,0.12)' },
    yaxis: { title: 'T_eff (K)', gridcolor: 'rgba(74,144,217,0.12)', titlefont: { color: '#EF4444' } },
    margin: { l: 60, r: hasLogg ? 60 : 40, t: 30, b: 50 },
    height: 400,
    showlegend: true,
    title: { text: 'Best-Fit Parameters vs Time', font: { size: 14, color: '#EF4444' } },
  };

  if (hasLogg) {
    layout.yaxis2 = {
      title: 'log(g)',
      overlaying: 'y',
      side: 'right',
      gridcolor: 'rgba(59,130,246,0.12)',
      titlefont: { color: '#3B82F6' },
    };
  }

  Plotly.newPlot('derivedPlot', traces, layout, { responsive: true });
}

// Parameter Readout

/**
 * Display fit parameters as styled text.
 */
function updateFitParameterReadout(type, result) {
  const el = document.getElementById('fittingParamsReadout');
  if (!el) return;

  if (type === 'sine') {
    const isVariability = currentSpectrumData && currentSpectrumData.zAxisDisplay !== 'flux';
    const refFlux = _getSineReferenceFlux();

    let displayOffset, displayUnit;
    if (isVariability && refFlux) {
      displayOffset = ((result.offset / refFlux - 1) * 100).toFixed(4);
      displayUnit = '%';
    } else {
      displayOffset = result.offset.toFixed(6);
      displayUnit = 'Jy';
    }

    let html = `<span style="color: #F59E0B; font-weight: 600;">Sinusoidal Fit</span><br>`;
    html += `<span style="color: var(--text-secondary);">Offset: ${displayOffset} ${displayUnit}</span><br>`;
    result.params.forEach((p, i) => {
      let displayAmp;
      if (isVariability && refFlux) {
        displayAmp = ((p.amplitude / refFlux) * 100).toFixed(4) + ' %';
      } else {
        displayAmp = p.amplitude.toFixed(6) + ' Jy';
      }
      html += `<span style="color: var(--text-secondary);">Sine ${i + 1}: A=${displayAmp}, P=${p.period.toFixed(4)} hr, φ=${p.phase.toFixed(3)} rad</span><br>`;
    });
    html += `<span style="color: var(--text-dim);">χ²_red = ${result.reduced_chi_squared.toFixed(3)}</span>`;
    el.innerHTML = html;
  } else if (type === 'grid') {
    let html = `<span style="color: #EF4444; font-weight: 600;">Grid Fit</span><br>`;
    const params = result.best_fit_params;
    for (const [k, v] of Object.entries(params)) {
      html += `<span style="color: var(--text-secondary);">${k}: ${typeof v === 'number' ? v.toFixed(2) : v}</span><br>`;
    }
    html += `<span style="color: var(--text-dim);">χ²_red = ${result.reduced_chi_squared.toFixed(3)}, scale = ${result.scaling_factor.toExponential(4)}</span>`;
    if (result.n_data_points != null) {
      html += `<br><span style="color: var(--text-dim);">N = ${result.n_data_points}, median SNR = ${result.median_snr != null ? result.median_snr.toFixed(1) : '—'}</span>`;
    }
    el.innerHTML = html;
  } else if (type === 'grid_chunked') {
    const chunks = result.chunk_results;
    let html = `<span style="color: #EF4444; font-weight: 600;">Grid Fit (${chunks.length} chunks)</span><br>`;
    chunks.forEach((cr) => {
      const color = cr._color || '#3B82F6';
      const label = cr._label || 'Chunk';
      if (!cr.success) {
        html += `<span style="color: ${color};">&bull; ${label} [${cr._wl_min.toFixed(3)}&ndash;${cr._wl_max.toFixed(3)} &mu;m]: ${cr.error || 'Failed'}</span><br>`;
        return;
      }
      html += `<span style="color: ${color}; font-weight: 500;">&bull; ${label} [${cr._wl_min.toFixed(3)}&ndash;${cr._wl_max.toFixed(3)} &mu;m]</span><br>`;
      const params = cr.best_fit_params;
      for (const [k, v] of Object.entries(params)) {
        html += `<span style="color: var(--text-secondary); margin-left: 1rem;">${k}: ${typeof v === 'number' ? v.toFixed(2) : v}</span><br>`;
      }
      html += `<span style="color: var(--text-dim); margin-left: 1rem;">&chi;&sup2;_red = ${cr.reduced_chi_squared.toFixed(3)}, scale = ${cr.scaling_factor.toExponential(4)}</span><br>`;
    });
    el.innerHTML = html;
  } else if (type === 'transit') {
    const p = result.params;
    let html = `<span style="color: #06B6D4; font-weight: 600;">Transit Fit</span><br>`;
    html += `<span style="color: var(--text-secondary);">Rp/Rs = ${p.rp_rs.toFixed(5)} &pm; ${p.rp_rs_err.toFixed(5)}</span><br>`;
    html += `<span style="color: var(--text-secondary);">Depth = ${(p.depth * 100).toFixed(4)}% (${p.depth_ppm.toFixed(0)} &pm; ${p.depth_ppm_err.toFixed(0)} ppm)</span><br>`;
    html += `<span style="color: var(--text-secondary);">t0 = ${p.t0.toFixed(4)} hr</span><br>`;
    html += `<span style="color: var(--text-dim);">Limb dark: ${p.limb_dark}, u = [${p.u.map(v => v.toFixed(3)).join(', ')}]</span><br>`;
    html += `<span style="color: var(--text-dim);">&chi;&sup2;_red = ${result.reduced_chi_squared.toFixed(3)}</span>`;
    el.innerHTML = html;
  }
}

// Grid List Loading

/**
 * Fetch available model grids and populate the dropdown.
 */
async function loadGridList() {
  const selectEl = document.getElementById('fitGridSelect');
  if (!selectEl) return;

  try {
    const resp = await fetch('/fit/grid_list');
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    const data = await resp.json();

    selectEl.innerHTML = '<option value="">-- No grids available --</option>';

    if (data.grids && data.grids.length > 0) {
      selectEl.innerHTML = '<option value="">-- Select grid --</option>';
      data.grids.forEach(g => {
        const opt = document.createElement('option');
        opt.value = g.name;
        opt.textContent = `${g.name} (${g.n_models} models)`;
        selectEl.appendChild(opt);
      });
    }
  } catch (e) {
    console.warn('Failed to load grid list:', e);
  }
}

// ExoMAST Target Parameter Lookup

let _exomastPopupShown = false;
let _exomastParams = null;
let _exomastFoundKeys = [];
let _exomastAbort = null;
let _exomastDebounce = null;

/**
 * Read the detected target name from FITS metadata.
 * @returns {string|null}
 */
function _getDetectedTarget() {
  const meta = window.__stampMetadata;
  if (!meta || !meta.targets || meta.targets.length === 0) return null;
  const t = meta.targets[0];
  return (t && t !== 'Unknown') ? t : null;
}

/**
 * Fetch target parameters via our unified lookup proxy
 * (ExoMAST → Exoplanet.eu → SIMBAD).
 * @param {string} name
 * @returns {Promise<{found: boolean, params?: Object, planet_name?: string, sources?: string[], error?: string}>}
 */
async function lookupExoMAST(name) {
  try {
    const resp = await fetch(`/exomast/lookup/${encodeURIComponent(name)}`);
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText) || `Server error (${resp.status})`);
    return await resp.json();
  } catch (e) {
    return { found: false, error: 'Network error: ' + e.message };
  }
}

/**
 * Fetch autocomplete suggestions from ExoMAST with debounce.
 * @param {string} term
 * @param {function} callback - receives array of name strings
 */
function fetchAutocomplete(term, callback) {
  if (_exomastDebounce) clearTimeout(_exomastDebounce);
  if (_exomastAbort) _exomastAbort.abort();

  if (!term || term.length < 2) { callback([]); return; }

  _exomastDebounce = setTimeout(async () => {
    _exomastAbort = new AbortController();
    try {
      const resp = await fetch(`/exomast/autocomplete?term=${encodeURIComponent(term)}`, {
        signal: _exomastAbort.signal,
      });
      if (!resp.ok) { callback([]); return; }
      const names = await resp.json();
      callback(Array.isArray(names) ? names : []);
    } catch (e) {
      if (e.name !== 'AbortError') callback([]);
    }
  }, 300);
}

/**
 * Apply looked-up parameters to fitting input fields.
 * Fills transit fields (period, a/Rs, Rp/Rs, inc, ecc, omega)
 * and sinusoidal period guess from rotation_period.
 * @param {Object} params
 */
function applyExoMASTParams(params, foundKeys) {
  if (!params) return;
  const fk = foundKeys || _exomastFoundKeys || [];
  const map = {
    orbital_period:  { id: 'transitPeriod', convert: v => (v * 24).toFixed(4) },
    a_rs:            { id: 'transitARs' },
    rp_rs:           { id: 'transitRpRs' },
    inclination:     { id: 'transitInc' },
    eccentricity:    { id: 'transitEcc' },
    omega:           { id: 'transitOmega' },
    rotation_period: { id: 'fitPeriodGuess', convert: v => (v * 24).toFixed(4) },
  };

  for (const [key, cfg] of Object.entries(map)) {
    const val = params[key];
    if (val == null) continue;
    const el = document.getElementById(cfg.id);
    if (!el) continue;
    el.value = cfg.convert ? cfg.convert(val) : val;
  }

  // Show warning icons on transit fields not found in catalogs
  const transitWarnable = {
    a_rs: 'transitARs',
    rp_rs: 'transitRpRs',
    inclination: 'transitInc',
    eccentricity: 'transitEcc',
    omega: 'transitOmega',
  };
  for (const [paramKey, inputId] of Object.entries(transitWarnable)) {
    const el = document.getElementById(inputId);
    if (!el) continue;
    const existing = el.parentElement.querySelector('.param-warning');
    if (existing) existing.remove();
    if (!fk.includes(paramKey)) {
      const warn = document.createElement('span');
      warn.className = 'param-warning';
      warn.title = 'Not found in catalogs \u2014 using default value';
      warn.textContent = ' \u26A0';
      warn.style.cssText = 'color: #F59E0B; cursor: help; font-size: 0.85rem;';
      el.parentElement.appendChild(warn);
    }
  }
}

/**
 * Render the parameter preview table in the popup.
 * @param {Object} params
 */
function _renderExoMASTPreview(params, sources) {
  const tbody = document.getElementById('exomastPreviewBody');
  const preview = document.getElementById('exomastPreview');
  if (!tbody || !preview) return;

  function fmt(val) {
    if (typeof val !== 'number') return val;
    return +val.toPrecision(6);
  }

  const allRows = [
    ['Period (days)',    params.orbital_period],
    ['a/R\u2097',       params.a_rs],
    ['Rp/R\u2097',      params.rp_rs],
    ['Inclination (\u00b0)', params.inclination],
    ['Eccentricity',    params.eccentricity],
    ['\u03c9 (\u00b0)', params.omega],
    ['Spectral Type',   params.spectral_type],
    ['Teff (K)',        params.teff],
    ['log(g)',          params.stellar_logg],
    ['[Fe/H]',         params.metallicity],
    ['Mass (M_Jup)',    params.mass_mjup],
    ['Radius (R_Jup)',  params.radius_rjup],
    ['Distance (pc)',   params.distance_pc],
    ['Rotation (days)', params.rotation_period],
    ['v sin i (km/s)',  params.v_sini],
    ['RV (km/s)',       params.radial_velocity],
  ];

  // Only show rows that have a value
  const rows = allRows.filter(function(r) { return r[1] != null; });

  tbody.innerHTML = rows.map(function(r) {
    var label = r[0], val = r[1];
    var display = fmt(val);
    return '<tr style="border-bottom: 1px solid var(--glass-border);">' +
      '<td style="padding: 4px 6px; color: var(--text-secondary);">' + label + '</td>' +
      '<td style="padding: 4px 6px; text-align: right; color: var(--text-primary);">' + display + '</td>' +
    '</tr>';
  }).join('');

  // Source attribution
  if (sources && sources.length) {
    tbody.innerHTML += '<tr><td colspan="2" style="padding: 6px 6px 2px; color: var(--text-dim); font-size: 0.75rem;">' +
      'Source: ' + sources.join(', ') + '</td></tr>';
  }

  preview.classList.remove('hidden');
}

/**
 * Perform a full ExoMAST lookup and update the popup UI.
 * @param {string} name
 */
async function performExoMASTLookup(name) {
  const statusEl = document.getElementById('exomastStatus');
  const applyBtn = document.getElementById('exomastApplyBtn');
  const preview = document.getElementById('exomastPreview');

  if (!name || !name.trim()) {
    if (statusEl) statusEl.textContent = 'Enter a target name';
    return;
  }

  if (statusEl) { statusEl.textContent = 'Searching catalogs for ' + name + '...'; statusEl.style.color = 'var(--text-secondary)'; }
  if (applyBtn) applyBtn.classList.add('hidden');
  if (preview) preview.classList.add('hidden');

  const result = await lookupExoMAST(name.trim());

  if (result.found) {
    _exomastParams = result.params;
    _exomastFoundKeys = result.found_keys || [];
    var sourceText = (result.sources && result.sources.length) ? ' (' + result.sources.join(', ') + ')' : '';
    if (statusEl) { statusEl.textContent = 'Found: ' + result.planet_name + sourceText; statusEl.style.color = '#10b981'; }
    _renderExoMASTPreview(result.params, result.sources);
    // Show Apply button if any fillable params exist (transit or sinusoidal)
    var canApply = ['orbital_period', 'a_rs', 'rp_rs', 'inclination', 'eccentricity', 'omega', 'rotation_period']
        .some(function(k) { return result.params[k] != null; });
    if (applyBtn) { if (canApply) applyBtn.classList.remove('hidden'); }
  } else {
    _exomastParams = null;
    _exomastFoundKeys = [];
    if (statusEl) { statusEl.textContent = result.error || 'Target not found'; statusEl.style.color = '#ef4444'; }
  }
}

/**
 * Show the ExoMAST popup, optionally pre-filling the target input.
 * @param {string|null} target
 */
function showExoMASTPopup(target) {
  const popup = document.getElementById('exomastPopup');
  const input = document.getElementById('exomastTargetInput');
  const statusEl = document.getElementById('exomastStatus');
  const applyBtn = document.getElementById('exomastApplyBtn');
  const preview = document.getElementById('exomastPreview');
  const dropdown = document.getElementById('exomastAutocomplete');

  if (!popup) return;

  // Reset state
  _exomastParams = null;
  _exomastFoundKeys = [];
  if (applyBtn) applyBtn.classList.add('hidden');
  if (preview) preview.classList.add('hidden');
  if (dropdown) dropdown.style.display = 'none';

  if (target) {
    if (input) input.value = target;
    if (statusEl) { statusEl.textContent = 'Detected target: ' + target; statusEl.style.color = 'var(--text-secondary)'; }
  } else {
    if (input) input.value = '';
    if (statusEl) { statusEl.textContent = 'Enter a target name'; statusEl.style.color = 'var(--text-secondary)'; }
  }

  popup.classList.remove('hidden');
  _exomastPopupShown = true;

  // Auto-trigger lookup if we have a target
  if (target) {
    performExoMASTLookup(target);
  }
}

/**
 * Hide the ExoMAST popup.
 */
function hideExoMASTPopup() {
  const popup = document.getElementById('exomastPopup');
  if (popup) popup.classList.add('hidden');
  const dropdown = document.getElementById('exomastAutocomplete');
  if (dropdown) dropdown.style.display = 'none';
}

/**
 * Render autocomplete dropdown items.
 * @param {string[]} names
 */
function _renderAutocompleteDropdown(names) {
  const dropdown = document.getElementById('exomastAutocomplete');
  if (!dropdown) return;

  if (!names || names.length === 0) {
    dropdown.style.display = 'none';
    return;
  }

  dropdown.innerHTML = names.slice(0, 10).map(n =>
    `<div class="exomast-autocomplete-item">${n}</div>`
  ).join('');
  dropdown.style.display = 'block';
}

// Event Binding

document.addEventListener('DOMContentLoaded', function() {
  // Load grid list
  loadGridList();

  // Sinusoidal fit buttons
  const lsBtn = document.getElementById('lombScargleBtn');
  if (lsBtn) lsBtn.addEventListener('click', requestLombScargle);

  const fitSineBtn = document.getElementById('fitSineBtn');
  if (fitSineBtn) fitSineBtn.addEventListener('click', requestSineFit);

  const clearSineBtn = document.getElementById('clearSineFitBtn');
  if (clearSineBtn) clearSineBtn.addEventListener('click', clearSineFit);

  const sineSweepBtn = document.getElementById('sineSweepBtn');
  if (sineSweepBtn) sineSweepBtn.addEventListener('click', requestSineSweep);

  // Grid fit buttons
  const fitGridBtn = document.getElementById('fitGridBtn');
  if (fitGridBtn) fitGridBtn.addEventListener('click', requestGridFit);

  const clearGridBtn = document.getElementById('clearGridFitBtn');
  if (clearGridBtn) clearGridBtn.addEventListener('click', clearGridFit);

  const gridSweepBtn = document.getElementById('gridSweepBtn');
  if (gridSweepBtn) gridSweepBtn.addEventListener('click', requestGridSweep);

  // Transit fit buttons
  const fitTransitBtn = document.getElementById('fitTransitBtn');
  if (fitTransitBtn) fitTransitBtn.addEventListener('click', requestTransitFit);

  const clearTransitBtn = document.getElementById('clearTransitFitBtn');
  if (clearTransitBtn) clearTransitBtn.addEventListener('click', clearTransitFit);

  const transitSweepBtn = document.getElementById('transitSweepBtn');
  if (transitSweepBtn) transitSweepBtn.addEventListener('click', requestTransitSweep);

  // Chunk count input — build range rows when > 1
  const chunkInput = document.getElementById('chunkCountInput');
  if (chunkInput) {
    chunkInput.addEventListener('input', function() {
      const n = parseInt(this.value);
      const container = document.getElementById('chunkRangesContainer');
      if (n > 1) {
        buildChunkRangeInputs(n);
      } else if (container) {
        container.style.display = 'none';
      }
    });
  }

  // ── ExoMAST Event Bindings ──

  // Autocomplete on target input
  const exomastInput = document.getElementById('exomastTargetInput');
  if (exomastInput) {
    exomastInput.addEventListener('input', function() {
      fetchAutocomplete(this.value, _renderAutocompleteDropdown);
    });
    exomastInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        const dropdown = document.getElementById('exomastAutocomplete');
        if (dropdown) dropdown.style.display = 'none';
        performExoMASTLookup(this.value);
      }
    });
  }

  // Autocomplete item click
  const autocompleteEl = document.getElementById('exomastAutocomplete');
  if (autocompleteEl) {
    autocompleteEl.addEventListener('click', function(e) {
      const item = e.target.closest('.exomast-autocomplete-item');
      if (!item) return;
      const name = item.textContent.trim();
      if (exomastInput) exomastInput.value = name;
      this.style.display = 'none';
      performExoMASTLookup(name);
    });
  }

  // Look Up button
  const lookupBtn = document.getElementById('exomastLookupBtn');
  if (lookupBtn) {
    lookupBtn.addEventListener('click', function() {
      const input = document.getElementById('exomastTargetInput');
      if (input) performExoMASTLookup(input.value);
    });
  }

  // Apply button
  const applyBtn = document.getElementById('exomastApplyBtn');
  if (applyBtn) {
    applyBtn.addEventListener('click', function() {
      applyExoMASTParams(_exomastParams);
      // Open the relevant fitting sections
      if (_exomastParams) {
        var hasTransit = ['orbital_period', 'a_rs', 'rp_rs', 'inclination', 'eccentricity', 'omega']
            .some(function(k) { return _exomastParams[k] != null; });
        if (hasTransit) {
          var td = document.getElementById('transitFittingDetails');
          if (td) td.open = true;
        }
        if (_exomastParams.rotation_period != null) {
          var sd = document.getElementById('sineFittingDetails');
          if (sd) sd.open = true;
        }
      }
      hideExoMASTPopup();
    });
  }

  // Dismiss button
  const dismissBtn = document.getElementById('exomastDismissBtn');
  if (dismissBtn) dismissBtn.addEventListener('click', hideExoMASTPopup);

  // Backdrop click dismisses
  const backdrop = document.getElementById('exomastPopupBackdrop');
  if (backdrop) backdrop.addEventListener('click', hideExoMASTPopup);

  // ExoMAST summary button — re-open popup manually
  const exomastBtn = document.getElementById('exomastBtn');
  if (exomastBtn) {
    exomastBtn.addEventListener('click', function(e) {
      e.stopPropagation(); // Don't toggle the <details>
      e.preventDefault();
      showExoMASTPopup(_getDetectedTarget());
    });
  }

  // Show popup when a fitting sub-section opens (once per dataset)
  ['sineFittingDetails', 'transitFittingDetails'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener('toggle', function() {
        if (this.open && !_exomastPopupShown && window.__stampMetadata) {
          setTimeout(function() {
            showExoMASTPopup(_getDetectedTarget());
          }, 300);
        }
      });
    }
  });

  // Bind Look Up button on Sinusoidal summary
  var exomastBtnSine = document.getElementById('exomastBtnSine');
  if (exomastBtnSine) {
    exomastBtnSine.addEventListener('click', function(e) {
      e.stopPropagation();
      e.preventDefault();
      showExoMASTPopup(_getDetectedTarget());
    });
  }

  // Reset on new dataset load
  window.addEventListener('stampsDataLoaded', function() {
    _exomastPopupShown = false;
    _exomastParams = null;
  });
});

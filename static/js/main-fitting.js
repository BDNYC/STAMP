// main-fitting.js - Model Fitting UI and Overlay Rendering

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
      let sum = 0, cnt = 0, esum = 0;
      for (let i = 0; i < wavelengths.length; i++) {
        const inBand = activeBands.some(b => wavelengths[i] >= b.start && wavelengths[i] <= b.end);
        if (!inBand) continue;
        const v = (fluxData[i] && fluxData[i][j] !== undefined) ? fluxData[i][j] : NaN;
        if (!isFinite(v)) continue;
        sum += v;
        cnt++;
        if (errData && errData[i] && errData[i][j] !== undefined) {
          const e = errData[i][j];
          if (isFinite(e)) esum += e * e;
        }
      }
      flux.push(cnt ? sum / cnt : NaN);
      error.push(cnt > 0 && esum > 0 ? Math.sqrt(esum / cnt) / Math.sqrt(cnt) : NaN);
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

// ── Sinusoidal Fitting ──

/**
 * Request a sinusoidal fit for the current light curve and overlay the result.
 */
async function requestSineFit() {
  if (spectrumMode !== 'vs_time') {
    alert('Switch to vs_time mode to fit a sinusoidal model.');
    return;
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
  updateSpectrumPlot();
  const readout = document.getElementById('fittingParamsReadout');
  if (readout) readout.innerHTML = '';
}

// ── Grid Fitting ──

/**
 * Request a spectral grid fit for the current spectrum and overlay the result.
 */
async function requestGridFit() {
  if (spectrumMode !== 'vs_wavelength') {
    alert('Switch to vs_wavelength mode to fit against a model grid.');
    return;
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

  try {
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
    const result = await resp.json();

    if (!result.success) {
      alert('Grid fit failed: ' + (result.error || 'Unknown error'));
      if (statusEl) statusEl.textContent = '';
      return;
    }

    lastGridFitResult = result;
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
  showGridFitOverlay = false;
  updateSpectrumPlot();
  const residualContainer = document.getElementById('residualPlotContainer');
  if (residualContainer) residualContainer.classList.add('hidden');
  const readout = document.getElementById('fittingParamsReadout');
  if (readout) readout.innerHTML = '';
}

// ── Async Sweep Jobs ──

/**
 * Poll a fitting job until complete, then invoke callback with results.
 */
function _pollFitJob(jobId, statusEl, onDone) {
  const poll = setInterval(async () => {
    try {
      const resp = await fetch(`/progress/${jobId}`);
      const prog = await resp.json();

      if (statusEl) statusEl.textContent = prog.message || 'Working...';

      if (prog.status === 'done') {
        clearInterval(poll);
        const resResp = await fetch(`/results/${jobId}`);
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
      } else {
        alert('Sweep failed: ' + (result.error || 'Unknown error'));
      }
    });
  } catch (e) {
    alert('Sweep request failed: ' + e.message);
    if (statusEl) statusEl.textContent = '';
  }
}

// ── Overlay Rendering ──

/**
 * Re-apply fit overlay traces after Plotly.newPlot completes.
 * Called from the setTimeout(0) hook in updateSpectrumPlot().
 */
function applyFitOverlays() {
  const plotEl = document.getElementById('spectrumPlot');
  if (!plotEl || !plotEl.data) return;

  if (showSineFitOverlay && lastSineFitResult && spectrumMode === 'vs_time') {
    Plotly.addTraces('spectrumPlot', {
      x: lastSineFitResult.fit_time,
      y: lastSineFitResult.fit_values,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#F59E0B', width: 2.5 },
      name: 'Sine Fit',
      hoverinfo: 'skip',
    });
  }

  if (showGridFitOverlay && lastGridFitResult && spectrumMode === 'vs_wavelength') {
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
}

// ── Derived Plots ──

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
 * Render amplitude vs wavelength derived plot.
 */
function renderAmplitudeVsWavelengthPlot(result) {
  const container = document.getElementById('derivedPlotContainer');
  if (!container) return;
  container.classList.remove('hidden');

  const n_sines = result.n_sines || 1;
  const traces = [];
  const colors = ['#F59E0B', '#EF4444', '#10B981'];

  for (let s = 0; s < n_sines; s++) {
    const amps = result.amplitudes.map(row => row[s]);
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

  const layout = {
    template: 'plotly_dark',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: { title: 'Wavelength (um)', gridcolor: 'rgba(74,144,217,0.12)' },
    yaxis: { title: 'Amplitude', gridcolor: 'rgba(74,144,217,0.12)' },
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

// ── Parameter Readout ──

/**
 * Display fit parameters as styled text.
 */
function updateFitParameterReadout(type, result) {
  const el = document.getElementById('fittingParamsReadout');
  if (!el) return;

  if (type === 'sine') {
    let html = `<span style="color: #F59E0B; font-weight: 600;">Sinusoidal Fit</span><br>`;
    html += `<span style="color: var(--text-secondary);">Offset: ${result.offset.toFixed(6)}</span><br>`;
    result.params.forEach((p, i) => {
      html += `<span style="color: var(--text-secondary);">Sine ${i + 1}: A=${p.amplitude.toFixed(6)}, P=${p.period.toFixed(4)} hr, φ=${p.phase.toFixed(3)} rad</span><br>`;
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
    const chi = result.reduced_chi_squared;
    if (result.quality_note) {
      const color = chi < 2 ? '#22c55e' : chi < 10 ? '#eab308' : '#f97316';
      html += `<br><span style="color: ${color}; font-weight: 600;">${result.quality_note}</span>`;
    } else if (chi < 2) {
      html += `<br><span style="color: #22c55e; font-weight: 600;">Excellent fit</span>`;
    } else if (chi < 10) {
      html += `<br><span style="color: #eab308; font-weight: 600;">Good fit</span>`;
    } else {
      html += `<br><span style="color: #f97316; font-weight: 600;">Poor shape match — model may not capture this object's atmosphere</span>`;
    }
    el.innerHTML = html;
  }
}

// ── Grid List Loading ──

/**
 * Fetch available model grids and populate the dropdown.
 */
async function loadGridList() {
  const selectEl = document.getElementById('fitGridSelect');
  if (!selectEl) return;

  try {
    const resp = await fetch('/fit/grid_list');
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

// ── Event Binding ──

document.addEventListener('DOMContentLoaded', function() {
  // Load grid list
  loadGridList();

  // Sinusoidal fit buttons
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
});

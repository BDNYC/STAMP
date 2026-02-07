// main-spectrum.js - Spectrum Viewer (Display, Animation & Navigation)

// Animation Controls

/**
 * Toggle spectrum animation play/pause. Advances the time or wavelength
 * index at the configured speed. Blocked in vs_time mode with active bands.
 */
function toggleAnimation() {
  if (spectrumMode === 'vs_time' && activeBands.length > 0) {
    return;
  }
  if (isAnimating) {
    clearInterval(animationInterval);
    isAnimating = false;
    document.getElementById('playAnimationBtn').innerHTML = 'Play';
    if (spectrumMode === 'vs_wavelength') {
      document.getElementById('prevSpectrumBtn').disabled = currentTimeIndex <= 0;
      document.getElementById('nextSpectrumBtn').disabled = currentTimeIndex >= totalTimePoints - 1;
    } else {
      document.getElementById('prevSpectrumBtn').disabled = currentWavelengthIndex <= 0;
      document.getElementById('nextSpectrumBtn').disabled = currentWavelengthIndex >= totalWavelengthPoints - 1;
    }
  } else {
    isAnimating = true;
    document.getElementById('playAnimationBtn').innerHTML = 'Pause';
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

/**
 * Update animation speed and restart playback if already running.
 * @param {string|number} newSpeed - Frames per second.
 */
function updateAnimationSpeed(newSpeed) {
  animationSpeed = parseInt(newSpeed);
  document.getElementById('speedValue').textContent = newSpeed;
  if (isAnimating) {
    clearInterval(animationInterval);
    isAnimating = false;
    toggleAnimation();
  }
}

// Spectrum Data Extraction

/**
 * Extract spectrum data at a clicked point on the surface or heatmap,
 * then open the spectrum viewer.
 * @param {Object} clickData - Plotly click event data with .x and .y.
 * @param {HTMLElement} plotDiv - The Plotly div that was clicked.
 */
function showSpectrumAtTime(clickData, plotDiv) {

  const cached = (plotOriginal[plotDiv.id] && plotOriginal[plotDiv.id].length) ? plotOriginal[plotDiv.id] : null;
  const live = (plotDiv && (plotDiv._fullData || plotDiv.data)) ? (plotDiv._fullData || plotDiv.data) : [];
  let plotData = cached || live;

  // 1. Locate relevant traces
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

  // 2. Accumulate multi-visit surface data
  if (plotDiv.id === 'surfacePlot' && allVisitTraces.length > 0) {
    const firstTrace = allVisitTraces[0].trace;
    let wavelengthData = firstTrace.y;
    if (Array.isArray(wavelengthData[0])) wavelengthData = wavelengthData.map(row => row[0]);

    let combinedTimeData = [];
    let combinedFluxData = [];
    let combinedErrData = [];

    const accumulateFrom = (traces) => {
      for (let k = 0; k < traces.length; k++) {
        const t = traces[k].trace || traces[k];
        if (!t || t.type !== 'surface') continue;
        let tx = t.x;
        if (Array.isArray(tx) && Array.isArray(tx[0])) tx = tx[0];
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
    };

    accumulateFrom(allVisitTraces);

    // Fallback: if cached data had no customdata, try live data
    if (combinedErrData.length === 0 && Array.isArray(live) && live.length) {
      const liveVisits = [];
      for (let i = 0; i < live.length; i++) {
        const t = live[i];
        if (t && t.type === 'surface' && !(String(t.name || '').includes('Gray'))) {
          liveVisits.push({ trace: t, index: i });
        }
      }
      if (liveVisits.length) {
        combinedTimeData = [];
        combinedFluxData = [];
        combinedErrData = [];
        accumulateFrom(liveVisits);
      }
    }

    mainTrace = {
      type: 'surface',
      x: combinedTimeData,
      y: wavelengthData,
      z: combinedFluxData,
      customdata: combinedErrData.length ? combinedErrData : null
    };
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

  // 3. Apply user-specified range filters
  let wlIndicesUsed = null;
  const ranges = window.__userRanges || {};

  // Wavelength range filter
  if (ranges.wavelengthRangeMin || ranges.wavelengthRangeMax) {
    const wlMin = ranges.wavelengthRangeMin ? parseFloat(ranges.wavelengthRangeMin) : -Infinity;
    const wlMax = ranges.wavelengthRangeMax ? parseFloat(ranges.wavelengthRangeMax) : Infinity;

    wlIndicesUsed = [];
    for (let i = 0; i < wavelengthData.length; i++) {
      if (wavelengthData[i] >= wlMin && wavelengthData[i] <= wlMax) {
        wlIndicesUsed.push(i);
      }
    }

    if (wlIndicesUsed.length > 0) {
      wavelengthData = wlIndicesUsed.map(i => wavelengthData[i]);
      fluxData = wlIndicesUsed.map(i => fluxData[i]);
      if (errData) errData = wlIndicesUsed.map(i => errData[i]);
    }
  }

  // Time range filter
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

  // 4. Find the clicked time/wavelength index
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

  // 5. Compute global min/max for Y-axis scaling
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

  // Apply reference spectrum filter if present
  let refSpec = Array.isArray(window.__referenceSpectrum) ? window.__referenceSpectrum.slice() : null;
  if (refSpec && wlIndicesUsed && wlIndicesUsed.length > 0) {
    refSpec = wlIndicesUsed.map(i => refSpec[i]);
  }

  // 6. Assemble spectrum data object
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
    referenceSpectrum: Array.isArray(refSpec) ? refSpec : null,
    lockedRibbonRange: null
  };

  currentSpectrumData.lockedRibbonRange = computeLockedRibbonRange(currentSpectrumData, null);

  // 7. Open viewer and render
  document.getElementById('spectrumContainer').classList.remove('hidden');
  updateSpectrumPlot();
  document.getElementById('spectrumContainer').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// Spectrum Plot Rendering

/**
 * Render the spectrum plot based on the current mode, band selection,
 * and error bar settings. Handles four rendering branches:
 * vs_wavelength +/- bands, vs_time +/- bands.
 */
function updateSpectrumPlot() {
  if (!currentSpectrumData) { return; }

  const wavelengths = currentSpectrumData.wavelengthData;
  const fluxData = currentSpectrumData.fluxData;
  const errData = currentSpectrumData.errorData;

  let values = [];
  let errors = [];
  let xAxisTitle = 'Wavelength (um)';
  let xValues = wavelengths;
  let infoPrimary = '';
  let infoIndex = 0;
  let infoTotal = 0;

  currentSpectrumData.bandAveraged = false;

  // Extract the 1-D slice based on current mode
  if (spectrumMode === 'vs_wavelength') {
    const currentTime = currentSpectrumData.timeData[currentTimeIndex];
    for (let i = 0; i < wavelengths.length; i++) {
      values.push((fluxData[i] && fluxData[i][currentTimeIndex] !== undefined) ? fluxData[i][currentTimeIndex] : NaN);
      errors.push((errData && errData[i] && errData[i][currentTimeIndex] !== undefined) ? errData[i][currentTimeIndex] :  NaN);
    }
    xAxisTitle = 'Wavelength (um)';
    xValues = wavelengths;
    infoPrimary = `Spectrum at Time:  ${currentTime.toFixed(2)} hours`;
    infoIndex = currentTimeIndex + 1;
    infoTotal = totalTimePoints;
  } else {
    const timeArray = currentSpectrumData.timeData || [];
    if (activeBands && activeBands.length >= 1) {
      // Band-averaged time series
      xAxisTitle = 'Time (hours)';
      xValues = timeArray;
      infoPrimary = activeBands.length === 1 ? `Band-integrated series: ${activeBands[0].name} (${activeBands[0].start.toFixed(2)}-${activeBands[0].end.toFixed(2)} um)` : `Band-integrated series (${activeBands.length} bands)`;
      infoIndex = 1;
      infoTotal = 1;
      currentSpectrumData.bandAveraged = true;
    } else {
      // Single wavelength time series
      const wlIdx = Math.max(0, Math.min(currentWavelengthIndex, wavelengths.length - 1));
      for (let j = 0; j < timeArray.length; j++) {
        values.push((fluxData[wlIdx] && fluxData[wlIdx][j] !== undefined) ? fluxData[wlIdx][j] : NaN);
        errors.push((errData && errData[wlIdx] && errData[wlIdx][j] !== undefined) ? errData[wlIdx][j] : NaN);
      }
      xAxisTitle = 'Time (hours)';
      xValues = timeArray;
      infoPrimary = `Series at Wavelength: ${wavelengths[wlIdx].toFixed(4)} um`;
      infoIndex = wlIdx + 1;
      infoTotal = totalWavelengthPoints;
    }
  }

  // Bail if no valid data (unless band-averaged mode which computes inline)
  if (! currentSpectrumData.bandAveraged) {
    const validValues = values.filter(v => !isNaN(v) && v !== null);
    if (validValues.length === 0) { return; }
  }

  // Y-axis label and formatting
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
      range: currentSpectrumData.lockedRibbonRange ?  currentSpectrumData.lockedRibbonRange : [currentSpectrumData.globalMin, currentSpectrumData.globalMax],
      tickformat: yTickFormat
    },
    margin: { l: 60, r: 40, t: 40, b: 60 },
    showlegend:  false
  };

  const showErrors = !! document.getElementById('toggleErrorBars') && document.getElementById('toggleErrorBars').checked === true;

  // Error sigma pass-through (reserved for future scaling logic)
  function sigmaFor(valuesArr, errsArr, wlIndexForTimeSeries = null) {
    if (!Array.isArray(errsArr) || ! errsArr.length) return errsArr;
    if (currentSpectrumData.bandAveraged && spectrumMode === 'vs_time') {
      return errsArr;
    }
    return errsArr;
  }

  // Branch 1: vs_wavelength + bands active
  if (spectrumMode === 'vs_wavelength') {
    if (activeBands && activeBands.length > 0) {
      const inMask = xValues.map((w) => activeBands.some(b => w >= b.start && w <= b.end));
      const inY = values.map((v, i) => inMask[i] ? v :  NaN);

      // Gray base trace (full spectrum, dimmed)
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

      // Colored in-band trace
      const spectrumIn = {
        x: xValues,
        y: inY,
        type: 'scatter',
        mode: 'lines',
        line: { color: '#3B82F6', width: 2 },
        name: 'In',
        hovertemplate: `Wavelength: %{x:.4f} um<br>${yAxisLabel}: %{y: ${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
      };

      const traces = [baseTrace, spectrumIn];

      // Segmented error ribbons (only within in-band regions)
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
            { x: xSeg, y:  upperSeg, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
            { x: xSeg, y:  lowerSeg, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps:  false }
          );
        }
      }

      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });

    // Branch 2: vs_wavelength + no bands
    } else {
      const spectrumTrace = {
        x: xValues,
        y:  values,
        type: 'scatter',
        mode: 'lines',
        line: { color: '#3B82F6', width: 2 },
        name: 'Spectrum',
        hovertemplate: `Wavelength: %{x:.4f} um<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
      };

      const traces = [spectrumTrace];

      // Full error ribbon
      if (showErrors) {
        const sigma = sigmaFor(values, errors);
        traces.push(
          { x: xValues, y: values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v + sigma[i] :  null), type: 'scatter', mode: 'lines', line:  { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
          { x:  xValues, y: values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v - sigma[i] : null), type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor:  'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false }
        );
      }

      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
    }

  // Branch 3: vs_time + bands active (band-averaged time series)
  } else {
    if (activeBands && activeBands.length >= 1) {
      const timeArray = xValues;
      const traces = [];
      const gapThresholdHours = 0.5;

      // Detect visit gaps for segmented rendering
      const segs = [];
      if (! currentSpectrumData.useInterpolation) {
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

      /** Convert hex color to rgba string. */
      function hexToRgba(hex, a) {
        const h = hex.replace('#', '');
        const r = parseInt(h.substring(0, 2), 16);
        const g = parseInt(h.substring(2, 4), 16);
        const b = parseInt(h.substring(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${a})`;
      }

      // Render each active band as a separate colored series
      for (let bi = 0; bi < activeBands.length; bi++) {
        const b = activeBands[bi];
        const col = bandColors[bi % bandColors.length];
        const fillCol = hexToRgba(col, 0.5);

        // Compute band-averaged flux and propagated error at each time point
        const y = [];
        const eArr = [];
        const hasErr = Array.isArray(errData) && errData.length;

        for (let j = 0; j < timeArray.length; j++) {
          let sum = 0, cnt = 0, esum = 0;

          for (let i = 0; i < wavelengths.length; i++) {
            const w = wavelengths[i];
            if (w >= b.start && w <= b.end) {
              const v = (fluxData[i] && fluxData[i][j] !== undefined) ? fluxData[i][j] : NaN;
              if (! isFinite(v)) continue;
              sum += v;
              cnt++;

              if (hasErr) {
                let sErr = (errData && errData[i] && errData[i][j] !== undefined) ? errData[i][j] : NaN;
                if (!isFinite(sErr)) continue;
                if (isFinite(sErr)) {
                  esum += sErr * sErr;
                }
              }
            }
          }

          y.push(cnt ?  (sum / cnt) : NaN);
          if (hasErr && cnt > 0 && esum > 0) {
            eArr.push(Math.sqrt(esum / cnt) / Math.sqrt(cnt));
          } else {
            eArr.push(NaN);
          }
        }

        // Render: segmented (gap-aware) or continuous (interpolated)
        if (! currentSpectrumData.useInterpolation) {
          segs.forEach(([a, bb], si) => {
            const xSeg = timeArray.slice(a, bb + 1);
            const ySeg = y.slice(a, bb + 1);
            const eSeg = eArr.slice(a, bb + 1);

            traces.push({
              x: xSeg,
              y: ySeg,
              type: 'scatter',
              mode: 'lines',
              name: b.name,
              connectgaps: false,
              showlegend: si === 0,
              line:  { color: col, width: 2 },
              legendgroup: `band_${bi}`,
              hovertemplate: `Time: %{x:.4f} hr<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
            });

            const hasFiniteErrors = eSeg.some(e => isFinite(e));

            if (showErrors && hasFiniteErrors) {
              const upperSeg = [];
              const lowerSeg = [];

              for (let k = 0; k < ySeg.length; k++) {
                if (isFinite(ySeg[k]) && isFinite(eSeg[k])) {
                  upperSeg.push(ySeg[k] + eSeg[k]);
                  lowerSeg.push(ySeg[k] - eSeg[k]);
                } else {
                  upperSeg.push(null);
                  lowerSeg.push(null);
                }
              }

              traces.push(
                {
                  x: xSeg,
                  y: upperSeg,
                  type: 'scatter',
                  mode:  'lines',
                  line: { width: 0 },
                  hoverinfo: 'skip',
                  showlegend: false,
                  connectgaps: false,
                  legendgroup: `band_${bi}`
                },
                {
                  x: xSeg,
                  y: lowerSeg,
                  type: 'scatter',
                  mode: 'lines',
                  fill:  'tonexty',
                  fillcolor: fillCol,
                  line: { width: 0 },
                  hoverinfo: 'skip',
                  showlegend:  false,
                  connectgaps: false,
                  legendgroup: `band_${bi}`
                }
              );
            }
          });
        } else {
          // Interpolated: single continuous trace per band
          traces.push({
            x: timeArray,
            y: y,
            type: 'scatter',
            mode: 'lines',
            name: b.name,
            line: { color: col, width:  2 },
            legendgroup: `band_${bi}`,
            hovertemplate: `Time: %{x:.4f} hr<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' : ''}<extra></extra>`
          });

          const hasFiniteErrors = eArr.some(e => isFinite(e));

          if (showErrors && hasFiniteErrors) {
            const upper = [];
            const lower = [];

            for (let k = 0; k < y.length; k++) {
              if (isFinite(y[k]) && isFinite(eArr[k])) {
                upper.push(y[k] + eArr[k]);
                lower.push(y[k] - eArr[k]);
              } else {
                upper.push(null);
                lower.push(null);
              }
            }

            traces.push(
              {
                x: timeArray,
                y: upper,
                type:  'scatter',
                mode:  'lines',
                line:  { width: 0 },
                hoverinfo: 'skip',
                showlegend: false,
                connectgaps: false,
                legendgroup: `band_${bi}`
              },
              {
                x: timeArray,
                y: lower,
                type: 'scatter',
                mode: 'lines',
                fill: 'tonexty',
                fillcolor: fillCol,
                line: { width:  0 },
                hoverinfo: 'skip',
                showlegend: false,
                connectgaps: false,
                legendgroup: `band_${bi}`
              }
            );
          }
        }
      }
      layout.showlegend = activeBands.length > 1;
      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });

    // Branch 4: vs_time + no bands (single wavelength time series)
    } else {
      const traces = [];
      const gapThresholdHours = 0.5;
      const xValuesTime = xValues;

      if (!currentSpectrumData.useInterpolation) {
        // Gap-aware segmentation
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
            hovertemplate: `Time: %{x:.4f} hr<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ?  ' %' : ''}<extra></extra>`,
            connectgaps: false,
            showlegend: false
          });

          if (showErrors) {
            const sigmaSeg = sigmaFor(ySeg, errors.slice(a, b + 1), currentWavelengthIndex);
            const upperSeg = ySeg.map((v, i) => (isFinite(v) && isFinite(sigmaSeg[i])) ? v + sigmaSeg[i] : null);
            const lowerSeg = ySeg.map((v, i) => (isFinite(v) && isFinite(sigmaSeg[i])) ? v - sigmaSeg[i] : null);
            traces.push(
              { x: xSeg, y:  upperSeg, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
              { x: xSeg, y:  lowerSeg, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps:  false }
            );
          }
        });
      } else {
        // Interpolated: single continuous trace
        const spectrumTrace = {
          x: xValuesTime,
          y: values,
          type:  'scatter',
          mode:  'lines',
          line:  { color: '#3B82F6', width: 2 },
          name: 'Series',
          hovertemplate:  `Time: %{x:.4f} hr<br>${yAxisLabel}: %{y:${hoverFormat}}${currentSpectrumData.zAxisDisplay === 'variability' ? ' %' :  ''}<extra></extra>`
        };
        traces.push(spectrumTrace);

        if (showErrors) {
          const sigma = sigmaFor(values, errors, currentWavelengthIndex);
          const upper = values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v + sigma[i] : null);
          const lower = values.map((v, i) => (isFinite(v) && isFinite(sigma[i])) ? v - sigma[i] : null);
          traces.push(
            { x: xValuesTime, y:  upper, type: 'scatter', mode: 'lines', line:  { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false },
            { x:  xValuesTime, y: lower, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor:  'rgba(239, 68, 68, 0.20)', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, connectgaps: false }
          );
        }
      }

      Plotly.newPlot('spectrumPlot', traces, layout, { responsive: true });
    }
  }

  // Update info text
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

  // Update navigation button states
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

// Spectrum Navigation

/**
 * Step through time or wavelength indices. Respects band-eligible indices.
 * @param {number} step - +1 for next, -1 for previous.
 */
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

/**
 * Close the spectrum viewer panel and reset its state.
 */
function closeSpectrumViewer() {
  if (isAnimating) {
    toggleAnimation();
  }
  document.getElementById('spectrumContainer').classList.add('hidden');
  currentSpectrumData = null;
}

// Helpers

/**
 * Return a Promise that resolves after the next animation frame.
 * @returns {Promise<void>}
 */
function nextAnimationFrame() {
  return new Promise(resolve => requestAnimationFrame(() => resolve()));
}

/**
 * Ensure spectrum data is initialized before operations that depend on it.
 * If none loaded, extracts one from the first time point of the available plot.
 * @returns {Promise<void>}
 * @throws {Error} If no plots are ready yet.
 */
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
  const origData = (plotOriginal[sourceDiv.id] && plotOriginal[sourceDiv.id].length) ? plotOriginal[sourceDiv.id] : sourceDiv.data;
  for (let i = 0; i < origData.length; i++) {
    const tr = origData[i];
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

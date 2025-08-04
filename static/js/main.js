// Animation state variables
let isAnimating = false;
let animationInterval = null;
let animationSpeed = 5;

// Updated plot creation without auto-download
function createPlot(plotId, data, layout, config) {
  const div = document.getElementById(plotId);

  // Enhanced config to ensure proper initial rendering
  const enhancedConfig = {
    ...config,
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
    toImageButtonOptions: {
      format: 'png',
      width: 1200,
      height: 800,
      scale: 2
    }
  };

  Plotly.newPlot(div, data, layout, enhancedConfig).then(() => {
    // Force a resize to ensure proper initial rendering
    window.dispatchEvent(new Event('resize'));

    // Setup click handlers after plot is created
    if (plotId === 'surfacePlot' || plotId === 'heatmapPlot') {
      setupPlotClickHandler(div);
    }
  });
}

document.addEventListener('DOMContentLoaded', function() {
  // Event listeners
  document.getElementById('addBandBtn').addEventListener('click', () => addCustomBand());
  document.getElementById('uploadMastBtn').addEventListener('click', uploadMastDirectory);
  document.getElementById('resetSurfaceViewBtn').addEventListener('click', () => resetPlotView('surfacePlot'));
  document.getElementById('resetHeatmapViewBtn').addEventListener('click', () => resetPlotView('heatmapPlot'));

  // Spectrum viewer controls
  document.getElementById('closeSpectrumBtn').addEventListener('click', closeSpectrumViewer);
  document.getElementById('prevSpectrumBtn').addEventListener('click', () => navigateSpectrum(-1));
  document.getElementById('nextSpectrumBtn').addEventListener('click', () => navigateSpectrum(1));

  // Animation controls
  document.getElementById('playAnimationBtn').addEventListener('click', toggleAnimation);
  document.getElementById('animationSpeed').addEventListener('input', (e) => updateAnimationSpeed(e.target.value));

  // Initialize color scales
  initializeColorScales();

  // Add default bands
  addCustomBand('CH₄ Band', 2.14, 2.50);
  addCustomBand('CO Band', 4.50, 5.05);
});

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
           class="flex-grow px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-gray-100
                  focus:outline-none focus:ring-2 focus:ring-blue-500" />
    <input type="number" step="0.01" placeholder="Start" value="${start}"
           class="w-24 px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-gray-100
                  focus:outline-none focus:ring-2 focus:ring-blue-500" />
    <input type="number" step="0.01" placeholder="End" value="${end}"
           class="w-24 px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-gray-100
                  focus:outline-none focus:ring-2 focus:ring-blue-500" />
    <button class="px-3 py-2 bg-red-600 text-gray-100 rounded-md hover:bg-red-700 transition duration-200">
      Remove
    </button>
  `;

  document.getElementById('customBands').appendChild(bandContainer);

  bandContainer.querySelector('button').addEventListener('click', () => {
    bandContainer.remove();
  });
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
  if (!mastZipFile) {
    alert('Please select a MAST ZIP file before processing.');
    return;
  }

  const formData = new FormData();
  formData.append('mast_zip', mastZipFile);

  // Get colorscale
  const selectedColorscale = document.querySelector('.colorscale-option.selected');
  if (!selectedColorscale) {
    alert('Please select a color scale.');
    return;
  }
  formData.append('colorscale', selectedColorscale.getAttribute('data-colorscale'));

  // Get interpolation preference
  const useInterpolation = document.getElementById('linearInterpolation').checked;
  formData.append('use_interpolation', useInterpolation);

  // Get number of integrations
  const numIntegrations = document.getElementById('numIntegrations').value;
  formData.append('num_integrations', numIntegrations || '0');  // 0 means plot all

  // Get range values
  const timeRangeMin = document.getElementById('timeRangeMin').value;
  const timeRangeMax = document.getElementById('timeRangeMax').value;
  const wavelengthRangeMin = document.getElementById('wavelengthRangeMin').value;
  const wavelengthRangeMax = document.getElementById('wavelengthRangeMax').value;
  const variabilityRangeMin = document.getElementById('variabilityRangeMin').value;
  const variabilityRangeMax = document.getElementById('variabilityRangeMax').value;

  // Get Z-axis display option
  const zAxisDisplay = document.querySelector('input[name="zAxisDisplay"]:checked').value;

  // Add range values to form data
  formData.append('time_range_min', timeRangeMin || '');
  formData.append('time_range_max', timeRangeMax || '');
  formData.append('wavelength_range_min', wavelengthRangeMin || '');
  formData.append('wavelength_range_max', wavelengthRangeMax || '');
  formData.append('variability_range_min', variabilityRangeMin || '');
  formData.append('variability_range_max', variabilityRangeMax || '');
  formData.append('z_axis_display', zAxisDisplay);

  // Extract custom bands
  const customBands = Array.from(document.getElementById('customBands').children).map(band => {
    const inputs = band.querySelectorAll('input');
    return {
      name:  inputs[0].value.trim(),
      start: parseFloat(inputs[1].value),
      end:   parseFloat(inputs[2].value)
    };
  }).filter(b => b.name && !isNaN(b.start) && !isNaN(b.end));
  formData.append('custom_bands', JSON.stringify(customBands));

  // Show loading state
  const uploadBtn = document.getElementById('uploadMastBtn');
  const originalText = uploadBtn.textContent;
  uploadBtn.textContent = 'Processing...';
  uploadBtn.disabled = true;

  try {
    const response = await fetch('/upload_mast', {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
    }

    const data = await response.json();
    if (data.error) {
      throw new Error(data.error);
    }

    const surfaceData = JSON.parse(data.surface_plot);
    const heatmapData = JSON.parse(data.heatmap_plot);

    // Display metadata
    if (data.metadata) {
      displayMetadata(data.metadata);
    }

    // Render plots without auto-download
    createPlot(
      'surfacePlot',
      surfaceData.data,
      surfaceData.layout,
      { responsive: true }
    );

    createPlot(
      'heatmapPlot',
      heatmapData.data,
      heatmapData.layout,
      { responsive: true }
    );

    // Log to confirm plots are rendered
    console.log('Plots rendered successfully');

    document.getElementById('plotsContainer').classList.remove('hidden');
    document.getElementById('plotsContainer').scrollIntoView({ behavior: 'smooth' });
  } catch (error) {
    console.error('Error processing MAST folder:', error);
    alert('Error processing MAST folder: ' + error.message);
  } finally {
    uploadBtn.textContent = originalText;
    uploadBtn.disabled = false;
  }
}

function updatePlotLayout(plotId, updates) {
  Plotly.update(plotId, {}, updates);
}

function resetPlotView(plotId) {
  if (plotId === 'surfacePlot') {
    updatePlotLayout(plotId, {
      'scene.camera': { eye: { x: 1.5, y: 1.5, z: 1.3 } }
    });
  } else if (plotId === 'heatmapPlot') {
    Plotly.relayout(plotId, {
      'xaxis.autorange': true,
      'yaxis.autorange': true
    });
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
  console.log('showSpectrumAtTime called with:', clickData);

  // Get the actual plot data
  const plotData = plotDiv.data;

  // Find the main data trace (not gray mask or bands)
  let mainTrace = null;
  let traceIndex = -1;

  // For surface plots, we need to find all visit traces
  let allVisitTraces = [];

  for (let i = 0; i < plotData.length; i++) {
    const trace = plotData[i];
    // Skip invisible traces and gray masks
    if (trace.visible !== false && !trace.name.includes('Gray')) {
      if (plotDiv.id === 'surfacePlot' && trace.type === 'surface') {
        // For surface plots, collect all visit traces
        if (trace.name.includes('Visit') || trace.name === 'Full Observation') {
          allVisitTraces.push({trace: trace, index: i});
        }
      } else if (plotDiv.id === 'heatmapPlot' && trace.type === 'heatmap') {
        // For heatmap, just get the main trace
        mainTrace = trace;
        traceIndex = i;
        break;
      }
    }
  }

  // For surface plots with multiple visits, combine data from all visits
  if (plotDiv.id === 'surfacePlot' && allVisitTraces.length > 0) {
    console.log('Found', allVisitTraces.length, 'visit traces');

    // Combine data from all visits
    let combinedWavelengthData = [];
    let combinedTimeData = [];
    let combinedFluxData = [];

    // Get wavelength data from first visit (should be same for all)
    const firstTrace = allVisitTraces[0].trace;
    if (Array.isArray(firstTrace.y[0])) {
      combinedWavelengthData = firstTrace.y.map(row => row[0]);
    } else {
      combinedWavelengthData = firstTrace.y;
    }

    // Combine time and flux data from all visits
    for (let visitData of allVisitTraces) {
      const trace = visitData.trace;

      // Extract time data
      let visitTimeData = trace.x;
      if (Array.isArray(visitTimeData[0])) {
        visitTimeData = visitTimeData[0];
      }

      // Add to combined arrays
      combinedTimeData = combinedTimeData.concat(visitTimeData);

      // For flux data, we need to combine columns
      if (combinedFluxData.length === 0) {
        // Initialize with first visit's data
        combinedFluxData = trace.z.map(row => [...row]);
      } else {
        // Append columns from this visit
        for (let i = 0; i < trace.z.length; i++) {
          combinedFluxData[i] = combinedFluxData[i].concat(trace.z[i]);
        }
      }
    }

    // Create a synthetic mainTrace with combined data
    mainTrace = {
      type: 'surface',
      x: combinedTimeData,
      y: combinedWavelengthData,
      z: combinedFluxData,
      name: 'Combined'
    };

    console.log('Combined data - Time points:', combinedTimeData.length);
    console.log('Combined data - Wavelengths:', combinedWavelengthData.length);
    console.log('Combined data - Flux dimensions:', combinedFluxData.length, 'x', combinedFluxData[0]?.length);
  }

  if (!mainTrace && plotDiv.id === 'surfacePlot') {
    // Fallback for single visit or continuous observation
    mainTrace = allVisitTraces[0]?.trace;
  }

  if (!mainTrace) {
    console.error('Could not find main trace');
    return;
  }

  // Get click coordinates
  const clickX = clickData.x;
  const clickY = clickData.y;

  console.log('Click coordinates - X:', clickX, 'Y:', clickY);

  // Extract all the necessary data from the main trace
  let wavelengthData, timeData, fluxData;

  if (mainTrace.type === 'surface') {
    // For surface plots
    wavelengthData = mainTrace.y; // Y axis is wavelength
    timeData = mainTrace.x; // X axis is time
    fluxData = mainTrace.z; // Z axis is flux/variability

    // Handle 2D arrays for surface plots
    if (Array.isArray(wavelengthData[0])) {
      // Extract from first column
      wavelengthData = wavelengthData.map(row => row[0]);
    }
    if (Array.isArray(timeData[0])) {
      // Extract from first row
      timeData = timeData[0];
    }
  } else if (mainTrace.type === 'heatmap') {
    // For heatmap plots
    wavelengthData = mainTrace.y; // Y axis is wavelength
    timeData = mainTrace.x; // X axis is time
    fluxData = mainTrace.z; // Z axis is flux/variability
  }

  // Find the closest time index
  let timeIndex = 0;
  let minDiff = Infinity;

  for (let i = 0; i < timeData.length; i++) {
    const diff = Math.abs(timeData[i] - clickX);
    if (diff < minDiff) {
      minDiff = diff;
      timeIndex = i;
    }
  }

  totalTimePoints = timeData.length;
  currentTimeIndex = timeIndex;

  console.log('Time index:', currentTimeIndex, 'of', totalTimePoints);
  console.log('Wavelength data length:', wavelengthData.length);
  console.log('Flux data dimensions:', fluxData.length, 'x', fluxData[0] ? fluxData[0].length : 0);

  // Calculate global min/max for fixed y-axis range
  let globalMin = Infinity;
  let globalMax = -Infinity;

  for (let i = 0; i < fluxData.length; i++) {
    for (let j = 0; j < fluxData[i].length; j++) {
      const val = fluxData[i][j];
      if (!isNaN(val) && val !== null) {
        globalMin = Math.min(globalMin, val);
        globalMax = Math.max(globalMax, val);
      }
    }
  }

  console.log('Global flux range for fixed y-axis:', globalMin, 'to', globalMax);

  // Get the current Z-axis display mode to determine how to interpret the data
  const zAxisDisplay = document.querySelector('input[name="zAxisDisplay"]:checked').value;

  // Store the current data for navigation
  currentSpectrumData = {
    wavelengthData: wavelengthData,
    timeData: timeData,
    fluxData: fluxData,
    plotType: mainTrace.type,
    clickedTime: timeData[timeIndex],
    useInterpolation: document.getElementById('linearInterpolation').checked,
    globalMin: globalMin,
    globalMax: globalMax,
    zAxisDisplay: zAxisDisplay
  };

  // Show the spectrum container
  document.getElementById('spectrumContainer').classList.remove('hidden');

  // Update the spectrum plot
  updateSpectrumPlot();

  // Scroll to spectrum view
  document.getElementById('spectrumContainer').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// Function to update spectrum plot
function updateSpectrumPlot() {
  if (!currentSpectrumData) {
    console.error('No spectrum data available');
    return;
  }

  console.log('updateSpectrumPlot called');
  console.log('Current time index:', currentTimeIndex);
  console.log('Use interpolation:', currentSpectrumData.useInterpolation);
  console.log('Z-axis display mode:', currentSpectrumData.zAxisDisplay);

  const wavelengths = currentSpectrumData.wavelengthData;
  const fluxData = currentSpectrumData.fluxData;
  const currentTime = currentSpectrumData.timeData[currentTimeIndex];

  // Extract spectrum values at this time point
  let values = [];

  try {
    // Extract column at currentTimeIndex
    for (let i = 0; i < wavelengths.length; i++) {
      if (fluxData[i] && fluxData[i][currentTimeIndex] !== undefined) {
        values.push(fluxData[i][currentTimeIndex]);
      } else {
        values.push(NaN);
      }
    }

    console.log('Extracted', values.length, 'values');
    console.log('First few values:', values.slice(0, 5));

    // Filter out NaN values for range calculation
    const validValues = values.filter(v => !isNaN(v) && v !== null);
    if (validValues.length > 0) {
      console.log('Values range:', Math.min(...validValues), 'to', Math.max(...validValues));
    }

  } catch (error) {
    console.error('Error extracting spectrum data:', error);
    return;
  }

  // Check if we have valid data
  const validValues = values.filter(v => !isNaN(v) && v !== null);
  if (validValues.length === 0) {
    console.error('All extracted values are NaN or null');
    // Try to debug the data structure
    console.log('Flux data structure check:');
    console.log('Total wavelengths:', wavelengths.length);
    console.log('Total time points:', currentSpectrumData.timeData.length);
    console.log('Flux data rows:', fluxData.length);
    console.log('Flux data cols (first row):', fluxData[0] ? fluxData[0].length : 0);
    console.log('Current time index:', currentTimeIndex);
    return;
  }

  // FIXED: Use the values directly as they come from the plot (already properly scaled)
  // No additional scaling needed - the values are already processed correctly by the backend
  let yAxisLabel, hoverFormat;

  if (currentSpectrumData.zAxisDisplay === 'flux') {
    // For flux mode, use values directly
    yAxisLabel = 'Flux';

    // Determine format based on flux scale
    const flux_max = Math.max(...validValues.map(v => Math.abs(v)));
    if (flux_max < 0.01 || flux_max > 1000) {
      hoverFormat = '.2e';
    } else {
      hoverFormat = '.4f';
    }
  } else {
    // For variability mode, use values directly (they're already scaled properly)
    yAxisLabel = 'Variability (%)';
    hoverFormat = '.4f';
  }

  console.log('Using values directly (no additional scaling)');
  console.log('Values range:', Math.min(...validValues), 'to', Math.max(...validValues));

  // Create 1D plot
  const spectrumTrace = {
    x: wavelengths,
    y: values,  // Use values directly, no scaling
    type: 'scatter',
    mode: 'lines',
    line: {
      color: '#3B82F6',
      width: 2
    },
    name: 'Spectrum',
    hovertemplate: 'Wavelength: %{x:.4f} µm<br>' + yAxisLabel + ': %{y:' + hoverFormat + '}<extra></extra>'
  };

  // Use fixed y-axis range that matches the 3D plot's z-axis range
  // This ensures consistent scale across all spectrum views
  const paddedYMin = currentSpectrumData.globalMin;
  const paddedYMax = currentSpectrumData.globalMax;

  const layout = {
    template: "plotly_dark",
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#ffffff' },
    xaxis: {
      title: 'Wavelength (µm)',
      gridcolor: '#555555',
      linecolor: '#555555',
      zeroline: false
    },
    yaxis: {
      title: yAxisLabel,
      gridcolor: '#555555',
      linecolor: '#555555',
      zeroline: false,
      range: [paddedYMin, paddedYMax],
      tickformat: currentSpectrumData.zAxisDisplay === 'flux' && hoverFormat === '.2e' ? '.2e' : undefined
    },
    margin: { l: 60, r: 40, t: 40, b: 60 },
    showlegend: false
  };

  console.log('Creating plot with', wavelengths.length, 'wavelengths and', values.length, 'values');
  console.log('Y-axis range:', paddedYMin, 'to', paddedYMax);
  console.log('Y-axis label:', yAxisLabel);

  Plotly.newPlot('spectrumPlot', [spectrumTrace], layout, { responsive: true });

  // Update title and info
  document.getElementById('spectrumTitle').textContent = `Spectrum at Time: ${currentTime.toFixed(2)} hours`;
  document.getElementById('spectrumInfo').textContent = `Time point ${currentTimeIndex + 1} of ${totalTimePoints}`;

  // Enable/disable navigation buttons
  document.getElementById('prevSpectrumBtn').disabled = currentTimeIndex <= 0;
  document.getElementById('nextSpectrumBtn').disabled = currentTimeIndex >= totalTimePoints - 1;
}

// Function to navigate through time points
function navigateSpectrum(direction) {
  const newIndex = currentTimeIndex + direction;
  if (newIndex >= 0 && newIndex < totalTimePoints) {
    currentTimeIndex = newIndex;
    updateSpectrumPlot();
  }
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
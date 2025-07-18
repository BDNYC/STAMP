/*******************************************************
 * main.js - Spectrum Analyzer Frontend Interactions
 * -----------------------------------------------------
 * Contains:
 *  - DOM event listeners for buttons & file inputs
 *  - Functions to generate and reset Plotly plots
 *  - Functions to upload & process MAST directories
 *  - AUTO-DOWNLOAD of each plot's HTML upon rendering
 *******************************************************/

/**
 * Immediately download a Plotly div as HTML after rendering.
 *
 * Requires Plotly >= 2.4.0 for Plotly.Plots.to_html.
 *
 * @param {HTMLElement} plotDiv - The <div> element containing a rendered Plotly figure.
 * @param {string} filename - Desired filename (without .html extension).
 */
function autoDownloadPlotHTML(plotDiv, filename) {
  // 1. Convert the current plot to an HTML string
  //    Plotly >= 2.4.0 supports Plotly.Plots.to_html(plotDiv)
  const htmlString = Plotly.Plots.to_html(plotDiv, { responsive: true });

  // 2. Convert that HTML string into a Blob
  const blob = new Blob([htmlString], { type: "text/html;charset=utf-8" });

  // 3. Create a temporary link to download the Blob
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename + ".html";

  // 4. Trigger the download
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Helper that wraps Plotly.newPlot(...) with a .then(...) callback
 * to automatically download the rendered plot as an HTML file.
 *
 * @param {string} plotId - The DOM element ID for the target plot div.
 * @param {object[]} data - Plotly data array (parsed from the server).
 * @param {object} layout - Plotly layout object (parsed from the server).
 * @param {object} config - Plotly config object (e.g. { responsive: true }).
 * @param {string} filename - Base filename to use when downloading.
 */
function newPlotAndDownload(plotId, data, layout, config, filename) {
  const div = document.getElementById(plotId);
  Plotly.newPlot(div, data, layout, config).then(() => {
    // Once rendering completes, auto-download the HTML
    autoDownloadPlotHTML(div, filename);
  });
}

document.addEventListener('DOMContentLoaded', function() {
  // ===================================
  // Event Listeners for UI Interactions
  // ===================================
  document.getElementById('addBandBtn').addEventListener('click', () => addCustomBand());
  document.getElementById('generatePlotsBtn').addEventListener('click', generatePlots);

  document.getElementById('resetSurfaceViewBtn').addEventListener('click', () => resetPlotView('surfacePlot'));
  document.getElementById('resetHeatmapViewBtn').addEventListener('click', () => resetPlotView('heatmapPlot'));

  // Additional MAST Upload Functionality
  const uploadMastBtn = document.getElementById('uploadMastBtn');
  const mastZipFileInput = document.getElementById('mastZipFile');
  if (uploadMastBtn && mastZipFileInput) {
    uploadMastBtn.addEventListener('click', uploadMastDirectory);
  }

  // Initialize color scale selection
  initializeColorScales();

  // Optionally add some default/preset bands:
  addCustomBand('CH₄ Band', 2.14, 2.50);
  addCustomBand('CO Band', 4.50, 5.05);
});

/**
 * Available color scales to show in the UI.
 * (You can add or remove from this array as desired.)
 */
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

/**
 * Create color scale swatches in the UI and select the first by default.
 */
function initializeColorScales() {
  const container = document.getElementById('colorscaleSelector');
  colorScales.forEach((scale, index) => {
    const option = document.createElement('div');
    option.className = `colorscale-option ${scale.class}`;
    option.setAttribute('data-colorscale', scale.name);
    option.title = scale.name;

    // Clicking an option selects it
    option.addEventListener('click', () => selectColorScale(option));

    container.appendChild(option);

    // Select the first color scale by default
    if (index === 0) selectColorScale(option);
  });
}

/**
 * Highlight the chosen color scale and unselect others.
 */
function selectColorScale(selectedOption) {
  document.querySelectorAll('.colorscale-option').forEach(option => {
    option.classList.remove('selected');
  });
  selectedOption.classList.add('selected');
}

/**
 * Dynamically add a custom band row to the UI.
 * @param {string} [name] - Optional band name
 * @param {number} [start] - Optional band start
 * @param {number} [end] - Optional band end
 */
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

  // Remove a custom band row
  bandContainer.querySelector('button').addEventListener('click', () => {
    bandContainer.remove();
  });
}

/**
 * Generate plots by sending the FITS files and options to the Flask `/upload` endpoint.
 */
async function generatePlots() {
  const formData = new FormData();
  const fluxFile = document.getElementById('fluxFile').files[0];
  const wavelengthFile = document.getElementById('wavelengthFile').files[0];
  const timeFile = document.getElementById('timeFile').files[0];

  if (!fluxFile || !wavelengthFile || !timeFile) {
    alert('Please upload all required FITS files (flux, wavelength, time).');
    return;
  }

  formData.append('flux', fluxFile);
  formData.append('wavelength', wavelengthFile);
  formData.append('time', timeFile);
  formData.append('num_plots', document.getElementById('numPlots').value);

  // Get the selected color scale
  const selectedColorscale = document.querySelector('.colorscale-option.selected');
  if (!selectedColorscale) {
    alert('Please select a color scale.');
    return;
  }
  formData.append('colorscale', selectedColorscale.getAttribute('data-colorscale'));

  // Extract custom bands from the UI
  const customBands = Array.from(document.getElementById('customBands').children).map(band => {
    const inputs = band.querySelectorAll('input');
    return {
      name:  inputs[0].value.trim(),
      start: parseFloat(inputs[1].value),
      end:   parseFloat(inputs[2].value)
    };
  }).filter(b => b.name && !isNaN(b.start) && !isNaN(b.end));
  formData.append('custom_bands', JSON.stringify(customBands));

  try {
    const response = await fetch('/upload', {
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

    // The returned JSON has "surface_plot" and "heatmap_plot" as Plotly.to_json() outputs
    const surfaceData = JSON.parse(data.surface_plot);
    const heatmapData = JSON.parse(data.heatmap_plot);

    // Plot the data & auto-download HTML once rendering completes
    newPlotAndDownload(
      'surfacePlot',
      surfaceData.data,
      surfaceData.layout,
      { responsive: true },
      'surface_plot'
    );

    newPlotAndDownload(
      'heatmapPlot',
      heatmapData.data,
      heatmapData.layout,
      { responsive: true },
      'heatmap_plot'
    );

    // Scroll to where the plots are displayed
    document.getElementById('plotsContainer').scrollIntoView({ behavior: 'smooth' });
  } catch (error) {
    console.error('Error generating plots:', error);
    alert('Error generating plots: ' + error.message);
  }
}

/**
 * Process a zipped MAST folder by sending it to the `/upload_mast` endpoint,
 * along with any custom bands from the UI.
 */
async function uploadMastDirectory() {
  const mastZipFile = document.getElementById('mastZipFile').files[0];
  if (!mastZipFile) {
    alert('Please select a MAST ZIP file before processing.');
    return;
  }

  const formData = new FormData();
  formData.append('mast_zip', mastZipFile);

  // Extract custom bands from the UI (exact same approach):
  const customBands = Array.from(document.getElementById('customBands').children).map(band => {
    const inputs = band.querySelectorAll('input');
    return {
      name:  inputs[0].value.trim(),
      start: parseFloat(inputs[1].value),
      end:   parseFloat(inputs[2].value)
    };
  }).filter(b => b.name && !isNaN(b.start) && !isNaN(b.end));
  formData.append('custom_bands', JSON.stringify(customBands));

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

    // Same structure: "surface_plot" and "heatmap_plot" in JSON
    const surfaceData = JSON.parse(data.surface_plot);
    const heatmapData = JSON.parse(data.heatmap_plot);

    // Render & auto-download HTML
    newPlotAndDownload(
      'surfacePlot',
      surfaceData.data,
      surfaceData.layout,
      { responsive: true },
      'surface_plot_mast'
    );

    newPlotAndDownload(
      'heatmapPlot',
      heatmapData.data,
      heatmapData.layout,
      { responsive: true },
      'heatmap_plot_mast'
    );

    // Scroll to where the plots are displayed
    document.getElementById('plotsContainer').scrollIntoView({ behavior: 'smooth' });
  } catch (error) {
    console.error('Error processing MAST folder:', error);
    alert('Error processing MAST folder: ' + error.message);
  }
}

/**
 * Update the layout of a plot using Plotly.update().
 * @param {string} plotId - The ID of the <div> containing the Plotly figure.
 * @param {object} updates - Layout updates to apply.
 */
function updatePlotLayout(plotId, updates) {
  Plotly.update(plotId, {}, updates);
}

/**
 * Reset the view for either the 3D surface plot or the heatmap.
 */
function resetPlotView(plotId) {
  if (plotId === 'surfacePlot') {
    // Reset 3D surface camera
    updatePlotLayout(plotId, {
      'scene.camera': { eye: { x: 1.5, y: 1.5, z: 1.3 } }
    });
  } else if (plotId === 'heatmapPlot') {
    // Reset heatmap axes
    Plotly.relayout(plotId, {
      'xaxis.autorange': true,
      'yaxis.autorange': true
    });
  }
}

/**
 * (Optional) Example of how you could track user interactions (camera/zoom) on each plot
 * so you can preserve them if needed. Currently, we just show how one might update the layout
 * if the user changes the camera or axis range.
 */
document.getElementById('surfacePlot').on('plotly_relayout', function(eventData) {
  if (eventData['scene.camera']) {
    updatePlotLayout('surfacePlot', { 'scene.camera': eventData['scene.camera'] });
  }
});

document.getElementById('heatmapPlot').on('plotly_relayout', function(eventData) {
  if (eventData['xaxis.range[0]'] || eventData['yaxis.range[0]']) {
    updatePlotLayout('heatmapPlot', {
      'xaxis.range': [eventData['xaxis.range[0]'], eventData['xaxis.range[1]']],
      'yaxis.range': [eventData['yaxis.range[0]'], eventData['yaxis.range[1]']]
    });
  }
});
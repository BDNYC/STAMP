// main-state.js - Shared State, Constants & Event Binding

// Animation State

/** @type {boolean} */
let isAnimating = false;

/** @type {number|null} setInterval ID for the active animation loop */
let animationInterval = null;

/** @type {number} Playback speed in frames per second */
let animationSpeed = 5;

// Band Filtering State

/** @type {Array<{id:string, name:string, start:number, end:number}>} */
let activeBands = [];

/**
 * Caches unfiltered Plotly data so band filtering can toggle without re-fetching.
 * @type {{surfacePlot: Array|null, heatmapPlot: Array|null}}
 */
const plotOriginal = { surfacePlot: null, heatmapPlot: null };

// Video Export Constants

/** @type {number} */
const VIDEO_FPS = 12;

/** @type {number} */
const VIDEO_MAX_FRAMES = 600;

/** @type {number} */
const VIDEO_WIDTH = 1600;

/** @type {number} */
const VIDEO_HEIGHT = 400;

/** @type {number} FFmpeg CRF quality (lower = better quality, larger file) */
const VIDEO_CRF = 20;

// Backend Job Polling State

/** @type {number|null} */
let __progressTimer = null;

/** @type {string|null} */
let __currentJobId = null;

// Spectrum Viewer State

/** @type {'vs_wavelength'|'vs_time'} */
let spectrumMode = 'vs_wavelength';

/** @type {Object|null} */
let currentSpectrumData = null;

/** @type {number} Current time-point index (when plotting vs wavelength) */
let currentTimeIndex = 0;

/** @type {number} */
let totalTimePoints = 0;

/** @type {number} Current wavelength index (when plotting vs time) */
let currentWavelengthIndex = 0;

/** @type {number} */
let totalWavelengthPoints = 0;

// Color Scales

/** @type {Array<{name:string, class:string}>} */
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

// DOMContentLoaded - Bind all UI event listeners

/**
 * Master initialization handler. Binds every button/input to its handler
 * and initializes default UI state.
 */
document.addEventListener('DOMContentLoaded', function() {
  initializeDemoData();
  setupDemoDataHandlers();

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

  addCustomBand('CH\u2084 Band', 2.14, 2.50);
  addCustomBand('CO Band', 4.50, 5.05);
  renderBandButtons();

  const dl = document.querySelector('a[href="/download_plots"]');
  if (dl) dl.addEventListener('click', downloadAllWithVideo);

  const tsm = document.getElementById('toggleSpectrumModeBtn');
  if (tsm) tsm.addEventListener('click', toggleSpectrumMode);
});

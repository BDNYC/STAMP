/*
 * ============================================================================
 * main-state.js — Shared State, Constants & Event Binding
 * ============================================================================
 *
 * Loaded FIRST among the main-*.js files. Defines every shared mutable
 * variable and constant that the other modules read/write at runtime, plus
 * the DOMContentLoaded handler that wires up all UI event listeners.
 *
 * No domain functions are defined here. All referenced functions
 * (addCustomBand, renderBandButtons, uploadMastDirectory, etc.) are defined
 * in later files and resolve at runtime when the callbacks fire, not at
 * parse time.
 *
 * Load order:
 *   main-state.js → main-plots.js → main-spectrum.js
 *                → main-upload.js → main-export.js
 * ============================================================================
 */

// ---------------------------------------------------------------------------
// Animation State
// ---------------------------------------------------------------------------

/** @type {boolean} Whether the spectrum animation is currently playing */
let isAnimating = false;

/** @type {number|null} setInterval ID for the active animation loop */
let animationInterval = null;

/** @type {number} Playback speed in frames per second */
let animationSpeed = 5;

// ---------------------------------------------------------------------------
// Band Filtering State
// ---------------------------------------------------------------------------

/** @type {Array<{id:string, name:string, start:number, end:number}>} Currently active spectral bands */
let activeBands = [];

/**
 * Caches the original (unfiltered) Plotly data for each plot so band
 * filtering can be toggled without re-fetching from the server.
 * @type {{surfacePlot: Array|null, heatmapPlot: Array|null}}
 */
const plotOriginal = { surfacePlot: null, heatmapPlot: null };

// ---------------------------------------------------------------------------
// Video Export Constants
// ---------------------------------------------------------------------------

/** @type {number} Video frame rate (frames per second) */
const VIDEO_FPS = 12;

/** @type {number} Maximum frames to capture for a video */
const VIDEO_MAX_FRAMES = 600;

/** @type {number} Video frame width in pixels */
const VIDEO_WIDTH = 1600;

/** @type {number} Video frame height in pixels */
const VIDEO_HEIGHT = 400;

/** @type {number} FFmpeg CRF quality (lower = better quality, larger file) */
const VIDEO_CRF = 20;

// ---------------------------------------------------------------------------
// Backend Job Polling State
// ---------------------------------------------------------------------------

/** @type {number|null} setInterval ID for progress polling */
let __progressTimer = null;

/** @type {string|null} Current backend job ID for async processing */
let __currentJobId = null;

// ---------------------------------------------------------------------------
// Spectrum Viewer State
// ---------------------------------------------------------------------------

/** @type {'vs_wavelength'|'vs_time'} Which axis the spectrum X-axis represents */
let spectrumMode = 'vs_wavelength';

/** @type {Object|null} Cached spectrum data extracted from the surface/heatmap */
let currentSpectrumData = null;

/** @type {number} Current time-point index (when plotting vs wavelength) */
let currentTimeIndex = 0;

/** @type {number} Total available time points */
let totalTimePoints = 0;

/** @type {number} Current wavelength index (when plotting vs time) */
let currentWavelengthIndex = 0;

/** @type {number} Total available wavelength points */
let totalWavelengthPoints = 0;

// ---------------------------------------------------------------------------
// Color Scales
// ---------------------------------------------------------------------------

/**
 * Available Plotly color scale options shown in the picker.
 * @type {Array<{name:string, class:string}>}
 */
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

// ---------------------------------------------------------------------------
// DOMContentLoaded — Bind all UI event listeners
// ---------------------------------------------------------------------------

/**
 * Master initialization handler.
 * Runs once when the DOM is ready. Binds every button/input to its handler
 * function and initializes default UI state (demo data, color scales, bands).
 */
document.addEventListener('DOMContentLoaded', function() {
  // --- Demo data ---
  initializeDemoData();
  setupDemoDataHandlers();

  // --- Input controls ---
  document.getElementById('addBandBtn').addEventListener('click', () => addCustomBand());
  document.getElementById('uploadMastBtn').addEventListener('click', uploadMastDirectory);

  // --- Plot controls ---
  document.getElementById('resetSurfaceViewBtn').addEventListener('click', () => resetPlotView('surfacePlot'));
  document.getElementById('resetHeatmapViewBtn').addEventListener('click', () => resetPlotView('heatmapPlot'));

  // --- Spectrum viewer controls ---
  document.getElementById('closeSpectrumBtn').addEventListener('click', closeSpectrumViewer);
  document.getElementById('prevSpectrumBtn').addEventListener('click', () => navigateSpectrum(-1));
  document.getElementById('nextSpectrumBtn').addEventListener('click', () => navigateSpectrum(1));
  document.getElementById('playAnimationBtn').addEventListener('click', toggleAnimation);
  document.getElementById('animationSpeed').addEventListener('input', (e) => updateAnimationSpeed(e.target.value));

  const teb = document.getElementById('toggleErrorBars');
  if (teb) teb.addEventListener('change', onToggleErrorBars);

  // --- Color scale picker ---
  initializeColorScales();

  // --- Default custom bands ---
  addCustomBand('CH₄ Band', 2.14, 2.50);
  addCustomBand('CO Band', 4.50, 5.05);
  renderBandButtons();

  // --- Download link ---
  const dl = document.querySelector('a[href="/download_plots"]');
  if (dl) dl.addEventListener('click', downloadAllWithVideo);

  // --- Spectrum mode toggle ---
  const tsm = document.getElementById('toggleSpectrumModeBtn');
  if (tsm) tsm.addEventListener('click', toggleSpectrumMode);
});

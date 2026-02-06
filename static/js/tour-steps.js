/*
 * ============================================================================
 * tour-steps.js — Tour Step Configuration & Shared State
 * ============================================================================
 *
 * This file is loaded FIRST among the tour scripts. It defines:
 *   1. Shared mutable state (currentStep, tourActive) read/written by all
 *      tour files via the global scope.
 *   2. The tourSteps array — the complete 23-step tour configuration.
 *
 * Each step object has these properties:
 *   - id            {string}   Unique kebab-case identifier.
 *   - element       {string|null}  CSS selector for the DOM element to highlight.
 *   - title         {string}   Short title shown in the message box.
 *   - message       {string}   Descriptive text explaining the feature.
 *   - position      {'left'|'right'|'center'}  Where the message box appears.
 *   - waitFor       {string|null}  Condition to poll for before enabling "Next":
 *                               'plotsLoaded' or 'spectrumOpened'.
 *   - action        {string|null}  Special action hint (e.g. 'checkBox').
 *   - autoNext      {boolean}  If true, auto-advance after waitFor resolves.
 *   - skipScroll    {boolean}  If true, don't scroll to the element.
 *   - highlightMultiple {string[]}  Array of selectors to highlight simultaneously.
 *   - isEnd         {boolean}  Marks the final tour step.
 *
 * Load order:  tour-steps.js → tour-overlay.js → tour-core.js
 * ============================================================================
 */

console.log(' TOUR-STEPS.JS LOADED');

// ---------------------------------------------------------------------------
// Shared state — read and written by tour-overlay.js and tour-core.js
// ---------------------------------------------------------------------------

/** @type {string} localStorage key (reserved for future "don't show again") */
const TOUR_STORAGE_KEY = 'stamp_tour_completed';

/** @type {number} Index of the currently displayed tour step */
// eslint-disable-next-line no-unused-vars
let currentStep = 0;

/** @type {boolean} Whether the tour is currently running */
// eslint-disable-next-line no-unused-vars
let tourActive = false;

// ---------------------------------------------------------------------------
// Tour step definitions (23 steps)
// ---------------------------------------------------------------------------

/**
 * Complete tour configuration.
 *
 * Steps 1–6:   Input settings (file, interpolation, z-axis, ranges, colors, bands)
 * Step 7:      "Process Data" button — waits for plots to load, then auto-advances
 * Steps 8–11:  Results overview (metadata, 3-D surface, bands, spectrum viewer)
 * Steps 12–17: Spectrum viewer controls (bands, errors, navigation, mode switch)
 * Steps 18–19: Heatmap view and bands
 * Step 20:     Download
 * Step 21:     Tour complete (end step)
 *
 * @type {Array<Object>}
 */
const tourSteps = [
    // ---- Input settings (steps 1–6) -------------------------------------
    {
        id: 'file-selection',
        element: '#fileDisplay',
        title: 'Select Your Dataset',
        message: 'Here you can select your dataset. A demo one is preloaded.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: false
    },
    {
        id: 'linear-interpolation',
        element: '#linearInterpolation',
        title: 'Linear Interpolation',
        message: 'Enable this to interpolate data across time for smoother visualizations and filled gaps between observations.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: false
    },
    {
        id: 'z-axis-display',
        element: '#zAxisDisplaySection',
        title: 'Z-Axis Display Options',
        message: 'Choose what the z-axis represents: flux or variability. This changes how the 3D surface plot visualizes your data.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: false
    },
    {
        id: 'data-ranges',
        element: '#dataRangesSection',
        title: 'Data Ranges',
        message: 'Here you can select ranges of data displayed. This can be used to leave out outliers or zoom into a section. Let\'s leave it blank for the demo.',
        position: 'right',
        waitFor: null,
        action: null
    },
    {
        id: 'color-scale',
        element: '#colorScaleSection',
        title: 'Color Scheme',
        message: 'Pick any color scheme you\'d like for the visualizations.',
        position: 'right',
        waitFor: null,
        action: null
    },
    {
        id: 'custom-bands',
        element: '#customBandsSection',
        title: 'Custom Bands',
        message: 'Another way to isolate sections of data. Two bands are already preloaded. Let\'s leave just those for now. We\'ll see these in action later',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: false
    },

    // ---- Process button (step 7) — waits for data loading ----------------
    {
        id: 'compile-button',
        element: '#uploadMastBtn',
        title: 'Process Data',
        message: 'Press this button to compile and visualize the data.',
        position: 'right',
        waitFor: 'plotsLoaded',
        action: null,
        autoNext: true
    },

    // ---- Results overview (steps 8–11) -----------------------------------
    {
        id: 'metadata',
        element: '#metadataInfo',
        title: 'Data Information',
        message: 'Here\'s some info about the data capture.',
        position: 'right',
        waitFor: null,
        action: null
    },
    {
        id: 'surface-plot',
        element: '#surfacePlot',
        title: '3D Surface Plot',
        message: 'This 3D visualization shows flux variability across wavelength and time. You can rotate and zoom.',
        position: 'left',
        waitFor: null,
        action: null,
        skipScroll: false
    },
    {
        id: 'surface-bands',
        element: '#surfaceBandButtons',
        title: 'Band Selection',
        message: 'Now we can click these band buttons and see them in action.',
        position: 'left',
        waitFor: null,
        action: null,
        skipScroll: true,
        highlightMultiple: ['#surfacePlot', '#surfaceBandButtons']
    },
    {
        id: 'enable-click',
        element: '#enableSurfaceClick',
        title: 'Enable Spectrum Viewer',
        message: 'Check this box to enable clicking on the plot to break the 3D plot down.',
        position: 'left',
        waitFor: 'spectrumOpened',
        action: 'checkBox',
        autoNext: true,
        skipScroll: true,
        highlightMultiple: ['#surfacePlot', '#enableSurfaceClick']
    },

    // ---- Spectrum viewer controls (steps 12–17) --------------------------
    {
        id: 'spectrum-viewer',
        element: '#spectrumContainer',
        title: 'Spectrum Viewer',
        message: 'This shows detailed spectral data at the selected time point.',
        position: 'left',
        waitFor: null,
        action: null,
        skipScroll: false
    },
    {
        id: 'spectrum-bands',
        element: '#spectrumBandButtons',
        title: 'Spectrum Bands',
        message: 'Band buttons work here too. Try clicking one!',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: true,
        highlightMultiple: ['#spectrumContainer', '#spectrumBandButtons']
    },
    {
        id: 'error-bars',
        element: '#toggleErrorBars',
        title: 'Error Bars',
        message: 'Toggle this to show/hide error on the graph.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: true,
        highlightMultiple: ['#spectrumContainer', '#toggleErrorBars']
    },
    {
        id: 'navigation-controls',
        element: '#prevSpectrumBtn',
        title: 'Navigate & Animate',
        message: 'Use Previous and Next to move between 2D spectral views, or hit Play to animate through them. The spectrum viewer lets you explore each time point in detail.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: true,
        highlightMultiple: ['#spectrumContainer', '#prevSpectrumBtn', '#nextSpectrumBtn', '#playAnimationBtn']
    },
    {
        id: 'x-axis-switch',
        element: '#toggleSpectrumModeBtn',
        title: 'Switch X-Axis',
        message: 'Click this to switch between wavelength and time on the x-axis.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: true,
        highlightMultiple: ['#spectrumContainer', '#toggleSpectrumModeBtn']
    },
    {
        id: 'time-mode-bands',
        element: '#spectrumBandButtons',
        title: 'Bands in Time Mode',
        message: 'When viewing time series, bands show averaged flux/variability across the band range.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: true,
        highlightMultiple: ['#spectrumContainer', '#spectrumBandButtons']
    },

    // ---- Heatmap (steps 18–19) -------------------------------------------
    {
        id: 'heatmap',
        element: '#heatmapPlot',
        title: 'Heatmap View',
        message: 'This 2D heatmap shows the same data in a different visualization style. Wavelength and time sit on the axis and the color intensity corresponds to the strength of the z axis ',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: false
    },
    {
        id: 'heatmap-bands',
        element: '#heatmapBandButtons',
        title: 'Heatmap Bands',
        message: 'Band selection works on the heatmap as well',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: true,
        highlightMultiple: ['#heatmapPlot', '#heatmapBandButtons']
    },

    // ---- Download & finish (steps 20–21) ---------------------------------
    {
        id: 'download-graphs',
        element: 'a[href="/download_plots"]',
        title: 'Download Your Graphs',
        message: 'Click here to download all plots at once, or use the camera icon in the Plotly toolbar when hovering over individual plots.',
        position: 'right',
        waitFor: null,
        action: null,
        skipScroll: false
    },
    {
        id: 'tour-complete',
        element: null,
        title: 'Tour Complete!',
        message: 'You\'re all set! Feel free to explore on your own.',
        position: 'center',
        waitFor: null,
        action: null,
        isEnd: true
    }
];

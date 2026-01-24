/*
========================================
STAMP Interactive Tour
========================================
*/
console.log(' TOUR.JS LOADED');

/*
========================================

 */

const TOUR_STORAGE_KEY = 'stamp_tour_completed';
let currentStep = 0;
let tourActive = false;

// Tour steps configuration
const tourSteps = [
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

    },
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

// Initialize tour on page load
document.addEventListener('DOMContentLoaded', function() {
    // Always show tour prompt on page load
    setTimeout(() => {
        showTourPrompt();
    }, 500);

    // Setup event listeners
    setupEventListeners();
});

function setupEventListeners() {
    // Tour accept/decline
    const acceptBtn = document.getElementById('tourAcceptBtn');
    const declineBtn = document.getElementById('tourDeclineBtn');

    if (acceptBtn) {
        acceptBtn.addEventListener('click', startTour);
    }

    if (declineBtn) {
        declineBtn.addEventListener('click', declineTour);
    }

    // Tour navigation
    const nextBtn = document.getElementById('tourNextBtn');
    const prevBtn = document.getElementById('tourPrevBtn');
    const closeBtn = document.getElementById('tourCloseBtn'); // Changed from skipBtn

    if (nextBtn) {
        nextBtn.addEventListener('click', nextStep);
    }

    if (prevBtn) {
        prevBtn.addEventListener('click', prevStep);
    }

    // Replace skip button with close X button
    if (closeBtn) {
        closeBtn.addEventListener('click', endTour);
    }
}

function showTourPrompt() {
    const prompt = document.getElementById('tourPrompt');
    if (prompt) {
        prompt.classList.remove('hidden');

        // Calculate optimal position
        const container = document.querySelector('.max-w-4xl');
        if (container) {
            const containerRect = container.getBoundingClientRect();
            const viewportWidth = window.innerWidth;
            const promptWidth = 240; // Updated to match new CSS width

            // Space available to the right of the container
            const spaceAfterContainer = viewportWidth - containerRect.right;

            // Center the prompt in that space, then nudge it left
            // Center the prompt in that space, then nudge it left
const optimalLeft = containerRect.right + (spaceAfterContainer / 2) - (promptWidth / 2) - 5; // subtract 10px to move left slightly

            // Much looser safety - only prevent going completely off screen
            const minLeft = 5; // just keep it on screen
            const maxLeft = viewportWidth - promptWidth - 5;

            const finalLeft = Math.max(minLeft, Math.min(maxLeft, optimalLeft));

            // Apply position
            prompt.style.left = finalLeft + 'px';
            prompt.style.right = 'auto';

            console.log('📍 Tour Prompt Positioning:');
            console.log('  Container right edge:', containerRect.right);
            console.log('  Viewport width:', viewportWidth);
            console.log('  Space after container:', spaceAfterContainer);
            console.log('  Optimal left:', optimalLeft);
            console.log('  Final left:', finalLeft);
        }
    }
}
function hideTourPrompt() {
    const prompt = document.getElementById('tourPrompt');
    if (prompt) {
        prompt.classList.add('hidden');
    }
}

function startTour() {
    hideTourPrompt();
    tourActive = true;
    currentStep = 0;

    // Clear any active focus from form elements
    if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
    }

    // Prevent horizontal scroll
    document.body.classList.add('tour-active');

    // Scroll to top of page before starting tour
    window.scrollTo({
        top: 0,
        behavior: 'instant'
    });

    // Wait for scroll, blur, and layout to complete
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            // Force multiple reflows
            document.body.offsetHeight;

            setTimeout(() => {
                document.body.offsetHeight;
                showStep(currentStep);
            }, 150);
        });
    });
}

function declineTour() {
    hideTourPrompt();
    // Just hide the prompt - don't save anything to localStorage
}



function showStep(stepIndex) {
    const step = tourSteps[stepIndex];

    if (!step) {
        endTour();
        return;
    }

    // Update step counter
    updateStepCounter(stepIndex);

    // Update message box
    const titleEl = document.getElementById('tourTitle');
    const messageEl = document.getElementById('tourMessage');
    const messageBox = document.getElementById('tourMessageBox');
    const nextBtn = document.getElementById('tourNextBtn');
    const prevBtn = document.getElementById('tourPrevBtn');

    if (titleEl) titleEl.textContent = step.title;
    if (messageEl) messageEl.textContent = step.message;

    // Show/hide back button
    if (prevBtn) {
        if (stepIndex > 0) {
            prevBtn.classList.remove('hidden');
        } else {
            prevBtn.classList.add('hidden');
        }
    }

    // Show overlay - always use transparent, cutouts will handle darkening
    const overlay = document.getElementById('tourOverlay');
    if (overlay) {
        overlay.classList.remove('hidden');
        overlay.classList.remove('preserve-plot');
        // Always transparent - the cutout overlay sections handle darkening
        overlay.style.background = 'transparent';
        overlay.style.clipPath = '';
    }

    // Handle special step cases
    if (step.isEnd) {
        showEndStep();
        return;
    }

    // Always show message box (don't hide it)
    if (messageBox) {
        messageBox.classList.remove('hidden');
        messageBox.classList.remove('positioning');
    }

    // Highlight element if specified
    if (step.element) {
        const element = document.querySelector(step.element);
        // ADD THIS DEBUG LOG
        console.log(' Tour Step:', step.id, 'Element:', step.element, 'Found:', element);

        if (element) {
            // Clear focus from this element if it has it
            if (element === document.activeElement) {
                element.blur();
            }

            // Force the browser to recalculate element position
            element.getBoundingClientRect();
            // Check if element is already in view - if so, skip scrolling
            const rect = element.getBoundingClientRect();
            const isInView = (
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                rect.right <= (window.innerWidth || document.documentElement.clientWidth)
            );

            // Only scroll if not in view and skipScroll is false
            if (!step.skipScroll && !isInView) {
                scrollToElement(element);
            }

            // Much shorter delay - instant if no scroll needed
            const delay = (!step.skipScroll && !isInView) ? 200 : 0;

            setTimeout(() => {
                // Check if we need to highlight multiple elements
                if (step.highlightMultiple && Array.isArray(step.highlightMultiple)) {
                    highlightMultipleElements(step.highlightMultiple);
                } else {
                    highlightElement(element);
                }

                // Position message box immediately
                positionMessageBox(element, step.position);
            }, delay);
        }
    } else {
        // If no element to highlight, just position the message box in center
        if (messageBox) {
            messageBox.style.position = 'fixed';
            messageBox.style.left = '50%';
            messageBox.style.top = '50%';
            messageBox.style.transform = 'translate(-50%, -50%)';
        }
    }

    // Handle wait conditions
    if (step.waitFor) {
        if (nextBtn) {
            nextBtn.disabled = true;
            nextBtn.textContent = 'Waiting...';
        }
        waitForCondition(step.waitFor, () => {
            if (nextBtn) {
                nextBtn.disabled = false;
                nextBtn.textContent = 'Next';
            }
            if (step.autoNext === true) {
                setTimeout(nextStep, 1500);
            }
        });
    } else {
        if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.textContent = 'Next';
        }
    }
}

function highlightMultipleElements(selectors) {
    const highlight = document.getElementById('tourHighlight');
    if (!highlight) return;

    // Clear any existing highlights first
    highlight.classList.add('hidden');

    // Remove any previous multi-highlights AND overlay sections
    document.querySelectorAll('.tour-multi-highlight').forEach(el => el.remove());
    document.querySelectorAll('.tour-overlay-section').forEach(el => el.remove());

    selectors.forEach((selector, index) => {
        const element = document.querySelector(selector);
        if (!element) return;

        const rect = element.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        const highlightBox = document.createElement('div');
        highlightBox.className = 'tour-multi-highlight';
        highlightBox.style.position = 'absolute';
        highlightBox.style.top = (rect.top + scrollTop - 5) + 'px';
        highlightBox.style.left = (rect.left + scrollLeft - 5) + 'px';
        highlightBox.style.width = (rect.width + 10) + 'px';
        highlightBox.style.height = (rect.height + 10) + 'px';
        highlightBox.style.border = '3px solid #ffffff';
        highlightBox.style.borderRadius = '8px';
        highlightBox.style.boxShadow = '0 0 10px rgba(255, 255, 255, 0.5), 0 0 20px rgba(255, 255, 255, 0.3)';
        highlightBox.style.pointerEvents = 'none';
        highlightBox.style.zIndex = '9999';
        highlightBox.style.animation = 'pulseGlow 2s ease-in-out infinite';

        document.body.appendChild(highlightBox);

        // Make elements clickable if needed
        const step = tourSteps[currentStep];
        if (step && (step.waitFor === 'plotsLoaded' || step.action === 'checkBox')) {
            element.style.position = 'relative';
            element.style.zIndex = '10000';
        }
    });

    // Update overlay to cut out highlighted areas
    updateOverlayWithCutouts(selectors);
}

function updateOverlayWithCutouts(selectors) {
    const overlay = document.getElementById('tourOverlay');
    if (!overlay) return;

    // Remove old cutout overlays
    document.querySelectorAll('.tour-overlay-section').forEach(el => el.remove());

    if (!selectors || selectors.length === 0) {
        overlay.style.clipPath = '';
        return;
    }

    // Ensure main overlay is transparent
    overlay.style.background = 'transparent';

    const rects = selectors.map(selector => {
        const el = document.querySelector(selector);
        if (!el) return null;
        const rect = el.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        return {
            left: rect.left - 5,
            top: rect.top + scrollTop - 5,
            right: rect.right + 5,
            bottom: rect.bottom + scrollTop + 5,
            width: rect.width + 10,
            height: rect.height + 10
        };
    }).filter(Boolean);

    if (rects.length === 0) return;

    const viewportHeight = window.innerHeight;
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    const documentHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight,
        scrollTop + viewportHeight + 1000
    );

    // Create four overlay sections (top, right, bottom, left) with cutouts
    // Top section - covers from page top to top of highlighted area
    const topDiv = document.createElement('div');
    topDiv.className = 'tour-overlay-section';
    const topHeight = Math.min(...rects.map(r => r.top));
    topDiv.style.cssText = `
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: ${topHeight}px;
        background: rgba(0, 0, 0, 0.5);
        z-index: 9998;
        pointer-events: none;
    `;
    document.body.appendChild(topDiv);

    // Bottom section - covers from bottom of highlighted area to page bottom
    const bottomTop = Math.max(...rects.map(r => r.bottom));
    const bottomDiv = document.createElement('div');
    bottomDiv.className = 'tour-overlay-section';
    bottomDiv.style.cssText = `
        position: absolute;
        top: ${bottomTop}px;
        left: 0;
        right: 0;
        height: ${documentHeight - bottomTop}px;
        background: rgba(0, 0, 0, 0.5);
        z-index: 9998;
        pointer-events: none;
    `;
    document.body.appendChild(bottomDiv);

    // Left section (middle band)
    const middleTop = Math.min(...rects.map(r => r.top));
    const middleBottom = Math.max(...rects.map(r => r.bottom));
    const leftDiv = document.createElement('div');
    leftDiv.className = 'tour-overlay-section';
    leftDiv.style.cssText = `
        position: absolute;
        top: ${middleTop}px;
        left: 0;
        width: ${Math.min(...rects.map(r => r.left))}px;
        height: ${middleBottom - middleTop}px;
        background: rgba(0, 0, 0, 0.5);
        z-index: 9998;
        pointer-events: none;
    `;
    document.body.appendChild(leftDiv);

    // Right section (middle band)
    const rightLeft = Math.max(...rects.map(r => r.right));
    const rightDiv = document.createElement('div');
    rightDiv.className = 'tour-overlay-section';
    rightDiv.style.cssText = `
        position: absolute;
        top: ${middleTop}px;
        left: ${rightLeft}px;
        right: 0;
        height: ${middleBottom - middleTop}px;
        background: rgba(0, 0, 0, 0.5);
        z-index: 9998;
        pointer-events: none;
    `;
    document.body.appendChild(rightDiv);

    // Middle section between the two cutouts (if they're not adjacent)
    if (rects.length === 2) {
        const leftRect = rects[0].left < rects[1].left ? rects[0] : rects[1];
        const rightRect = rects[0].left < rects[1].left ? rects[1] : rects[0];

        if (leftRect.right < rightRect.left) {
            const middleDiv = document.createElement('div');
            middleDiv.className = 'tour-overlay-section';
            middleDiv.style.cssText = `
                position: absolute;
                top: ${middleTop}px;
                left: ${leftRect.right}px;
                width: ${rightRect.left - leftRect.right}px;
                height: ${middleBottom - middleTop}px;
                background: rgba(0, 0, 0, 0.5);
                z-index: 9998;
                pointer-events: none;
            `;
            document.body.appendChild(middleDiv);
        }
    }
}

function scrollToElement(element) {
    const elementRect = element.getBoundingClientRect();
    const absoluteElementTop = elementRect.top + window.pageYOffset;
    const absoluteElementBottom = elementRect.bottom + window.pageYOffset;

    const viewportHeight = window.innerHeight;
    const currentScroll = window.pageYOffset;

    // Get current step to determine message box position
    const step = tourSteps[currentStep];
    const messageBoxHeight = 300; // Approximate height of message box
    const topMargin = 100; // Space at top of viewport
    const bottomMargin = 100; // Space at bottom of viewport

    let targetScroll;

    if (step && step.position === 'right') {
        // Message box is on the right side (vertically centered)
        // Need to ensure element is vertically centered in viewport
        const elementCenter = (absoluteElementTop + absoluteElementBottom) / 2;
        targetScroll = elementCenter - (viewportHeight / 2);
    } else if (step && step.position === 'left') {
        // Message box is on the left side (vertically centered)
        // Need to ensure element is vertically centered in viewport
        const elementCenter = (absoluteElementTop + absoluteElementBottom) / 2;
        targetScroll = elementCenter - (viewportHeight / 2);
    } else {
        // Default: position element near top with margin
        targetScroll = absoluteElementTop - topMargin;
    }

    // Check if current scroll position is already good enough
    const elementTopInView = elementRect.top >= topMargin;
    const elementBottomInView = elementRect.bottom <= viewportHeight - bottomMargin;

    if (elementTopInView && elementBottomInView) {
        return; // Element is already well positioned
    }

    // Ensure we don't scroll past the top of the page
    targetScroll = Math.max(0, targetScroll);

    window.scrollTo({
        top: targetScroll,
        behavior: 'smooth'
    });
}

function highlightElement(element) {
    const highlight = document.getElementById('tourHighlight');
    if (!highlight) return;

    // Clear any existing cutouts first
    document.querySelectorAll('.tour-overlay-section').forEach(el => el.remove());

    // Force a fresh layout calculation - wait one more frame
    requestAnimationFrame(() => {
        const rect = element.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        // Debug: log the element being highlighted
        console.log('🎯 Highlighting element:', element.id || element.className);
        console.log('   Position:', {
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height
        });

        highlight.style.top = (rect.top + scrollTop - 5) + 'px';
        highlight.style.left = (rect.left + scrollLeft - 5) + 'px';
        highlight.style.width = (rect.width + 10) + 'px';
        highlight.style.height = (rect.height + 10) + 'px';
        highlight.classList.remove('hidden');

        // Add special class if highlighting the surface plot to prevent brightening
        if (element.id === 'surfacePlot') {
            highlight.classList.add('highlight-plot');
        } else {
            highlight.classList.remove('highlight-plot');
        }

        // Make element clickable during tour
        const step = tourSteps[currentStep];
        if (step && (step.waitFor === 'plotsLoaded' || step.action === 'checkBox')) {
            highlight.style.pointerEvents = 'none';
            element.style.position = 'relative';
            element.style.zIndex = '10000';
        }

        // IMPORTANT: Create overlay cutouts for single highlights
        const selector = step.element;
        if (selector) {
            // Use requestAnimationFrame to ensure layout is complete
            requestAnimationFrame(() => {
                updateOverlayWithCutouts([selector]);
            });
        }
    });
}

function positionMessageBox(element, position) {
    const messageBox = document.getElementById('tourMessageBox');
    if (!messageBox) return;

    const rect = element.getBoundingClientRect();
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    // Get the main container
    const container = document.querySelector('.max-w-4xl');
    const containerRect = container ? container.getBoundingClientRect() : null;

    // Special handling for 3D plot-related steps - keep message box in same position
    const step = tourSteps[currentStep];
    const surfacePlotSteps = ['surface-plot', 'surface-bands', 'enable-click'];

    // Cache position for surface plot steps to prevent movement
    if (!window.surfacePlotMessagePosition) {
        window.surfacePlotMessagePosition = null;
    }

    if (step && surfacePlotSteps.includes(step.id)) {
        const viewportWidth = window.innerWidth;
        const messageBoxWidth = 280;
        let left, top;

        // If we already have a cached position for surface plot steps, use it
        if (window.surfacePlotMessagePosition && step.id !== 'surface-plot') {
            messageBox.style.transform = 'none';
            messageBox.style.position = 'absolute';
            messageBox.style.right = 'auto';
            messageBox.style.left = window.surfacePlotMessagePosition.left + 'px';
            messageBox.style.top = window.surfacePlotMessagePosition.top + 'px';
            console.log('Using cached surface plot position:', window.surfacePlotMessagePosition);
            return;
        }

        // Position on the left side (consistent for all 3D plot steps)
        if (containerRect) {
            const spaceBeforeContainer = containerRect.left;

            if (spaceBeforeContainer >= messageBoxWidth + 100) {
                left = (spaceBeforeContainer / 2) - (messageBoxWidth / 2);
            } else {
                left = 40;
            }

            const minLeft = 20;
            if (left < minLeft) left = minLeft;
        } else {
            left = 40;
        }

        // For surface plot steps, position based on the plot's actual position
        // Wait for the plot to be fully laid out before positioning
        requestAnimationFrame(() => {
            const plotRect = document.querySelector('#surfacePlot')?.getBoundingClientRect();

            if (plotRect) {
                const plotCenter = plotRect.top + (plotRect.height / 2);
                top = plotCenter - (messageBox.offsetHeight / 2) + scrollTop;

                // Ensure it stays within viewport
                const minTop = scrollTop + 80;
                const maxTop = scrollTop + window.innerHeight - messageBox.offsetHeight - 80;
                top = Math.max(minTop, Math.min(maxTop, top));

                messageBox.style.top = top + 'px';
                window.surfacePlotMessagePosition.top = top;
            }
        });

        // Set initial position
        const plotRect = document.querySelector('#surfacePlot')?.getBoundingClientRect();
        if (plotRect) {
            const plotCenter = plotRect.top + (plotRect.height / 2);
            top = plotCenter - (messageBox.offsetHeight / 2) + scrollTop;

            // Ensure it stays within viewport
            const minTop = scrollTop + 80;
            const maxTop = scrollTop + window.innerHeight - messageBox.offsetHeight - 80;
            top = Math.max(minTop, Math.min(maxTop, top));
        } else {
            // Fallback: middle of viewport
            const middleThird = scrollTop + (window.innerHeight / 2) - (messageBox.offsetHeight / 2);
            top = middleThird;
        }

        // Cache this position for subsequent surface plot steps
        window.surfacePlotMessagePosition = { left, top };

        messageBox.style.transform = 'none';
        messageBox.style.position = 'absolute';
        messageBox.style.right = 'auto';
        messageBox.style.left = left + 'px';
        messageBox.style.top = top + 'px';

        console.log('Surface plot step - fixed position:', left, top);
        return;
    }

    // Special handling for spectrum-viewer step and all subsequent spectrum steps
    const spectrumSteps = ['spectrum-viewer', 'spectrum-bands', 'error-bars', 'x-axis-switch', 'time-mode-bands'];
    const heatmapSteps = ['heatmap', 'heatmap-bands'];

    if (step && (spectrumSteps.includes(step.id) || heatmapSteps.includes(step.id))) {
        const viewportWidth = window.innerWidth;
        const messageBoxWidth = 280;
        let left, top;

        // Position on the right side
        if (containerRect) {
            const spaceAfterContainer = viewportWidth - containerRect.right;

            if (spaceAfterContainer >= messageBoxWidth + 100) {
                left = containerRect.right + (spaceAfterContainer / 2) - (messageBoxWidth / 2);
            } else {
                left = viewportWidth - messageBoxWidth - 40;
            }

            const minLeft = containerRect.right + 200;
            if (left < minLeft) left = minLeft;

            const maxLeft = viewportWidth - messageBoxWidth - 20;
            if (left > maxLeft) left = maxLeft;
        } else {
            left = viewportWidth - messageBoxWidth - 40;
        }

        // Position in lower portion of screen to avoid covering spectrum data
        // Use 70% down from top (instead of 66% / bottom third)
        const viewportHeight = window.innerHeight;
        top = scrollTop + (viewportHeight * 0.95) - (messageBox.offsetHeight / 2);

        // Ensure it doesn't go off bottom of screen
        const maxTop = scrollTop + viewportHeight - messageBox.offsetHeight - 30;
        if (top > maxTop) {
            top = maxTop;
        }

        // Ensure minimum top position (don't go too high)
        const minTop = scrollTop + (viewportHeight * 0.5);
        if (top < minTop) {
            top = minTop;
        }

        messageBox.style.transform = 'none';
        messageBox.style.position = 'absolute';
        messageBox.style.right = 'auto';
        messageBox.style.left = left + 'px';
        messageBox.style.top = top + 'px';

        console.log('Spectrum step message box positioned at:', left, top);
        return;
    }

    let left, top;

    if (position === 'left') {
        // Position on the left side of the viewport, not relative to element
        const messageBoxWidth = 280;

        if (containerRect) {
            const spaceBeforeContainer = containerRect.left;

            if (spaceBeforeContainer >= messageBoxWidth + 100) {
                // Center in the available left space
                left = (spaceBeforeContainer / 2) - (messageBoxWidth / 2);
            } else {
                // Not enough space, position at far left with margin
                left = 40;
            }
        } else {
            // Fallback: position at left side with margin
            left = 40;
        }

        // Safety: don't go off screen
        const minLeft = 20;
        if (left < minLeft) {
            left = minLeft;
        }
    } else if (containerRect) {
        // Original right-side positioning
        const viewportWidth = window.innerWidth;
        const messageBoxWidth = 280;

        // Calculate space to the right of container
        const spaceAfterContainer = viewportWidth - containerRect.right;

        // If there's enough space, center in that space
        // Otherwise, push to far right
        if (spaceAfterContainer >= messageBoxWidth + 100) {
            // Center in the available right space
            left = containerRect.right + (spaceAfterContainer / 2) - (messageBoxWidth / 2);
        } else {
            // Not enough space, position at far right with margin
            left = viewportWidth - messageBoxWidth - 40;
        }

        // Safety: ensure minimum 200px gap from container
        const minLeft = containerRect.right + 200;
        if (left < minLeft) {
            left = minLeft;
        }

        // Safety: don't go off screen
        const maxLeft = viewportWidth - messageBoxWidth - 20;
        if (left > maxLeft) {
            left = maxLeft;
        }
    } else {
        // Fallback: far right of screen
        left = window.innerWidth - 320;
    }

    // Position vertically next to the highlighted element
    // Calculate the vertical center of the highlighted element
    const elementVerticalCenter = rect.top + (rect.height / 2) + scrollTop;

    // Position message box so its center aligns with element's center
    top = elementVerticalCenter - (messageBox.offsetHeight / 2);

    // Ensure message box doesn't go off top of viewport
    const minTop = scrollTop + 20;
    if (top < minTop) {
        top = minTop;
    }

    // Ensure message box doesn't go off bottom of viewport
    const maxTop = scrollTop + window.innerHeight - messageBox.offsetHeight - 20;
    if (top > maxTop) {
        top = maxTop;
    }

    // Special case: if element is near top of page AND small height, position next to it
    // This handles the first step (file display)
    if (rect.top < 300 && rect.height < 200) {
        // Element is near top and short - position message box next to it vertically
        const elementMidpoint = rect.top + (rect.height / 2) + scrollTop;
        top = elementMidpoint - (messageBox.offsetHeight / 2);

        // Ensure it doesn't go too low either
        const maxTopForFirstStep = scrollTop + window.innerHeight - messageBox.offsetHeight - 80;
        if (top > maxTopForFirstStep) {
            top = maxTopForFirstStep;
        }

        // Don't let it go above a reasonable minimum
        const absoluteMinTop = scrollTop + 80;
        if (top < absoluteMinTop) {
            top = absoluteMinTop;
        }
    }

    // Override for file-selection step specifically
    if (step && step.id === 'file-selection') {
        // Position at a fixed comfortable position on the right
        const viewportHeight = window.innerHeight;
        top = scrollTop + (viewportHeight * 0.35); // Position at 35% down from top

        // Ensure reasonable bounds
        const minTop = scrollTop + 100;
        const maxTop = scrollTop + viewportHeight - messageBox.offsetHeight - 100;
        top = Math.max(minTop, Math.min(maxTop, top));
    }

    // Reset transform and set position
    messageBox.style.transform = 'none';
    messageBox.style.position = 'absolute';
    messageBox.style.right = 'auto';
    messageBox.style.left = left + 'px';
    messageBox.style.top = top + 'px';

    console.log('Message box positioned at:', left, 'Container right edge:', containerRect ? containerRect.right : 'N/A');
}

function updateStepCounter(stepIndex) {
    const counter = document.getElementById('tourStepCounter');
    if (counter) {
        counter.textContent = `Step ${stepIndex + 1} of ${tourSteps.length}`;
    }
}

function nextStep() {
    currentStep++;
    if (currentStep < tourSteps.length) {
        showStep(currentStep);
    } else {
        endTour();
    }
}

function prevStep() {
    if (currentStep > 0) {
        currentStep--;
        showStep(currentStep);
    }
}

function showEndStep() {
    const messageBox = document.getElementById('tourMessageBox');
    const nextBtn = document.getElementById('tourNextBtn');
    const prevBtn = document.getElementById('tourPrevBtn');
    const highlight = document.getElementById('tourHighlight');

    // Hide highlight
    if (highlight) {
        highlight.classList.add('hidden');
    }

    // Center message box on screen
    if (messageBox) {
        messageBox.style.position = 'fixed';
        messageBox.style.left = '50%';
        messageBox.style.top = '50%';
        messageBox.style.transform = 'translate(-50%, -50%)';
    }

    // Change button text
    if (nextBtn) {
        nextBtn.textContent = 'Finish';
        nextBtn.onclick = endTour;
    }

    // Hide back button (close X stays visible)
    if (prevBtn) prevBtn.classList.add('hidden');
}

function endTour() {
    tourActive = false;

    // Clear cached positions
    window.surfacePlotMessagePosition = null; // ADD THIS LINE

    // Remove overflow prevention
    document.body.classList.remove('tour-active');

    // Reset any z-index changes
    document.querySelectorAll('[style*="z-index: 10000"]').forEach(el => {
        el.style.zIndex = '';
        el.style.position = '';
    });

    // Don't save to localStorage

    // Hide all tour elements
    const elements = ['tourMessageBox', 'tourOverlay', 'tourHighlight'];
    elements.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // Remove multi-highlights
    document.querySelectorAll('.tour-multi-highlight').forEach(el => el.remove());

    // Remove overlay sections
    document.querySelectorAll('.tour-overlay-section').forEach(el => el.remove());

    // Reset main overlay
    const overlay = document.getElementById('tourOverlay');
    if (overlay) {
        overlay.style.background = '';
        overlay.style.clipPath = '';
    }

    // Show the tour prompt again after a short delay
    setTimeout(() => {
        showTourPrompt();
    }, 300);

    // Reset message box positioning
    const messageBox = document.getElementById('tourMessageBox');
    if (messageBox) {
        messageBox.style.transform = '';
    }
}

function waitForCondition(condition, callback) {
    if (condition === 'plotsLoaded') {
        const checkInterval = setInterval(() => {
            if (window.stampsDataLoaded === true) {
                clearInterval(checkInterval);
                callback();
            }
        }, 500);
    } else if (condition === 'spectrumOpened') {
        const checkInterval = setInterval(() => {
            const spectrumContainer = document.getElementById('spectrumContainer');
            const checkbox = document.getElementById('enableSurfaceClick');

            // Only proceed if checkbox is checked AND spectrum viewer is visible
            if (checkbox && checkbox.checked &&
                spectrumContainer && !spectrumContainer.classList.contains('hidden')) {
                clearInterval(checkInterval);
                // Small delay to ensure everything is rendered
                setTimeout(callback, 300);
            }
        }, 200);
    }
}

// Export for use in main.js if needed
window.tourActive = () => tourActive;
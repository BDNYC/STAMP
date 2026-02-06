/*
 * ============================================================================
 * tour-core.js — Tour Lifecycle, Navigation & Step Display
 * ============================================================================
 *
 * This file is loaded LAST among the tour scripts. It orchestrates the tour
 * by wiring up DOM event listeners, managing step transitions, and calling
 * visual functions defined in tour-overlay.js.
 *
 * Dependencies (must be loaded before this file):
 *   tour-steps.js   — tourSteps[], currentStep, tourActive, TOUR_STORAGE_KEY
 *   tour-overlay.js — highlightElement(), highlightMultipleElements(),
 *                     updateOverlayWithCutouts(), scrollToElement(),
 *                     positionMessageBox()
 *
 * Exports to global scope:
 *   window.tourActive  — getter function used by main.js to check tour state
 *
 * Load order:  tour-steps.js → tour-overlay.js → tour-core.js
 * ============================================================================
 */

console.log(' TOUR-CORE.JS LOADED');

// ---------------------------------------------------------------------------
// Initialization — runs once when the DOM is ready
// ---------------------------------------------------------------------------

/**
 * Bootstrap the tour system on page load.
 * Shows the initial tour prompt after a short delay and binds all UI buttons.
 */
document.addEventListener('DOMContentLoaded', function () {
    // Always show tour prompt on page load
    setTimeout(() => {
        showTourPrompt();
    }, 500);

    // Setup event listeners
    setupEventListeners();
});

// ---------------------------------------------------------------------------
// Event Binding
// ---------------------------------------------------------------------------

/**
 * Bind click handlers to all tour UI buttons.
 *
 * Buttons wired:
 *   - #tourAcceptBtn   → startTour()
 *   - #tourDeclineBtn  → declineTour()
 *   - #tourNextBtn     → nextStep()
 *   - #tourPrevBtn     → prevStep()
 *   - #tourCloseBtn    → endTour()   (the "X" close button)
 */
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
    const closeBtn = document.getElementById('tourCloseBtn');

    if (nextBtn) {
        nextBtn.addEventListener('click', nextStep);
    }

    if (prevBtn) {
        prevBtn.addEventListener('click', prevStep);
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', endTour);
    }
}

// ---------------------------------------------------------------------------
// Tour Prompt (the initial "Want a tour?" dialog)
// ---------------------------------------------------------------------------

/**
 * Display the initial tour prompt dialog.
 * Calculates an optimal horizontal position so the prompt sits centered in
 * the space to the right of the main content container.
 */
function showTourPrompt() {
    const prompt = document.getElementById('tourPrompt');
    if (prompt) {
        prompt.classList.remove('hidden');

        // Calculate optimal position to the right of the content container
        const container = document.querySelector('.max-w-4xl');
        if (container) {
            const containerRect = container.getBoundingClientRect();
            const viewportWidth = window.innerWidth;
            const promptWidth = 240;

            // Center the prompt in the space after the container, nudged left slightly
            const spaceAfterContainer = viewportWidth - containerRect.right;
            const optimalLeft = containerRect.right + (spaceAfterContainer / 2) - (promptWidth / 2) - 5;

            // Keep it on screen
            const minLeft = 5;
            const maxLeft = viewportWidth - promptWidth - 5;
            const finalLeft = Math.max(minLeft, Math.min(maxLeft, optimalLeft));

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

/**
 * Hide the tour prompt dialog.
 */
function hideTourPrompt() {
    const prompt = document.getElementById('tourPrompt');
    if (prompt) {
        prompt.classList.add('hidden');
    }
}

// ---------------------------------------------------------------------------
// Tour Start / Decline
// ---------------------------------------------------------------------------

/**
 * Begin the interactive tour.
 *
 * Hides the prompt, sets tour state to active, scrolls to the top of the
 * page, and displays the first step after layout settles.
 */
function startTour() {
    hideTourPrompt();
    tourActive = true;
    currentStep = 0;

    // Clear any active focus from form elements
    if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
    }

    // Prevent horizontal scroll while tour is running
    document.body.classList.add('tour-active');

    // Scroll to top of page before starting tour
    window.scrollTo({
        top: 0,
        behavior: 'instant'
    });

    // Wait for scroll, blur, and layout to complete before showing the first step
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            document.body.offsetHeight; // force reflow
            setTimeout(() => {
                document.body.offsetHeight; // force another reflow
                showStep(currentStep);
            }, 150);
        });
    });
}

/**
 * Decline the tour — simply hides the prompt without saving any state.
 */
function declineTour() {
    hideTourPrompt();
}

// ---------------------------------------------------------------------------
// Step Display — the core rendering function
// ---------------------------------------------------------------------------

/**
 * Display a specific tour step.
 *
 * This is the central function that drives each step transition. It:
 *   1. Validates the step index.
 *   2. Updates the message box content (title, body text).
 *   3. Toggles the Back button visibility.
 *   4. Shows the overlay backdrop.
 *   5. Delegates to the end-step handler for the final step.
 *   6. Scrolls to the target element (if needed).
 *   7. Highlights the element(s) and positions the message box.
 *   8. Sets up wait conditions (e.g. waiting for data to load).
 *
 * @param {number} stepIndex - Zero-based index into the tourSteps array.
 */
function showStep(stepIndex) {
    const step = tourSteps[stepIndex];

    // --- 1. Validation ---
    if (!step) {
        endTour();
        return;
    }

    // --- 2. Update message box content ---
    updateStepCounter(stepIndex);

    const titleEl = document.getElementById('tourTitle');
    const messageEl = document.getElementById('tourMessage');
    const messageBox = document.getElementById('tourMessageBox');
    const nextBtn = document.getElementById('tourNextBtn');
    const prevBtn = document.getElementById('tourPrevBtn');

    if (titleEl) titleEl.textContent = step.title;
    if (messageEl) messageEl.textContent = step.message;

    // --- 3. Back button visibility ---
    if (prevBtn) {
        if (stepIndex > 0) {
            prevBtn.classList.remove('hidden');
        } else {
            prevBtn.classList.add('hidden');
        }
    }

    // --- 4. Show overlay (transparent; cutouts handle darkening) ---
    const overlay = document.getElementById('tourOverlay');
    if (overlay) {
        overlay.classList.remove('hidden');
        overlay.classList.remove('preserve-plot');
        overlay.style.background = 'transparent';
        overlay.style.clipPath = '';
    }

    // --- 5. Handle end step ---
    if (step.isEnd) {
        showEndStep();
        return;
    }

    // Ensure message box is visible
    if (messageBox) {
        messageBox.classList.remove('hidden');
        messageBox.classList.remove('positioning');
    }

    // --- 6–7. Scroll, highlight, and position ---
    if (step.element) {
        const element = document.querySelector(step.element);
        console.log(' Tour Step:', step.id, 'Element:', step.element, 'Found:', element);

        if (element) {
            // Clear focus from this element if it has it
            if (element === document.activeElement) {
                element.blur();
            }

            // Force layout recalculation
            element.getBoundingClientRect();
            const rect = element.getBoundingClientRect();

            // Check if element is already fully visible in the viewport
            const isInView = (
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                rect.right <= (window.innerWidth || document.documentElement.clientWidth)
            );

            // Only scroll if element is off-screen and skipScroll is not set
            if (!step.skipScroll && !isInView) {
                scrollToElement(element);
            }

            // Shorter delay if no scroll was needed
            const delay = (!step.skipScroll && !isInView) ? 200 : 0;

            setTimeout(() => {
                // Highlight: single element or multiple simultaneous highlights
                if (step.highlightMultiple && Array.isArray(step.highlightMultiple)) {
                    highlightMultipleElements(step.highlightMultiple);
                } else {
                    highlightElement(element);
                }

                // Position the message box relative to the highlighted element
                positionMessageBox(element, step.position);
            }, delay);
        }
    } else {
        // No element to highlight — center the message box on screen
        if (messageBox) {
            messageBox.style.position = 'fixed';
            messageBox.style.left = '50%';
            messageBox.style.top = '50%';
            messageBox.style.transform = 'translate(-50%, -50%)';
        }
    }

    // --- 8. Wait conditions ---
    if (step.waitFor) {
        // Disable Next button while waiting
        if (nextBtn) {
            nextBtn.disabled = true;
            nextBtn.textContent = 'Waiting...';
        }
        waitForCondition(step.waitFor, () => {
            if (nextBtn) {
                nextBtn.disabled = false;
                nextBtn.textContent = 'Next';
            }
            // Auto-advance after a short delay if configured
            if (step.autoNext === true) {
                setTimeout(nextStep, 1500);
            }
        });
    } else {
        // No wait — ensure Next button is enabled
        if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.textContent = 'Next';
        }
    }
}

// ---------------------------------------------------------------------------
// Step Counter
// ---------------------------------------------------------------------------

/**
 * Update the "Step X of Y" counter text.
 *
 * @param {number} stepIndex - Zero-based index of the current step.
 */
function updateStepCounter(stepIndex) {
    const counter = document.getElementById('tourStepCounter');
    if (counter) {
        counter.textContent = `Step ${stepIndex + 1} of ${tourSteps.length}`;
    }
}

// ---------------------------------------------------------------------------
// Navigation — Next / Previous
// ---------------------------------------------------------------------------

/**
 * Advance to the next tour step, or end the tour if on the last step.
 */
function nextStep() {
    currentStep++;
    if (currentStep < tourSteps.length) {
        showStep(currentStep);
    } else {
        endTour();
    }
}

/**
 * Go back to the previous tour step (no-op if already on step 0).
 */
function prevStep() {
    if (currentStep > 0) {
        currentStep--;
        showStep(currentStep);
    }
}

// ---------------------------------------------------------------------------
// End Step & Tour Cleanup
// ---------------------------------------------------------------------------

/**
 * Display the final "Tour Complete!" step.
 *
 * Hides the highlight, centers the message box on screen, changes the Next
 * button to "Finish", and hides the Back button.
 */
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

    // Change Next button to "Finish"
    if (nextBtn) {
        nextBtn.textContent = 'Finish';
        nextBtn.onclick = endTour;
    }

    // Hide back button (close X stays visible)
    if (prevBtn) prevBtn.classList.add('hidden');
}

/**
 * End the tour and clean up all tour-related DOM modifications.
 *
 * Cleanup includes:
 *   - Resetting the tourActive flag
 *   - Clearing cached message-box positions
 *   - Removing the `tour-active` body class (re-enables horizontal scroll)
 *   - Resetting z-index overrides applied to interactive elements
 *   - Hiding the message box, overlay, and highlight
 *   - Removing dynamically created multi-highlight and overlay-section elements
 *   - Re-showing the tour prompt after a short delay
 */
function endTour() {
    tourActive = false;

    // Clear cached positions
    window.surfacePlotMessagePosition = null;

    // Remove overflow prevention
    document.body.classList.remove('tour-active');

    // Reset any z-index changes applied to make elements clickable during tour
    document.querySelectorAll('[style*="z-index: 10000"]').forEach(el => {
        el.style.zIndex = '';
        el.style.position = '';
    });

    // Hide all tour UI elements
    const elements = ['tourMessageBox', 'tourOverlay', 'tourHighlight'];
    elements.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // Remove dynamically created multi-highlight boxes
    document.querySelectorAll('.tour-multi-highlight').forEach(el => el.remove());

    // Remove dynamically created overlay sections (the darkened cutout panels)
    document.querySelectorAll('.tour-overlay-section').forEach(el => el.remove());

    // Reset main overlay styles
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

// ---------------------------------------------------------------------------
// Condition Waiting — polls for async events before enabling "Next"
// ---------------------------------------------------------------------------

/**
 * Poll for an asynchronous condition and invoke a callback when it resolves.
 *
 * Supported conditions:
 *   - 'plotsLoaded'     — waits until window.stampsDataLoaded === true
 *                         (set by main.js after data processing completes)
 *   - 'spectrumOpened'  — waits until the #enableSurfaceClick checkbox is
 *                         checked AND #spectrumContainer is visible
 *
 * @param {string}   condition - The condition identifier to wait for.
 * @param {Function} callback  - Called once the condition is satisfied.
 */
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

// ---------------------------------------------------------------------------
// Global Export — used by main.js to check if tour is active
// ---------------------------------------------------------------------------

/**
 * Expose a getter so main.js can check tour state via window.tourActive().
 * @returns {boolean} Whether the tour is currently running.
 */
window.tourActive = () => tourActive;

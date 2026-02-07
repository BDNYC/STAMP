/* tour-core.js -- Tour Lifecycle, Navigation & Step Display */

console.log('TOUR-CORE.JS LOADED');

/* Timer & state tracking -- cleared on every step transition and tour end */

/** Interval ID from waitForCondition(), cleared on step change */
let activeWaitInterval = null;

/** Timeout ID from autoNext setTimeout, cleared on step change */
let autoNextTimeout = null;

/** Timeout ID for the highlight/position delay after scrolling */
let highlightTimeout = null;

/** rAF ID for scroll-settled detection loop */
let scrollCheckRafId = null;

/** True when the end step is displayed; makes Next call endTour() */
let isOnEndStep = false;

/** True when user pressed Back; suppresses waitFor/autoNext on the target step */
let navigatingBack = false;

/** Cancel any running waitForCondition interval and autoNext timeout. */
function clearActiveTimers() {
    if (activeWaitInterval !== null) {
        clearInterval(activeWaitInterval);
        activeWaitInterval = null;
    }
    if (autoNextTimeout !== null) {
        clearTimeout(autoNextTimeout);
        autoNextTimeout = null;
    }
    if (highlightTimeout !== null) {
        clearTimeout(highlightTimeout);
        highlightTimeout = null;
    }
    if (scrollCheckRafId !== null) {
        cancelAnimationFrame(scrollCheckRafId);
        scrollCheckRafId = null;
    }
}

/** Check whether a waitFor condition is already satisfied. */
function isConditionCurrentlyMet(condition) {
    if (condition === 'plotsLoaded') {
        return window.stampsDataLoaded === true;
    }
    if (condition === 'spectrumOpened') {
        const spectrumContainer = document.getElementById('spectrumContainer');
        const checkbox = document.getElementById('enableSurfaceClick');
        return !!(checkbox && checkbox.checked &&
            spectrumContainer && !spectrumContainer.classList.contains('hidden'));
    }
    return false;
}

/* Initialization -- runs once when the DOM is ready */

/** Bootstrap the tour system on page load. */
document.addEventListener('DOMContentLoaded', function () {
    // Always show tour prompt on page load
    setTimeout(() => {
        showTourPrompt();
    }, 500);

    // Setup event listeners
    setupEventListeners();
});

/* Event Binding */

/** Bind click handlers to all tour UI buttons. */
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

/* Tour Prompt */

/** Display the initial tour prompt dialog with optimal positioning. */
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

            console.log('Tour Prompt Positioning:');
            console.log('  Container right edge:', containerRect.right);
            console.log('  Viewport width:', viewportWidth);
            console.log('  Space after container:', spaceAfterContainer);
            console.log('  Optimal left:', optimalLeft);
            console.log('  Final left:', finalLeft);
        }
    }
}

/** Hide the tour prompt dialog. */
function hideTourPrompt() {
    const prompt = document.getElementById('tourPrompt');
    if (prompt) {
        prompt.classList.add('hidden');
    }
}

/* Tour Start / Decline */

/** Begin the interactive tour. */
function startTour() {
    hideTourPrompt();
    tourActive = true;
    currentStep = 0;

    // Clean up state from any previous tour run
    clearActiveTimers();
    isOnEndStep = false;
    navigatingBack = false;

    // Remove any lingering onclick handler left by showEndStep from a prior tour
    const nextBtn = document.getElementById('tourNextBtn');
    if (nextBtn) {
        nextBtn.onclick = null;
    }

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

/** Decline the tour -- simply hides the prompt. */
function declineTour() {
    hideTourPrompt();
}

/* Step Display -- the core rendering function */

/** Display a specific tour step by index. */
function showStep(stepIndex) {
    // Clean up timers and state from the previous step
    clearActiveTimers();
    isOnEndStep = false;

    // Capture and clear the back-navigation flag
    const isBackNavigation = navigatingBack;
    navigatingBack = false;

    const step = tourSteps[stepIndex];

    // Validation
    if (!step) {
        endTour();
        return;
    }

    // Update message box content
    updateStepCounter(stepIndex);

    const titleEl = document.getElementById('tourTitle');
    const messageEl = document.getElementById('tourMessage');
    const messageBox = document.getElementById('tourMessageBox');
    const nextBtn = document.getElementById('tourNextBtn');
    const prevBtn = document.getElementById('tourPrevBtn');

    if (titleEl) titleEl.textContent = step.title;
    if (messageEl) messageEl.textContent = step.message;

    // Back button visibility
    if (prevBtn) {
        if (stepIndex > 0) {
            prevBtn.classList.remove('hidden');
        } else {
            prevBtn.classList.add('hidden');
        }
    }

    // Show overlay (transparent; cutouts handle darkening)
    const overlay = document.getElementById('tourOverlay');
    if (overlay) {
        overlay.classList.remove('hidden');
        overlay.classList.remove('preserve-plot');
        overlay.style.background = 'transparent';
        overlay.style.clipPath = '';
    }

    // Handle end step
    if (step.isEnd) {
        showEndStep();
        return;
    }

    // Ensure message box is visible
    if (messageBox) {
        messageBox.classList.remove('hidden');
        messageBox.classList.remove('positioning');
    }

    // Scroll, highlight, and position
    if (step.element) {
        const element = document.querySelector(step.element);
        console.log('Tour Step:', step.id, 'Element:', step.element, 'Found:', element);

        if (element) {
            // Clear focus from this element if it has it
            if (element === document.activeElement) {
                element.blur();
            }

            // When step highlights multiple elements, compute a combined
            // bounding rect so the scroll and visibility check cover the
            // full highlighted region.
            let rect;
            if (step.highlightMultiple && Array.isArray(step.highlightMultiple)) {
                const rects = step.highlightMultiple
                    .map(sel => document.querySelector(sel))
                    .filter(Boolean)
                    .map(el => el.getBoundingClientRect());
                if (rects.length > 0) {
                    rect = {
                        top: Math.min(...rects.map(r => r.top)),
                        left: Math.min(...rects.map(r => r.left)),
                        bottom: Math.max(...rects.map(r => r.bottom)),
                        right: Math.max(...rects.map(r => r.right))
                    };
                    rect.width = rect.right - rect.left;
                    rect.height = rect.bottom - rect.top;
                } else {
                    rect = element.getBoundingClientRect();
                }
            } else {
                element.getBoundingClientRect(); // force layout
                rect = element.getBoundingClientRect();
            }

            // Check if the target region is already fully visible
            const isInView = (
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                rect.right <= (window.innerWidth || document.documentElement.clientWidth)
            );

            // On back-navigation, ignore skipScroll
            const shouldSkipScroll = step.skipScroll && !isBackNavigation;

            const needsScroll = !shouldSkipScroll && !isInView;
            if (needsScroll) {
                if (step.highlightMultiple && Array.isArray(step.highlightMultiple)) {
                    // Scroll to center the combined bounding box
                    const scrollTop = window.pageYOffset;
                    const viewportHeight = window.innerHeight;
                    const absTop = rect.top + scrollTop;
                    const absBottom = rect.bottom + scrollTop;
                    const regionCenter = (absTop + absBottom) / 2;
                    const targetScroll = Math.max(0, regionCenter - (viewportHeight / 2));
                    window.scrollTo({ top: targetScroll, behavior: 'smooth' });
                } else {
                    scrollToElement(element);
                }
            }

            // Helper: highlight elements and position the message box.
            const doHighlightAndPosition = () => {
                if (step.highlightMultiple && Array.isArray(step.highlightMultiple)) {
                    highlightMultipleElements(step.highlightMultiple);
                } else {
                    highlightElement(element);
                }
                positionMessageBox(element, step.position);
                // Re-enable CSS transitions after positioning
                if (messageBox) {
                    requestAnimationFrame(() => {
                        messageBox.style.transition = '';
                    });
                }
            };

            if (needsScroll) {
                // Suppress CSS transition so the message box snaps to the new position
                if (messageBox) messageBox.style.transition = 'none';

                // Wait for smooth scroll to finish before positioning.
                let lastY = window.pageYOffset;
                let stableFrames = 0;

                const checkSettled = () => {
                    const y = window.pageYOffset;
                    if (y === lastY) {
                        stableFrames++;
                        if (stableFrames >= 5) {
                            scrollCheckRafId = null;
                            doHighlightAndPosition();
                            return;
                        }
                    } else {
                        stableFrames = 0;
                        lastY = y;
                    }
                    scrollCheckRafId = requestAnimationFrame(checkSettled);
                };

                // Small delay to let the smooth scroll animation start
                highlightTimeout = setTimeout(() => {
                    scrollCheckRafId = requestAnimationFrame(checkSettled);
                }, 50);
            } else {
                doHighlightAndPosition();
            }
        }
    } else {
        // No element to highlight -- center the message box on screen
        if (messageBox) {
            messageBox.style.position = 'fixed';
            messageBox.style.left = '50%';
            messageBox.style.top = '50%';
            messageBox.style.transform = 'translate(-50%, -50%)';
        }
    }

    // Wait conditions
    if (step.waitFor) {
        const alreadyMet = isConditionCurrentlyMet(step.waitFor);

        if (isBackNavigation || alreadyMet) {
            if (nextBtn) {
                nextBtn.disabled = false;
                nextBtn.textContent = 'Next';
            }
        } else {
            // Condition not yet met -- disable Next and start polling.
            if (nextBtn) {
                nextBtn.disabled = true;
                nextBtn.textContent = 'Waiting...';
            }
            waitForCondition(step.waitFor, () => {
                // Guard: if the user navigated away before the condition
                // resolved, ignore this stale callback.
                if (currentStep !== stepIndex) return;

                if (nextBtn) {
                    nextBtn.disabled = false;
                    nextBtn.textContent = 'Next';
                }
                if (step.autoNext === true) {
                    autoNextTimeout = setTimeout(nextStep, 1500);
                }
            });
        }
    } else {
        // No wait -- ensure Next button is enabled
        if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.textContent = 'Next';
        }
    }
}

/* Step Counter */

/** Update the "Step X of Y" counter text. */
function updateStepCounter(stepIndex) {
    const counter = document.getElementById('tourStepCounter');
    if (counter) {
        counter.textContent = `Step ${stepIndex + 1} of ${tourSteps.length}`;
    }
}

/* Navigation -- Next / Previous */

/** Advance to the next tour step, or end the tour if on the last step. */
function nextStep() {
    if (isOnEndStep) {
        endTour();
        return;
    }

    currentStep++;
    if (currentStep < tourSteps.length) {
        showStep(currentStep);
    } else {
        endTour();
    }
}

/** Go back to the previous tour step. */
function prevStep() {
    if (currentStep > 0) {
        currentStep--;
        navigatingBack = true;
        showStep(currentStep);
    }
}

/* End Step & Tour Cleanup */

/** Display the final "Tour Complete!" step. */
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

    // Change Next button to "Finish" and set flag for nextStep() to check.
    if (nextBtn) {
        nextBtn.textContent = 'Finish';
        nextBtn.disabled = false;
    }
    isOnEndStep = true;

    // Hide back button (close X stays visible)
    if (prevBtn) prevBtn.classList.add('hidden');
}

/** End the tour and clean up all tour-related DOM modifications. */
function endTour() {
    tourActive = false;

    // Cancel any running timers from the last step
    clearActiveTimers();
    isOnEndStep = false;
    navigatingBack = false;

    // Remove any onclick handler that showEndStep may have set and reset button
    const nextBtn = document.getElementById('tourNextBtn');
    if (nextBtn) {
        nextBtn.onclick = null;
        nextBtn.disabled = false;
        nextBtn.textContent = 'Next';
    }

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

/* Condition Waiting -- polls for async events before enabling "Next" */

/** Poll for an async condition and invoke callback when it resolves. */
function waitForCondition(condition, callback) {
    // Clear any previously running wait interval (safety net)
    if (activeWaitInterval !== null) {
        clearInterval(activeWaitInterval);
        activeWaitInterval = null;
    }

    if (condition === 'plotsLoaded') {
        activeWaitInterval = setInterval(() => {
            if (window.stampsDataLoaded === true) {
                clearInterval(activeWaitInterval);
                activeWaitInterval = null;
                callback();
            }
        }, 500);
    } else if (condition === 'spectrumOpened') {
        activeWaitInterval = setInterval(() => {
            const spectrumContainer = document.getElementById('spectrumContainer');
            const checkbox = document.getElementById('enableSurfaceClick');

            // Only proceed if checkbox is checked AND spectrum viewer is visible
            if (checkbox && checkbox.checked &&
                spectrumContainer && !spectrumContainer.classList.contains('hidden')) {
                clearInterval(activeWaitInterval);
                activeWaitInterval = null;
                // Small delay to ensure everything is rendered
                setTimeout(callback, 300);
            }
        }, 200);
    }
}

/* Global Export -- used by main.js to check if tour is active */

/** Expose a getter so main.js can check tour state via window.tourActive(). */
window.tourActive = () => tourActive;

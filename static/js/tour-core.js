/* tour-core.js -- Tour Lifecycle, Navigation & Step Display */

/* Timer & state tracking */

/** Cleanup function for the active waitForCondition (observer / listener). */
let activeWaitCleanup = null;

/** Timeout ID from autoNext setTimeout. */
let autoNextTimeout = null;

/** Timeout ID for the highlight/position delay after scrolling. */
let highlightTimeout = null;

/** True when the end step is displayed; makes Next call endTour(). */
let isOnEndStep = false;

/** True when user pressed Back; suppresses waitFor/autoNext on the target step. */
let navigatingBack = false;

/** Cancel any running wait, autoNext, or scroll timer. */
function clearActiveTimers() {
    if (activeWaitCleanup) {
        activeWaitCleanup();
        activeWaitCleanup = null;
    }
    if (autoNextTimeout !== null) {
        clearTimeout(autoNextTimeout);
        autoNextTimeout = null;
    }
    if (highlightTimeout !== null) {
        clearTimeout(highlightTimeout);
        highlightTimeout = null;
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
    if (condition === 'gridFitComplete') {
        return typeof showGridFitOverlay !== 'undefined' && showGridFitOverlay === true;
    }
    if (condition === 'gridSweepComplete') {
        var container = document.getElementById('derivedPlotContainer');
        return !!(container && !container.classList.contains('hidden'));
    }
    if (condition === 'sineFitComplete') {
        return typeof showSineFitOverlay !== 'undefined' && showSineFitOverlay === true;
    }
    if (condition === 'sineSweepComplete') {
        return window._sineSweepDone === true;
    }
    return false;
}

/* Initialization */

document.addEventListener('DOMContentLoaded', function () {
    setTimeout(function () {
        showTourPrompt();
    }, 500);
    setupEventListeners();
});

/* Event Binding */

function setupEventListeners() {
    const acceptBtn  = document.getElementById('tourAcceptBtn');
    const declineBtn = document.getElementById('tourDeclineBtn');
    const nextBtn    = document.getElementById('tourNextBtn');
    const prevBtn    = document.getElementById('tourPrevBtn');
    const closeBtn   = document.getElementById('tourCloseBtn');

    if (acceptBtn)  acceptBtn.addEventListener('click', startTour);
    if (declineBtn) declineBtn.addEventListener('click', declineTour);
    if (nextBtn)    nextBtn.addEventListener('click', nextStep);
    if (prevBtn)    prevBtn.addEventListener('click', prevStep);
    if (closeBtn)   closeBtn.addEventListener('click', endTour);
}

/* Tour Prompt */

function showTourPrompt() {
    const prompt = document.getElementById('tourPrompt');
    if (!prompt) return;
    prompt.classList.remove('hidden');

    const container = document.querySelector('.max-w-4xl');
    if (container) {
        const containerRect = container.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const promptWidth   = 240;
        const spaceAfter    = viewportWidth - containerRect.right;
        let optimalLeft     = containerRect.right + (spaceAfter / 2) - (promptWidth / 2) - 5;
        optimalLeft = Math.max(5, Math.min(viewportWidth - promptWidth - 5, optimalLeft));
        prompt.style.left  = optimalLeft + 'px';
        prompt.style.right = 'auto';
    }
}

function hideTourPrompt() {
    const prompt = document.getElementById('tourPrompt');
    if (prompt) prompt.classList.add('hidden');
}

/* Tour Start / Decline */

function startTour() {
    hideTourPrompt();
    tourActive = true;
    currentStep = 0;

    clearActiveTimers();
    isOnEndStep = false;
    navigatingBack = false;

    const nextBtn = document.getElementById('tourNextBtn');
    if (nextBtn) nextBtn.onclick = null;

    if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
    }

    document.body.classList.add('tour-active');
    lockScroll();

    // Instant scroll to top
    window.scrollTo({ top: 0, behavior: 'instant' });

    // Show overlay, then show first step after paint
    showOverlay();
    requestAnimationFrame(function () {
        showStep(currentStep);
    });
}

function declineTour() {
    hideTourPrompt();
}

/* Step Display */

function showStep(stepIndex) {
    clearActiveTimers();
    isOnEndStep = false;

    const isBackNavigation = navigatingBack;
    navigatingBack = false;

    const step = tourSteps[stepIndex];
    if (!step) {
        endTour();
        return;
    }

    // Programmatically open any <details> elements this step requires
    if (step.openDetails && Array.isArray(step.openDetails)) {
        step.openDetails.forEach(function (selector) {
            var details = document.querySelector(selector);
            if (details && !details.open) details.open = true;
        });
    }

    const titleEl    = document.getElementById('tourTitle');
    const messageEl  = document.getElementById('tourMessage');
    const messageBox = document.getElementById('tourMessageBox');
    const nextBtn    = document.getElementById('tourNextBtn');
    const prevBtn    = document.getElementById('tourPrevBtn');

    if (titleEl)   titleEl.textContent   = step.title;
    if (messageEl) messageEl.textContent = step.message;

    // Back button visibility
    if (prevBtn) {
        prevBtn.classList.toggle('hidden', stepIndex <= 0);
    }

    // Handle end step
    if (step.isEnd) {
        showEndStep();
        return;
    }

    // Ensure message box is visible
    if (messageBox) {
        messageBox.classList.remove('hidden');
    }

    // Compute which selectors to highlight
    const highlightSelectors = (step.highlightMultiple && Array.isArray(step.highlightMultiple))
        ? step.highlightMultiple
        : (step.element ? [step.element] : []);

    if (step.element) {
        const element = document.querySelector(step.element);
        if (!element) {
            // Element not found — show message centred
            centreMessageBox(messageBox);
            clearHighlights();
            setupWaitCondition(step, stepIndex, isBackNavigation, nextBtn);
            return;
        }

        // Clear focus from element
        if (element === document.activeElement) element.blur();

        // Should we scroll?
        const shouldSkipScroll = step.skipScroll && !isBackNavigation;
        var scrollTarget = false;
        if (!shouldSkipScroll) {
            scrollTarget = scrollToElement(element, highlightSelectors);
        }
        var needsScroll = scrollTarget !== false;

        if (needsScroll) {
            // CSS slide + scroll run in parallel
            positionHighlights(highlightSelectors);
            positionMessageBox(element, step.position, { targetScrollTop: scrollTarget });
            syncClipPathWithBoxes(); // override 450ms with indefinite

            const stepAtScroll = currentStep;
            const onScrollSettled = function () {
                if (currentStep !== stepAtScroll) return;
                stopClipPathSync();
                positionHighlights(highlightSelectors, { skipTransition: true });
                positionMessageBox(element, step.position, { skipTransition: true });
                syncClipPathWithBoxes(300); // catch post-settle scroll drift
            };

            if ('onscrollend' in window) {
                const handler = function () {
                    window.removeEventListener('scrollend', handler);
                    clearTimeout(highlightTimeout);
                    highlightTimeout = null;
                    onScrollSettled();
                };
                window.addEventListener('scrollend', handler, { once: true });
                highlightTimeout = setTimeout(function () {
                    window.removeEventListener('scrollend', handler);
                    onScrollSettled();
                }, 1200);
            } else {
                highlightTimeout = setTimeout(onScrollSettled, 800);
            }
        } else {
            // No scroll — let highlights and message box slide (or snap on first step)
            positionHighlights(highlightSelectors);
            positionMessageBox(element, step.position);
        }
    } else {
        // No element — centre the message box, clear highlights
        centreMessageBox(messageBox);
        clearHighlights();
    }

    // Set up wait conditions
    setupWaitCondition(step, stepIndex, isBackNavigation, nextBtn);
}

/** Centre the message box on screen (for no-element steps). */
function centreMessageBox(messageBox) {
    if (!messageBox) return;
    messageBox.classList.remove('hidden');
    messageBox.style.position  = 'fixed';
    messageBox.style.left      = '50%';
    messageBox.style.top       = '50%';
    messageBox.style.transform = 'translate(-50%, -50%)';
    messageBox.style.right     = 'auto';
}

/** Scroll to afterElement and re-position highlights/message box. */
function transitionToAfterState(step) {
    var afterEl = document.querySelector(step.afterElement);
    var afterSelectors = step.afterHighlightMultiple || [step.afterElement];
    if (!afterEl) return;

    // Capture step index so scroll-settle callback is ignored if user navigated away
    var stepAtCall = currentStep;

    // Update message text if provided
    if (step.afterMessage) {
        var messageEl = document.getElementById('tourMessage');
        if (messageEl) messageEl.textContent = step.afterMessage;
    }

    var scrollTarget = scrollToElement(afterEl, afterSelectors);
    var needsScroll = scrollTarget !== false;

    if (needsScroll) {
        // CSS slide + scroll run in parallel
        positionHighlights(afterSelectors);
        positionMessageBox(afterEl, step.position, { targetScrollTop: scrollTarget });
        syncClipPathWithBoxes(); // override 450ms with indefinite

        var onSettled = function () {
            if (currentStep !== stepAtCall) return;
            stopClipPathSync();
            positionHighlights(afterSelectors, { skipTransition: true });
            positionMessageBox(afterEl, step.position, { skipTransition: true });
            syncClipPathWithBoxes(300); // catch post-settle scroll drift
        };
        if ('onscrollend' in window) {
            var handler = function () {
                window.removeEventListener('scrollend', handler);
                clearTimeout(highlightTimeout);
                highlightTimeout = null;
                onSettled();
            };
            window.addEventListener('scrollend', handler, { once: true });
            highlightTimeout = setTimeout(function () {
                window.removeEventListener('scrollend', handler);
                onSettled();
            }, 1200);
        } else {
            highlightTimeout = setTimeout(onSettled, 800);
        }
    } else {
        // No scroll — let highlights and message box slide to new position
        positionHighlights(afterSelectors);
        positionMessageBox(afterEl, step.position);
    }
}

/** Set up waitFor conditions and Next button state for a step. */
function setupWaitCondition(step, stepIndex, isBackNavigation, nextBtn) {
    if (step.waitFor) {
        const alreadyMet = isConditionCurrentlyMet(step.waitFor);

        if (isBackNavigation || alreadyMet) {
            if (nextBtn) {
                nextBtn.disabled = false;
                nextBtn.textContent = 'Next';
            }
            // If already met and step has afterElement, show the after state
            if (alreadyMet && step.afterElement) {
                transitionToAfterState(step);
            }
        } else {
            if (nextBtn) {
                nextBtn.disabled = true;
                nextBtn.textContent = 'Waiting...';
            }
            waitForCondition(step.waitFor, function () {
                if (currentStep !== stepIndex) return;
                if (nextBtn) {
                    nextBtn.disabled = false;
                    nextBtn.textContent = 'Next';
                }
                // Scroll to afterElement and re-highlight when condition is met
                if (step.afterElement) {
                    transitionToAfterState(step);
                }
                if (step.autoNext === true) {
                    autoNextTimeout = setTimeout(nextStep, 1000);
                }
            });
        }
    } else {
        if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.textContent = 'Next';
        }
    }
}

/* Navigation */

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

function prevStep() {
    if (currentStep > 0) {
        currentStep--;
        navigatingBack = true;
        showStep(currentStep);
    }
}

/* End Step & Tour Cleanup */

function showEndStep() {
    const messageBox = document.getElementById('tourMessageBox');
    const nextBtn    = document.getElementById('tourNextBtn');
    const prevBtn    = document.getElementById('tourPrevBtn');

    clearHighlights();
    centreMessageBox(messageBox);

    if (nextBtn) {
        nextBtn.textContent = 'Finish';
        nextBtn.disabled = false;
    }
    isOnEndStep = true;

    if (prevBtn) prevBtn.classList.add('hidden');
}

function endTour() {
    tourActive = false;
    clearActiveTimers();
    isOnEndStep = false;
    navigatingBack = false;

    const nextBtn = document.getElementById('tourNextBtn');
    if (nextBtn) {
        nextBtn.onclick = null;
        nextBtn.disabled = false;
        nextBtn.textContent = 'Next';
    }

    unlockScroll();
    document.body.classList.remove('tour-active');

    // Fade out highlights and overlay
    clearHighlights();
    hideOverlay();

    // Hide message box
    const messageBox = document.getElementById('tourMessageBox');
    if (messageBox) {
        messageBox.classList.add('hidden');
        messageBox.style.transform = '';
    }

    // Show tour prompt again after a short delay
    setTimeout(function () {
        showTourPrompt();
    }, 300);
}

/* Condition Waiting (event-driven) */

function waitForCondition(condition, callback) {
    // Clear any previous wait
    if (activeWaitCleanup) {
        activeWaitCleanup();
        activeWaitCleanup = null;
    }

    if (condition === 'plotsLoaded') {
        // Check if already met
        if (window.stampsDataLoaded === true) {
            callback();
            return;
        }
        // Listen for custom event (dispatched from main-upload.js)
        const handler = function () {
            window.removeEventListener('stampsDataLoaded', handler);
            activeWaitCleanup = null;
            callback();
        };
        window.addEventListener('stampsDataLoaded', handler);
        activeWaitCleanup = function () {
            window.removeEventListener('stampsDataLoaded', handler);
        };

    } else if (condition === 'spectrumOpened') {
        const spectrumContainer = document.getElementById('spectrumContainer');
        const checkbox = document.getElementById('enableSurfaceClick');
        if (!spectrumContainer) return;

        // Check if already met
        if (checkbox && checkbox.checked &&
            !spectrumContainer.classList.contains('hidden')) {
            callback();
            return;
        }

        // Watch for class changes on spectrum container (removal of 'hidden')
        const observer = new MutationObserver(function () {
            const chk = document.getElementById('enableSurfaceClick');
            if (chk && chk.checked &&
                !spectrumContainer.classList.contains('hidden')) {
                observer.disconnect();
                activeWaitCleanup = null;
                callback();
            }
        });
        observer.observe(spectrumContainer, { attributes: true, attributeFilter: ['class'] });
        activeWaitCleanup = function () {
            observer.disconnect();
        };

    } else if (condition === 'gridFitComplete') {
        if (typeof showGridFitOverlay !== 'undefined' && showGridFitOverlay === true) {
            callback();
            return;
        }
        const handler = function () {
            window.removeEventListener('gridFitComplete', handler);
            activeWaitCleanup = null;
            callback();
        };
        window.addEventListener('gridFitComplete', handler);
        activeWaitCleanup = function () {
            window.removeEventListener('gridFitComplete', handler);
        };

    } else if (condition === 'gridSweepComplete') {
        var container = document.getElementById('derivedPlotContainer');
        if (container && !container.classList.contains('hidden')) {
            callback();
            return;
        }
        const handler = function () {
            window.removeEventListener('gridSweepComplete', handler);
            activeWaitCleanup = null;
            callback();
        };
        window.addEventListener('gridSweepComplete', handler);
        activeWaitCleanup = function () {
            window.removeEventListener('gridSweepComplete', handler);
        };

    } else if (condition === 'sineFitComplete') {
        if (typeof showSineFitOverlay !== 'undefined' && showSineFitOverlay === true) {
            callback();
            return;
        }
        const handler = function () {
            window.removeEventListener('sineFitComplete', handler);
            activeWaitCleanup = null;
            callback();
        };
        window.addEventListener('sineFitComplete', handler);
        activeWaitCleanup = function () {
            window.removeEventListener('sineFitComplete', handler);
        };

    } else if (condition === 'sineSweepComplete') {
        if (window._sineSweepDone === true) {
            callback();
            return;
        }
        const handler = function () {
            window.removeEventListener('sineSweepComplete', handler);
            activeWaitCleanup = null;
            callback();
        };
        window.addEventListener('sineSweepComplete', handler);
        activeWaitCleanup = function () {
            window.removeEventListener('sineSweepComplete', handler);
        };
    }
}

/* Global Export */

window.tourActive = function () { return tourActive; };

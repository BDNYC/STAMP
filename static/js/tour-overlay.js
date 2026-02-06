/*
 * ============================================================================
 * tour-overlay.js — Visual Layer (highlighting, overlay, scroll, positioning)
 * ============================================================================
 *
 * Pure DOM-manipulation functions for the tour's visual effects.  These
 * functions have NO tour lifecycle logic — they are called by tour-core.js.
 *
 * Requires:  tour-steps.js (provides tourSteps, currentStep)
 *
 * Z-index hierarchy (lowest → highest):
 *   9998  .tour-overlay-section  — dark semi-transparent overlay panels
 *   9999  #tourHighlight /
 *         .tour-multi-highlight  — white-border highlight boxes
 *  10000  interactive elements   — elements the user must click during tour
 *  10001  #tourMessageBox        — message box (always on top for button clicks)
 *
 * Load order:  tour-steps.js → tour-overlay.js → tour-core.js
 * ============================================================================
 */

console.log(' TOUR-OVERLAY.JS LOADED');


// ---------------------------------------------------------------------------
// highlightMultipleElements — highlight several elements simultaneously
// ---------------------------------------------------------------------------

/**
 * Highlight multiple DOM elements at once with white-bordered boxes and
 * create a darkened overlay with cutouts around them.
 *
 * Used for steps that reference related UI groups (e.g. a plot and its
 * band buttons).  Each selector gets its own highlight box positioned
 * absolutely over the element.
 *
 * @param {string[]} selectors - CSS selectors for elements to highlight.
 */
function highlightMultipleElements(selectors) {
    const highlight = document.getElementById('tourHighlight');
    if (!highlight) return;

    // Hide the single-element highlight box
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

        // Create a highlight box around the element
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

        // Make elements clickable if the step requires user interaction
        const step = tourSteps[currentStep];
        if (step && (step.waitFor === 'plotsLoaded' || step.action === 'checkBox')) {
            element.style.position = 'relative';
            element.style.zIndex = '10000';
        }
    });

    // Update overlay to cut out highlighted areas
    updateOverlayWithCutouts(selectors);
}


// ---------------------------------------------------------------------------
// updateOverlayWithCutouts — dark overlay that leaves highlighted areas clear
// ---------------------------------------------------------------------------

/**
 * Create four (or five) absolutely-positioned dark overlay panels around
 * the highlighted elements, leaving transparent cutouts so the highlighted
 * areas remain visible.
 *
 * Layout (single cutout):
 *   ┌──────────────────────────────┐
 *   │         TOP overlay          │
 *   ├────┬────────────────┬────────┤
 *   │LEFT│   (cutout)     │  RIGHT │
 *   ├────┴────────────────┴────────┤
 *   │        BOTTOM overlay        │
 *   └──────────────────────────────┘
 *
 * For two non-adjacent cutouts, a fifth "middle" panel fills the gap
 * between the two cutouts in the horizontal band.
 *
 * @param {string[]} selectors - CSS selectors for the highlighted elements.
 */
function updateOverlayWithCutouts(selectors) {
    const overlay = document.getElementById('tourOverlay');
    if (!overlay) return;

    // Remove old cutout overlays
    document.querySelectorAll('.tour-overlay-section').forEach(el => el.remove());

    if (!selectors || selectors.length === 0) {
        overlay.style.clipPath = '';
        return;
    }

    // Ensure main overlay is transparent (dark panels handle the dimming)
    overlay.style.background = 'transparent';

    // Compute bounding rects for each highlighted element (with 5px padding)
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

    // --- TOP panel: from page top to the top of the highest element -------
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

    // --- BOTTOM panel: from bottom of lowest element to page bottom -------
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

    // --- LEFT panel: middle band, left of leftmost element ----------------
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

    // --- RIGHT panel: middle band, right of rightmost element -------------
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

    // --- MIDDLE gap panel: for 2-element pairs with a horizontal gap ------
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


// ---------------------------------------------------------------------------
// scrollToElement — smart scrolling with viewport-aware margins
// ---------------------------------------------------------------------------

/**
 * Scroll the page so that the target element is comfortably visible,
 * accounting for the tour message box position and viewport margins.
 *
 * Skips scrolling if the element is already fully visible with margins.
 * Handles elements near the page bottom with gentler positioning.
 *
 * @param {HTMLElement} element - The DOM element to scroll into view.
 */
function scrollToElement(element) {
    const elementRect = element.getBoundingClientRect();
    const absoluteElementTop = elementRect.top + window.pageYOffset;
    const absoluteElementBottom = elementRect.bottom + window.pageYOffset;

    const viewportHeight = window.innerHeight;
    const currentScroll = window.pageYOffset;

    // Get current step to determine message box position
    const step = tourSteps[currentStep];
    const topMargin = 100;    // space at top of viewport
    const bottomMargin = 150; // space at bottom (extra room for message box)

    let targetScroll;

    // Check if element is already fully visible with margins
    const elementTopInView = elementRect.top >= topMargin;
    const elementBottomInView = elementRect.bottom <= viewportHeight - bottomMargin;

    if (elementTopInView && elementBottomInView) {
        return; // already well positioned
    }

    // Calculate document bounds
    const documentHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight
    );
    const maxScroll = Math.max(0, documentHeight - viewportHeight);

    // For elements near the bottom of the page, use gentle scrolling
    const elementDistanceFromBottom = documentHeight - absoluteElementBottom;
    const isNearBottom = elementDistanceFromBottom < viewportHeight * 0.5;

    if (isNearBottom) {
        // Scroll just enough to show the element with top/bottom margins
        targetScroll = Math.min(
            absoluteElementTop - topMargin,
            absoluteElementBottom - viewportHeight + bottomMargin
        );
        targetScroll = Math.max(0, Math.min(targetScroll, maxScroll));
    } else if (step && step.position === 'right') {
        // Message box on right — vertically center the element
        const elementCenter = (absoluteElementTop + absoluteElementBottom) / 2;
        targetScroll = elementCenter - (viewportHeight / 2);
        targetScroll = Math.max(0, Math.min(targetScroll, maxScroll));
    } else if (step && step.position === 'left') {
        // Message box on left — vertically center the element
        const elementCenter = (absoluteElementTop + absoluteElementBottom) / 2;
        targetScroll = elementCenter - (viewportHeight / 2);
        targetScroll = Math.max(0, Math.min(targetScroll, maxScroll));
    } else {
        // Default: position element near top with margin
        targetScroll = absoluteElementTop - topMargin;
        targetScroll = Math.max(0, Math.min(targetScroll, maxScroll));
    }

    window.scrollTo({
        top: targetScroll,
        behavior: 'smooth'
    });
}


// ---------------------------------------------------------------------------
// highlightElement — single-element highlight with overlay cutout
// ---------------------------------------------------------------------------

/**
 * Highlight a single DOM element by positioning the #tourHighlight box
 * over it, then creating a darkened overlay cutout around it.
 *
 * For the 3D surface plot, a special CSS class prevents the highlight
 * from brightening the plot colors.
 *
 * @param {HTMLElement} element - The DOM element to highlight.
 */
function highlightElement(element) {
    const highlight = document.getElementById('tourHighlight');
    if (!highlight) return;

    // Clear any existing cutouts first
    document.querySelectorAll('.tour-overlay-section').forEach(el => el.remove());

    // Force a fresh layout calculation — wait one frame
    requestAnimationFrame(() => {
        const rect = element.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        console.log('🎯 Highlighting element:', element.id || element.className);
        console.log('   Position:', {
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height
        });

        // Position the highlight box around the element (5px padding)
        highlight.style.top = (rect.top + scrollTop - 5) + 'px';
        highlight.style.left = (rect.left + scrollLeft - 5) + 'px';
        highlight.style.width = (rect.width + 10) + 'px';
        highlight.style.height = (rect.height + 10) + 'px';
        highlight.classList.remove('hidden');

        // Prevent brightening effect on the 3D surface plot
        if (element.id === 'surfacePlot') {
            highlight.classList.add('highlight-plot');
        } else {
            highlight.classList.remove('highlight-plot');
        }

        // Make the element clickable during tour if step requires interaction
        const step = tourSteps[currentStep];
        if (step && (step.waitFor === 'plotsLoaded' || step.action === 'checkBox')) {
            highlight.style.pointerEvents = 'none';
            element.style.position = 'relative';
            element.style.zIndex = '10000';
        }

        // Create overlay cutouts for this single highlight
        const selector = step.element;
        if (selector) {
            requestAnimationFrame(() => {
                updateOverlayWithCutouts([selector]);
            });
        }
    });
}


// ---------------------------------------------------------------------------
// positionMessageBox — complex message box positioning logic
// ---------------------------------------------------------------------------

/**
 * Position the tour message box relative to the highlighted element.
 *
 * This function handles five distinct positioning strategies based on the
 * current tour step:
 *
 * 1. **Surface plot steps** (surface-plot, surface-bands, enable-click):
 *    Left-side positioning, vertically centred on the 3D plot.  The
 *    position is cached in window.surfacePlotMessagePosition so subsequent
 *    surface steps stay pinned in the same spot.
 *
 * 2. **Spectrum / heatmap steps** (spectrum-viewer through heatmap-bands):
 *    Right-side positioning at ~95% down the viewport so the message box
 *    doesn't cover the plot data.
 *
 * 3. **Generic "left" position**:
 *    Centred in the space to the left of the main content container.
 *
 * 4. **Generic "right" position** (default):
 *    Centred in the space to the right of the main content container,
 *    vertically aligned with the highlighted element.
 *
 * 5. **File-selection override**:
 *    Fixed at 35% down the viewport for a comfortable first-step position.
 *
 * @param {HTMLElement} element  - The highlighted DOM element.
 * @param {'left'|'right'|'center'} position - Requested side for the box.
 */
function positionMessageBox(element, position) {
    const messageBox = document.getElementById('tourMessageBox');
    if (!messageBox) return;

    const rect = element.getBoundingClientRect();
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    // Get the main content container for reference positioning
    const container = document.querySelector('.max-w-4xl');
    const containerRect = container ? container.getBoundingClientRect() : null;

    const step = tourSteps[currentStep];

    // ======================================================================
    // Strategy 1: Surface plot steps — left side, cached position
    // ======================================================================
    const surfacePlotSteps = ['surface-plot', 'surface-bands', 'enable-click'];

    // Initialise the position cache if needed
    if (!window.surfacePlotMessagePosition) {
        window.surfacePlotMessagePosition = null;
    }

    if (step && surfacePlotSteps.includes(step.id)) {
        const viewportWidth = window.innerWidth;
        const messageBoxWidth = 280;
        let left, top;

        // Re-use cached position for surface-bands and enable-click
        if (window.surfacePlotMessagePosition && step.id !== 'surface-plot') {
            messageBox.style.transform = 'none';
            messageBox.style.position = 'absolute';
            messageBox.style.right = 'auto';
            messageBox.style.left = window.surfacePlotMessagePosition.left + 'px';
            messageBox.style.top = window.surfacePlotMessagePosition.top + 'px';
            console.log('Using cached surface plot position:', window.surfacePlotMessagePosition);
            return;
        }

        // Calculate left position (centred in space before container)
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

        // Vertically centre on the surface plot (with async refinement)
        requestAnimationFrame(() => {
            const plotRect = document.querySelector('#surfacePlot')?.getBoundingClientRect();
            if (plotRect) {
                const plotCenter = plotRect.top + (plotRect.height / 2);
                top = plotCenter - (messageBox.offsetHeight / 2) + scrollTop;
                const minTop = scrollTop + 80;
                const maxTop = scrollTop + window.innerHeight - messageBox.offsetHeight - 80;
                top = Math.max(minTop, Math.min(maxTop, top));
                messageBox.style.top = top + 'px';
                window.surfacePlotMessagePosition.top = top;
            }
        });

        // Set initial position (synchronous fallback)
        const plotRect = document.querySelector('#surfacePlot')?.getBoundingClientRect();
        if (plotRect) {
            const plotCenter = plotRect.top + (plotRect.height / 2);
            top = plotCenter - (messageBox.offsetHeight / 2) + scrollTop;
            const minTop = scrollTop + 80;
            const maxTop = scrollTop + window.innerHeight - messageBox.offsetHeight - 80;
            top = Math.max(minTop, Math.min(maxTop, top));
        } else {
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

    // ======================================================================
    // Strategy 2: Spectrum / heatmap steps — right side, lower viewport
    // ======================================================================
    const spectrumSteps = ['spectrum-viewer', 'spectrum-bands', 'error-bars', 'navigation-controls', 'x-axis-switch', 'time-mode-bands'];
    const heatmapSteps = ['heatmap', 'heatmap-bands'];

    if (step && (spectrumSteps.includes(step.id) || heatmapSteps.includes(step.id))) {
        const viewportWidth = window.innerWidth;
        const messageBoxWidth = 280;
        let left, top;

        // Right-side horizontal positioning
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

        // Position at 95% down viewport to avoid covering plot data
        const viewportHeight = window.innerHeight;
        top = scrollTop + (viewportHeight * 0.95) - (messageBox.offsetHeight / 2);

        // Keep within viewport bounds
        const maxTop = scrollTop + viewportHeight - messageBox.offsetHeight - 30;
        if (top > maxTop) top = maxTop;
        const minTop = scrollTop + (viewportHeight * 0.5);
        if (top < minTop) top = minTop;

        messageBox.style.transform = 'none';
        messageBox.style.position = 'absolute';
        messageBox.style.right = 'auto';
        messageBox.style.left = left + 'px';
        messageBox.style.top = top + 'px';

        console.log('Spectrum step message box positioned at:', left, top);
        return;
    }

    // ======================================================================
    // Strategy 3 & 4: Generic left / right positioning
    // ======================================================================
    let left, top;

    if (position === 'left') {
        // --- Strategy 3: Left side of viewport ---
        const messageBoxWidth = 280;
        if (containerRect) {
            const spaceBeforeContainer = containerRect.left;
            if (spaceBeforeContainer >= messageBoxWidth + 100) {
                left = (spaceBeforeContainer / 2) - (messageBoxWidth / 2);
            } else {
                left = 40;
            }
        } else {
            left = 40;
        }
        const minLeft = 20;
        if (left < minLeft) left = minLeft;

    } else if (containerRect) {
        // --- Strategy 4: Right side of container (default) ---
        const viewportWidth = window.innerWidth;
        const messageBoxWidth = 280;
        const spaceAfterContainer = viewportWidth - containerRect.right;

        if (spaceAfterContainer >= messageBoxWidth + 100) {
            left = containerRect.right + (spaceAfterContainer / 2) - (messageBoxWidth / 2);
        } else {
            left = viewportWidth - messageBoxWidth - 40;
        }

        // Ensure minimum 200px gap from container
        const minLeft = containerRect.right + 200;
        if (left < minLeft) left = minLeft;

        const maxLeft = viewportWidth - messageBoxWidth - 20;
        if (left > maxLeft) left = maxLeft;

    } else {
        // Fallback: far right of screen
        left = window.innerWidth - 320;
    }

    // Vertically centre message box relative to highlighted element
    const elementVerticalCenter = rect.top + (rect.height / 2) + scrollTop;
    top = elementVerticalCenter - (messageBox.offsetHeight / 2);

    // Keep within viewport bounds
    const minTop = scrollTop + 20;
    if (top < minTop) top = minTop;
    const maxTop = scrollTop + window.innerHeight - messageBox.offsetHeight - 20;
    if (top > maxTop) top = maxTop;

    // For small elements near the top of page, centre vertically
    if (rect.top < 300 && rect.height < 200) {
        const elementMidpoint = rect.top + (rect.height / 2) + scrollTop;
        top = elementMidpoint - (messageBox.offsetHeight / 2);
        const maxTopForFirstStep = scrollTop + window.innerHeight - messageBox.offsetHeight - 80;
        if (top > maxTopForFirstStep) top = maxTopForFirstStep;
        const absoluteMinTop = scrollTop + 80;
        if (top < absoluteMinTop) top = absoluteMinTop;
    }

    // ======================================================================
    // Strategy 5: File-selection override — fixed 35% down viewport
    // ======================================================================
    if (step && step.id === 'file-selection') {
        const viewportHeight = window.innerHeight;
        top = scrollTop + (viewportHeight * 0.35);
        const minTopFS = scrollTop + 100;
        const maxTopFS = scrollTop + viewportHeight - messageBox.offsetHeight - 100;
        top = Math.max(minTopFS, Math.min(maxTopFS, top));
    }

    // Apply final position
    messageBox.style.transform = 'none';
    messageBox.style.position = 'absolute';
    messageBox.style.right = 'auto';
    messageBox.style.left = left + 'px';
    messageBox.style.top = top + 'px';

    console.log('Message box positioned at:', left, 'Container right edge:', containerRect ? containerRect.right : 'N/A');
}

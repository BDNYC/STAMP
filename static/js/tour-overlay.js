/* tour-overlay.js -- Visual Layer (overlay, highlight pool, scroll, positioning) */

/* ── Overlay control ─────────────────────────────────────────────── */

/** Show the persistent dimming overlay (called once at tour start). */
function showOverlay() {
    const overlay = document.getElementById('tourOverlay');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    // Force a paint before adding .active so the opacity transition fires
    overlay.offsetHeight;
    overlay.classList.add('active');
}

/** Hide the dimming overlay (called once at tour end). */
function hideOverlay() {
    const overlay = document.getElementById('tourOverlay');
    if (!overlay) return;
    overlay.classList.remove('active');
    const onDone = () => {
        overlay.classList.add('hidden');
        overlay.removeEventListener('transitionend', onDone);
    };
    overlay.addEventListener('transitionend', onDone);
}

/* ── Highlight pool ──────────────────────────────────────────────── */

/**
 * Position highlight boxes from the pre-created pool around target elements.
 * Handles both single and multi-element highlighting in one code-path.
 *
 * @param {string[]} selectors  CSS selectors for elements to highlight
 * @param {object}   [opts]
 * @param {boolean}  [opts.skipTransition=false]  Snap instantly (after scroll)
 */
function positionHighlights(selectors, opts) {
    opts = opts || {};
    const pool = document.querySelectorAll('.tour-highlight-box');
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

    // Clear previously elevated elements
    document.querySelectorAll('.tour-elevated').forEach(function (el) {
        el.classList.remove('tour-elevated');
    });

    selectors.forEach(function (selector, i) {
        if (i >= pool.length) return; // pool exhausted
        var el = document.querySelector(selector);
        var box = pool[i];

        if (!el) {
            box.classList.remove('visible');
            return;
        }

        var rect = el.getBoundingClientRect();

        if (opts.skipTransition) {
            box.classList.add('no-transition');
        }

        box.style.top  = (rect.top  + scrollTop  - 5) + 'px';
        box.style.left = (rect.left + scrollLeft - 5) + 'px';
        box.style.width  = (rect.width  + 10) + 'px';
        box.style.height = (rect.height + 10) + 'px';
        box.classList.add('visible');

        // Elevate the actual DOM element above the overlay so it appears bright
        el.classList.add('tour-elevated');

        // Make interactive elements clickable during waitFor steps
        var step = tourSteps[currentStep];
        if (step && (step.waitFor || step.action)) {
            el.style.pointerEvents = 'auto';
        }

        if (opts.skipTransition) {
            // Force reflow so the position applies, then re-enable transitions
            box.offsetHeight;
            box.classList.remove('no-transition');
        }
    });

    // Fade out unused pool elements
    for (var i = selectors.length; i < pool.length; i++) {
        pool[i].classList.remove('visible');
    }
}

/** Fade out all highlight boxes and remove elevation from elements. */
function clearHighlights() {
    document.querySelectorAll('.tour-highlight-box').forEach(function (box) {
        box.classList.remove('visible');
    });
    document.querySelectorAll('.tour-elevated').forEach(function (el) {
        el.classList.remove('tour-elevated');
        el.style.pointerEvents = '';
    });
}

/* ── Scrolling ───────────────────────────────────────────────────── */

/**
 * Scroll the page so that the target region is comfortably visible.
 * Returns true if scrolling was initiated, false if already in view.
 *
 * @param {Element}  element           Primary element
 * @param {string[]} [highlightSelectors]  All selectors being highlighted (for combined bbox)
 * @returns {boolean}
 */
function scrollToElement(element, highlightSelectors) {
    var rect;

    // Compute combined bounding box when highlighting multiple elements
    if (highlightSelectors && highlightSelectors.length > 1) {
        var rects = highlightSelectors
            .map(function (sel) { return document.querySelector(sel); })
            .filter(Boolean)
            .map(function (el) { return el.getBoundingClientRect(); });
        if (rects.length > 0) {
            rect = {
                top:    Math.min.apply(null, rects.map(function (r) { return r.top; })),
                bottom: Math.max.apply(null, rects.map(function (r) { return r.bottom; })),
                left:   Math.min.apply(null, rects.map(function (r) { return r.left; })),
                right:  Math.max.apply(null, rects.map(function (r) { return r.right; }))
            };
        }
    }
    if (!rect) {
        rect = element.getBoundingClientRect();
    }

    var topMargin = 100;
    var bottomMargin = 150;

    // Already fully visible with margins?
    if (rect.top >= topMargin &&
        rect.bottom <= window.innerHeight - bottomMargin) {
        return false;
    }

    var scrollTop = window.pageYOffset;
    var absTop    = rect.top    + scrollTop;
    var absBottom = rect.bottom + scrollTop;
    var centre    = (absTop + absBottom) / 2;
    var target    = Math.max(0, centre - (window.innerHeight / 2));

    // Clamp so we don't over-scroll past the document
    var docHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var maxScroll = Math.max(0, docHeight - window.innerHeight);
    target = Math.min(target, maxScroll);

    window.scrollTo({ top: target, behavior: 'smooth' });
    return true;
}

/* ── Message box positioning ─────────────────────────────────────── */

/** Position the tour message box relative to the highlighted element. */
function positionMessageBox(element, position) {
    var messageBox = document.getElementById('tourMessageBox');
    if (!messageBox) return;

    var rect      = element.getBoundingClientRect();
    var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    var container = document.querySelector('.max-w-4xl');
    var containerRect = container ? container.getBoundingClientRect() : null;
    var step      = tourSteps[currentStep];
    var messageBoxWidth = 280;
    var viewportWidth   = window.innerWidth;
    var viewportHeight  = window.innerHeight;
    var left, top;

    // ── Strategy 1: Surface-plot steps (left side, centred on plot) ──
    var surfacePlotSteps = ['surface-plot', 'surface-bands', 'enable-click'];
    if (step && surfacePlotSteps.indexOf(step.id) !== -1) {
        if (containerRect) {
            var spaceBefore = containerRect.left;
            left = (spaceBefore >= messageBoxWidth + 100)
                ? (spaceBefore / 2) - (messageBoxWidth / 2)
                : 40;
            if (left < 20) left = 20;
        } else {
            left = 40;
        }

        var plotRect = document.querySelector('#surfacePlot');
        plotRect = plotRect ? plotRect.getBoundingClientRect() : null;
        if (plotRect) {
            var plotCentre = plotRect.top + (plotRect.height / 2);
            top = plotCentre - (messageBox.offsetHeight / 2) + scrollTop;
        } else {
            top = scrollTop + (viewportHeight / 2) - (messageBox.offsetHeight / 2);
        }
        top = Math.max(scrollTop + 80, Math.min(scrollTop + viewportHeight - messageBox.offsetHeight - 80, top));

        applyMessageBoxPosition(messageBox, left, top);
        return;
    }

    // ── Strategy 2: Spectrum / heatmap steps (right side, lower viewport) ──
    var spectrumSteps = ['spectrum-viewer', 'spectrum-bands', 'error-bars',
                         'navigation-controls', 'x-axis-switch', 'time-mode-bands'];
    var heatmapSteps  = ['heatmap', 'heatmap-bands'];
    if (step && (spectrumSteps.indexOf(step.id) !== -1 || heatmapSteps.indexOf(step.id) !== -1)) {
        if (containerRect) {
            var spaceAfter = viewportWidth - containerRect.right;
            left = (spaceAfter >= messageBoxWidth + 100)
                ? containerRect.right + (spaceAfter / 2) - (messageBoxWidth / 2)
                : viewportWidth - messageBoxWidth - 40;
            var minLeft = containerRect.right + 200;
            if (left < minLeft) left = minLeft;
            var maxLeft = viewportWidth - messageBoxWidth - 20;
            if (left > maxLeft) left = maxLeft;
        } else {
            left = viewportWidth - messageBoxWidth - 40;
        }

        top = scrollTop + (viewportHeight * 0.95) - (messageBox.offsetHeight / 2);
        var maxTop = scrollTop + viewportHeight - messageBox.offsetHeight - 30;
        if (top > maxTop) top = maxTop;
        var minTop = scrollTop + (viewportHeight * 0.5);
        if (top < minTop) top = minTop;

        applyMessageBoxPosition(messageBox, left, top);
        return;
    }

    // ── Strategy 3 & 4: Generic left / right positioning ──
    if (position === 'left') {
        if (containerRect) {
            var spaceBefore2 = containerRect.left;
            left = (spaceBefore2 >= messageBoxWidth + 100)
                ? (spaceBefore2 / 2) - (messageBoxWidth / 2)
                : 40;
        } else {
            left = 40;
        }
        if (left < 20) left = 20;
    } else if (containerRect) {
        var spaceAfter2 = viewportWidth - containerRect.right;
        left = (spaceAfter2 >= messageBoxWidth + 100)
            ? containerRect.right + (spaceAfter2 / 2) - (messageBoxWidth / 2)
            : viewportWidth - messageBoxWidth - 40;
        var minLeft2 = containerRect.right + 200;
        if (left < minLeft2) left = minLeft2;
        var maxLeft2 = viewportWidth - messageBoxWidth - 20;
        if (left > maxLeft2) left = maxLeft2;
    } else {
        left = viewportWidth - 320;
    }

    // Vertically centre on the highlighted element
    var elCentreY = rect.top + (rect.height / 2) + scrollTop;
    top = elCentreY - (messageBox.offsetHeight / 2);
    top = Math.max(scrollTop + 20, Math.min(scrollTop + viewportHeight - messageBox.offsetHeight - 20, top));

    // Small elements near page top: centre with generous padding
    if (rect.top < 300 && rect.height < 200) {
        var mid = rect.top + (rect.height / 2) + scrollTop;
        top = mid - (messageBox.offsetHeight / 2);
        top = Math.max(scrollTop + 80, Math.min(scrollTop + viewportHeight - messageBox.offsetHeight - 80, top));
    }

    // ── Strategy 5: File-selection override ──
    if (step && step.id === 'file-selection') {
        top = scrollTop + (viewportHeight * 0.35);
        top = Math.max(scrollTop + 100, Math.min(scrollTop + viewportHeight - messageBox.offsetHeight - 100, top));
    }

    applyMessageBoxPosition(messageBox, left, top);
}

/** Apply final position to the message box. */
function applyMessageBoxPosition(messageBox, left, top) {
    messageBox.style.transform = 'none';
    messageBox.style.position  = 'absolute';
    messageBox.style.right     = 'auto';
    messageBox.style.left      = left + 'px';
    messageBox.style.top       = top  + 'px';
}

/* tour-overlay.js -- Visual Layer (overlay, highlight pool, scroll, positioning) */

/* Scroll lock (block user scrolling, allow programmatic) */

/** Block user-initiated scrolling (wheel, touch, keyboard). */
var _scrollHandler = function (e) { e.preventDefault(); };
var _keyScrollHandler = function (e) {
    // Block Space, Page Up/Down, Home, End, Arrow Up/Down
    var keys = [32, 33, 34, 35, 36, 38, 40];
    if (keys.indexOf(e.keyCode) !== -1) e.preventDefault();
};

function lockScroll() {
    window.addEventListener('wheel', _scrollHandler, { passive: false });
    window.addEventListener('touchmove', _scrollHandler, { passive: false });
    window.addEventListener('keydown', _keyScrollHandler, { passive: false });
}

function unlockScroll() {
    window.removeEventListener('wheel', _scrollHandler);
    window.removeEventListener('touchmove', _scrollHandler);
    window.removeEventListener('keydown', _keyScrollHandler);
}

/* Clip-path ↔ highlight-box sync (rAF loop) */

var _clipSyncRAF = null;

function stopClipPathSync() {
    if (_clipSyncRAF !== null) {
        cancelAnimationFrame(_clipSyncRAF);
        _clipSyncRAF = null;
    }
}

/** Remove holes fully contained within another hole (prevents winding cancellation). */
function filterContainedHoles(holes) {
    return holes.filter(function (h, i) {
        for (var j = 0; j < holes.length; j++) {
            if (i === j) continue;
            var o = holes[j];
            if (h.top >= o.top && h.bottom <= o.bottom &&
                h.left >= o.left && h.right <= o.right) {
                return false;
            }
        }
        return true;
    });
}

/**
 * Single source of truth for applying the overlay clip-path polygon.
 * Takes an array of viewport-pixel hole objects and sets the overlay's clip-path.
 *
 * @param {Array<{top:number, left:number, bottom:number, right:number}>} holes
 */
function applyClipPathFromHoles(holes) {
    var overlay = document.getElementById('tourOverlay');
    if (!overlay) return;

    holes = filterContainedHoles(holes);

    if (holes.length === 0) {
        overlay.style.clipPath = '';
        return;
    }

    holes.sort(function (a, b) { return a.top - b.top; });

    var parts = ['0% 0%, 100% 0%, 100% 100%, 0% 100%'];
    holes.forEach(function (h) {
        parts.push(
            '0px ' + h.top + 'px',
            h.left  + 'px ' + h.top    + 'px',
            h.left  + 'px ' + h.bottom + 'px',
            h.right + 'px ' + h.bottom + 'px',
            h.right + 'px ' + h.top    + 'px',
            '0px ' + h.top + 'px'
        );
    });
    parts.push('0% 0%');
    overlay.style.clipPath = 'polygon(' + parts.join(', ') + ')';
}

/**
 * Run a requestAnimationFrame loop that reads the current getBoundingClientRect()
 * of every visible highlight box each frame and rebuilds the overlay clip-path
 * so the cutout slides in sync with the CSS-transitioning boxes.
 * Self-terminates after `duration` ms.
 */
function syncClipPathWithBoxes(duration) {
    stopClipPathSync();
    var overlay = document.getElementById('tourOverlay');
    if (!overlay) return;

    var start = performance.now();

    function tick(now) {
        if (duration && (now - start > duration)) {
            _clipSyncRAF = null;
            return;
        }
        var boxes = document.querySelectorAll('.tour-highlight-box.visible');
        var holes = [];
        boxes.forEach(function (box) {
            var r = box.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;
            // Box already includes the 5px padding around the element,
            // so its rect IS the cutout (no extra pad needed).
            holes.push({
                top:    r.top,
                left:   r.left,
                bottom: r.bottom,
                right:  r.right
            });
        });

        applyClipPathFromHoles(holes);

        _clipSyncRAF = requestAnimationFrame(tick);
    }

    _clipSyncRAF = requestAnimationFrame(tick);
}

/* Overlay control */

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

/* Highlight pool */

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
    stopClipPathSync(); // cancel any previous rAF loop

    const pool = document.querySelectorAll('.tour-highlight-box');
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

    // Clear previously elevated elements and ancestors
    document.querySelectorAll('.tour-elevated').forEach(function (el) {
        el.classList.remove('tour-elevated');
    });
    document.querySelectorAll('.tour-elevated-ancestor').forEach(function (el) {
        el.classList.remove('tour-elevated-ancestor');
    });

    // --- Pass 1: Resolve elements, apply elevated classes BEFORE measuring ---
    // This ensures rects reflect the element's final CSS state (position, overflow, etc.)
    var elements = [];
    selectors.forEach(function (selector) {
        var el = document.querySelector(selector);
        elements.push(el);
        if (!el) return;

        el.classList.add('tour-elevated');

        var wrapper = el.closest('.plot-wrapper');
        if (wrapper && wrapper !== el) {
            wrapper.classList.add('tour-elevated-ancestor');
        }
    });

    // --- Pass 2: Measure rects and position boxes ---
    var anySliding = false;
    var computedHoles = [];

    elements.forEach(function (el, i) {
        if (i >= pool.length) return; // pool exhausted
        var box = pool[i];

        if (!el) {
            box.classList.remove('visible');
            return;
        }

        var rect = el.getBoundingClientRect();
        var newTop    = rect.top  + scrollTop  - 5;
        var newLeft   = rect.left + scrollLeft - 5;
        var newWidth  = rect.width  + 10;
        var newHeight = rect.height + 10;

        // Collect clip-path hole from the SAME rect used for the box
        // (viewport coordinates with 5px padding — matches box positioning)
        computedHoles.push({
            top:    rect.top    - 5,
            left:   rect.left   - 5,
            bottom: rect.bottom + 5,
            right:  rect.right  + 5
        });

        var alreadyVisible = box.classList.contains('visible');

        if (alreadyVisible && !opts.skipTransition) {
            // Step-to-step slide: just update position props.
            // CSS transition on the box slides it smoothly.
            box.style.top    = newTop    + 'px';
            box.style.left   = newLeft   + 'px';
            box.style.width  = newWidth  + 'px';
            box.style.height = newHeight + 'px';
            anySliding = true;
        } else {
            // First appearance or forced snap: disable transitions, set coords
            box.classList.add('no-transition');
            box.classList.remove('visible');

            box.style.top    = newTop    + 'px';
            box.style.left   = newLeft   + 'px';
            box.style.width  = newWidth  + 'px';
            box.style.height = newHeight + 'px';

            // Force reflow so snapped position applies
            box.offsetHeight;
            box.classList.remove('no-transition');

            // Fade in via opacity transition at the correct position
            box.classList.add('visible');
        }

        // Accent the feature boxes (index > 0) in multi-element steps
        if (selectors.length > 1 && i > 0) {
            box.classList.add('tour-highlight-accent');
        } else {
            box.classList.remove('tour-highlight-accent');
        }

        // Make interactive elements clickable during waitFor steps
        var step = tourSteps[currentStep];
        if (step && (step.waitFor || step.action)) {
            el.style.pointerEvents = 'auto';
        }
    });

    // Fade out unused pool elements
    for (var i = selectors.length; i < pool.length; i++) {
        pool[i].classList.remove('visible');
    }

    // Sync overlay cutout with highlight boxes
    if (anySliding) {
        // rAF loop keeps clip-path in sync with CSS-transitioning boxes
        syncClipPathWithBoxes(450); // 0.35s transition + 100ms buffer
    } else {
        // One-shot snap using the same rects we positioned boxes with
        applyClipPathFromHoles(computedHoles);
    }
}

/**
 * Update the overlay's clip-path to cut out highlighted regions so content
 * beneath appears at full brightness (not dimmed by the overlay).
 * Delegates to applyClipPathFromHoles for the actual polygon building.
 *
 * @param {string[]} selectors  CSS selectors for highlighted elements
 */
function updateOverlayClipPath(selectors) {
    if (!selectors || selectors.length === 0) {
        var overlay = document.getElementById('tourOverlay');
        if (overlay) overlay.style.clipPath = '';
        return;
    }

    var pad = 5;
    var holes = [];
    selectors.forEach(function (sel) {
        var el = document.querySelector(sel);
        if (!el) return;
        var r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return;
        holes.push({
            top:    r.top    - pad,
            left:   r.left   - pad,
            bottom: r.bottom + pad,
            right:  r.right  + pad
        });
    });

    applyClipPathFromHoles(holes);
}

/** Fade out all highlight boxes and remove elevation from elements. */
function clearHighlights() {
    stopClipPathSync();
    document.querySelectorAll('.tour-highlight-box').forEach(function (box) {
        box.classList.remove('visible');
        box.classList.remove('tour-highlight-accent');
    });
    document.querySelectorAll('.tour-elevated').forEach(function (el) {
        el.classList.remove('tour-elevated');
        el.style.pointerEvents = '';
    });
    document.querySelectorAll('.tour-elevated-ancestor').forEach(function (el) {
        el.classList.remove('tour-elevated-ancestor');
    });

    // Remove overlay cutout so it returns to full coverage
    var overlay = document.getElementById('tourOverlay');
    if (overlay) overlay.style.clipPath = '';
}

/* Scrolling */

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
        // If combined bbox is too tall, fall back to primary element only
        if (rect && (rect.bottom - rect.top) > window.innerHeight * 1.5) {
            rect = null;
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

    // Only clamp to show edges when the element fits in the viewport;
    // for tall elements the centered position is already optimal.
    var elementHeight = absBottom - absTop;
    var availableHeight = window.innerHeight - topMargin - bottomMargin;
    if (elementHeight <= availableHeight) {
        // Element fits — clamp to keep both edges visible with margins
        target = Math.min(target, absTop - topMargin);
        var bottomClamp = absBottom - window.innerHeight + bottomMargin;
        target = Math.max(target, bottomClamp);
    }

    target = Math.max(0, target);

    // Clamp so we don't over-scroll past the document
    var docHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var maxScroll = Math.max(0, docHeight - window.innerHeight);
    target = Math.min(target, maxScroll);

    window.scrollTo({ top: target, behavior: 'smooth' });
    return target || 0.1;   // avoid falsy 0 — callers check !== false
}

/* Message box positioning */

/** Position the tour message box relative to the highlighted element. */
function positionMessageBox(element, position, opts) {
    opts = opts || {};
    var messageBox = document.getElementById('tourMessageBox');
    if (!messageBox) return;

    if (opts.skipTransition) {
        messageBox.classList.add('no-transition');
    }

    var rect      = element.getBoundingClientRect();
    var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    var clampTop  = (opts.targetScrollTop !== undefined) ? opts.targetScrollTop : scrollTop;
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
            top = clampTop + (viewportHeight / 2) - (messageBox.offsetHeight / 2);
        }
        top = Math.max(clampTop + 80, Math.min(clampTop + viewportHeight - messageBox.offsetHeight - 80, top));

        applyMessageBoxPosition(messageBox, left, top);
        if (opts.skipTransition) {
            messageBox.offsetHeight;
            messageBox.classList.remove('no-transition');
        }
        return;
    }

    // ── Strategy 2: Spectrum / heatmap steps (right side, lower viewport) ──
    var spectrumSteps = ['spectrum-viewer', 'spectrum-bands', 'error-bars',
                         'navigation-controls', 'grid-fitting',
                         'parameter-sweep', 'x-axis-switch', 'time-mode-bands',
                         'sine-fitting', 'amplitude-sweep'];
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

        top = clampTop + (viewportHeight * 0.80) - (messageBox.offsetHeight / 2);
        var maxTop = clampTop + viewportHeight - messageBox.offsetHeight - 50;
        if (top > maxTop) top = maxTop;
        var minTop = clampTop + (viewportHeight * 0.5);
        if (top < minTop) top = minTop;

        applyMessageBoxPosition(messageBox, left, top);
        if (opts.skipTransition) {
            messageBox.offsetHeight;
            messageBox.classList.remove('no-transition');
        }
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
    top = Math.max(clampTop + 20, Math.min(clampTop + viewportHeight - messageBox.offsetHeight - 20, top));

    // Small elements near page top: centre with generous padding
    if (rect.top < 300 && rect.height < 200) {
        var mid = rect.top + (rect.height / 2) + scrollTop;
        top = mid - (messageBox.offsetHeight / 2);
        top = Math.max(clampTop + 80, Math.min(clampTop + viewportHeight - messageBox.offsetHeight - 80, top));
    }

    // ── Strategy 5: File-selection override ──
    if (step && step.id === 'file-selection') {
        top = clampTop + (viewportHeight * 0.35);
        top = Math.max(clampTop + 100, Math.min(clampTop + viewportHeight - messageBox.offsetHeight - 100, top));
    }

    applyMessageBoxPosition(messageBox, left, top);
    if (opts.skipTransition) {
        messageBox.offsetHeight;
        messageBox.classList.remove('no-transition');
    }
}

/** Apply final position to the message box. */
function applyMessageBoxPosition(messageBox, left, top) {
    messageBox.style.transform = 'none';
    messageBox.style.position  = 'absolute';
    messageBox.style.right     = 'auto';
    messageBox.style.left      = left + 'px';
    messageBox.style.top       = top  + 'px';
}

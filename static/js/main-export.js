/*
 * ============================================================================
 * main-export.js — Video Export & Demo Data Initialization
 * ============================================================================
 *
 * Video pipeline: captures spectrum animation frames as PNGs, uploads them
 * to the server for FFmpeg encoding, then triggers the ZIP download.
 *
 * Also contains the demo data initialization (selecting the built-in demo
 * dataset vs. user-uploaded files) and file display management.
 *
 * Requires:
 *   main-state.js    (VIDEO_* constants, spectrum state variables)
 *   main-plots.js    (getEligibleWavelengthIndices)
 *   main-spectrum.js (ensureSpectrumInitialized, updateSpectrumPlot,
 *                     nextAnimationFrame)
 *
 * Load order:
 *   main-state.js → main-plots.js → main-spectrum.js
 *                → main-upload.js → main-export.js
 * ============================================================================
 */

// ---------------------------------------------------------------------------
// Video Frame Capture & Encoding
// ---------------------------------------------------------------------------

/**
 * Convert a base64 data URL to a Blob object.
 *
 * @param {string} dataurl - The data URL (e.g. from Plotly.toImage).
 * @returns {Blob} Binary blob of the image data.
 */
function dataURLtoBlob(dataurl) {
  const arr = dataurl.split(',');
  const mime = arr[0].match(/:(.*?);/)[1];
  const bstr = atob(arr[1]);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  for (let i = 0; i < n; i++) { u8arr[i] = bstr.charCodeAt(i); }
  return new Blob([u8arr], { type: mime });
}

/**
 * Capture PNG frames of the spectrum plot at each time or wavelength point.
 *
 * Respects VIDEO_MAX_FRAMES by evenly sampling indices if the total exceeds
 * the limit. In vs_time mode with active bands, only captures eligible
 * (in-band) wavelength indices.
 *
 * @returns {Promise<Blob[]>} Array of PNG image blobs, one per frame.
 * @throws {Error} If no time/wavelength points are available.
 */
async function captureSpectrumFrames() {
  await ensureSpectrumInitialized();
  const spDiv = document.getElementById('spectrumPlot');

  if (spectrumMode === 'vs_wavelength') {
    // Capture one frame per time point
    const N = totalTimePoints;
    if (!N || N <= 0) throw new Error('No spectrum time points available.');
    const target = Math.min(N, VIDEO_MAX_FRAMES);
    const step = Math.max(1, Math.floor(N / target));
    const indices = [];
    for (let i = 0; i < N; i += step) indices.push(i);
    if (indices[indices.length - 1] !== N - 1) indices.push(N - 1);

    const frames = [];
    for (let idx of indices) {
      currentTimeIndex = idx;
      updateSpectrumPlot();
      await nextAnimationFrame();
      const dataUrl = await Plotly.toImage(spDiv, { format: 'png', width: VIDEO_WIDTH, height: VIDEO_HEIGHT, scale: 1 });
      frames.push(dataURLtoBlob(dataUrl));
    }
    return frames;
  } else {
    // Capture one frame per wavelength point (filtered to eligible bands)
    const N = totalWavelengthPoints;
    if (!N || N <= 0) throw new Error('No spectrum wavelength points available.');
    const eligible = getEligibleWavelengthIndices(currentSpectrumData.wavelengthData || []);
    const domain = eligible.length ? eligible : Array.from({length: N}, (_, i) => i);
    const target = Math.min(domain.length, VIDEO_MAX_FRAMES);
    const step = Math.max(1, Math.floor(domain.length / target));
    const indices = [];
    for (let i = 0; i < domain.length; i += step) indices.push(domain[i]);
    if (indices[indices.length - 1] !== domain[domain.length - 1]) indices.push(domain[domain.length - 1]);

    const frames = [];
    for (let idx of indices) {
      currentWavelengthIndex = idx;
      updateSpectrumPlot();
      await nextAnimationFrame();
      const dataUrl = await Plotly.toImage(spDiv, { format: 'png', width: VIDEO_WIDTH, height: VIDEO_HEIGHT, scale: 1 });
      frames.push(dataURLtoBlob(dataUrl));
    }
    return frames;
  }
}

/**
 * Upload captured PNG frames to the server for FFmpeg video encoding.
 *
 * POSTs a FormData with all frames, fps, and crf settings to
 * /upload_spectrum_frames. On success, stores the returned video token
 * in window.__lastVideoToken.
 *
 * @param {Blob[]} frames - Array of PNG blobs from captureSpectrumFrames.
 * @returns {Promise<void>}
 * @throws {Error} If the upload or encoding fails.
 */
async function uploadFramesAndEncode(frames) {
  const fd = new FormData();
  fd.append('fps', String(VIDEO_FPS));
  fd.append('crf', String(VIDEO_CRF));
  for (let i = 0; i < frames.length; i++) {
    fd.append('frames', frames[i], `frame_${String(i).padStart(5, '0')}.png`);
  }
  const res = await fetch('/upload_spectrum_frames', { method: 'POST', body: fd });
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) {
    const msg = ct.includes('application/json') ? (await res.json()).error || 'encode failed' : await res.text();
    throw new Error(`Video upload/encode failed: ${msg}`);
  }
  const data = ct.includes('application/json') ? await res.json() : {};
  if (!data.ok) throw new Error(`Video upload/encode failed: ${data.error || 'unknown error'}`);
  window.__lastVideoToken = data.token || null;
}

/**
 * Orchestrate the full download flow: capture spectrum frames, upload
 * them for video encoding, then download the ZIP containing plots and
 * the generated video.
 *
 * Handles the ffmpeg-not-available case gracefully by showing a
 * user-friendly alert instead of a raw error.
 *
 * @param {Event} e - The click event from the download link.
 * @returns {Promise<void>}
 */
async function downloadAllWithVideo(e) {
  if (e) e.preventDefault();
  const link = document.querySelector('a[href="/download_plots"]');
  const originalText = link ? link.textContent : null;
  if (link) { link.textContent = 'Preparing video…'; link.classList.add('opacity-70'); }

  try {
    // Capture frames and encode video
    const frames = await captureSpectrumFrames();
    await uploadFramesAndEncode(frames);

    // Download the ZIP (with video token if available)
    const token = window.__lastVideoToken ? `?video_token=${encodeURIComponent(window.__lastVideoToken)}` : '';
    const resp = await fetch('/download_plots' + token);
    if (!resp.ok) {
      const et = await resp.text();
      throw new Error(`Download failed: ${et}`);
    }
    const blob = await resp.blob();
    let filename = 'jwst_plots.zip';
    const cd = resp.headers.get('Content-Disposition');
    if (cd) {
      const m = cd.match(/filename="?([^"]+)"?/);
      if (m && m[1]) filename = m[1];
    }

    // Trigger browser download
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error(err);
    if (err.message && err.message.includes('ffmpeg')) {
      alert('Download completed, but video generation was skipped (ffmpeg not available on server).');
    } else {
      alert(err.message || 'Failed to prepare video download.');
    }
  } finally {
    if (link && originalText) { link.textContent = originalText; link.classList.remove('opacity-70'); }
  }
}

// ---------------------------------------------------------------------------
// Demo Data Initialization
// ---------------------------------------------------------------------------

/**
 * Set the demo dataset as the initially selected data source and update
 * the file display.
 */
function initializeDemoData() {
  window.isDemoDataSelected = true;
  window.selectedFile = null;
  updateFileDisplay();
  console.log('Demo dataset initialized:  demo_jwst_timeseries.zip');
}

/**
 * Update the file display UI to reflect the current selection state:
 * demo dataset, user-uploaded file, or no file.
 */
function updateFileDisplay() {
  const fileNameEl = document.getElementById('fileName');
  const fileDisplayEl = document.getElementById('fileDisplay');

  if (!fileNameEl || !fileDisplayEl) {
    console.warn('File display elements not found');
    return;
  }

  if (window.isDemoDataSelected) {
    fileNameEl.innerHTML = '📁 demo_jwst_timeseries.zip <span class="text-xs text-blue-400 ml-2">(Demo Dataset)</span>';
    fileDisplayEl.classList.add('border-blue-500', 'bg-blue-900/20');
    fileDisplayEl.classList.remove('border-gray-600');
  } else if (window.selectedFile) {
    fileNameEl.innerHTML = `📁 ${window.selectedFile.name}`;
    fileDisplayEl.classList.remove('border-blue-500', 'bg-blue-900/20');
    fileDisplayEl.classList.add('border-gray-600');
  } else {
    fileNameEl.innerHTML = '📁 No file selected';
    fileDisplayEl.classList.remove('border-blue-500', 'bg-blue-900/20');
    fileDisplayEl.classList.add('border-gray-600');
  }
}

/**
 * Attach event listeners for all file-selection UI elements:
 *   - "Choose your own file" button → opens file dialog
 *   - Hidden file input → stores selected file
 *   - File display area → opens file dialog on click
 *   - "Use Demo" button → reverts to demo dataset
 */
function setupDemoDataHandlers() {
  // "Choose your own file" button
  const changeFileBtn = document.getElementById('changeFileBtn');
  if (changeFileBtn) {
    changeFileBtn.addEventListener('click', () => {
      const mastFile = document.getElementById('mastZipFile');
      if (mastFile) {
        mastFile.click();
      }
    });
  }

  // Hidden file input
  const mastFileInput = document.getElementById('mastZipFile');
  if (mastFileInput) {
    mastFileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length > 0) {
        window.selectedFile = e.target.files[0];
        window.isDemoDataSelected = false;
        updateFileDisplay();
        console.log('User file selected:', window.selectedFile.name);
      }
    });
  }

  // File display area click
  const fileDisplay = document.getElementById('fileDisplay');
  if (fileDisplay) {
    fileDisplay.addEventListener('click', () => {
      const mastFile = document.getElementById('mastZipFile');
      if (mastFile) {
        mastFile.click();
      }
    });
  }

  // "Use Demo" button
  const useDemoBtn = document.getElementById('useDemoBtn');
  if (useDemoBtn) {
    useDemoBtn.addEventListener('click', () => {
      window.isDemoDataSelected = true;
      window.selectedFile = null;
      const mastFile = document.getElementById('mastZipFile');
      if (mastFile) {
        mastFile.value = '';
      }
      updateFileDisplay();
      console.log('Reverted to demo dataset');
    });
  }
}

/* ============================================================
   PaintViz — Client-side application
   ============================================================ */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  originalImage: null,    // HTMLImageElement
  originalDataURL: null,  // base64 PNG of original image
  resultDataURL: null,    // base64 PNG of painted result
  currentColor: null,     // { name, hex, rgb, code }

  activeTool: 'brush',    // 'brush' | 'eraser'
  brushSize: 30,

  isDrawing: false,
  viewMode: 'original',   // 'original' | 'result' | 'compare'

  canvasW: 0,
  canvasH: 0,
};

// ── DOM refs ─────────────────────────────────────────────────────────────────
const uploadZone      = document.getElementById('upload-zone');
const fileInput       = document.getElementById('file-input');
const colorInput      = document.getElementById('color-input');
const lookupBtn       = document.getElementById('lookup-btn');
const colorCard       = document.getElementById('color-preview-card');
const colorSwatch     = document.getElementById('color-swatch');
const colorName       = document.getElementById('color-name');
const colorCode       = document.getElementById('color-code-display');
const colorHex        = document.getElementById('color-hex');

const toolBtns        = document.querySelectorAll('.tool-btn[data-tool]');
const brushSizeSlider = document.getElementById('brush-size');
const brushSizeVal    = document.getElementById('brush-size-val');
const brushRow        = document.getElementById('brush-row');

const detectWallsBtn  = document.getElementById('detect-walls-btn');
const detectIcon      = document.getElementById('detect-icon');
const clearMaskBtn    = document.getElementById('clear-mask-btn');
const visualizeBtn    = document.getElementById('visualize-btn');
const downloadBtn     = document.getElementById('download-btn');
const statusMsg       = document.getElementById('status-msg');

const mainCanvas      = document.getElementById('main-canvas');
const maskCanvas      = document.getElementById('mask-canvas');
const resultCanvas    = document.getElementById('result-canvas');
const compareHandle   = document.getElementById('compare-handle');
const compareOverlay  = document.getElementById('compare-overlay');
const emptyState      = document.getElementById('empty-state');

const viewBtns        = document.querySelectorAll('.view-btn[data-view]');
const canvasWrapper   = document.getElementById('canvas-wrapper');

const mainCtx   = mainCanvas.getContext('2d');
const maskCtx   = maskCanvas.getContext('2d');
const resultCtx = resultCanvas.getContext('2d');

// ── Upload ────────────────────────────────────────────────────────────────────
uploadZone.addEventListener('dragover', e => {
  e.preventDefault();
  uploadZone.classList.add('drag-over');
});
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) loadImageFile(file);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) loadImageFile(fileInput.files[0]);
});

function loadImageFile(file) {
  if (!file.type.startsWith('image/')) {
    showStatus('Please upload an image file (JPG, PNG, WEBP).', 'error');
    return;
  }
  const reader = new FileReader();
  reader.onload = e => {
    const img = new Image();
    img.onload = () => {
      state.originalImage = img;

      const maxW = canvasWrapper.clientWidth  - 40;
      const maxH = canvasWrapper.clientHeight - 40;
      const ratio = Math.min(maxW / img.width, maxH / img.height, 1);
      state.canvasW = Math.round(img.width  * ratio);
      state.canvasH = Math.round(img.height * ratio);

      [mainCanvas, maskCanvas, resultCanvas].forEach(c => {
        c.width  = state.canvasW;
        c.height = state.canvasH;
      });

      compareOverlay.style.width  = state.canvasW + 'px';
      compareOverlay.style.height = state.canvasH + 'px';

      mainCtx.drawImage(img, 0, 0, state.canvasW, state.canvasH);
      state.originalDataURL = mainCanvas.toDataURL('image/png');

      maskCtx.clearRect(0, 0, state.canvasW, state.canvasH);
      state.resultDataURL = null;
      resultCtx.clearRect(0, 0, state.canvasW, state.canvasH);

      emptyState.style.display = 'none';
      detectWallsBtn.disabled = false;
      setViewMode('original');
      showStatus('Image loaded. Click "Detect Walls Automatically" to let the AI select the walls.', 'info');
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

// ── Color lookup ──────────────────────────────────────────────────────────────
lookupBtn.addEventListener('click', lookupColor);
colorInput.addEventListener('keydown', e => { if (e.key === 'Enter') lookupColor(); });

async function lookupColor() {
  const code = colorInput.value.trim();
  if (!code) { showStatus('Enter a Sherwin-Williams color code (e.g. SW 7029).', 'error'); return; }

  lookupBtn.disabled = true;
  lookupBtn.innerHTML = '<span class="spinner"></span>';
  hideStatus();

  try {
    const res = await fetch(`/api/color/${encodeURIComponent(code)}`);
    const data = await res.json();

    if (!res.ok) {
      showStatus(data.error || 'Color not found.', 'error');
      return;
    }

    state.currentColor = data;
    colorSwatch.style.background = data.hex;
    colorName.textContent = data.name;
    colorCode.textContent  = data.code;
    colorHex.textContent   = data.hex;
    colorCard.classList.add('visible');
    showStatus(`Found: ${data.name} (${data.code})`, 'success');
  } catch (err) {
    showStatus('Network error — could not reach server.', 'error');
  } finally {
    lookupBtn.disabled = false;
    lookupBtn.textContent = 'Look Up';
  }
}

// ── AI Wall Detection ─────────────────────────────────────────────────────────
detectWallsBtn.addEventListener('click', async () => {
  if (!state.originalImage) {
    showStatus('Upload a room photo first.', 'error');
    return;
  }

  detectWallsBtn.disabled = true;
  detectIcon.textContent = '';
  detectWallsBtn.innerHTML = '<span class="spinner"></span> Analysing room…';
  showStatus('AI is detecting walls — first run downloads the model (~85 MB), subsequent runs are instant.', 'info');

  try {
    const res = await fetch('/api/detect-walls', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: state.originalDataURL }),
    });
    const data = await res.json();

    if (!res.ok) {
      showStatus(data.error || 'Wall detection failed.', 'error');
      return;
    }

    // Replace current mask with AI result
    const maskImg = new Image();
    maskImg.onload = () => {
      maskCtx.clearRect(0, 0, state.canvasW, state.canvasH);
      // Draw mask tinted blue so it's visible as a selection overlay
      maskCtx.globalCompositeOperation = 'source-over';

      // Create an off-screen canvas to tint the grayscale mask
      const tmp = document.createElement('canvas');
      tmp.width  = state.canvasW;
      tmp.height = state.canvasH;
      const tCtx = tmp.getContext('2d');

      tCtx.drawImage(maskImg, 0, 0, state.canvasW, state.canvasH);
      // Tint white pixels to a semi-transparent blue
      const id = tCtx.getImageData(0, 0, state.canvasW, state.canvasH);
      for (let i = 0; i < id.data.length; i += 4) {
        const v = id.data[i]; // grayscale value
        id.data[i]     = 70;   // R
        id.data[i + 1] = 130;  // G
        id.data[i + 2] = 200;  // B
        id.data[i + 3] = v;    // A — walls are opaque, non-walls transparent
      }
      tCtx.putImageData(id, 0, 0);
      maskCtx.drawImage(tmp, 0, 0);

      showStatus('Walls detected! Use the Add/Remove brush to refine, then click Apply Paint Color.', 'success');
    };
    maskImg.src = data.mask;

  } catch (err) {
    showStatus('Network error — could not reach the server.', 'error');
  } finally {
    detectWallsBtn.disabled = false;
    detectWallsBtn.innerHTML = '<span id="detect-icon">&#x1F916;</span> Detect Walls Automatically';
  }
});

// ── Brush / Eraser tools ──────────────────────────────────────────────────────
toolBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    state.activeTool = btn.dataset.tool;
    toolBtns.forEach(b => b.classList.toggle('active', b === btn));
  });
});

brushSizeSlider.addEventListener('input', () => {
  state.brushSize = +brushSizeSlider.value;
  brushSizeVal.textContent = state.brushSize;
});

mainCanvas.addEventListener('mousedown', onCanvasDown);
mainCanvas.addEventListener('mousemove', onCanvasMove);
mainCanvas.addEventListener('mouseup',   () => { state.isDrawing = false; });
mainCanvas.addEventListener('mouseleave',() => { state.isDrawing = false; });

mainCanvas.addEventListener('touchstart', e => {
  e.preventDefault();
  onCanvasDown(syntheticEvent(e.touches[0]));
});
mainCanvas.addEventListener('touchmove', e => {
  e.preventDefault();
  onCanvasMove(syntheticEvent(e.touches[0]));
});
mainCanvas.addEventListener('touchend', () => { state.isDrawing = false; });

function syntheticEvent(touch) {
  const rect = mainCanvas.getBoundingClientRect();
  return { offsetX: touch.clientX - rect.left, offsetY: touch.clientY - rect.top, buttons: 1 };
}

function onCanvasDown(e) {
  if (!state.originalImage) return;
  state.isDrawing = true;
  drawBrush(e.offsetX, e.offsetY);
}

function onCanvasMove(e) {
  if (!state.isDrawing) return;
  drawBrush(e.offsetX, e.offsetY);
}

function drawBrush(x, y) {
  const r = state.brushSize / 2;
  if (state.activeTool === 'eraser') {
    maskCtx.globalCompositeOperation = 'destination-out';
    maskCtx.fillStyle = 'rgba(0,0,0,1)';
  } else {
    maskCtx.globalCompositeOperation = 'source-over';
    maskCtx.fillStyle = 'rgba(70, 130, 200, 1)';
  }
  maskCtx.beginPath();
  maskCtx.arc(x, y, r, 0, Math.PI * 2);
  maskCtx.fill();
}

// ── Clear mask ────────────────────────────────────────────────────────────────
clearMaskBtn.addEventListener('click', () => {
  maskCtx.clearRect(0, 0, state.canvasW, state.canvasH);
  showStatus('Selection cleared.', 'info');
});

// ── Visualize ─────────────────────────────────────────────────────────────────
visualizeBtn.addEventListener('click', async () => {
  if (!state.originalImage) {
    showStatus('Upload a room photo first.', 'error'); return;
  }
  if (!state.currentColor) {
    showStatus('Look up a Sherwin-Williams color code first.', 'error'); return;
  }

  const maskData = maskCtx.getImageData(0, 0, state.canvasW, state.canvasH);
  const hasContent = maskData.data.some((v, i) => i % 4 === 3 && v > 0);
  if (!hasContent) {
    showStatus('No walls selected. Click "Detect Walls Automatically" first.', 'error');
    return;
  }

  visualizeBtn.disabled = true;
  visualizeBtn.innerHTML = '<span class="spinner"></span> Processing…';
  showStatus('Applying paint color — this may take a few seconds…', 'info');

  const maskDataURL = maskCanvas.toDataURL('image/png');

  try {
    const res = await fetch('/api/visualize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image:      state.originalDataURL,
        mask:       maskDataURL,
        color_code: state.currentColor.code,
      }),
    });
    const data = await res.json();

    if (!res.ok) {
      showStatus(data.error || 'Visualization failed.', 'error');
      return;
    }

    const resultImg = new Image();
    resultImg.onload = () => {
      resultCtx.clearRect(0, 0, state.canvasW, state.canvasH);
      resultCtx.drawImage(resultImg, 0, 0, state.canvasW, state.canvasH);
      state.resultDataURL = data.result;
      downloadBtn.disabled = false;
      showStatus(`Done! Showing "${data.color.name}" (${data.color.hex}).`, 'success');
      setViewMode('compare');
    };
    resultImg.src = data.result;

  } catch (err) {
    showStatus('Network error — could not reach the server.', 'error');
  } finally {
    visualizeBtn.disabled = false;
    visualizeBtn.innerHTML = '🎨 Apply Paint Color';
  }
});

// ── Download ──────────────────────────────────────────────────────────────────
downloadBtn.addEventListener('click', () => {
  if (!state.resultDataURL) return;
  const a = document.createElement('a');
  const code = state.currentColor ? state.currentColor.code.replace(' ', '') : 'result';
  a.href = state.resultDataURL;
  a.download = `paintviz-${code}.png`;
  a.click();
});

// ── View modes ────────────────────────────────────────────────────────────────
viewBtns.forEach(btn => {
  btn.addEventListener('click', () => setViewMode(btn.dataset.view));
});

function setViewMode(mode) {
  if (mode === 'result' && !state.resultDataURL) mode = 'original';
  state.viewMode = mode;
  viewBtns.forEach(b => b.classList.toggle('active', b.dataset.view === mode));

  const showResult  = mode === 'result' || mode === 'compare';
  const showMask    = mode === 'original';
  const showCompare = mode === 'compare';

  compareOverlay.style.display = showResult ? '' : 'none';
  compareHandle.style.display  = showCompare ? '' : 'none';
  maskCanvas.style.display     = showMask ? '' : 'none';

  if (showCompare) setComparePos(state.canvasW / 2);
}

// ── Compare drag ──────────────────────────────────────────────────────────────
let compareDragging = false;
compareHandle.addEventListener('mousedown', () => { compareDragging = true; });
window.addEventListener('mousemove', e => {
  if (!compareDragging) return;
  const rect = mainCanvas.getBoundingClientRect();
  setComparePos(e.clientX - rect.left);
});
window.addEventListener('mouseup', () => { compareDragging = false; });

compareHandle.addEventListener('touchstart', e => { e.preventDefault(); compareDragging = true; });
window.addEventListener('touchmove', e => {
  if (!compareDragging) return;
  const rect = mainCanvas.getBoundingClientRect();
  setComparePos(e.touches[0].clientX - rect.left);
});
window.addEventListener('touchend', () => { compareDragging = false; });

function setComparePos(x) {
  x = Math.max(0, Math.min(x, state.canvasW));
  compareHandle.style.left = x + 'px';
  compareOverlay.style.width = x + 'px';
}

// ── Status messages ───────────────────────────────────────────────────────────
function showStatus(msg, type = 'info') {
  statusMsg.textContent = msg;
  statusMsg.className = `status-msg visible ${type}`;
}
function hideStatus() { statusMsg.className = 'status-msg'; }

// ── Init ──────────────────────────────────────────────────────────────────────
document.querySelector('.tool-btn[data-tool="brush"]').classList.add('active');
detectWallsBtn.disabled = true; // enabled after image loads

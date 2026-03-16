/* ============================================================
   PaintViz — Client-side application
   ============================================================ */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  originalDataURL: null,
  resultDataURL:   null,
  currentColor:    null,
  canvasW: 0,
  canvasH: 0,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const uploadZone    = document.getElementById('upload-zone');
const fileInput     = document.getElementById('file-input');
const colorInput    = document.getElementById('color-input');
const lookupBtn     = document.getElementById('lookup-btn');
const colorCard     = document.getElementById('color-preview-card');
const colorSwatch   = document.getElementById('color-swatch');
const colorName     = document.getElementById('color-name');
const colorCodeEl   = document.getElementById('color-code-display');
const colorHex      = document.getElementById('color-hex');
const statusMsg     = document.getElementById('status-msg');

const paintBtn      = document.getElementById('paint-btn');
const downloadBtn   = document.getElementById('download-btn');
const resetBtn      = document.getElementById('reset-btn');
const resultSection = document.getElementById('result-section');

const mainCanvas    = document.getElementById('main-canvas');
const resultCanvas  = document.getElementById('result-canvas');
const compareHandle = document.getElementById('compare-handle');
const compareOverlay= document.getElementById('compare-overlay');
const emptyState    = document.getElementById('empty-state');
const canvasWrapper = document.getElementById('canvas-wrapper');
const viewBtns      = document.querySelectorAll('.view-btn[data-view]');

const mainCtx   = mainCanvas.getContext('2d');
const resultCtx = resultCanvas.getContext('2d');

// ── Upload ────────────────────────────────────────────────────────────────────
uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) loadImageFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) loadImageFile(fileInput.files[0]); });

function loadImageFile(file) {
  if (!file.type.startsWith('image/')) {
    showStatus('Please upload an image file (JPG, PNG, WEBP).', 'error');
    return;
  }
  const reader = new FileReader();
  reader.onload = e => {
    const img = new Image();
    img.onload = () => {
      const maxW = canvasWrapper.clientWidth  - 40;
      const maxH = canvasWrapper.clientHeight - 40;
      const ratio = Math.min(maxW / img.width, maxH / img.height, 1);
      state.canvasW = Math.round(img.width  * ratio);
      state.canvasH = Math.round(img.height * ratio);

      [mainCanvas, resultCanvas].forEach(c => {
        c.width  = state.canvasW;
        c.height = state.canvasH;
      });
      compareOverlay.style.width  = state.canvasW + 'px';
      compareOverlay.style.height = state.canvasH + 'px';

      mainCtx.drawImage(img, 0, 0, state.canvasW, state.canvasH);
      state.originalDataURL = mainCanvas.toDataURL('image/png');

      state.resultDataURL = null;
      resultCtx.clearRect(0, 0, state.canvasW, state.canvasH);
      resultSection.style.display = 'none';

      emptyState.style.display = 'none';
      setViewMode('original');
      updatePaintBtn();
      showStatus('Photo loaded. Enter a color code and click Paint My Room.', 'info');
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
    const res  = await fetch(`/api/color/${encodeURIComponent(code)}`);
    const data = await res.json();
    if (!res.ok) { showStatus(data.error || 'Color not found.', 'error'); return; }

    state.currentColor = data;
    colorSwatch.style.background = data.hex;
    colorName.textContent  = data.name;
    colorCodeEl.textContent = data.code;
    colorHex.textContent   = data.hex;
    colorCard.classList.add('visible');
    showStatus(`Found: ${data.name} (${data.hex})`, 'success');
    updatePaintBtn();
  } catch {
    showStatus('Network error — could not reach server.', 'error');
  } finally {
    lookupBtn.disabled = false;
    lookupBtn.textContent = 'Look Up';
  }
}

function updatePaintBtn() {
  paintBtn.disabled = !(state.originalDataURL && state.currentColor);
}

// ── Paint My Room (one-shot) ──────────────────────────────────────────────────
paintBtn.addEventListener('click', async () => {
  paintBtn.disabled = true;
  paintBtn.innerHTML = '<span class="spinner"></span> Working…';
  showStatus('AI is detecting walls and applying paint — please wait…', 'info');

  try {
    const res  = await fetch('/api/paint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image:      state.originalDataURL,
        color_code: state.currentColor.code,
      }),
    });
    const data = await res.json();

    if (!res.ok) { showStatus(data.error || 'Something went wrong.', 'error'); return; }

    const img = new Image();
    img.onload = () => {
      resultCtx.clearRect(0, 0, state.canvasW, state.canvasH);
      resultCtx.drawImage(img, 0, 0, state.canvasW, state.canvasH);
      state.resultDataURL = data.result;
      resultSection.style.display = '';
      showStatus(`Done! "${data.color.name}" (${data.color.hex})`, 'success');
      setViewMode('compare');
    };
    img.src = data.result;

  } catch {
    showStatus('Network error — could not reach the server.', 'error');
  } finally {
    paintBtn.disabled = false;
    paintBtn.innerHTML = '🎨 Paint My Room';
  }
});

// ── Download ──────────────────────────────────────────────────────────────────
downloadBtn.addEventListener('click', () => {
  if (!state.resultDataURL) return;
  const a = document.createElement('a');
  a.href = state.resultDataURL;
  a.download = `paintviz-${state.currentColor?.code || 'result'}.png`;
  a.click();
});

// ── Reset ─────────────────────────────────────────────────────────────────────
resetBtn.addEventListener('click', () => {
  resultCtx.clearRect(0, 0, state.canvasW, state.canvasH);
  state.resultDataURL = null;
  resultSection.style.display = 'none';
  setViewMode('original');
  hideStatus();
});

// ── View modes ────────────────────────────────────────────────────────────────
viewBtns.forEach(btn => btn.addEventListener('click', () => setViewMode(btn.dataset.view)));

function setViewMode(mode) {
  if (mode !== 'original' && !state.resultDataURL) mode = 'original';
  viewBtns.forEach(b => b.classList.toggle('active', b.dataset.view === mode));

  compareOverlay.style.display = (mode === 'result' || mode === 'compare') ? '' : 'none';
  compareHandle.style.display  = mode === 'compare' ? '' : 'none';

  if (mode === 'compare') setComparePos(state.canvasW / 2);
}

// ── Compare drag ──────────────────────────────────────────────────────────────
let dragging = false;
compareHandle.addEventListener('mousedown', () => { dragging = true; });
window.addEventListener('mousemove', e => {
  if (!dragging) return;
  setComparePos(e.clientX - mainCanvas.getBoundingClientRect().left);
});
window.addEventListener('mouseup', () => { dragging = false; });
compareHandle.addEventListener('touchstart', e => { e.preventDefault(); dragging = true; });
window.addEventListener('touchmove', e => {
  if (!dragging) return;
  setComparePos(e.touches[0].clientX - mainCanvas.getBoundingClientRect().left);
});
window.addEventListener('touchend', () => { dragging = false; });

function setComparePos(x) {
  x = Math.max(0, Math.min(x, state.canvasW));
  compareHandle.style.left = x + 'px';
  compareOverlay.style.width = x + 'px';
}

// ── Status ────────────────────────────────────────────────────────────────────
function showStatus(msg, type = 'info') {
  statusMsg.textContent = msg;
  statusMsg.className = `status-msg visible ${type}`;
}
function hideStatus() { statusMsg.className = 'status-msg'; }

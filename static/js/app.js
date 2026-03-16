/* ============================================================
   PaintViz — Visualizer page
   ============================================================ */
'use strict';

const S = {
  origURL: null, resultURL: null, color: null,
  cW: 0, cH: 0,
};

const $ = id => document.getElementById(id);

const uploadZone   = $('upload-zone'),  fileInput  = $('file-input');
const colorInput   = $('color-input'),  lookupBtn  = $('lookup-btn');
const colorCard    = $('color-card'),   swatch     = $('swatch');
const cName        = $('c-name'),       cCode      = $('c-code'), cHex = $('c-hex');
const paintBtn     = $('paint-btn'),    status     = $('status');
const resultSec    = $('result-section');
const downloadBtn  = $('download-btn'), resetBtn   = $('reset-btn');
const cvOrig       = $('cv-orig'),      cvRes      = $('cv-result');
const cmpOverlay   = $('cmp-overlay'),  cmpHandle  = $('cmp-handle');
const emptyEl      = $('empty'),        canvasWrap = $('canvas-wrap');
const optModel     = $('opt-model');

const ctxO = cvOrig.getContext('2d'), ctxR = cvRes.getContext('2d');

/* ── Upload ────────────────────────────────────────────────── */
uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault(); uploadZone.classList.remove('drag');
  if (e.dataTransfer.files[0]) load(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) load(fileInput.files[0]); });

function load(file) {
  if (!file.type.startsWith('image/')) return msg('Upload an image file.', 'error');
  const r = new FileReader();
  r.onload = ev => {
    const img = new Image();
    img.onload = () => {
      const mW = canvasWrap.clientWidth - 40, mH = canvasWrap.clientHeight - 40;
      const ratio = Math.min(mW / img.width, mH / img.height, 1);
      S.cW = Math.round(img.width * ratio);
      S.cH = Math.round(img.height * ratio);
      [cvOrig, cvRes].forEach(c => { c.width = S.cW; c.height = S.cH; });
      cmpOverlay.style.width = S.cW + 'px';
      cmpOverlay.style.height = S.cH + 'px';
      ctxO.drawImage(img, 0, 0, S.cW, S.cH);
      S.origURL = cvOrig.toDataURL('image/png');
      S.resultURL = null;
      ctxR.clearRect(0, 0, S.cW, S.cH);
      resultSec.classList.add('hidden');
      emptyEl.style.display = 'none';
      view('original');
      enablePaint();
      msg('Photo loaded. Enter a colour and click Paint My Room.', 'info');
    };
    img.src = ev.target.result;
  };
  r.readAsDataURL(file);
}

/* ── Colour lookup ─────────────────────────────────────────── */
lookupBtn.addEventListener('click', lookup);
colorInput.addEventListener('keydown', e => { if (e.key === 'Enter') lookup(); });

async function lookup() {
  const code = colorInput.value.trim();
  if (!code) return msg('Enter a SW code (e.g. SW 7029).', 'error');
  lookupBtn.disabled = true;
  lookupBtn.innerHTML = '<span class="spinner"></span>';
  try {
    const r = await fetch(`/api/color/${encodeURIComponent(code)}`);
    const d = await r.json();
    if (!r.ok) return msg(d.error, 'error');
    S.color = d;
    swatch.style.background = d.hex;
    cName.textContent = d.name;
    cCode.textContent = d.code;
    cHex.textContent = d.hex;
    colorCard.classList.remove('hidden');
    msg(`${d.name} (${d.hex})`, 'ok');
    enablePaint();
  } catch { msg('Network error.', 'error'); }
  finally { lookupBtn.disabled = false; lookupBtn.textContent = 'Look Up'; }
}

function enablePaint() { paintBtn.disabled = !(S.origURL && S.color); }

/* ── Paint ─────────────────────────────────────────────────── */
paintBtn.addEventListener('click', async () => {
  paintBtn.disabled = true;
  paintBtn.innerHTML = '<span class="spinner"></span> Working\u2026';
  msg('AI is detecting walls and recolouring via ControlNet\u2026', 'info');

  const body = {
    image: S.origURL,
    color_code: S.color.code,
    steps:    +$('opt-steps').value,
    guidance: +$('opt-guidance').value,
    controlnet_scale: +$('opt-cn').value,
    strength: +$('opt-str').value,
  };
  const model = optModel.value;
  if (model) body.model_name = model;

  try {
    const r = await fetch('/api/paint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) return msg(d.error, 'error');

    const img = new Image();
    img.onload = () => {
      ctxR.clearRect(0, 0, S.cW, S.cH);
      ctxR.drawImage(img, 0, 0, S.cW, S.cH);
      S.resultURL = d.result;
      resultSec.classList.remove('hidden');
      msg(`Done! "${d.color.name}" (${d.color.hex})`, 'ok');
      view('compare');
    };
    img.src = d.result;
  } catch { msg('Network error.', 'error'); }
  finally { paintBtn.disabled = false; paintBtn.innerHTML = '&#x1f3a8; Paint My Room'; enablePaint(); }
});

/* ── Download / Reset ──────────────────────────────────────── */
downloadBtn.addEventListener('click', () => {
  if (!S.resultURL) return;
  const a = document.createElement('a');
  a.href = S.resultURL;
  a.download = `paintviz-${S.color?.code || 'result'}.png`;
  a.click();
});
resetBtn.addEventListener('click', () => {
  ctxR.clearRect(0, 0, S.cW, S.cH);
  S.resultURL = null;
  resultSec.classList.add('hidden');
  view('original');
});

/* ── View toggle ───────────────────────────────────────────── */
document.querySelectorAll('.vb[data-v]').forEach(b =>
  b.addEventListener('click', () => view(b.dataset.v))
);

function view(m) {
  if (m !== 'original' && !S.resultURL) m = 'original';
  document.querySelectorAll('.vb').forEach(b => b.classList.toggle('active', b.dataset.v === m));
  cmpOverlay.style.display = (m === 'result' || m === 'compare') ? '' : 'none';
  cmpHandle.style.display  = m === 'compare' ? '' : 'none';
  if (m === 'compare') setPos(S.cW / 2);
}

/* ── Compare slider ────────────────────────────────────────── */
let drag = false;
cmpHandle.addEventListener('mousedown', () => drag = true);
window.addEventListener('mousemove', e => { if (drag) setPos(e.clientX - cvOrig.getBoundingClientRect().left); });
window.addEventListener('mouseup', () => drag = false);
cmpHandle.addEventListener('touchstart', e => { e.preventDefault(); drag = true; });
window.addEventListener('touchmove', e => { if (drag) setPos(e.touches[0].clientX - cvOrig.getBoundingClientRect().left); });
window.addEventListener('touchend', () => drag = false);

function setPos(x) {
  x = Math.max(0, Math.min(x, S.cW));
  cmpHandle.style.left = x + 'px';
  cmpOverlay.style.width = x + 'px';
}

/* ── Status ────────────────────────────────────────────────── */
function msg(t, type = 'info') { status.textContent = t; status.className = `status ${type}`; }

/* ── Load model list into <select> ─────────────────────────── */
(async () => {
  try {
    const r = await fetch('/api/models');
    const models = await r.json();
    models.forEach(m => {
      const o = document.createElement('option');
      o.value = m.name;
      o.textContent = m.name;
      optModel.appendChild(o);
    });
  } catch {}
})();

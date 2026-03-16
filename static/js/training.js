/* ============================================================
   PaintViz — Training page
   ============================================================ */
'use strict';

const $ = id => document.getElementById(id);

/* ── Tabs ──────────────────────────────────────────────────── */
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    $('tab-' + t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'datasets') loadDatasets();
    if (t.dataset.tab === 'train') loadDatasetsSelect();
    if (t.dataset.tab === 'models') loadModels();
  });
});

/* ═══ DATASETS ═══════════════════════════════════════════════ */
let selectedDs = null;

$('new-ds-btn').addEventListener('click', () => {
  $('new-ds-form').classList.toggle('hidden');
  $('ds-name-input').focus();
});

$('ds-create-btn').addEventListener('click', async () => {
  const name = $('ds-name-input').value.trim();
  if (!name) return;
  const fd = new FormData();
  fd.append('name', name);
  await fetch('/api/datasets', { method: 'POST', body: fd });
  $('ds-name-input').value = '';
  $('new-ds-form').classList.add('hidden');
  loadDatasets();
});

async function loadDatasets() {
  const r = await fetch('/api/datasets');
  const ds = await r.json();
  const el = $('ds-list');
  if (!ds.length) { el.innerHTML = '<p class="muted">No datasets yet. Create one above.</p>'; return; }
  el.innerHTML = ds.map(d => `
    <div class="ds-item" data-name="${d.name}">
      <div>
        <div class="ds-name">${d.name}</div>
        <div class="ds-meta">${d.pairs} pair(s) &middot; ${d.valid ? 'Valid' : d.errors?.join(', ') || 'Invalid'}</div>
      </div>
      <div class="ds-actions">
        <button class="btn sm sec ds-open" data-name="${d.name}">Open</button>
        <button class="btn sm danger ds-del" data-name="${d.name}">&times;</button>
      </div>
    </div>`).join('');

  el.querySelectorAll('.ds-open').forEach(b =>
    b.addEventListener('click', e => { e.stopPropagation(); openDataset(b.dataset.name); })
  );
  el.querySelectorAll('.ds-del').forEach(b =>
    b.addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm(`Delete dataset "${b.dataset.name}"?`)) return;
      await fetch(`/api/datasets/${b.dataset.name}`, { method: 'DELETE' });
      loadDatasets();
    })
  );
}

async function openDataset(name) {
  selectedDs = name;
  $('up-ds-name').textContent = name;
  $('upload-panel').classList.remove('hidden');
  loadPairs(name);
}

async function loadPairs(name) {
  const r = await fetch(`/api/datasets/${name}/pairs`);
  const pairs = await r.json();
  const el = $('pair-grid');
  if (!pairs.length) { el.innerHTML = '<p class="muted">No pairs uploaded yet.</p>'; return; }
  el.innerHTML = pairs.map(p => `
    <div class="pair-card">
      <div class="pair-imgs">
        <img src="${p.before}" title="Before">
        <img src="${p.after}" title="After">
      </div>
      <div class="pair-name">${p.name}</div>
    </div>`).join('');
}

$('up-submit').addEventListener('click', async () => {
  if (!selectedDs) return;
  const bf = $('up-before').files[0];
  const af = $('up-after').files[0];
  if (!bf || !af) { showUpStatus('Select both before and after images.', 'error'); return; }
  const fd = new FormData();
  fd.append('before', bf);
  fd.append('after', af);
  const prompt = $('up-prompt').value.trim();
  if (prompt) fd.append('prompt', prompt);
  try {
    const r = await fetch(`/api/datasets/${selectedDs}/upload`, { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok) { showUpStatus(d.error, 'error'); return; }
    showUpStatus(`Uploaded! ${d.pairs} pair(s) total.`, 'ok');
    $('up-before').value = '';
    $('up-after').value = '';
    $('up-prompt').value = '';
    loadPairs(selectedDs);
  } catch { showUpStatus('Upload failed.', 'error'); }
});

function showUpStatus(t, type) {
  const el = $('up-status');
  el.textContent = t;
  el.className = `status ${type}`;
}

/* ═══ TRAINING ═══════════════════════════════════════════════ */
const lossHistory = [];

async function loadDatasetsSelect() {
  const r = await fetch('/api/datasets');
  const ds = await r.json();
  const sel = $('tr-dataset');
  sel.innerHTML = ds.filter(d => d.valid).map(d =>
    `<option value="${d.name}">${d.name} (${d.pairs} pairs)</option>`
  ).join('');
  if (!sel.innerHTML) sel.innerHTML = '<option value="">No valid datasets</option>';
}

$('tr-start-btn').addEventListener('click', async () => {
  const dataset = $('tr-dataset').value;
  if (!dataset) return;
  const body = {
    dataset,
    model_name: $('tr-model-name').value.trim() || dataset,
    epochs: +$('tr-epochs').value,
    learning_rate: +$('tr-lr').value,
    batch_size: +$('tr-batch').value,
    resolution: +$('tr-res').value,
    save_every: +$('tr-save').value,
  };
  try {
    const r = await fetch('/api/training/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) { $('tr-msg').textContent = d.error; $('tr-msg').className = 'status error'; return; }
    $('tr-start-btn').classList.add('hidden');
    $('tr-stop-btn').classList.remove('hidden');
    $('tr-progress-card').classList.remove('hidden');
    lossHistory.length = 0;
    startSSE();
  } catch { $('tr-msg').textContent = 'Failed to start.'; $('tr-msg').className = 'status error'; }
});

$('tr-stop-btn').addEventListener('click', async () => {
  await fetch('/api/training/stop', { method: 'POST' });
  $('tr-stop-btn').classList.add('hidden');
  $('tr-start-btn').classList.remove('hidden');
});

function startSSE() {
  const es = new EventSource('/api/training/stream');
  es.onmessage = e => {
    const s = JSON.parse(e.data);
    $('tr-bar').style.width = s.progress + '%';
    $('tr-epoch').textContent = `Epoch ${s.epoch}/${s.total_epochs}`;
    $('tr-step').textContent = `Step ${s.step}`;
    $('tr-loss').textContent = `Loss: ${s.loss.toFixed(6)}`;
    $('tr-state').textContent = s.state;
    $('tr-msg').textContent = s.message;
    $('tr-msg').className = `status ${s.state === 'failed' ? 'error' : 'info'}`;

    if (s.step > 0 && s.loss > 0) {
      lossHistory.push(s.loss);
      drawChart();
    }

    if (s.state === 'completed' || s.state === 'failed') {
      es.close();
      $('tr-stop-btn').classList.add('hidden');
      $('tr-start-btn').classList.remove('hidden');
      if (s.state === 'completed') $('tr-msg').className = 'status ok';
    }
  };
  es.onerror = () => { es.close(); };
}

/* ── Loss chart (simple canvas) ────────────────────────────── */
function drawChart() {
  const cv = $('loss-chart');
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;
  const pad = { l: 55, r: 15, t: 15, b: 30 };
  const gW = W - pad.l - pad.r, gH = H - pad.t - pad.b;

  ctx.clearRect(0, 0, W, H);

  if (lossHistory.length < 2) return;

  const maxL = Math.max(...lossHistory) * 1.1 || 1;
  const minL = 0;

  // Grid
  ctx.strokeStyle = '#e0e0e0';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + gH * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + gW, y); ctx.stroke();
    ctx.fillStyle = '#999'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText((maxL - (maxL - minL) * i / 4).toFixed(4), pad.l - 6, y + 4);
  }

  // Line
  ctx.strokeStyle = '#2D6EA3';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let i = 0; i < lossHistory.length; i++) {
    const x = pad.l + (i / (lossHistory.length - 1)) * gW;
    const y = pad.t + gH * (1 - (lossHistory[i] - minL) / (maxL - minL));
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Axis labels
  ctx.fillStyle = '#666'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
  ctx.fillText('Steps', pad.l + gW / 2, H - 4);
  ctx.save(); ctx.translate(12, pad.t + gH / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText('Loss', 0, 0); ctx.restore();
}

/* ═══ MODELS ═════════════════════════════════════════════════ */
async function loadModels() {
  const r = await fetch('/api/models');
  const models = await r.json();
  const el = $('model-list');
  if (!models.length) { el.innerHTML = '<p class="muted">No trained models yet.</p>'; return; }
  el.innerHTML = models.map(m => {
    const cfg = m.config || {};
    return `
    <div class="model-item">
      <div>
        <div class="mi-name">${m.name}</div>
        <div class="mi-meta">${cfg.epochs || '?'} epochs &middot; loss ${(cfg.final_loss || 0).toFixed(6)}</div>
      </div>
      <div class="mi-actions">
        <button class="btn sm" onclick="activateModel('${m.name}')">Use for Inference</button>
        <button class="btn sm danger" onclick="deleteModel('${m.name}')">&times;</button>
      </div>
    </div>`;
  }).join('');
}

async function activateModel(name) {
  const r = await fetch(`/api/models/${name}/activate`, { method: 'POST' });
  const d = await r.json();
  alert(r.ok ? `Model "${name}" activated for inference.` : (d.error || 'Failed'));
}

async function deleteModel(name) {
  if (!confirm(`Delete model "${name}"?`)) return;
  await fetch(`/api/models/${name}`, { method: 'DELETE' });
  loadModels();
}

/* ── Init ──────────────────────────────────────────────────── */
loadDatasets();

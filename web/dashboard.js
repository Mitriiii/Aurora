// AURORA dashboard — SIMULATION only. Talks to the local FastAPI backend.

const NODES = {
  gen1: { x: 40, y: 240, kind: 'gen', gen: '1' },
  bus1: { x: 150, y: 240, kind: 'bus', bus: '1' },
  bus5: { x: 300, y: 240, kind: 'bus', bus: '5' },
  bus6: { x: 450, y: 240, kind: 'bus', bus: '6' },
  bus7: { x: 600, y: 240, kind: 'bus', bus: '7', load: true },
  bus8: { x: 750, y: 240, kind: 'bus', bus: '8', surge: true },
  bus9: { x: 900, y: 240, kind: 'bus', bus: '9', load: true },
  bus10: { x: 1050, y: 240, kind: 'bus', bus: '10', battery: true },
  gen4: { x: 1160, y: 240, kind: 'gen', gen: '4' },
  gen2: { x: 450, y: 400, kind: 'gen', gen: '2' },
  gen3: { x: 900, y: 80, kind: 'gen', gen: '3' },
};

const EDGES = [
  { id: 'Line_11', a: 'gen1', b: 'bus1' },
  { id: 'Line_0', a: 'bus5', b: 'bus6' },
  { id: 'Line_1', a: 'bus5', b: 'bus6', offset: 10 },
  { id: 'Line_2', a: 'bus6', b: 'bus7' },
  { id: 'Line_3', a: 'bus6', b: 'bus7', offset: 10 },
  { id: 'Line_4', a: 'bus7', b: 'bus8', tie: true },
  { id: 'Line_5', a: 'bus7', b: 'bus8', tie: true, offset: 10 },
  { id: 'Line_6', a: 'bus7', b: 'bus8', tie: true, offset: -10 },
  { id: 'Line_7', a: 'bus8', b: 'bus9' },
  { id: 'Line_8', a: 'bus8', b: 'bus9', offset: 10 },
  { id: 'Line_9', a: 'bus9', b: 'bus10' },
  { id: 'Line_10', a: 'bus9', b: 'bus10', offset: 10 },
  { id: 'Line_12', a: 'gen2', b: 'bus6' },
  { id: 'Line_13', a: 'gen3', b: 'bus9' },
  { id: 'Line_14', a: 'gen4', b: 'bus10' },
];

const VBOX = { w: 1200, h: 480 };

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function buildDiagram(container, cellId) {
  const svg = svgEl('svg', { viewBox: `0 0 ${VBOX.w} ${VBOX.h}`, id: cellId });

  const defs = svgEl('defs', {});
  const glow = svgEl('filter', { id: `glow-${cellId}` });
  glow.innerHTML = '<feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>';
  defs.appendChild(glow);
  svg.appendChild(defs);

  // edges first (under nodes)
  for (const e of EDGES) {
    const a = NODES[e.a], b = NODES[e.b];
    const dy = e.offset || 0;
    const line = svgEl('line', {
      x1: a.x, y1: a.y + dy, x2: b.x, y2: b.y + dy,
      class: 'grid-edge' + (e.tie ? ' tie' : ''),
      'data-id': e.id, stroke: '#1f3040', 'stroke-width': 3,
    });
    svg.appendChild(line);
  }

  // nodes
  for (const [key, n] of Object.entries(NODES)) {
    const g = svgEl('g', { class: 'node-group', 'data-node': key });

    if (n.kind === 'bus') {
      const c = svgEl('circle', {
        cx: n.x, cy: n.y, r: 14, class: 'bus-node', 'data-bus': n.bus,
        fill: '#123', stroke: '#3fd9c7', 'stroke-width': 2,
      });
      g.appendChild(c);
      const label = svgEl('text', { x: n.x, y: n.y + 32, class: 'node-label', 'text-anchor': 'middle' });
      label.textContent = `BUS ${n.bus}`;
      g.appendChild(label);
      const vlabel = svgEl('text', { x: n.x, y: n.y - 22, class: 'v-label', 'text-anchor': 'middle', 'data-bus-v': n.bus });
      vlabel.textContent = '1.00';
      g.appendChild(vlabel);
      if (n.load) {
        const tri = svgEl('path', { d: `M ${n.x - 7} ${n.y + 44} L ${n.x + 7} ${n.y + 44} L ${n.x} ${n.y + 56} Z`, fill: '#4a5a6a' });
        g.appendChild(tri);
      }
      if (n.surge) {
        const cap = svgEl('rect', {
          x: n.x - 10, y: n.y + 44, width: 20, height: 10, rx: 2, class: 'surge-marker',
          fill: '#222', stroke: '#f2b33d', 'stroke-width': 1.5, opacity: 0.25,
        });
        g.appendChild(cap);
        const clabel = svgEl('text', { x: n.x, y: n.y + 68, class: 'marker-label', 'text-anchor': 'middle' });
        clabel.textContent = 'reactive surge';
        g.appendChild(clabel);
      }
      if (n.battery) {
        const bat = svgEl('rect', {
          x: n.x - 10, y: n.y + 44, width: 20, height: 10, rx: 2, class: 'battery-marker',
          fill: '#222', stroke: '#3fd9c7', 'stroke-width': 1.5, opacity: 0.25,
        });
        g.appendChild(bat);
        const blabel = svgEl('text', { x: n.x, y: n.y + 68, class: 'marker-label', 'text-anchor': 'middle' });
        blabel.textContent = 'storage';
        g.appendChild(blabel);
      }
    } else {
      const rect = svgEl('rect', {
        x: n.x - 16, y: n.y - 16, width: 32, height: 32, rx: 6, class: 'gen-node', 'data-gen': n.gen,
        fill: '#0e2420', stroke: '#3fd9c7', 'stroke-width': 2,
      });
      g.appendChild(rect);
      const label = svgEl('text', { x: n.x, y: n.y + 32, class: 'node-label', 'text-anchor': 'middle' });
      label.textContent = `G${n.gen}`;
      g.appendChild(label);
      // reactive margin gauge ring
      const gaugeBg = svgEl('circle', {
        cx: n.x, cy: n.y, r: 24, fill: 'none', stroke: '#1b2634', 'stroke-width': 3,
      });
      g.appendChild(gaugeBg);
      const gaugeFg = svgEl('circle', {
        cx: n.x, cy: n.y, r: 24, fill: 'none', stroke: '#3fd9c7', 'stroke-width': 3,
        'stroke-dasharray': `${2 * Math.PI * 24}`, 'stroke-dashoffset': '0',
        transform: `rotate(-90 ${n.x} ${n.y})`, class: 'margin-gauge', 'data-gen-gauge': n.gen,
        'stroke-linecap': 'round',
      });
      g.appendChild(gaugeFg);
    }
    svg.appendChild(g);
  }

  container.innerHTML = '';
  container.appendChild(svg);
  return svg;
}

function voltageColor(v) {
  if (v == null) return '#3a4a5a';
  const dev = Math.abs(v - 1.0);
  if (dev < 0.05) return '#3fd9c7';
  if (dev < 0.10) return '#f2b33d';
  return '#ef5b5b';
}

function updateDiagram(svg, frame) {
  if (!frame || frame.status_flags && frame.status_flags.collapsed) {
    svg.parentElement.classList.add('collapsed');
    return;
  }
  svg.parentElement.classList.remove('collapsed');

  for (const b of Object.keys(frame.bus_v_pu || {})) {
    const v = frame.bus_v_pu[b];
    const node = svg.querySelector(`circle.bus-node[data-bus="${b}"]`);
    if (node) node.setAttribute('stroke', voltageColor(v));
    const vlabel = svg.querySelector(`text[data-bus-v="${b}"]`);
    if (vlabel) vlabel.textContent = v.toFixed(2);
  }

  for (const ln of Object.keys(frame.branch_p_pu || {})) {
    const p = frame.branch_p_pu[ln];
    const el = svg.querySelector(`line[data-id="${ln}"]`);
    if (el) {
      const intensity = Math.min(1, Math.abs(p) / 6);
      el.setAttribute('stroke', `rgba(63, 217, 199, ${0.25 + 0.6 * intensity})`);
      el.setAttribute('stroke-width', 2 + 3 * intensity);
    }
  }

  const tanphi = Math.tan(Math.acos(0.98));
  for (const g of ['1', '2', '3', '4']) {
    const p = (frame.gen_p_pu || {})[g];
    const q = (frame.gen_q_pu || {})[g];
    if (p == null) continue;
    const qmax = Math.abs(p) * tanphi;
    const ratio = qmax > 1e-6 ? Math.min(1.4, Math.abs(q) / qmax) : 0;
    const circumference = 2 * Math.PI * 24;
    const offset = circumference * ratio;
    const gaugeEl = svg.querySelector(`circle[data-gen-gauge="${g}"]`);
    if (gaugeEl) {
      gaugeEl.setAttribute('stroke-dashoffset', String(circumference - Math.min(circumference, offset)));
      gaugeEl.setAttribute('stroke', ratio > 1 ? '#ef5b5b' : ratio > 0.7 ? '#f2b33d' : '#3fd9c7');
    }
  }
}

// ---------- Vitals ----------

function vitalCard(id, label) {
  const div = document.createElement('div');
  div.className = 'vital-card';
  div.innerHTML = `<div class="label">${label}</div><div class="value" id="${id}-value">—</div><canvas id="${id}-canvas" width="300" height="44"></canvas>`;
  return div;
}

const vitalsGrid = document.getElementById('vitalsGrid');
['freq', 'v8', 'margin', 'osc'].forEach((id, i) => {
  const labels = { freq: 'Frequency (Hz)', v8: 'Voltage — bus 8 (p.u.)', margin: 'Min reactive margin (p.u.)', osc: 'Oscillation amplitude — bus 8' };
  vitalsGrid.appendChild(vitalCard(id, labels[id]));
});

const scadaGrid = document.getElementById('scadaGrid');
['freq', 'v8'].forEach((id) => {
  const labels = { freq: 'Frequency (Hz)', v8: 'Voltage — bus 8 (p.u.)' };
  const div = vitalCard('scada-' + id, labels[id]);
  scadaGrid.appendChild(div);
});

const sparkHistory = {};
function pushSpark(id, val, maxN = 150) {
  if (!sparkHistory[id]) sparkHistory[id] = [];
  sparkHistory[id].push(val);
  if (sparkHistory[id].length > maxN) sparkHistory[id].shift();
  drawSpark(id);
}
function drawSpark(id) {
  const canvas = document.getElementById(id + '-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const data = sparkHistory[id];
  if (!data || data.length < 2) return;
  const min = Math.min(...data), max = Math.max(...data);
  const span = (max - min) || 1;
  ctx.beginPath();
  ctx.strokeStyle = '#3fd9c7';
  ctx.lineWidth = 1.5;
  data.forEach((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / span) * (h - 6) - 3;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}
function setVal(id, text, cls) {
  const el = document.getElementById(id + '-value');
  if (!el) return;
  el.textContent = text;
  el.className = 'value' + (cls ? ' ' + cls : '');
}

// ---------- Markdown (tiny, purpose-built renderer) ----------

function renderMarkdown(md) {
  const lines = md.split('\n');
  let html = '';
  let inTable = false;
  for (let raw of lines) {
    const line = raw;
    if (line.startsWith('# ')) { html += `<h1>${inline(line.slice(2))}</h1>`; continue; }
    if (line.startsWith('## ')) { html += `<h2>${inline(line.slice(3))}</h2>`; continue; }
    if (line.startsWith('|')) {
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      if (cells.every(c => /^-+$/.test(c))) continue;
      if (!inTable) { html += '<table>'; inTable = true; }
      const tag = html.endsWith('<table>') ? 'th' : 'td';
      html += `<tr>${cells.map(c => `<${tag}>${inline(c)}</${tag}>`).join('')}</tr>`;
      continue;
    } else if (inTable) { html += '</table>'; inTable = false; }
    if (line.startsWith('- ')) { html += `<div>• ${inline(line.slice(2))}</div>`; continue; }
    if (line.trim() === '') { html += '<br/>'; continue; }
    html += `<p>${inline(line)}</p>`;
  }
  if (inTable) html += '</table>';
  return html;
}
function inline(s) {
  return s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`(.+?)`/g, '<code>$1</code>');
}

// ---------- Wiring ----------

let svgLeft = buildDiagram(document.getElementById('cellLeft'), 'svgLeft');
let svgRight = null;
let latestRun = null;
let ws = null;
let lastScadaUpdate = -999;

const runBtn = document.getElementById('runBtn');
const playBtn = document.getElementById('playBtn');
const statusPill = document.getElementById('statusPill');
const countdownValue = document.getElementById('countdownValue');
const countdownDetail = document.getElementById('countdownDetail');
const diagramTitleRight = document.getElementById('diagramTitleRight');
const cellRight = document.getElementById('cellRight');
const diagramGrid = document.getElementById('diagramGrid');

function setStatus(text, cls) {
  statusPill.textContent = text;
  statusPill.className = 'status-pill ' + cls;
}

runBtn.addEventListener('click', async () => {
  runBtn.disabled = true;
  playBtn.disabled = true;
  setStatus('running scenario…', 'running');
  countdownValue.textContent = 'RUNNING';
  countdownValue.className = 'countdown-value';
  countdownDetail.textContent = 'ANDES is integrating both branches (uncorrected + AURORA-corrected)…';
  try {
    const resp = await fetch('/api/run', { method: 'POST' });
    const summary = await resp.json();
    latestRun = summary;
    setStatus('ready to play', 'done');
    countdownValue.textContent = 'READY';
    countdownDetail.textContent = summary.detection_t != null
      ? `Detector will fire at t=${summary.detection_t.toFixed(1)}s — ${summary.lead_time_to_first_trip_s.toFixed(1)}s before the first real trip.`
      : 'Detector did not fire in this run.';
    playBtn.disabled = false;
    loadReport();
  } catch (e) {
    setStatus('error', 'danger');
    countdownDetail.textContent = String(e);
  } finally {
    runBtn.disabled = false;
  }
});

playBtn.addEventListener('click', () => {
  playBtn.disabled = true;
  diagramGrid.classList.remove('split');
  cellRight.style.display = 'none';
  diagramTitleRight.style.display = 'none';
  svgLeft = buildDiagram(document.getElementById('cellLeft'), 'svgLeft');
  document.getElementById('diagramTitleLeft').textContent = 'What actually happened';
  sparkHistory.freq = []; sparkHistory.v8 = []; sparkHistory.margin = []; sparkHistory.osc = [];

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/stream`);
  ws.onopen = () => {
    const speed = parseFloat(document.getElementById('speedSelect').value);
    ws.send(JSON.stringify({ cmd: 'play', speed }));
    setStatus('playing', 'running');
  };
  ws.onmessage = (evt) => onWsMessage(JSON.parse(evt.data));
  ws.onclose = () => { playBtn.disabled = false; };
});

let meta = null;
let splitStarted = false;

function onWsMessage(msg) {
  if (msg.type === 'meta') {
    meta = msg;
    splitStarted = false;
    return;
  }
  if (msg.type === 'tick') {
    handleTick(msg);
    return;
  }
  if (msg.type === 'done') {
    setStatus('done', 'done');
    loadReport();
    return;
  }
  if (msg.type === 'error') {
    setStatus('error', 'danger');
    countdownDetail.textContent = msg.message;
  }
}

function handleTick(msg) {
  const uf = msg.uncorrected;
  const t = uf.t;

  // Countdown / status logic
  const detT = meta.detection_t;
  const collapseT = meta.collapse_t;
  if (detT != null && t < detT) {
    countdownValue.textContent = 'NOMINAL';
    countdownValue.className = 'countdown-value';
    countdownDetail.textContent = `t=${t.toFixed(1)}s — grid operating within normal bounds.`;
  } else if (collapseT != null && t < collapseT) {
    const remain = collapseT - t;
    countdownValue.textContent = `T-minus ${remain.toFixed(1)}s`;
    countdownValue.className = 'countdown-value danger';
    countdownDetail.textContent = (meta.detection_reasons || []).join(' · ') || 'Fragile-regime signature detected.';
    setStatus('danger flag — AURORA correcting', 'danger');
  } else if (collapseT != null && t >= collapseT) {
    countdownValue.textContent = 'COLLAPSED';
    countdownValue.className = 'countdown-value collapsed';
    countdownDetail.textContent = 'Uncorrected branch: total system collapse. See the corrected branch on the right.';
  }

  // Split view once we pass the first trip time
  if (!splitStarted && meta.scenario_times && t >= meta.scenario_times.trip_1_t) {
    splitStarted = true;
    diagramGrid.classList.add('split');
    cellRight.style.display = 'block';
    diagramTitleRight.style.display = 'block';
    svgRight = buildDiagram(cellRight, 'svgRight');
  }

  updateDiagram(svgLeft, uf);
  if (svgRight && msg.corrected) updateDiagram(svgRight, msg.corrected);

  // Vitals (AURORA view — every tick)
  const freqHz = uf.freq_hz || 0;
  const v8 = (uf.bus_v_pu || {})['8'];
  const margins = (uf.gen_p_pu && uf.gen_q_pu) ? Object.keys(uf.gen_p_pu).map(g => {
    const p = uf.gen_p_pu[g], q = uf.gen_q_pu[g];
    return Math.abs(p) * Math.tan(Math.acos(0.98)) - Math.abs(q);
  }) : [];
  const minMargin = margins.length ? Math.min(...margins) : null;

  setVal('freq', freqHz ? freqHz.toFixed(3) : '—', freqHz < 49.5 ? 'danger' : freqHz < 49.9 ? 'warn' : '');
  pushSpark('freq', freqHz || 50);
  setVal('v8', v8 != null ? v8.toFixed(3) : '—', v8 != null && Math.abs(v8 - 1) > 0.1 ? 'danger' : v8 != null && Math.abs(v8 - 1) > 0.05 ? 'warn' : '');
  pushSpark('v8', v8 != null ? v8 : 1);
  setVal('margin', minMargin != null ? minMargin.toFixed(2) : '—', minMargin != null && minMargin < 0 ? 'danger' : minMargin != null && minMargin < 0.3 ? 'warn' : '');
  pushSpark('margin', minMargin != null ? minMargin : 0);

  const oscHist = sparkHistory['v8'] || [];
  const oscAmp = oscHist.length > 10 ? Math.max(...oscHist.slice(-30)) - Math.min(...oscHist.slice(-30)) : 0;
  setVal('osc', oscAmp.toFixed(3), oscAmp > 0.05 ? 'danger' : oscAmp > 0.02 ? 'warn' : '');
  pushSpark('osc', oscAmp);

  // SCADA (throttled to ~4s sim-time refresh, sparse)
  if (t - lastScadaUpdate >= 4.0 || lastScadaUpdate < 0) {
    lastScadaUpdate = t;
    setVal('scada-freq', uf.data_quality === 'MISSING' ? 'NO DATA' : freqHz ? freqHz.toFixed(1) : '—');
    setVal('scada-v8', uf.data_quality === 'MISSING' ? 'NO DATA' : v8 != null ? v8.toFixed(2) : '—');
  }
}

async function loadReport() {
  try {
    const resp = await fetch('/api/report/latest');
    const text = await resp.text();
    document.getElementById('reportBody').innerHTML = renderMarkdown(text);
  } catch (e) { /* ignore */ }
}

async function loadCredibility() {
  try {
    const resp = await fetch('/api/entsoe/spain-today');
    const data = await resp.json();
    const body = document.getElementById('credibilityBody');
    if (data.status !== 'ok') {
      body.innerHTML = `<div>${data.message || 'offline'}</div>`;
      return;
    }
    let html = `<div>as of ${data.as_of}</div>`;
    for (const [src, mw] of Object.entries(data.generation_mw_by_source || {})) {
      html += `<div class="kv"><span>${src}</span><span>${mw.toFixed(0)} MW</span></div>`;
    }
    body.innerHTML = html;
  } catch (e) {
    document.getElementById('credibilityBody').textContent = 'unavailable';
  }
}
loadCredibility();
setInterval(loadCredibility, 60000);

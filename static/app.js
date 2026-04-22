'use strict';

const $ = id => document.getElementById(id);

// ── State ──────────────────────────────────────────────────────────────────
let eventCount = 0;
let alertTimeout = null;

// ── WebSocket ──────────────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setStatus('idle');
    // Keepalive ping every 25 s
    ws._ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 25_000);
  };

  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    switch (msg.type) {
      case 'history':  handleHistory(msg.events); break;
      case 'event':    handleEvent(msg.event, true); break;
      case 'status':   setStatus(msg.status); break;
      case 'error':    setStatus('error'); break;
    }
  };

  ws.onclose = () => {
    clearInterval(ws._ping);
    setStatus('error');
    // Reconnect after 3 s
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

// ── Event rendering ────────────────────────────────────────────────────────
function handleHistory(events) {
  events.forEach(evt => handleEvent(evt, false));
}

function handleEvent(evt, isNew) {
  const type = evt.event_type; // 'comment' | 'alert'
  if (type !== 'comment' && type !== 'alert') return;

  hideEmpty();
  const li = buildCard(evt);

  const list = $('event-list');
  list.appendChild(li);
  if (isNew) {
    li.scrollIntoView({ behavior: 'smooth', block: 'end' });
    updateLastAnalysis(evt);
    if (type === 'alert') showOverlayAlert(evt.message);
  }

  eventCount++;
  $('event-counter').textContent = `${eventCount} event${eventCount !== 1 ? 's' : ''}`;
}

function buildCard(evt) {
  const type = evt.event_type;
  const li = document.createElement('li');
  li.className = `event-card ${type}`;

  const tags = (evt.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
  const tagsHtml = tags ? `<div class="card-tags">${tags}</div>` : '';

  li.innerHTML = `
    <div class="card-header">
      <span class="type-badge ${type}">${type}</span>
      <span class="card-time">${formatTime(evt.timestamp)}</span>
    </div>
    <div class="card-message">${esc(evt.message)}</div>
    ${tagsHtml}
  `;
  return li;
}

// ── Alert overlay on camera feed ───────────────────────────────────────────
function showOverlayAlert(message) {
  const overlay = $('overlay-alert');
  $('overlay-message').textContent = message;
  overlay.classList.remove('hidden');
  clearTimeout(alertTimeout);
  alertTimeout = setTimeout(() => overlay.classList.add('hidden'), 8000);
}

// ── Status badge ───────────────────────────────────────────────────────────
const STATUS_CLASSES = { idle: 'badge-idle', analyzing: 'badge-analyzing', error: 'badge-error' };
const STATUS_LABELS  = { idle: 'IDLE', analyzing: '● ANALYZING', error: '✕ ERROR' };

function setStatus(status) {
  const badge = $('status-badge');
  badge.className = `badge ${STATUS_CLASSES[status] || 'badge-idle'}`;
  badge.textContent = STATUS_LABELS[status] || status.toUpperCase();
}

function updateLastAnalysis(evt) {
  $('last-analysis').textContent =
    `Last analysis: ${formatTime(evt.timestamp)} — ${evt.event_type.toUpperCase()}`;
}

// ── Helpers ────────────────────────────────────────────────────────────────
function hideEmpty() {
  const el = $('empty-state');
  if (el) el.style.display = 'none';
}

function formatTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Clear button ───────────────────────────────────────────────────────────
$('clear-btn').addEventListener('click', () => {
  $('event-list').innerHTML = '';
  eventCount = 0;
  $('event-counter').textContent = '0 events';
  $('empty-state').style.display = '';
  $('overlay-alert').classList.add('hidden');
  $('last-analysis').textContent = 'Waiting for first analysis…';
});

// ── Stream error handling (reconnect img src) ──────────────────────────────
const streamImg = $('stream');
streamImg.onerror = () => {
  setTimeout(() => { streamImg.src = '/stream?' + Date.now(); }, 2000);
};

// ── Boot ───────────────────────────────────────────────────────────────────
connect();

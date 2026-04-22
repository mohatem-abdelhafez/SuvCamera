'use strict';

const $ = id => document.getElementById(id);

// ── State ──────────────────────────────────────────────────────────────────
let eventCount   = 0;
let alertTimeout = null;
let cameraRunning = true;
let currentMode  = 'proactive';

// ── WebSocket ──────────────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setStatus('idle');
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
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

// ── Event rendering ────────────────────────────────────────────────────────
function handleHistory(events) {
  events.forEach(evt => handleEvent(evt, false));
}

function handleEvent(evt, isNew) {
  const type = evt.event_type;
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

function hideEmpty() {
  const el = $('empty-state');
  if (el) el.style.display = 'none';
}

// ── Alert overlay ──────────────────────────────────────────────────────────
function showOverlayAlert(message) {
  $('overlay-message').textContent = message;
  $('overlay-alert').classList.remove('hidden');
  clearTimeout(alertTimeout);
  alertTimeout = setTimeout(() => $('overlay-alert').classList.add('hidden'), 8000);
}

// ── Status badge ───────────────────────────────────────────────────────────
const STATUS_MAP = {
  idle:      { cls: 'badge-idle',      label: 'IDLE' },
  analyzing: { cls: 'badge-analyzing', label: '● ANALYZING' },
  error:     { cls: 'badge-error',     label: '✕ ERROR' },
};

function setStatus(status) {
  const badge = $('status-badge');
  const s = STATUS_MAP[status] || STATUS_MAP.idle;
  badge.className = `badge ${s.cls}`;
  badge.textContent = s.label;
}

function updateLastAnalysis(evt) {
  $('last-analysis').textContent =
    `Last: ${formatTime(evt.timestamp)} — ${evt.event_type.toUpperCase()}`;
}

// ── Camera control ─────────────────────────────────────────────────────────
const ICON_UPLOAD  = `<svg id="source-toggle-icon" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 2v8M4 6l4-4 4 4M2 13h12"/></svg>`;
const ICON_WEBCAM  = `<svg id="source-toggle-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="15" height="12" rx="2"/><path d="M17 9l5-3v12l-5-3"/></svg>`;

let isFileSource = false;

function updateSourceToggle(isFile) {
  isFileSource = isFile;
  const btn   = $('source-toggle-btn');
  const label = $('source-toggle-label');
  if (!btn || !label) return;

  if (isFile) {
    btn.querySelector('svg')?.remove();
    btn.insertAdjacentHTML('afterbegin', ICON_WEBCAM);
    label.textContent = 'Use Camera';
    btn.className = 'btn btn-accent';
  } else {
    btn.querySelector('svg')?.remove();
    btn.insertAdjacentHTML('afterbegin', ICON_UPLOAD);
    label.textContent = 'Upload Video';
    btn.className = 'btn btn-ghost';
  }
}

function updateCameraUI(running, source, isFile) {
  cameraRunning = running;
  const toggleBtn = $('camera-toggle-btn');
  const restartBtn = $('restart-camera-btn');
  const offOverlay = $('camera-off-overlay');
  const liveBadge  = $('live-badge');
  const streamImg  = $('stream');

  if (running) {
    toggleBtn.innerHTML = '<span class="btn-dot btn-dot-stop"></span>Stop';
    toggleBtn.className = 'btn btn-danger';
    offOverlay.classList.add('hidden');
    liveBadge.innerHTML = '<span class="live-dot"></span>LIVE';
    liveBadge.className = 'badge badge-live';
    streamImg.src = '/stream?' + Date.now();
  } else {
    toggleBtn.innerHTML = '<span class="btn-dot btn-dot-start"></span>Start';
    toggleBtn.className = 'btn btn-success';
    offOverlay.classList.remove('hidden');
    liveBadge.innerHTML = '<span class="live-dot"></span>OFF';
    liveBadge.className = 'badge badge-off';
  }

  if (source) $('camera-label').textContent = source;
  if (restartBtn) restartBtn.style.display = running ? 'none' : '';

  updateSourceToggle(!!isFile);

  // Hide camera select while streaming from a file
  const camSel = $('camera-select');
  if (camSel && camSel.options.length > 1) {
    camSel.classList.toggle('hidden', !!isFile);
  }
}

async function toggleCamera() {
  $('camera-toggle-btn').disabled = true;
  try {
    const ep = cameraRunning ? '/api/camera/stop' : '/api/camera/start';
    const data = await fetch(ep, { method: 'POST' }).then(r => r.json());
    updateCameraUI(data.status === 'started' || data.status === 'already_running', data.source, data.is_file);
  } catch (err) {
    console.error('Camera toggle failed:', err);
  } finally {
    $('camera-toggle-btn').disabled = false;
  }
}

async function switchToWebcam() {
  const btn = $('source-toggle-btn');
  btn.disabled = true;
  try {
    const data = await fetch('/api/camera/use-camera', { method: 'POST' }).then(r => r.json());
    updateCameraUI(data.status === 'started', data.source, data.is_file);
  } catch (err) {
    console.error('Switch to webcam failed:', err);
  } finally {
    btn.disabled = false;
  }
}

async function switchCamera(index) {
  const sel = $('camera-select');
  if (sel) sel.disabled = true;
  try {
    const data = await fetch(`/api/camera/switch/${index}`, { method: 'POST' }).then(r => r.json());
    updateCameraUI(data.status === 'started', data.source, data.is_file);
  } catch (err) {
    console.error('Camera switch failed:', err);
  } finally {
    if (sel) sel.disabled = false;
  }
}

function buildCameraSelect(cameras, current) {
  const sel = $('camera-select');
  if (!sel) return;

  if (cameras.length <= 1) {
    sel.classList.add('hidden');
    return;
  }

  sel.innerHTML = cameras
    .map(c => `<option value="${c.index}"${c.index === current ? ' selected' : ''}>${c.label}</option>`)
    .join('');
  sel.classList.remove('hidden');
}

// Source toggle: upload file when in camera mode, switch to webcam when in video mode
$('source-toggle-btn').addEventListener('click', () => {
  if (isFileSource) {
    switchToWebcam();
  } else {
    $('video-upload').click();
  }
});

$('camera-toggle-btn').addEventListener('click', toggleCamera);
$('restart-camera-btn')?.addEventListener('click', toggleCamera);
$('camera-select')?.addEventListener('change', e => switchCamera(Number(e.target.value)));

// Fetch camera list and status in parallel
Promise.all([
  fetch('/api/cameras').then(r => r.json()).catch(() => ({ cameras: [], current: 0 })),
  fetch('/api/camera/status').then(r => r.json()).catch(() => ({})),
]).then(([camData, status]) => {
  buildCameraSelect(camData.cameras, camData.current);
  updateCameraUI(status.running, status.source, status.is_file);
});

// ── Video upload ───────────────────────────────────────────────────────────
$('video-upload').addEventListener('change', async e => {
  const file = e.target.files[0];
  if (!file) return;

  $('camera-toggle-btn').disabled = true;
  $('source-toggle-btn').disabled = true;
  $('camera-label').textContent = 'Uploading…';

  const form = new FormData();
  form.append('file', file);

  try {
    const data = await fetch('/api/upload-video', { method: 'POST', body: form }).then(r => r.json());
    if (data.error) { alert(data.error); return; }
    updateCameraUI(true, data.source, data.is_file);
  } catch {
    alert('Upload failed. Check console for details.');
  } finally {
    $('camera-toggle-btn').disabled = false;
    $('source-toggle-btn').disabled = false;
    e.target.value = '';
  }
});

// ── Mode toggle ────────────────────────────────────────────────────────────
document.querySelectorAll('.mode-pill-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.dataset.mode;
    if (mode === currentMode) return;
    currentMode = mode;

    document.querySelectorAll('.mode-pill-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    $('proactive-view').classList.toggle('hidden', mode !== 'proactive');
    $('chat-view').classList.toggle('hidden', mode !== 'chat');

    // Show clear only in proactive mode
    const clearBtn = $('clear-btn');
    clearBtn.style.visibility = mode === 'proactive' ? 'visible' : 'hidden';

    if (mode === 'chat') $('chat-input').focus();
  });
});

// ── Clear button ───────────────────────────────────────────────────────────
$('clear-btn').addEventListener('click', () => {
  $('event-list').innerHTML = '';
  eventCount = 0;
  $('event-counter').textContent = '0 events';
  $('empty-state').style.display = '';
  $('overlay-alert').classList.add('hidden');
  $('last-analysis').textContent = 'Waiting for first analysis…';
});

// ── Chat ───────────────────────────────────────────────────────────────────
const chatMessages = $('chat-messages');
const chatInput    = $('chat-input');
const chatSendBtn  = $('chat-send');

function addBubble(role, text) {
  // Remove welcome screen on first message
  const welcome = chatMessages.querySelector('.chat-welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = `chat-bubble chat-bubble-${role}`;

  if (role === 'ai' && text === '__typing__') {
    div.id = 'chat-typing';
    div.className = 'chat-bubble chat-bubble-ai typing-indicator';
    div.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  } else {
    div.innerHTML = `${esc(text)}<span class="bubble-time">${formatTime(new Date().toISOString())}</span>`;
  }

  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

async function sendChat(text) {
  text = text.trim();
  if (!text) return;

  chatInput.value = '';
  chatInput.style.height = '';
  chatSendBtn.disabled = true;

  addBubble('user', text);
  addBubble('ai', '__typing__');

  try {
    const res  = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    $('chat-typing')?.remove();
    addBubble('ai', data.error ? `Error: ${data.error}` : data.reply);
  } catch {
    $('chat-typing')?.remove();
    addBubble('ai', 'Request failed. Please check your connection.');
  } finally {
    chatSendBtn.disabled = false;
    chatInput.focus();
  }
}

chatSendBtn.addEventListener('click', () => sendChat(chatInput.value));

chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat(chatInput.value);
  }
});

chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
});

// Suggestion chips
document.querySelectorAll('.suggestion-chip').forEach(chip => {
  chip.addEventListener('click', () => sendChat(chip.dataset.q));
});

// ── System prompt ──────────────────────────────────────────────────────────
const promptTA  = $('prompt-textarea');
const saveBtn   = $('save-prompt-btn');

fetch('/api/prompt')
  .then(r => r.json())
  .then(d => { promptTA.value = d.instructions || ''; })
  .catch(() => {});

saveBtn.addEventListener('click', async () => {
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';
  try {
    const res = await fetch('/api/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instructions: promptTA.value }),
    });
    saveBtn.textContent = res.ok ? 'Saved!' : 'Error';
  } catch {
    saveBtn.textContent = 'Error';
  } finally {
    saveBtn.disabled = false;
    setTimeout(() => { saveBtn.textContent = 'Save'; }, 2000);
  }
});

// ── Stream reconnect ───────────────────────────────────────────────────────
$('stream').onerror = () => {
  if (cameraRunning) setTimeout(() => { $('stream').src = '/stream?' + Date.now(); }, 2000);
};

// ── Helpers ────────────────────────────────────────────────────────────────
function formatTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Boot ───────────────────────────────────────────────────────────────────
connect();

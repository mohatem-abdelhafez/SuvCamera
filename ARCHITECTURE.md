# Cognitive Camera — System Architecture

## Overview

Cognitive Camera is a FastAPI-based AI surveillance application that captures frames from a webcam or video file, sends them to the Qwen Vision Language Model (via DashScope), and streams observations to a browser UI in real time.

---

## Input Sources

| Source | Description |
|---|---|
| Webcam | Device index (e.g. `0`) configured in `config.yaml` |
| Uploaded Video | `.mp4`, `.avi`, `.mkv`, `.mov`, `.webm` uploaded via the UI |
| RTSP / HTTP | Any URL string accepted by OpenCV `VideoCapture` |

---

## Component Diagram

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                              INPUT SOURCES                                   ║
╠══════════════╦══════════════════╦═════════════════════════════════════════════╣
║  Webcam      ║  Uploaded Video  ║  RTSP / HTTP stream                        ║
║  /dev/video0 ║  .mp4 .avi etc   ║  (via URL in config.yaml)                  ║
╚══════════════╩══════════════════╩═════════════════════════════════════════════╝
                           │
                           ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                        app/camera.py  —  Camera                              ║
║                                                                              ║
║  • cv2.VideoCapture — opens device index, file path, or URL                  ║
║  • Background thread (_capture_loop) reads frames continuously               ║
║  • Video files: reads native FPS, loops on EOF                               ║
║  • Encodes each frame as JPEG (quality set in config.yaml)                   ║
║  • Stores latest frame in _latest_frame (thread-safe lock)                   ║
║  • list_cameras() probes indices 0-7 to detect available devices             ║
║                                                                              ║
║  API:  grab_frame() → bytes    generate_mjpeg() → async generator            ║
╚══════════════════════════════════════════════════════════════════════════════╝
          │                          │
          │ grab_frame()             │ generate_mjpeg()
          │  every N seconds         │  continuously (~25 fps)
          ▼                          ▼
╔═══════════════════════╗   ╔══════════════════════════════════════════════════╗
║  app/scheduler.py     ║   ║  GET /stream  (server.py)                        ║
║  Scheduler            ║   ║                                                  ║
║                       ║   ║  StreamingResponse                               ║
║  asyncio loop:        ║   ║  multipart/x-mixed-replace; boundary=frame       ║
║  every interval_sec   ║   ║  → browser <img id="stream"> displays live feed  ║
║  (default 6s)         ║   ╚══════════════════════════════════════════════════╝
║                       ║
║  1. grab frame        ║
║  2. fetch history     ║   ╔══════════════════════════════════════════════════╗
║  3. call analyzer     ║   ║  app/events.py  —  EventStore                    ║
║  4. check cooldowns   ║   ║                                                  ║
║  5. save & broadcast  ║◄──║  SQLite  (data/events.db)                        ║
║                       ║──►║                                                  ║
║  cooldowns:           ║   ║  • save(event_type, message, tags) → record      ║
║   comment: 30s        ║   ║  • get_recent(limit, types) → list[dict]         ║
║   alert:    8s        ║   ║  • _purge_old() — deletes events > 48h           ║
╚═══════════════════════╝   ╚══════════════════════════════════════════════════╝
          │
          │ analyze(frame_jpeg, history)
          ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                      app/analyzer.py  —  Analyzer                            ║
║                                                                              ║
║  openai SDK  →  DashScope International endpoint                             ║
║  https://dashscope-intl.aliyuncs.com/compatible-mode/v1                     ║
║                                                                              ║
║  ┌─ analyze() ─────────────────────────────────────────────────────────┐    ║
║  │  System prompt: role + monitoring instructions + recent history      │    ║
║  │  User message:  JPEG frame (base64) + "Analyze this frame."         │    ║
║  │  Returns JSON: { type, message, tags }                              │    ║
║  │    type = "ignore" | "comment" | "alert"                            │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
║  ┌─ chat() ────────────────────────────────────────────────────────────┐    ║
║  │  System: "Answer about what's visible in the frame"                 │    ║
║  │  User:   JPEG frame (base64) + free-form question                   │    ║
║  │  Returns: plain text reply                                          │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                  │                                           ║
║                     Model: qwen-vl-plus  (config.yaml)                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
          │
          │ broadcast(event) / broadcast(status)
          ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                    app/server.py  —  FastAPI App                              ║
║                                                                              ║
║  ConnectionManager  — holds list of active WebSocket connections             ║
║  broadcast(payload) — sends JSON to all connected browsers                   ║
║                                                                              ║
║  REST Endpoints:                                                             ║
║  ┌──────────────────────────────┬──────────────────────────────────────┐    ║
║  │ GET  /stream                 │ MJPEG camera feed                    │    ║
║  │ GET  /api/camera/status      │ running, source, is_file             │    ║
║  │ POST /api/camera/start       │ start capture                        │    ║
║  │ POST /api/camera/stop        │ stop capture                         │    ║
║  │ POST /api/camera/use-camera  │ reset to default webcam              │    ║
║  │ POST /api/camera/switch/{i}  │ switch to camera index i             │    ║
║  │ GET  /api/cameras            │ list all detected camera devices     │    ║
║  │ POST /api/upload-video       │ save file, restart camera on it      │    ║
║  │ POST /api/chat               │ grab frame → analyzer.chat()         │    ║
║  │ GET  /api/prompt             │ read monitoring instructions         │    ║
║  │ POST /api/prompt             │ update instructions in-memory        │    ║
║  │ GET  /api/events             │ fetch recent events from DB          │    ║
║  │ WS   /ws                     │ push history + live events           │    ║
║  └──────────────────────────────┴──────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════════════╝
          │  WebSocket  /ws
          │  push: history, event, status, error
          ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                        Browser  —  static/                                   ║
║                                                                              ║
║  ┌─────────────────────────┐   ┌──────────────────────────────────────────┐ ║
║  │   Camera Panel          │   │   Right Panel                            │ ║
║  │                         │   │                                          │ ║
║  │  <img src="/stream">    │   │  ┌─ Proactive Mode ──────────────────┐  │ ║
║  │  Start / Stop button    │   │  │  Event list (comment / alert)     │  │ ║
║  │  Upload Video  ────────►│   │  │  Overlay alert popup (8s)         │  │ ║
║  │  Use Camera  ◄──────────│   │  └───────────────────────────────────┘  │ ║
║  │  Camera selector        │   │                                          │ ║
║  │  (dropdown if >1 cam)   │   │  ┌─ Chat Mode ────────────────────────┐ │ ║
║  └─────────────────────────┘   │  │  User types question               │ │ ║
║                                │  │  POST /api/chat → AI reply         │ │ ║
║  ┌─────────────────────────┐   │  │  Typing indicator (3 dots)         │ │ ║
║  │  Monitoring Instructions│   │  └───────────────────────────────────┘  │ ║
║  │  <textarea>             │   └──────────────────────────────────────────┘ ║
║  │  POST /api/prompt       │                                                 ║
║  └─────────────────────────┘                                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Data Flow

### Proactive Monitoring (automatic)

```
Input source
    └─► Camera (thread) — captures + JPEG encodes frames
            ├─► /stream endpoint — browser displays live MJPEG feed
            └─► Scheduler (asyncio, every 6s)
                    ├─► EventStore.get_recent() — fetches last 5 events as context
                    ├─► Analyzer.analyze()  — sends frame + history to Qwen VL
                    │       └─► DashScope API → JSON { type, message, tags }
                    ├─► Cooldown check (30s comment / 8s alert)
                    ├─► EventStore.save()   — persists to SQLite
                    └─► ConnectionManager.broadcast() → WebSocket → Browser UI
```

### Chat Mode (on demand)

```
User types question in browser
    └─► POST /api/chat
            ├─► Camera.grab_frame()   — snapshot of current frame
            └─► Analyzer.chat()       — sends frame + question to Qwen VL
                    └─► DashScope API → plain text reply → browser chat bubble
```

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `app/camera.py` | Frame capture, JPEG encoding, source switching, camera enumeration |
| `app/analyzer.py` | DashScope API calls for both proactive analysis and chat Q&A |
| `app/scheduler.py` | Timed analysis loop, cooldown enforcement, event broadcasting |
| `app/events.py` | SQLite persistence, history queries, old event purging |
| `app/server.py` | FastAPI routes, WebSocket manager, request/response handling |
| `static/index.html` | UI layout — camera panel, proactive view, chat view, prompt editor |
| `static/style.css` | Dark theme, coral accent palette, responsive layout |
| `static/app.js` | WebSocket client, camera controls, chat bubbles, mode switching |
| `config.yaml` | All runtime configuration (model, intervals, cooldowns, DB path) |

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| Separate `_capture_loop` thread | `cv2.VideoCapture.read()` is blocking — running it in asyncio would freeze the event loop |
| `_latest_frame` with threading lock | Decouples capture speed from consumer speed; any number of consumers read the same latest frame |
| Cooldowns per event type | Prevents comment/alert spam when the scene has repetitive motion |
| SQLite via `aiosqlite` | Async-safe, zero server setup, survives process restarts |
| `openai` SDK against DashScope | DashScope exposes an OpenAI-compatible REST API; no custom HTTP client needed |
| WebSocket for event push | Zero-polling — status updates and new events arrive at the browser instantly |
| MJPEG via `StreamingResponse` | Works in any browser with a plain `<img>` tag; no JavaScript video player needed |
| `run_in_executor` for camera start | `_start_capture` opens the device (blocking I/O) without stalling the async server |

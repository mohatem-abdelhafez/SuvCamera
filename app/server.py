import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import Analyzer
from .camera import Camera
from .events import EventStore
from .scheduler import Scheduler

logger = logging.getLogger(__name__)

UPLOAD_DIR = "data/uploads"


class PromptUpdate(BaseModel):
    instructions: str


class ChatMessage(BaseModel):
    message: str


class ConnectionManager:
    def __init__(self):
        self._sockets: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._sockets.append(ws)

    def disconnect(self, ws: WebSocket):
        try:
            self._sockets.remove(ws)
        except ValueError:
            pass

    async def broadcast(self, payload: dict):
        msg = json.dumps(payload, default=str)
        dead = []
        for ws in self._sockets:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def create_app(config: dict) -> FastAPI:
    camera = Camera(config)
    store = EventStore(config)
    analyzer = Analyzer(config)
    manager = ConnectionManager()
    scheduler = Scheduler(config, camera, analyzer, store, manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await store.init()
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        await camera.start()
        asyncio.create_task(scheduler.run())
        logger.info("ProWatch AI started — http://localhost:%s", config.get("server", {}).get("port", 8000))
        yield
        await camera.stop()

    app = FastAPI(title="ProWatch AI", lifespan=lifespan)

    # ── Video stream ───────────────────────────────────────────────────────
    @app.get("/stream")
    async def video_stream():
        return StreamingResponse(
            camera.generate_mjpeg(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # ── Camera control ─────────────────────────────────────────────────────
    @app.post("/api/camera/start")
    async def camera_start():
        if camera.is_running:
            return JSONResponse({"status": "already_running", "source": camera.source_label})
        await camera.start()
        return JSONResponse({"status": "started", "source": camera.source_label})

    @app.post("/api/camera/stop")
    async def camera_stop():
        if not camera.is_running:
            return JSONResponse({"status": "already_stopped"})
        await camera.stop()
        return JSONResponse({"status": "stopped"})

    @app.get("/api/camera/status")
    async def camera_status():
        return JSONResponse({
            "running": camera.is_running,
            "source": camera.source_label,
            "is_file": camera.is_file,
        })

    @app.post("/api/camera/use-camera")
    async def camera_use_webcam():
        await camera.stop()
        camera.reset_to_default()
        await camera.start()
        return JSONResponse({"status": "started", "source": camera.source_label, "is_file": camera.is_file})

    @app.get("/api/cameras")
    async def list_cameras():
        loop = asyncio.get_event_loop()
        cameras = await loop.run_in_executor(None, Camera.list_cameras)
        current_source = None if camera.is_file else camera._source
        return JSONResponse({"cameras": cameras, "current": current_source})

    @app.post("/api/camera/switch/{index}")
    async def switch_camera(index: int):
        await camera.stop()
        camera.set_source(index)
        await camera.start()
        return JSONResponse({"status": "started", "source": camera.source_label, "is_file": camera.is_file})

    # ── Video upload ───────────────────────────────────────────────────────
    @app.post("/api/upload-video")
    async def upload_video(file: UploadFile):
        if not file.filename:
            return JSONResponse({"error": "No file provided"}, status_code=400)

        ext = os.path.splitext(file.filename)[1].lower()
        allowed = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
        if ext not in allowed:
            return JSONResponse(
                {"error": f"Unsupported format. Allowed: {', '.join(allowed)}"},
                status_code=400,
            )

        save_path = os.path.join(UPLOAD_DIR, file.filename)
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        # Stop current camera, switch source to uploaded video, restart
        await camera.stop()
        camera.set_source(save_path)
        await camera.start()

        return JSONResponse({"status": "streaming", "source": camera.source_label, "is_file": camera.is_file})

    # ── Chat (ask about current frame) ────────────────────────────────────
    @app.post("/api/chat")
    async def chat_endpoint(body: ChatMessage):
        frame = camera.grab_frame()
        if frame is None:
            return JSONResponse({"error": "No camera frame available. Start the camera first."}, status_code=503)
        try:
            reply = await analyzer.chat(frame, body.message)
            return JSONResponse({"reply": reply})
        except Exception as exc:
            logger.error("Chat failed: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    # ── System prompt ──────────────────────────────────────────────────────
    @app.get("/api/prompt")
    async def get_prompt():
        instructions = config.get("monitoring", {}).get("instructions", "")
        return JSONResponse({"instructions": instructions})

    @app.post("/api/prompt")
    async def update_prompt(body: PromptUpdate):
        config.setdefault("monitoring", {})["instructions"] = body.instructions
        return JSONResponse({"status": "updated"})

    # ── Events ─────────────────────────────────────────────────────────────
    @app.get("/api/events")
    async def get_events(limit: int = 100):
        events = await store.get_recent(limit=limit)
        return JSONResponse(events)

    @app.get("/api/config")
    async def get_config():
        safe = {k: v for k, v in config.items() if k != "api"}
        return JSONResponse(safe)

    # ── WebSocket ──────────────────────────────────────────────────────────
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await manager.connect(ws)
        try:
            history = await store.get_recent(limit=50)
            await ws.send_text(json.dumps({"type": "history", "events": history}))
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception as exc:
            logger.debug("WebSocket closed: %s", exc)
            manager.disconnect(ws)

    app.mount("/", StaticFiles(directory="static", html=True), name="static")
    return app

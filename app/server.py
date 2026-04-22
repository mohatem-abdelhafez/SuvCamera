import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import Analyzer
from .camera import Camera
from .events import EventStore
from .scheduler import Scheduler

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._sockets: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._sockets.append(ws)

    def disconnect(self, ws: WebSocket):
        self._sockets.discard if hasattr(self._sockets, "discard") else None
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
        await camera.start()
        asyncio.create_task(scheduler.run())
        logger.info("ProWatch AI started — http://localhost:%s", config.get("server", {}).get("port", 8000))
        yield
        await camera.stop()

    app = FastAPI(title="ProWatch AI", lifespan=lifespan)

    @app.get("/stream")
    async def video_stream():
        return StreamingResponse(
            camera.generate_mjpeg(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/api/events")
    async def get_events(limit: int = 100):
        events = await store.get_recent(limit=limit)
        return JSONResponse(events)

    @app.get("/api/config")
    async def get_config():
        # Strip API key before sending to browser
        safe = {k: v for k, v in config.items() if k != "api"}
        return JSONResponse(safe)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await manager.connect(ws)
        try:
            # Replay recent history on fresh connection
            history = await store.get_recent(limit=50)
            await ws.send_text(json.dumps({"type": "history", "events": history}))
            while True:
                # Keep socket alive; client sends periodic pings
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception as exc:
            logger.debug("WebSocket closed: %s", exc)
            manager.disconnect(ws)

    app.mount("/", StaticFiles(directory="static", html=True), name="static")
    return app

import asyncio
import logging
import time

from .analyzer import Analyzer
from .camera import Camera
from .events import EventStore

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, config: dict, camera: Camera, analyzer: Analyzer, store: EventStore, manager):
        self._config = config
        self._camera = camera
        self._analyzer = analyzer
        self._store = store
        self._manager = manager  # ConnectionManager

        sampling = config.get("sampling", {})
        self._interval = sampling.get("interval_seconds", 6)

        monitoring = config.get("monitoring", {})
        self._cooldown = monitoring.get("cooldown_seconds", 30)
        self._alert_cooldown = monitoring.get("alert_cooldown_seconds", 8)
        self._max_history = monitoring.get("max_history", 5)

        self._last_comment_time: float = 0.0
        self._last_alert_time: float = 0.0
        self._analyzing = False

    async def run(self):
        while True:
            await asyncio.sleep(self._interval)
            if not self._analyzing:
                asyncio.create_task(self._cycle())

    async def _cycle(self):
        self._analyzing = True
        await self._manager.broadcast({"type": "status", "status": "analyzing"})
        try:
            frame = self._camera.grab_frame()
            if frame is None:
                return

            history = await self._store.get_recent(limit=self._max_history, types=("comment", "alert"))
            result = await self._analyzer.analyze(frame, history)

            event_type = result.get("type", "ignore")
            message = result.get("message", "")
            tags = result.get("tags", [])

            if event_type == "ignore" or not message:
                return

            if not self._should_emit(event_type):
                return

            record = await self._store.save(event_type, message, tags)
            self._update_cooldown(event_type)
            await self._manager.broadcast({"type": "event", "event": record})

        except Exception as exc:
            logger.error("Analysis cycle failed: %s", exc, exc_info=True)
            await self._manager.broadcast({"type": "error", "message": str(exc)})
        finally:
            self._analyzing = False
            await self._manager.broadcast({"type": "status", "status": "idle"})

    def _should_emit(self, event_type: str) -> bool:
        now = time.monotonic()
        if event_type == "alert":
            return now - self._last_alert_time >= self._alert_cooldown
        if event_type == "comment":
            return now - self._last_comment_time >= self._cooldown
        return False

    def _update_cooldown(self, event_type: str):
        now = time.monotonic()
        if event_type == "alert":
            self._last_alert_time = now
        elif event_type == "comment":
            self._last_comment_time = now

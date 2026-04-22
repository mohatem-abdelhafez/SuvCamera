import asyncio
import io
import threading
import time
from typing import AsyncGenerator

import cv2
from PIL import Image


class Camera:
    def __init__(self, config: dict):
        self._config = config
        cam_cfg = config.get("camera", {})
        self._source = cam_cfg.get("source", 0)
        self._width = cam_cfg.get("width", 1280)
        self._height = cam_cfg.get("height", 720)
        self._quality = config.get("sampling", {}).get("jpeg_quality", 82)

        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._latest_frame: bytes | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    async def start(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._start_capture)

    def _start_capture(self):
        source = self._source
        # Numeric sources stay as int; string sources (RTSP, HTTP) stay as str
        if isinstance(source, str) and source.isdigit():
            source = int(source)

        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera source: {source!r}")

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.1)
                continue
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            encoded = self._encode_jpeg(frame)
            with self._lock:
                self._latest_frame = encoded
            time.sleep(0.033)  # ~30 fps

    def _encode_jpeg(self, frame) -> bytes:
        ok, buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._quality]
        )
        if not ok:
            raise RuntimeError("Failed to encode frame as JPEG")
        return buf.tobytes()

    def grab_frame(self) -> bytes | None:
        with self._lock:
            return self._latest_frame

    async def generate_mjpeg(self) -> AsyncGenerator[bytes, None]:
        """Yields MJPEG boundary frames for browser streaming."""
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        while True:
            frame = self.grab_frame()
            if frame:
                yield boundary + frame + b"\r\n"
            await asyncio.sleep(0.04)  # ~25 fps to browser

    async def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap:
            self._cap.release()

import asyncio
import os
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
        self._is_file = False  # True when streaming from a video file

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_file(self) -> bool:
        return self._is_file

    @property
    def source_label(self) -> str:
        if self._is_file:
            return f"Video: {os.path.basename(str(self._source))}"
        return f"Camera: {self._source}"

    def reset_to_default(self):
        """Reset source back to the configured default (webcam)."""
        cam_cfg = self._config.get("camera", {})
        self._source = cam_cfg.get("source", 0)

    async def start(self):
        if self._running:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._start_capture)

    def _start_capture(self):
        source = self._source
        # Numeric sources stay as int; string sources (RTSP, HTTP) stay as str
        if isinstance(source, str) and source.isdigit():
            source = int(source)

        # Detect whether the source is a local video file
        self._is_file = isinstance(source, str) and os.path.isfile(source)

        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera source: {source!r}")

        if not self._is_file:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

        # For video files, read the native FPS to pace playback
        if self._is_file:
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            self._frame_delay = 1.0 / fps if fps and fps > 0 else 0.033
        else:
            self._frame_delay = 0.033  # ~30 fps

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
                if self._is_file:
                    # Loop video files back to the beginning
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.05)
                continue
            encoded = self._encode_jpeg(frame)
            with self._lock:
                self._latest_frame = encoded
            time.sleep(self._frame_delay)

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

    def set_source(self, source):
        """Change the camera source (device index, URL, or file path)."""
        self._source = source

    @staticmethod
    def list_cameras(max_index: int = 8) -> list[dict]:
        """Probe camera indices 0‥max_index-1 and return the ones that open."""
        available = []
        for i in range(max_index):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append({"index": i, "label": f"Camera {i}"})
                cap.release()
        return available

    async def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        with self._lock:
            self._latest_frame = None

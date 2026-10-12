from __future__ import annotations

import hashlib
import io
import threading
import time
from dataclasses import dataclass

from PIL import Image

from note4_claude.render.layout import H, W
from note4_claude.state import HEARTBEAT_S

FRAME_BYTES = W * H // 8  # 15,000: one bit per pixel, row-major, MSB first


def png_to_frame(png: bytes) -> bytes:
    """A 400x300 1-bit PNG as the panel's raw frame: row-major, MSB first, 0 = black."""
    im = Image.open(io.BytesIO(png))
    if im.size != (W, H) or im.mode != "1":
        raise ValueError(f"expected a {W}x{H} 1-bit image, got {im.size} mode {im.mode}")
    data = im.tobytes()
    if len(data) != FRAME_BYTES:
        raise ValueError(f"frame is {len(data)} bytes, expected {FRAME_BYTES}")
    return data


@dataclass(frozen=True)
class Frame:
    data: bytes
    etag: str
    key: str
    stored_at: float


class LanSink:
    """Holds the latest frame per page for the HTTP server. Same push() call as the cloud Pusher."""

    def __init__(self, *, heartbeat_s: float = HEARTBEAT_S, clock=time.time):
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        self._frames: dict[int, Frame] = {}
        self._lock = threading.Lock()

    def push(self, page_id: int, png: bytes, key: str) -> str:
        now = self.clock()
        with self._lock:
            cur = self._frames.get(page_id)
            if cur is not None and cur.key == key and now - cur.stored_at < self.heartbeat_s:
                return "unchanged"
        data = png_to_frame(png)
        etag = hashlib.sha256(data).hexdigest()[:16]
        with self._lock:
            self._frames[page_id] = Frame(data, etag, key, now)
        return "pushed"

    def get(self, page_id: int) -> Frame | None:
        with self._lock:
            return self._frames.get(page_id)

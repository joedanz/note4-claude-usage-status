from __future__ import annotations

import time

import httpx

from claude_eink.config import DEFAULT_API_BASE
from claude_eink.state import HEARTBEAT_S, State

# Multipart field name for the image file. Verified live against the real API (see the
# live-verification step in the plan); adjust here if the API rejects it.
IMAGE_FIELD = "images"


class PushError(Exception):
    pass


def device_id_of(device: dict) -> str:
    return str(device.get("deviceId") or device.get("id") or device.get("mac") or "")


def list_devices(client: httpx.Client, api_key: str, base_url: str = DEFAULT_API_BASE) -> list[dict]:
    r = client.get(f"{base_url}/open/v1/devices", headers={"X-API-Key": api_key}, timeout=15)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        raise PushError(f"devices call failed: {body}")
    return list(body.get("data") or [])


class Pusher:
    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        device_id: str,
        state: State,
        *,
        base_url: str = DEFAULT_API_BASE,
        min_interval_s: float = 60.0,
        heartbeat_s: float = HEARTBEAT_S,
        clock=time.time,
    ):
        self.client = client
        self.api_key = api_key
        self.device_id = device_id
        self.state = state
        self.base_url = base_url
        self.min_interval_s = min_interval_s
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        self._failures = 0
        self._blocked_until = 0.0

    def push(self, page_id: int, png: bytes, key: str) -> str:
        now = self.clock()
        page = self.state.pages.get(str(page_id), {})
        age = now - page.get("at", float("-inf"))
        if page.get("key") == key and age < self.heartbeat_s:
            return "unchanged"
        if now < self._blocked_until:
            return "backoff"
        if age < self.min_interval_s:
            return "throttled"
        try:
            r = self.client.post(
                f"{self.base_url}/open/v1/devices/{self.device_id}/display/image",
                headers={"X-API-Key": self.api_key},
                files={IMAGE_FIELD: ("page.png", png, "image/png")},
                data={"dither": "false", "pageId": str(page_id)},
                timeout=30,
            )
            body = r.json()
            if r.status_code >= 400 or body.get("code") != 0:
                raise PushError(f"HTTP {r.status_code}: {body}")
        except (httpx.HTTPError, ValueError, PushError) as e:
            self._failures += 1
            self._blocked_until = now + min(900.0, 30.0 * 2 ** (self._failures - 1))
            raise PushError(str(e)) from e
        self._failures = 0
        self.state.pages[str(page_id)] = {"key": key, "at": now}
        self.state.save()
        return "pushed"

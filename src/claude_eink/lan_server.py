from __future__ import annotations

import hmac
import logging
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("claude_eink")
PAGE_RE = re.compile(r"^/v1/page/(\d{1,4})\.bin$")


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    for part in header.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("W/"):
            part = part[2:]
        if part == f'"{etag}"':
            return True
    return False


def make_server(
    sink, host: str, port: int, device_key: str, next_poll_s: int = 300, request_timeout_s: float = 10.0
) -> ThreadingHTTPServer:
    """An HTTP server for the device. Not started; the caller runs serve_forever()."""
    if not device_key:
        raise ValueError("a device key is required to serve frames")
    key_bytes = device_key.encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "claude-eink"
        timeout = request_timeout_s  # an idle or half-open client must not hold a thread forever

        def _send(self, code: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
            self.send_response(code)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _authorized(self) -> bool:
            given = self.headers.get("X-Device-Key", "")
            return hmac.compare_digest(given.encode(), key_bytes)

        def do_GET(self) -> None:
            if not self._authorized():
                return self._send(401, b"unauthorized\n")
            match = PAGE_RE.match(self.path.split("?", 1)[0])
            frame = sink.get(int(match.group(1))) if match else None
            if frame is None:
                return self._send(404, b"not found\n")
            headers = {
                "ETag": f'"{frame.etag}"',
                "X-Next-Poll": str(next_poll_s),
                "Cache-Control": "no-store",
            }
            if _etag_matches(self.headers.get("If-None-Match"), frame.etag):
                return self._send(304, b"", headers)
            headers["Content-Type"] = "application/octet-stream"
            self._send(200, frame.data, headers)

        def _method_not_allowed(self) -> None:
            self._send(405, b"", {"Allow": "GET"})

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _method_not_allowed

        def log_message(self, fmt, *args) -> None:  # never log headers (they carry the key)
            log.debug("lan %s", fmt % args)

    return ThreadingHTTPServer((host, port), Handler)


def detect_lan_ip() -> str:
    """The address of the interface that routes to the LAN, or loopback if there is none."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

from __future__ import annotations

from dataclasses import dataclass
from http.server import ThreadingHTTPServer

import httpx

from note4_claude import keychain
from note4_claude.config import Config
from note4_claude.lan import LanSink
from note4_claude.lan_server import detect_lan_ip, make_server
from note4_claude.pusher import Pusher
from note4_claude.state import State


@dataclass
class Delivery:
    sink: object                      # anything with push(page_id, png, key) -> str
    server: ThreadingHTTPServer | None


def build_delivery(
    cfg: Config,
    *,
    state: State,
    serve: bool = True,
    api_key_getter=keychain.get_api_key,
    client: httpx.Client | None = None,
) -> Delivery:
    if cfg.delivery == "cloud":
        key = api_key_getter()
        if not key or not cfg.device_id:
            raise SystemExit("Not set up for cloud delivery: run `note4-claude setup --cloud` first.")
        pusher = Pusher(client or httpx.Client(), key, cfg.device_id, state, base_url=cfg.api_base)
        return Delivery(pusher, None)
    if not cfg.device_key:
        raise SystemExit("Not set up: run `note4-claude setup` first (it creates the device key).")
    sink = LanSink()
    if not serve:                      # e.g. push-once: the running daemon owns the port
        return Delivery(sink, None)
    host = cfg.lan_bind or detect_lan_ip()
    if not cfg.lan_bind and host == "127.0.0.1":
        # No route yet (for example right after a reboot, before Wi-Fi is up). Failing lets launchd's
        # KeepAlive retry, instead of serving on loopback where the device can never reach it.
        raise SystemExit("No LAN address yet (no network route); exiting so the daemon is retried.")
    try:
        server = make_server(sink, host, cfg.lan_port, cfg.device_key, cfg.next_poll_s)
    except OSError as e:
        raise SystemExit(f"Cannot listen on {host}:{cfg.lan_port}: {e}. Is another note4-claude already running?") from e
    return Delivery(sink, server)

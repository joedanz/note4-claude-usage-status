from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta

import httpx

from claude_eink import config as config_mod
from claude_eink import paths
from claude_eink.models import NotLoggedIn, ParseFailed, TransientError
from claude_eink.parser import parse
from claude_eink.pusher import PushError
from claude_eink.render.screens import render_login
from claude_eink.render.status_page import render_status
from claude_eink.render.usage_page import render_usage
from claude_eink.state import State

log = logging.getLogger("claude_eink")
STALE_AFTER = timedelta(minutes=15)
DEBUG_AFTER_FAILURES = 3
MAX_BARLESS_SKIPS = 2      # ticks a healthy status page may be held back while the uptime data is unavailable
USAGE_PAGE, STATUS_PAGE = 1, 2
PAGES = (USAGE_PAGE, STATUS_PAGE)


class Collector:
    def __init__(self, read_usage, read_status, pusher, now, save_debug=None, state=None):
        self.read_usage = read_usage
        self.read_status = read_status
        self.pusher = pusher
        self.now = now
        self.save_debug = save_debug
        self.last_good = None
        self.last_good_at: datetime | None = None
        self.status = None
        self.failures = 0
        self.barless_skips = 0
        self.logged_out = False
        self.state = state
        self.results: dict[int, str] = {}
        self._restore()

    def _restore(self) -> None:
        """Bring back the last good read after a restart so the STALE rule still applies."""
        st = self.state
        if st is None or not st.last_good_text or st.last_good_at is None:
            return
        try:
            at = datetime.fromtimestamp(st.last_good_at, tz=self.now().tzinfo)
            self.last_good = parse(st.last_good_text, at)
            self.last_good_at = at
        except (ParseFailed, ValueError, OSError) as e:
            log.warning("could not restore last good usage: %s", e)

    # -- emitting -------------------------------------------------------
    def _emit(self, page: int, render) -> None:
        png = render(True)
        key = hashlib.sha256(render(False)).hexdigest()
        try:
            result = self.pusher.push(page, png, key)
            self.results[page] = result
            log.info("page %s: %s", page, result)
        except PushError as e:
            self.results[page] = f"error: {e}"
            log.warning("push failed for page %s: %s", page, e)

    def _emit_usage_page(self) -> None:
        now = self.now()
        if self.logged_out:
            self._emit(USAGE_PAGE, lambda clock: render_login(now=now, show_clock=clock))
            return
        if self.last_good is None:
            return
        stale = self.last_good_at if now - self.last_good_at > STALE_AFTER else None
        alert = self.status.alert if self.status else None      # incident title, or the site's headline
        usage = self.last_good
        self._emit(
            USAGE_PAGE,
            lambda clock: render_usage(
                usage, now=now, stale_since=stale, incident=alert, show_clock=clock
            ),
        )

    # -- ticks ----------------------------------------------------------
    def tick_usage(self) -> None:
        now = self.now()
        text = None
        try:
            text = self.read_usage()
            usage = parse(text, now)
        except NotLoggedIn:
            self.logged_out = True
        except TransientError as e:
            log.info("transient usage read error: %s", e)
        except ParseFailed as e:
            self.failures += 1
            log.warning("parse failed (%s in a row): %s", self.failures, e)
            if self.failures == DEBUG_AFTER_FAILURES and self.save_debug and text is not None:
                self.save_debug(text)
        else:
            self.logged_out = False
            self.failures = 0
            self.last_good, self.last_good_at = usage, now
            if self.state is not None:
                self.state.last_good_text = text
                self.state.last_good_at = now.timestamp()
                self.state.save()
        self._emit_usage_page()

    def tick_status(self) -> None:
        try:
            status = self.read_status()
        except Exception as e:  # noqa: BLE001 - a status outage must not stop usage updates
            log.warning("status read failed: %s", e)
            return
        changed_alert = (self.status.alert if self.status else None) != status.alert
        self.status = status
        now = self.now()
        if self._hold_barless(status):
            return
        self._emit(STATUS_PAGE, lambda clock: render_status(status, now=now, show_clock=clock))
        if changed_alert:
            self._emit_usage_page()

    def _hold_barless(self, status) -> bool:
        """True to skip pushing a healthy status page that lost its uptime bars (a failed fetch on a cold cache).

        An incident always goes out: the fresh headline matters more than the bars. The hold is bounded
        so a permanently missing uptime feed still ends up showing the plain page.
        """
        if not status.ok or any(c.days for c in status.components):
            self.barless_skips = 0
            return False
        if self.barless_skips >= MAX_BARLESS_SKIPS:
            return False
        self.barless_skips += 1
        log.info("holding the status page: no uptime bars yet (%s/%s)", self.barless_skips, MAX_BARLESS_SKIPS)
        return True


def build_collector(cfg=None, *, serve=True):
    """The collector plus the LAN server (None for cloud delivery). The server is not started here."""
    from claude_eink.delivery import build_delivery
    from claude_eink.readers import status_reader, usage_reader

    cfg = cfg or config_mod.load()
    state = State.load(paths.state_path())
    delivery = build_delivery(cfg, state=state, serve=serve)
    client = httpx.Client()
    uptime_cache = status_reader.UptimeCache()     # the 90-day data is re-fetched at most every 30 minutes

    def now() -> datetime:
        return datetime.now().astimezone()

    def read_usage() -> str:
        shot = paths.debug_dir() / "last.png"
        paths.debug_dir().mkdir(parents=True, exist_ok=True)
        return usage_reader.read_usage_text(paths.profile_dir(), screenshot_to=shot)

    def save_debug(text: str) -> None:
        paths.debug_dir().mkdir(parents=True, exist_ok=True)
        (paths.debug_dir() / f"modal-{now():%Y%m%d-%H%M%S}.txt").write_text(text)

    collector = Collector(
        read_usage,
        lambda: status_reader.read_status(client, now(), uptime_cache=uptime_cache),
        delivery.sink,
        now,
        save_debug,
        state,
    )
    return collector, delivery.server


def run_forever(collector: Collector, cfg, sleep=time.sleep) -> None:
    next_usage = next_status = 0.0
    while True:
        t = time.monotonic()
        if t >= next_status:
            _safe(collector.tick_status)
            next_status = t + cfg.status_interval_s
        if t >= next_usage:
            _safe(collector.tick_usage)
            next_usage = t + cfg.usage_interval_s
        sleep(5)


def _safe(fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - the daemon must survive anything
        log.exception("tick failed")

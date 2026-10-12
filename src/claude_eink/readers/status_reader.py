from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import datetime, timedelta, timezone

import httpx

from claude_eink.models import ComponentStatus, StatusData

log = logging.getLogger("claude_eink")
SUMMARY_URL = "https://status.claude.com/api/v2/summary.json"
UPTIME_URL = "https://status.claude.com/uptime_showcase"
RELEASE_URL = "https://api.github.com/repos/anthropics/claude-code/releases/latest"
UPTIME_TTL = timedelta(minutes=30)
# (substring of the site's component name, label shown on the panel), in the site's order
COMPONENTS = (
    ("claude.ai", "claude.ai"),
    ("console", "Console"),
    ("api", "API"),
    ("claude code", "Claude Code"),
    ("cowork", "Cowork"),
)
SEVERITY = {"operational": 0, "under_maintenance": 0, "major_outage": 2}   # anything else counts as degraded (1)


@dataclass
class UptimeCache:
    """The 90-day data changes daily, so it is fetched at most every UPTIME_TTL."""

    ids: tuple[str, ...] = ()
    parsed: dict | None = None
    fetched_at: datetime | None = None


def _match(summary: dict) -> list[tuple[str, dict]]:
    comps = summary.get("components") or []
    found = []
    for needle, label in COMPONENTS:
        comp = next((c for c in comps if needle in c.get("name", "").lower()), None)
        if comp is not None:
            found.append((label, comp))
    return found


def _tier(day: dict) -> int:
    outages = day.get("outages") or {}
    return 2 if outages.get("m") else 1 if outages.get("p") else 0


def parse_uptime(payload: dict) -> dict[str, tuple[float | None, tuple[int, ...]]]:
    """component id -> (90-day uptime percent, per-day tiers oldest first)."""
    values = {v["component"]: v.get("ninety") for v in payload.get("values") or []}
    return {
        code: (values.get(code), tuple(_tier(day) for day in tl.get("days") or []))
        for code, tl in (payload.get("timelines") or {}).items()
    }


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def parse_summary(summary: dict, release: dict | None, now: datetime, uptime: dict | None = None) -> StatusData:
    status = summary.get("status", {})
    ok = status.get("indicator") == "none"
    headline = "ALL SYSTEMS OK" if ok else str(status.get("description", "ISSUES")).upper()

    incidents = summary.get("incidents") or []
    inc = incidents[0] if incidents else {}

    parts = []
    for label, comp in _match(summary):
        ninety, days = (uptime or {}).get(comp.get("id"), (None, ()))
        severity = SEVERITY.get(comp.get("status"), 1)
        parts.append(ComponentStatus(label, severity, ninety, days))

    tag, age = None, None
    if release and release.get("tag_name"):
        tag = release["tag_name"]
        try:
            published = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
            age = max(0, (now.astimezone(timezone.utc) - published).days)
        except (KeyError, ValueError):
            age = None
    return StatusData(
        headline,
        ok,
        tuple(parts),
        inc.get("name"),
        inc.get("status"),
        _parse_time(inc.get("started_at") or inc.get("created_at")),
        tag,
        age,
    )


def _uptime(client: httpx.Client, ids: tuple[str, ...], now: datetime, cache: UptimeCache | None):
    if cache is not None and cache.parsed is not None and cache.ids == ids and cache.fetched_at is not None:
        if now - cache.fetched_at < UPTIME_TTL:
            return cache.parsed
    try:
        r = client.get(
            UPTIME_URL,
            params={"components": ",".join(ids)},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            timeout=20,
        )
        r.raise_for_status()
        parsed = parse_uptime(r.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("uptime fetch failed (%s); %s", repr(e), "using the cached bars" if cache and cache.parsed else "no bars")
        return cache.parsed if cache is not None else None     # stale bars beat no bars
    if cache is not None:
        cache.ids, cache.parsed, cache.fetched_at = ids, parsed, now
    return parsed


def read_status(client: httpx.Client, now: datetime, uptime_cache: UptimeCache | None = None) -> StatusData:
    r = client.get(SUMMARY_URL, timeout=15)
    r.raise_for_status()
    summary = r.json()
    release = None
    try:
        rr = client.get(RELEASE_URL, timeout=15, headers={"Accept": "application/vnd.github+json"})
        if rr.status_code == 200:
            release = rr.json()
    except httpx.HTTPError:
        release = None
    ids = tuple(c["id"] for _, c in _match(summary) if c.get("id"))
    uptime = _uptime(client, ids, now, uptime_cache) if ids else None
    return parse_summary(summary, release, now, uptime)

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from note4_claude.models import ComponentStatus, StatusData, Usage
from note4_claude.parser import parse
from note4_claude.readers.status_reader import COMPONENTS
from note4_claude.render.screens import render_login
from note4_claude.render.status_page import render_status
from note4_claude.render.usage_page import render_usage

# The fixture is a snapshot from Tue 2026-09-29 around 10:04 AM Eastern; its "Resets ..."
# lines only validate against a clock near that moment, so previews use this fixed clock.
SAMPLE_NOW = datetime(2026, 9, 29, 10, 4, tzinfo=ZoneInfo("America/New_York"))

_DATA = Path(__file__).parent / "sample_data" / "modal_max20x.txt"


def sample_text() -> str:
    return _DATA.read_text()


def sample_usage(now: datetime) -> Usage:
    return parse(sample_text(), now)


_LABELS = tuple(label for _, label in COMPONENTS)     # the same five, in the site's order
_UPTIME = (99.42, 99.95, 99.52, 99.44, 99.44)


def _sample_days(shift: int) -> tuple[int, ...]:
    """A fixed, realistic-looking 90 days: mostly normal, some partial (1) and a few major (2) outage days."""
    days = [0] * 90
    for k in (3, 4, 9, 17, 18, 30, 41, 55, 63, 64, 77):
        days[(k + shift) % 90] = 1
    for k in (12, 47, 70):
        days[(k + shift) % 90] = 2
    return tuple(days)


def sample_status(*, degraded: bool = False, bars: bool = True) -> StatusData:
    comps = tuple(
        ComponentStatus(
            label,
            1 if degraded and label in ("API", "Claude Code") else 0,
            _UPTIME[k] if bars else None,
            _sample_days(k * 5) if bars else (),
        )
        for k, label in enumerate(_LABELS)
    )
    common = dict(components=comps, release_tag="v0.0.0", release_age_days=2)
    if not degraded:
        return StatusData(headline="ALL SYSTEMS OK", ok=True, **common)
    return StatusData(
        headline="PARTIALLY DEGRADED SERVICE",
        ok=False,
        incident="Elevated errors on claude.ai, Claude Code, Claude Cowork and the Claude API",
        incident_status="monitoring",
        incident_since=SAMPLE_NOW.replace(hour=10, minute=21),
        **common,
    )


def sample_pngs(now: datetime = SAMPLE_NOW) -> dict[str, bytes]:
    """The sample usage, status and login pages as PNGs (used by `preview` and the dev server)."""
    return {
        "usage": render_usage(sample_usage(now), now=now),
        "status": render_status(sample_status(), now=now),
        "status_degraded": render_status(sample_status(degraded=True), now=now),
        "login": render_login(now=now),
    }

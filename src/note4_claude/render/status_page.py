from __future__ import annotations

from datetime import datetime

from note4_claude.models import StatusData
from note4_claude.render.canvas import (
    draw_header,
    draw_text,
    fit_text,
    format_clock,
    new_canvas,
    text_width,
    to_png,
    wrap_text,
)
from note4_claude.render.layout import H, HEADER_H, W

STRIP_X0 = 20      # left edge of the 90-day strip
BAR_PITCH = 4      # 3 px bar + 1 px gap per day
BAR_W = 3
BAR_H = 14
DAYS = 90
ROWS_END = 254     # component rows must end above this (the axis labels sit at AXIS_LABEL_Y)
AXIS_LABEL_Y = 256  # centred between the last strip baseline (~246) and the release rule (266)
PLAIN_STEP = 30    # row spacing when there is no uptime data to draw


def _has_bars(status: StatusData) -> bool:
    return any(c.days for c in status.components)


def _band_bottom(status: StatusData) -> int | None:
    """Bottom edge of the inverted alert band, or None when everything is fine."""
    if status.ok:
        return None
    return 76 if status.incident else 48


def row_geometry(i: int, status: StatusData) -> tuple[int, int]:
    """(top y of row i, baseline y of its strip)."""
    bottom = _band_bottom(status)
    y0 = 66 if bottom is None else bottom + 4
    n = max(1, len(status.components))
    step = min(38, (ROWS_END - y0) // n) if _has_bars(status) else PLAIN_STEP
    y = y0 + i * step
    return y, y + 30


def _badge(d, right: int, y: int, label: str) -> int:
    """An inverted label ending at x=right; returns its left edge."""
    wpx = int(text_width(label, 9, True)) + 8
    d.rectangle((right - wpx, y - 2, right, y + 14), fill=0)
    draw_text(d, (right - wpx + 4, y + 6), label, 9, bold=True, fill=1, anchor="lm")
    return right - wpx


def _draw_strip(d, days: list[int], base: int) -> None:
    """Same-height bars, oldest left: solid = normal day, striped = partial outage, gap = major outage."""
    top = base - BAR_H + 1
    for k, tier in enumerate(days):
        x = STRIP_X0 + k * BAR_PITCH
        if tier == 0:
            d.rectangle((x, top, x + BAR_W - 1, base), fill=0)
        elif tier == 1:
            for yy in range(top, base + 1, 2):
                d.line((x, yy, x + BAR_W - 1, yy), fill=0)
    d.line((STRIP_X0, base + 2, STRIP_X0 + len(days) * BAR_PITCH - 2, base + 2), fill=0)


def _draw_band(d, status: StatusData, now: datetime) -> None:
    bottom = _band_bottom(status)
    d.rectangle((0, HEADER_H, W, bottom), fill=0)
    txt, size = fit_text(status.headline, W - 20, 18, 12, bold=True)
    draw_text(d, (10, 35), txt, size, bold=True, fill=1, anchor="lm")
    if not status.incident:
        return
    for k, line in enumerate(wrap_text(status.incident, W - 20, 9, max_lines=2, bold=True)):
        draw_text(d, (10, 48 + k * 10), line, 9, bold=True, fill=1, anchor="lm")
    meta = []
    if status.incident_status:
        meta.append(status.incident_status.lower())
    if status.incident_since is not None:
        meta.append(f"since {format_clock(status.incident_since.astimezone(now.tzinfo))}")
    if meta:
        draw_text(d, (10, 69), "  -  ".join(meta), 8, fill=1, anchor="lm")


def render_status(status: StatusData, *, now: datetime, show_clock: bool = True) -> bytes:
    im, d = new_canvas()
    draw_header(d, "ANTHROPIC STATUS", updated=now if show_clock else None)

    if status.ok:
        txt, size = fit_text(status.headline, W - 20, 18, 12, bold=True)
        draw_text(d, (10, 38), txt, size, bold=True, anchor="lm")
    else:
        _draw_band(d, status, now)

    bars = _has_bars(status)
    for i, c in enumerate(status.components):
        y, base = row_geometry(i, status)
        draw_text(d, (10, y + 6), c.label, 11, bold=True, anchor="lm")
        right = W - 10
        if c.uptime_90 is not None:
            up = f"{c.uptime_90:.2f}%"
            width = text_width(up, 11, True)
            draw_text(d, (right - width, y + 6), up, 11, bold=True, anchor="lm")
            right -= int(width) + 10
        elif c.operational:
            width = text_width("OK", 11, True)
            draw_text(d, (right - width, y + 6), "OK", 11, bold=True, anchor="lm")
        if not c.operational:
            _badge(d, right, y, "DEGRADED" if c.severity == 1 else "OUTAGE")
        if bars and c.days:
            days = list(c.days[-DAYS:])
            if c.severity:                       # a live problem shows up in today's bar straight away
                days[-1] = max(days[-1], c.severity)
            _draw_strip(d, days, base)

    if bars:
        draw_text(d, (STRIP_X0, AXIS_LABEL_Y), "90 days ago", 8, anchor="lm")
        draw_text(d, (W - 20 - text_width("today", 8), AXIS_LABEL_Y), "today", 8, anchor="lm")

    # release line
    d.line((0, H - 34, W, H - 34), fill=0, width=2)
    if status.release_tag:
        age = "" if status.release_age_days is None else f" - {status.release_age_days}d ago"
        line = f"LATEST CLAUDE CODE  {status.release_tag}{age}"
    else:
        line = "LATEST CLAUDE CODE  unknown"
    txt, size = fit_text(line, W - 20, 11, 8, bold=True)
    draw_text(d, (10, H - 17), txt, size, bold=True, anchor="lm")
    return to_png(im)

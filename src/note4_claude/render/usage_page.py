from __future__ import annotations

import math
from datetime import datetime, timedelta

from note4_claude.models import LimitReset, Usage, Window, WindowKind
from note4_claude.render.canvas import (
    badge,
    draw_header,
    draw_text,
    fit_text,
    format_clock,
    hatch_rect,
    new_canvas,
    text_width,
    to_png,
)
from note4_claude.render.layout import (
    H,
    HEADER_H,
    MAIN_W,
    MAX_ROWS,
    ROWS_TOP,
    TOP,
    W,
    bar_box,
    row_box,
)

SHORT_PRODUCT = {"Claude Code": "Code", "Claude Duet": "Duet", "Chats": "Chat"}
HATCH_AT = 80
RESET_SOON = timedelta(days=7)   # a reset this close to expiring is drawn inverted
MAX_RESET_COLUMNS = 3            # reset types that fit side by side


def select_windows(windows) -> list[Window]:
    primary = [w for w in windows if w.kind != WindowKind.MODEL_WEEK]
    primary.sort(key=lambda w: 0 if w.kind == WindowKind.SESSION_5H else 1)
    models = sorted((w for w in windows if w.kind == WindowKind.MODEL_WEEK), key=lambda w: -w.pct)
    return (primary + models)[:MAX_ROWS]


def caption_for(w: Window, now: datetime, compact: bool = False) -> str:
    """When the window resets. Compact ("Fri 3AM") leaves room for a reset tag beside it."""
    t = w.resets_at
    if t is None:
        return "idle" if compact else "no active window"
    when = format_clock(t, short=compact)
    if t.date() != now.date():
        when = f"{t:%a} {when}"
    return when if compact else f"resets {when}"


def _expiry(at: datetime | None, now: datetime) -> tuple[str, bool]:
    """Short expiry text, and whether it is close enough to flag."""
    if at is None:
        return "", False
    if at.date() == now.date():
        return "exp today", True
    if at - now <= RESET_SOON:
        return f"exp {at.strftime('%a')}", True
    year = "" if at.year == now.year else f" '{at.strftime('%y')}"
    return f"exp {at.strftime('%b')} {at.day}{year}", False


def _by_expiry(resets) -> list[LimitReset]:
    return sorted(resets, key=lambda r: r.expires_at.timestamp() if r.expires_at else math.inf)


def reset_columns(resets, now: datetime) -> list[tuple[str, str, str, bool]]:
    """One (count, name, expiry, soon) column per reset type, soonest expiry first, as many as fit."""
    return [
        (str(r.count), r.kind.upper(), *_expiry(r.expires_at, now)) for r in _by_expiry(resets)[:MAX_RESET_COLUMNS]
    ]


def reset_tag(w: Window, resets, now: datetime) -> str | None:
    """The tag for a gauge when there is no free row: how many resets refill it, and the soonest expiry."""
    mine = _by_expiry(r for r in resets if r.refills == w.label)
    if not mine:
        return None
    n = sum(r.count for r in mine)
    exp, _ = _expiry(mine[0].expires_at, now)
    return f"{n} reset{'' if n == 1 else 's'}" + (f" - {exp}" if exp else "")


def _name_for(w: Window) -> str:
    if w.kind == WindowKind.SESSION_5H:
        return "5-HOUR"
    if w.kind == WindowKind.WEEK:
        return "7-DAY"
    return f"{w.label.upper()} 7D"


def _money(v: float) -> str:
    return f"${v:,.0f}" if v >= 10 else f"${v:.2f}"


def side_lines(u: Usage) -> list[tuple[str, int, bool]]:
    out: list[tuple[str, int, bool]] = []
    m = u.money
    if m.usage_credits_usd is not None:
        out += [("CREDITS", 9, True), (_money(m.usage_credits_usd), 16, True)]
    if m.cloud_credit_usd is not None:
        out += [("CLOUD CREDIT", 9, True), (_money(m.cloud_credit_usd), 16, True)]
    if m.month_spend_usd is not None:
        out += [("MONTH SPEND", 9, True), (_money(m.month_spend_usd), 16, True)]
        if m.month_cap_usd is not None:
            out.append((f"of {_money(m.month_cap_usd)} cap", 9, False))
    if u.product_split:
        out.append(("BY PRODUCT", 9, True))
        top = sorted(u.product_split.items(), key=lambda kv: -kv[1])[:3]
        out += [(f"{SHORT_PRODUCT.get(n, n)} {p}%", 9, False) for n, p in top]
    return out


def _draw_figure(d, cy: int, big: str, name: str, inverted: bool = False) -> None:
    """A row's left block: a big figure (inverted when high) with a small bold name under it."""
    if inverted:
        right = max(78, 10 + int(text_width(big, 28, True)) + 6)
        d.rectangle((6, cy - 22, right, cy + 8), fill=0)
    draw_text(d, (10, cy - 7), big, 28, bold=True, fill=int(inverted), anchor="lm")
    name, size = fit_text(name, 78, 10, 8, bold=True)
    draw_text(d, (10, cy + 18), name, size, bold=True, anchor="lm")


def _draw_row(im, d, w: Window, i: int, n: int, now: datetime, tag: str | None = None) -> None:
    _, y0, _, y1 = row_box(i, n)
    bx0, by0, bx1, by1 = bar_box(i, n)
    cy = (by0 + by1) // 2

    _draw_figure(d, cy, f"{w.pct}%", _name_for(w), inverted=w.pct >= HATCH_AT)

    # bar
    d.rectangle((bx0, by0, bx1, by1), outline=0, width=3)
    inner_w = bx1 - bx0 - 6
    fill_w = round(inner_w * w.pct / 100)
    if fill_w > 0:
        box = (bx0 + 3, by0 + 3, bx0 + 3 + fill_w - 1, by1 - 3)
        if w.pct >= HATCH_AT:
            hatch_rect(im, box)
        else:
            d.rectangle(box, fill=0)
    for frac in (0.25, 0.5, 0.75):
        x = bx0 + 3 + round(inner_w * frac)
        d.line((x, by0 - 4, x, by0 - 1), fill=0)
        d.line((x, by1 + 1, x, by1 + 4), fill=0)
    if w.elapsed_fraction is not None:
        mx = bx0 + 3 + round(inner_w * w.elapsed_fraction)
        d.polygon([(mx - 5, by0 - 12), (mx + 5, by0 - 12), (mx, by0 - 5)], fill=0)

    cap_w = bx1 - bx0
    if tag:
        tag, tsize = fit_text(tag, cap_w * 2 // 3, 10, 8, bold=True)
        cap_w = badge(d, bx1, by1 + 4, tag, tsize) - bx0 - 6
    cap, csize = fit_text(caption_for(w, now, compact=bool(tag)), cap_w, 10, 8)
    draw_text(d, (bx0, by1 + 10), cap, csize, anchor="lm")
    if i < n - 1:
        d.line((0, y1 - 1, MAIN_W, y1 - 1), fill=0)


def _draw_resets_row(d, resets, i: int, n: int, now: datetime) -> None:
    _, y0, _, y1 = row_box(i, n)
    bx0, by0, bx1, by1 = bar_box(i, n)
    total = sum(r.count for r in resets)
    _draw_figure(d, (by0 + by1) // 2, str(total), "RESET" if total == 1 else "RESETS")
    # The breakdown: each type's count, name and expiry stacked in a column of its own, inverted when expiring soon.
    cols = reset_columns(resets, now)
    cy, col_w = (y0 + y1) // 2, (bx1 - bx0) // len(cols)
    for k, (count, name, exp, soon) in enumerate(cols):
        x, fill = bx0 + k * col_w, int(soon)
        if soon:
            d.rectangle((x - 4, cy - 30, x + col_w - 8, cy + 30), fill=0)
        draw_text(d, (x, cy - 15), count, 22, bold=True, fill=fill, anchor="lm")
        name, size = fit_text(name, col_w - 12, 12, 8, bold=True)
        draw_text(d, (x, cy + 6), name, size, bold=True, fill=fill, anchor="lm")
        if text_width(exp, 9) > col_w - 12:  # a narrow column keeps the whole date by dropping "exp "
            exp = exp.removeprefix("exp ")
        exp, size = fit_text(exp, col_w - 12, 10, 8)
        draw_text(d, (x, cy + 22), exp, size, fill=fill, anchor="lm")


def render_usage(
    usage: Usage,
    *,
    now: datetime,
    stale_since: datetime | None = None,
    incident: str | None = None,
    show_clock: bool = True,
) -> bytes:
    im, d = new_canvas()

    plan = usage.plan.replace("(", "").replace(")", "").upper()
    draw_header(
        d, f"CLAUDE - {plan}",
        updated=usage.captured_at if show_clock else None, stale_since=stale_since,
    )

    # pace strip (incident takes over the strip)
    strip_y = HEADER_H + (TOP - HEADER_H) // 2
    if incident:
        d.rectangle((0, HEADER_H, W, TOP - 1), fill=0)
        txt, size = fit_text(f"! {incident}", W - 20, 11, 8, bold=True)
        draw_text(d, (10, strip_y), txt, size, bold=True, fill=1, anchor="lm")
    elif usage.pace_headline:
        txt, size = fit_text(usage.pace_headline, W - 20, 11, 8, bold=True)
        draw_text(d, (10, strip_y), txt, size, bold=True, anchor="lm")
    d.line((0, TOP - 1, W, TOP - 1), fill=0)

    # gauges, then limit resets: a row of their own when the plan leaves one free, else a tag on each gauge
    rows = select_windows(usage.windows)
    resets_row = bool(usage.resets) and len(rows) < MAX_ROWS
    n = len(rows) + resets_row
    for i, w in enumerate(rows):
        _draw_row(im, d, w, i, n, now, None if resets_row else reset_tag(w, usage.resets, now))
    if resets_row:
        _draw_resets_row(d, usage.resets, len(rows), n, now)

    # right column
    d.line((MAIN_W, TOP, MAIN_W, H), fill=0, width=2)
    y = ROWS_TOP + 8
    for txt, size, bold in side_lines(usage):
        txt, size = fit_text(txt, 76, size, 8, bold)
        draw_text(d, (MAIN_W + 8, y), txt, size, bold=bold)
        y += size + 4 + (4 if size >= 16 else 0)

    return to_png(im)

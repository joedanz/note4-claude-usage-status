from __future__ import annotations

from datetime import datetime

from note4_claude.models import Usage, Window, WindowKind
from note4_claude.render.canvas import (
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

SHORT_PRODUCT = {"Claude Code": "Code", "Chats": "Chat"}
HATCH_AT = 80


def select_windows(windows) -> list[Window]:
    primary = [w for w in windows if w.kind != WindowKind.MODEL_WEEK]
    primary.sort(key=lambda w: 0 if w.kind == WindowKind.SESSION_5H else 1)
    models = sorted((w for w in windows if w.kind == WindowKind.MODEL_WEEK), key=lambda w: -w.pct)
    return (primary + models)[:MAX_ROWS]


def caption_for(w: Window, now: datetime) -> str:
    if w.resets_at is None:
        return "no active window"
    if w.resets_at.date() == now.date():
        return f"resets {format_clock(w.resets_at)}"
    return f"resets {w.resets_at.strftime('%a')} {format_clock(w.resets_at)}"


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


def _draw_row(im, d, w: Window, i: int, n: int, now: datetime) -> None:
    _, y0, _, y1 = row_box(i, n)
    bx0, by0, bx1, by1 = bar_box(i, n)
    cy = (by0 + by1) // 2

    # percent (inverted badge when high)
    pct_txt = f"{w.pct}%"
    if w.pct >= HATCH_AT:
        badge_right = max(78, 10 + int(text_width(pct_txt, 28, True)) + 6)
        d.rectangle((6, cy - 22, badge_right, cy + 8), fill=0)
        draw_text(d, (10, cy - 7), pct_txt, 28, bold=True, fill=1, anchor="lm")
    else:
        draw_text(d, (10, cy - 7), pct_txt, 28, bold=True, anchor="lm")
    name, nsize = fit_text(_name_for(w), 78, 10, 8, bold=True)
    draw_text(d, (10, cy + 18), name, nsize, bold=True, anchor="lm")

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

    cap, csize = fit_text(caption_for(w, now), bx1 - bx0, 10, 8)
    draw_text(d, (bx0, by1 + 10), cap, csize, anchor="lm")
    if i < n - 1:
        d.line((0, y1 - 1, MAIN_W, y1 - 1), fill=0)


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

    # gauges
    rows = select_windows(usage.windows)
    for i, w in enumerate(rows):
        _draw_row(im, d, w, i, len(rows), now)

    # right column
    d.line((MAIN_W, TOP, MAIN_W, H), fill=0, width=2)
    y = ROWS_TOP + 8
    for txt, size, bold in side_lines(usage):
        txt, size = fit_text(txt, 76, size, 8, bold)
        draw_text(d, (MAIN_W + 8, y), txt, size, bold=bold)
        y += size + 4 + (4 if size >= 16 else 0)

    return to_png(im)

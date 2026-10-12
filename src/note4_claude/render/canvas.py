from __future__ import annotations

import io
from datetime import datetime
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from note4_claude.render.layout import H, HEADER_H, W


@lru_cache(maxsize=None)
def font(size: int) -> ImageFont.FreeTypeFont:
    # Pillow >= 10.1 bundles a scalable font, so no font file ships in the repo.
    return ImageFont.load_default(size=size)


def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    return im, d


def _gap(size: int) -> int:
    """Pixels between words. Hinted spaces are 1-2 px at small sizes, which e-ink's soft edges
    swallow ("Atthis pace"), so words are placed with an explicit, wider gap."""
    return max(5, round(size * 0.5))


def _layout(s: str, size: int) -> tuple[list[tuple[str, float]], float]:
    """Each word with its x offset, plus the total width. The one layout that measuring and drawing share."""
    f, gap = font(size), _gap(size)
    x, placed = 0.0, []
    for word in s.split(" "):
        placed.append((word, x))
        x += f.getlength(word, mode="1") + gap  # mode="1": hinted advances, matching the 1-bit canvas
    return placed, x - gap


def text_width(s: str, size: int, bold: bool = False) -> float:
    return _layout(s, size)[1] + (1 if bold else 0)


def draw_text(d, xy, s, size, bold=False, fill=0, anchor="la") -> None:
    f = font(size)
    x0, y = xy
    placed, total = _layout(s, size)
    h = anchor[0]
    start = x0 - total if h == "r" else x0 - total / 2 if h == "m" else x0
    word_anchor = "l" + anchor[1]
    for word, dx in placed:
        if word:
            d.text((round(start + dx), y), word, font=f, fill=fill, anchor=word_anchor)
            if bold:
                d.text((round(start + dx) + 1, y), word, font=f, fill=fill, anchor=word_anchor)


def format_clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def draw_header(d, title: str, *, updated: datetime | None = None, stale_since: datetime | None = None) -> None:
    """The title bar every page shares: title left, "updated HH:MM" (or an inverted STALE badge) right."""
    draw_text(d, (10, HEADER_H // 2), title, 10, bold=True, anchor="lm")
    if stale_since is not None:
        label = f"STALE {format_clock(stale_since)}"
        wpx = int(text_width(label, 10, True)) + 12
        d.rectangle((W - wpx - 4, 2, W - 4, HEADER_H - 4), fill=0)
        draw_text(d, (W - wpx + 2, HEADER_H // 2 - 1), label, 10, bold=True, fill=1, anchor="lm")
    elif updated is not None:
        label = f"updated {format_clock(updated)}"
        draw_text(d, (W - 10 - text_width(label, 10), HEADER_H // 2), label, 10, anchor="lm")
    d.line((0, HEADER_H - 1, W, HEADER_H - 1), fill=0, width=2)


def fit_text(s: str, max_w: float, size_max: int, size_min: int = 8, bold: bool = False):
    for size in range(size_max, size_min - 1, -1):
        if text_width(s, size, bold) <= max_w:
            return s, size
    size = size_min
    while len(s) > 1 and text_width(s.rstrip() + "...", size, bold) > max_w:
        s = s[:-1]
    return s.rstrip() + "...", size


def wrap_text(s: str, max_w: float, size: int, max_lines: int = 2, bold: bool = False) -> list[str]:
    """Greedy word wrap into at most `max_lines` lines that fit `max_w`; overflow is ellipsized on the last line."""
    lines: list[str] = []
    cur = ""
    for word in s.split():
        trial = f"{cur} {word}" if cur else word
        if cur and text_width(trial, size, bold) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return [fit_text(line, max_w, size, size, bold)[0] for line in lines] or [""]


def hatch_rect(im: Image.Image, box, gap: int = 4) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0 + 1, y1 - y0 + 1
    tile = Image.new("1", (w, h), 1)
    td = ImageDraw.Draw(tile)
    for k in range(-h, w, gap):
        td.line([(k, h), (k + h, 0)], fill=0, width=2)
    im.paste(tile, (x0, y0))


def to_png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()

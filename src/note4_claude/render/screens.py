from __future__ import annotations

from datetime import datetime

from note4_claude.render.canvas import draw_header, draw_text, new_canvas, to_png
from note4_claude.render.layout import W


def render_login(*, now: datetime, show_clock: bool = True) -> bytes:
    im, d = new_canvas()
    draw_header(d, "CLAUDE USAGE", updated=now if show_clock else None)
    d.rectangle((20, 70, W - 20, 150), fill=0)
    draw_text(d, (W // 2, 96), "LOG IN AGAIN", 30, bold=True, fill=1, anchor="mm")
    draw_text(d, (W // 2, 132), "claude.ai session expired", 12, fill=1, anchor="mm")
    draw_text(d, (W // 2, 190), "On your Mac, run:", 12, anchor="mm")
    draw_text(d, (W // 2, 214), "note4-claude login", 18, bold=True, anchor="mm")
    return to_png(im)

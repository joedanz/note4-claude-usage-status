import dataclasses
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

from claude_eink.sample import SAMPLE_NOW
from claude_eink.models import Window, WindowKind
from claude_eink.render.layout import H, W, bar_box
from claude_eink.render.usage_page import caption_for, render_usage, select_windows
from claude_eink.sample import sample_usage

NY = ZoneInfo("America/New_York")
NOW = SAMPLE_NOW


def img(png):
    return Image.open(io.BytesIO(png))


def with_pct(u, idx, pct):
    ws = list(u.windows)
    ws[idx] = dataclasses.replace(ws[idx], pct=pct)
    return dataclasses.replace(u, windows=tuple(ws))


def test_size_and_mode():
    im = img(render_usage(sample_usage(NOW), now=NOW))
    assert im.size == (W, H)
    assert im.mode == "1"


def test_solid_fill_is_proportional():
    u = with_pct(sample_usage(NOW), 1, 50)  # weekly at 50%
    im = img(render_usage(u, now=NOW))
    x0, y0, x1, y1 = bar_box(1, 3)
    cy = (y0 + y1) // 2
    assert im.getpixel((x0 + 8, cy)) == 0        # inside the filled half
    assert im.getpixel((x1 - 8, cy)) == 255      # inside the empty half


def test_high_usage_uses_hatch_not_solid():
    im = img(render_usage(sample_usage(NOW), now=NOW))  # weekly at 90%
    x0, y0, x1, y1 = bar_box(1, 3)
    cy = (y0 + y1) // 2
    row = [im.getpixel((x, cy)) for x in range(x0 + 6, x0 + 80)]
    assert 0 in row and 255 in row


def test_stale_badge_and_incident_change_the_image():
    u = sample_usage(NOW)
    base = render_usage(u, now=NOW)
    assert render_usage(u, now=NOW, stale_since=NOW) != base
    assert render_usage(u, now=NOW, incident="Elevated errors on Claude Code") != base


def test_clock_can_be_hidden_for_change_detection():
    u = sample_usage(NOW)
    later = dataclasses.replace(u, captured_at=datetime(2026, 9, 29, 10, 9, tzinfo=NY))
    assert render_usage(u, now=NOW, show_clock=False) == render_usage(later, now=NOW, show_clock=False)
    assert render_usage(u, now=NOW) != render_usage(later, now=NOW)


# Review Focus 2: more than three windows
def test_more_than_three_windows_keeps_session_week_and_highest_model():
    def w(label, kind, pct):
        return Window(label, kind, pct, None, None)

    ws = (
        w("Opus", WindowKind.MODEL_WEEK, 10),
        w("Weekly", WindowKind.WEEK, 90),
        w("Fable", WindowKind.MODEL_WEEK, 60),
        w("5-hour", WindowKind.SESSION_5H, 3),
    )
    chosen = select_windows(ws)
    assert [x.label for x in chosen] == ["5-hour", "Weekly", "Fable"]


def test_two_windows_render_without_error():
    u = sample_usage(NOW)
    u = dataclasses.replace(u, windows=u.windows[:2])
    assert img(render_usage(u, now=NOW)).size == (W, H)


# Review Focus 1: idle session caption
def test_caption_for_idle_and_active_windows():
    idle = Window("5-hour", WindowKind.SESSION_5H, 0, None, None)
    assert caption_for(idle, NOW) == "no active window"
    today = Window("5-hour", WindowKind.SESSION_5H, 3, datetime(2026, 9, 29, 12, 0, tzinfo=NY), 0.6)
    assert caption_for(today, NOW) == "resets 12:00 PM"
    fri = Window("Weekly", WindowKind.WEEK, 90, datetime(2026, 10, 2, 3, 0, tzinfo=NY), 0.6)
    assert caption_for(fri, NOW) == "resets Fri 3:00 AM"


# Review Focus 3: absurdly long strings must not crash or change the canvas size
def test_long_headline_and_model_name_render():
    u = sample_usage(NOW)
    ws = list(u.windows)
    ws[2] = dataclasses.replace(ws[2], label="An Extremely Long Model Name " * 4)
    u = dataclasses.replace(u, windows=tuple(ws), pace_headline="Heads up. " * 40)
    assert img(render_usage(u, now=NOW)).size == (W, H)


def test_golden_usage(golden):
    golden("usage_q.png", render_usage(sample_usage(NOW), now=NOW))


def test_hundred_percent_badge_is_wide_enough_for_the_text():
    # The inverted badge must extend past the 3-digit "100%" so the % is not white-on-white.
    u = with_pct(sample_usage(NOW), 1, 100)
    im = img(render_usage(u, now=NOW))
    x0, y0, x1, y1 = bar_box(1, 3)
    cy = (y0 + y1) // 2
    assert im.getpixel((80, cy - 20)) == 0   # badge still black beyond the old 78px edge

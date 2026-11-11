import dataclasses
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

from note4_claude.models import LimitReset, Window, WindowKind
from note4_claude.render.layout import H, W, bar_box, row_box
from note4_claude.render.usage_page import (
    caption_for,
    render_usage,
    reset_columns,
    reset_tag,
    select_windows,
    side_lines,
)
from note4_claude.sample import SAMPLE_NOW, ULTRA_NOW, sample_usage, ultra_usage

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


def test_side_panel_shortens_long_product_names_so_the_percent_fits():
    u = dataclasses.replace(sample_usage(SAMPLE_NOW), product_split={"Claude Code": 93, "Claude Duet": 6, "Chats": 1})
    assert ("Duet 6%", 9, False) in side_lines(u)


# --- Limit resets ---------------------------------------------------------------------------------

def ink(png, box):
    return img(png).crop(box).histogram()[0]   # black pixels


def test_reset_columns_list_the_soonest_expiry_first():
    assert reset_columns(ultra_usage().resets, ULTRA_NOW) == [
        ("1", "WEEKLY", "Dec 15", False),
        ("3", "FABLE", "Mar 9 '27", False),
    ]


def test_only_as_many_reset_columns_as_fit():
    four = tuple(LimitReset(k, 1, datetime(2026, 12, d, 23, 59, tzinfo=NY)) for d, k in enumerate("ABCD", start=1))
    assert [name for _, name, _, _ in reset_columns(four, ULTRA_NOW)] == ["A", "B", "C"]


def test_reset_expiring_within_a_week_shows_its_weekday_and_is_marked():
    thu = LimitReset("Weekly", 1, datetime(2026, 11, 12, 23, 59, tzinfo=NY))
    today = LimitReset("Weekly", 1, datetime(2026, 11, 9, 23, 59, tzinfo=NY))
    undated = LimitReset("Weekly", 1, None)
    assert reset_columns((thu,), ULTRA_NOW) == [("1", "WEEKLY", "Thu", True)]
    assert reset_columns((today,), ULTRA_NOW) == [("1", "WEEKLY", "today", True)]
    assert reset_columns((undated,), ULTRA_NOW) == [("1", "WEEKLY", "", False)]


def test_resets_fill_the_row_a_plan_leaves_free():
    u = ultra_usage()
    x0, y0, _, y1 = bar_box(1, 3)
    edge = (x0, (y0 + y1) // 2)                      # left edge of the Fable bar in a three-row layout
    with_resets = render_usage(u, now=ULTRA_NOW)
    assert img(with_resets).getpixel(edge) == 0       # Fable moved up to make room...
    _, ry0, _, ry1 = row_box(2, 3)
    assert ink(with_resets, (x0, ry0, W, ry1)) > 300  # ...for the resets row
    without = render_usage(dataclasses.replace(u, resets=()), now=ULTRA_NOW)
    assert img(without).getpixel(edge) == 255         # no resets: the two gauges keep half the page each


def test_a_reset_about_to_expire_is_drawn_inverted():
    u = ultra_usage()
    soon = dataclasses.replace(u, resets=(LimitReset("Weekly", 1, datetime(2026, 11, 12, 23, 59, tzinfo=NY)),))
    later = dataclasses.replace(u, resets=(LimitReset("Weekly", 1, datetime(2026, 12, 15, 23, 59, tzinfo=NY)),))
    free_row = row_box(2, 3)
    assert ink(render_usage(soon, now=ULTRA_NOW), free_row) > ink(render_usage(later, now=ULTRA_NOW), free_row) + 1500


def test_without_a_free_row_each_reset_tags_the_gauge_it_refills():
    u = dataclasses.replace(sample_usage(NOW), resets=ultra_usage().resets)
    rows = select_windows(u.windows)
    assert [reset_tag(w, u.resets, NOW) for w in rows] == [
        None,                                  # 5-hour: no reset type of its own
        "1 reset - exp Dec 15",                # Weekly
        "3 resets - exp Mar 9 '27",            # Fable
    ]


def test_compact_caption_leaves_room_for_a_tag():
    fri = Window("Weekly", WindowKind.WEEK, 90, datetime(2026, 10, 2, 3, 0, tzinfo=NY), 0.6)
    noon = Window("5-hour", WindowKind.SESSION_5H, 3, datetime(2026, 9, 29, 12, 30, tzinfo=NY), 0.6)
    assert caption_for(fri, NOW, compact=True) == "Fri 3AM"
    assert caption_for(noon, NOW, compact=True) == "12:30PM"


def test_golden_usage_with_resets(golden):
    golden("usage_ultra.png", render_usage(ultra_usage(), now=ULTRA_NOW))
    tagged = dataclasses.replace(sample_usage(NOW), resets=ultra_usage().resets)
    golden("usage_tags.png", render_usage(tagged, now=NOW))

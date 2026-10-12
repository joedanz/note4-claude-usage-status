import dataclasses
import io

from PIL import Image

from claude_eink.models import ComponentStatus, StatusData
from claude_eink.render.layout import H, W
from claude_eink.render.screens import render_login
from claude_eink.render.status_page import (
    BAR_H, BAR_PITCH, STRIP_X0, render_status, row_geometry,
)
from claude_eink.sample import SAMPLE_NOW as NOW
from claude_eink.sample import sample_status


def img(png):
    return Image.open(io.BytesIO(png))


def only(*components, **kw):
    """A StatusData with just these components, all-clear unless overridden."""
    base = dict(headline="ALL SYSTEMS OK", ok=True, components=tuple(components))
    return StatusData(**{**base, **kw})


def column(im, i, y, base):
    """The pixels of day i's bar (its middle column) from top to bottom."""
    x = STRIP_X0 + i * BAR_PITCH + 1
    return [im.getpixel((x, yy)) for yy in range(base - BAR_H + 1, base + 1)]


def test_size_and_mode():
    im = img(render_status(sample_status(), now=NOW))
    assert im.size == (W, H) and im.mode == "1"


def test_a_normal_day_is_solid_a_partial_day_striped_a_major_day_a_gap():
    days = (0, 1, 2) + (0,) * 87
    st = only(ComponentStatus("API", 0, 99.5, days))
    y, base = row_geometry(0, st)
    im = img(render_status(st, now=NOW))
    solid, striped, gap = column(im, 0, y, base), column(im, 1, y, base), column(im, 2, y, base)
    assert set(solid) == {0}                                     # filled = no issues
    assert set(striped) == {0, 255} and solid != striped         # texture = partial outage
    assert set(gap) == {255}                                     # a hole = major outage


def test_a_currently_degraded_component_shows_a_problem_today():
    days = (0,) * 90
    st = only(ComponentStatus("API", 1, 99.5, days), ComponentStatus("Claude Code", 2, 99.4, days),
              headline="PARTIALLY DEGRADED SERVICE", ok=False)
    im = img(render_status(st, now=NOW))
    for row, expected in ((0, {0, 255}), (1, {255})):
        y, base = row_geometry(row, st)
        assert set(column(im, 89, y, base)) == expected          # today: striped (partial) or gap (major)
        assert set(column(im, 88, y, base)) == {0}               # yesterday untouched


def test_degraded_screen_has_an_inverted_band_and_differs_from_normal():
    normal = render_status(sample_status(), now=NOW)
    degraded = render_status(sample_status(degraded=True), now=NOW)
    assert normal != degraded
    im = img(degraded)
    assert im.getpixel((3, 30)) == 0 and im.getpixel((W - 3, 30)) == 0     # black band edge to edge


def test_layout_gives_five_rows_room_in_every_state():
    for st in (sample_status(), sample_status(degraded=True), sample_status(bars=False),
               sample_status(degraded=True, bars=False)):
        ys = [row_geometry(i, st)[0] for i in range(5)]
        assert ys == sorted(ys) and all(b - a >= 28 for a, b in zip(ys, ys[1:]))
        assert row_geometry(4, st)[1] < 250          # the last strip ends above the axis labels


def test_without_uptime_data_the_page_falls_back_to_a_plain_list():
    with_bars = render_status(sample_status(), now=NOW)
    without = render_status(sample_status(bars=False), now=NOW)
    assert with_bars != without and img(without).size == (W, H)


def test_incident_without_a_title_or_time_still_renders():
    st = dataclasses.replace(sample_status(degraded=True), incident=None, incident_status=None, incident_since=None)
    assert img(render_status(st, now=NOW)).size == (W, H)


def test_very_long_incident_titles_do_not_break_the_layout():
    st = dataclasses.replace(sample_status(degraded=True), incident="Elevated errors " * 30)
    assert img(render_status(st, now=NOW)).size == (W, H)


def test_golden_status_pages(golden):
    golden("status.png", render_status(sample_status(), now=NOW))
    golden("status_degraded.png", render_status(sample_status(degraded=True), now=NOW))
    golden("status_nobars.png", render_status(sample_status(bars=False), now=NOW))
    golden("login.png", render_login(now=NOW))


import pytest
from PIL import Image

from note4_claude.sample import SAMPLE_NOW
from note4_claude.lan import FRAME_BYTES, LanSink, png_to_frame
from note4_claude.render.canvas import to_png
from note4_claude.render.screens import render_login

NOW = SAMPLE_NOW


png_of = to_png


def test_frame_is_15000_bytes_msb_first_with_zero_as_black():
    im = Image.new("1", (400, 300), 1)          # all white
    im.putpixel((0, 0), 0)                       # black at the first pixel
    im.putpixel((399, 299), 0)                   # black at the very last pixel
    frame = png_to_frame(png_of(im))
    assert len(frame) == FRAME_BYTES == 15000
    assert frame[0] == 0b01111111                # leftmost pixel is the top bit, 0 = black
    assert frame[-1] == 0b11111110               # rightmost pixel is the bottom bit
    assert frame[1] == 0xFF                      # untouched pixels are white (1)


def test_real_render_converts():
    frame = png_to_frame(render_login(now=NOW))
    assert len(frame) == 15000 and any(b != 0xFF for b in frame)


def test_wrong_size_or_mode_is_rejected():
    with pytest.raises(ValueError):
        png_to_frame(png_of(Image.new("1", (100, 100), 1)))
    with pytest.raises(ValueError):
        png_to_frame(png_of(Image.new("L", (400, 300), 255)))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def png_with_dot(x: int) -> bytes:
    im = Image.new("1", (400, 300), 1)
    im.putpixel((x, 0), 0)
    return png_of(im)


def test_first_push_stores_a_frame_with_an_etag():
    sink = LanSink(clock=Clock())
    assert sink.push(1, png_with_dot(0), "k1") == "pushed"
    f = sink.get(1)
    assert len(f.data) == 15000 and f.key == "k1" and len(f.etag) == 16


def test_unknown_page_is_none():
    assert LanSink(clock=Clock()).get(7) is None


def test_same_key_is_unchanged_until_the_heartbeat():
    clock = Clock()
    sink = LanSink(heartbeat_s=1800, clock=clock)
    sink.push(1, png_with_dot(0), "k1")
    etag = sink.get(1).etag
    clock.t += 600
    assert sink.push(1, png_with_dot(1), "k1") == "unchanged"     # clock-only change is not shown
    assert sink.get(1).etag == etag
    clock.t += 1300                                               # 1900 s since the store
    assert sink.push(1, png_with_dot(1), "k1") == "pushed"        # heartbeat: fresh frame
    assert sink.get(1).etag != etag


def test_new_key_replaces_the_frame_immediately():
    clock = Clock()
    sink = LanSink(clock=clock)
    sink.push(1, png_with_dot(0), "k1")
    before = sink.get(1).etag
    clock.t += 5
    assert sink.push(1, png_with_dot(2), "k2") == "pushed"
    assert sink.get(1).etag != before


def test_pages_are_independent():
    sink = LanSink(clock=Clock())
    sink.push(1, png_with_dot(0), "a")
    sink.push(2, png_with_dot(1), "b")
    assert sink.get(1).key == "a" and sink.get(2).key == "b"

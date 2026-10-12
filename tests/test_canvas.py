from PIL import ImageChops

from claude_eink.render.canvas import draw_text, fit_text, new_canvas, text_width


def test_short_text_keeps_max_size():
    s, size = fit_text("Run out tonight", 200, 11)
    assert (s, size) == ("Run out tonight", 11)


def test_long_text_shrinks_before_truncating():
    s, size = fit_text("Heads up. At this pace you will run out tonight", 250, 11)
    assert size < 11
    assert not s.endswith("...")
    assert text_width(s, size) <= 250


def test_very_long_text_is_ellipsized_and_fits():
    s, size = fit_text("x" * 300, 200, 11)
    assert s.endswith("...")
    assert text_width(s, size) <= 200


def test_bold_width_is_measured():
    assert text_width("WEEK", 12, bold=True) > text_width("WEEK", 12)


def test_fitted_text_renders_within_its_width():
    # Measuring must match how the 1-bit canvas actually renders (hinted advances).
    im, d = new_canvas()
    s, size = fit_text(
        "Elevated errors on claude.ai, Claude Code, Claude Cowork and the Claude API",
        380, 12, 8, bold=True,
    )
    draw_text(d, (10, 20), s, size, bold=True, anchor="lm")
    right_edge = ImageChops.invert(im.convert("L")).getbbox()[2]
    assert right_edge <= 10 + 380


def _max_blank_run(text, size, bold=False):
    """Widest run of empty columns between the first and last ink of a rendered string."""
    im, d = new_canvas()
    draw_text(d, (10, 20), text, size, bold=bold, anchor="lm")
    cols = [any(im.getpixel((x, y)) == 0 for y in range(40)) for x in range(400)]
    xs = [i for i, c in enumerate(cols) if c]
    gaps, run = [], 0
    for c in cols[xs[0]:xs[-1] + 1]:
        if not c:
            run += 1
        elif run:
            gaps.append(run)
            run = 0
    return max(gaps) if gaps else 0


def test_word_gaps_survive_eink_soft_edges():
    # On the real panel a 1-2 px space disappears ("Atthis", "outtonight"), so words need >= 5 px.
    for size in (9, 10, 11):
        assert _max_blank_run("At this", size) >= 5, size
        assert _max_blank_run("CLAUDE - MAX 20X", size, bold=True) >= 5, size


def test_centered_and_right_anchored_text_keeps_its_anchor():
    for anchor, expect in (("mm", "center"), ("rm", "right")):
        im, d = new_canvas()
        draw_text(d, (200, 20), "log in again", 12, anchor=anchor)
        cols = [i for i in range(400) if any(im.getpixel((i, y)) == 0 for y in range(40))]
        left, right = cols[0], cols[-1]
        if expect == "center":
            assert abs((left + right) / 2 - 200) <= 3
        else:
            assert abs(right - 200) <= 3


from claude_eink.render.canvas import wrap_text


def test_wrap_text_keeps_short_text_on_one_line():
    assert wrap_text("Elevated errors", 300, 9) == ["Elevated errors"]


def test_wrap_text_wraps_to_at_most_two_lines_that_fit():
    title = "Elevated errors on claude.ai, Claude Code, Claude Cowork and the Claude API"
    lines = wrap_text(title, 180, 9, max_lines=2, bold=True)
    assert len(lines) == 2
    assert all(text_width(line, 9, True) <= 180 for line in lines)
    assert lines[0].split()[0] == "Elevated"                       # wrapped at a word boundary


def test_wrap_text_ellipsizes_what_does_not_fit():
    lines = wrap_text("word " * 60, 120, 9, max_lines=2)
    assert len(lines) == 2 and lines[-1].endswith("...")
    assert all(text_width(line, 9) <= 120 for line in lines)


def test_wrap_text_handles_a_single_endless_word():
    lines = wrap_text("x" * 200, 100, 9, max_lines=2)
    assert len(lines) <= 2 and all(text_width(line, 9) <= 100 for line in lines)

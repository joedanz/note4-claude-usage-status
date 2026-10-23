from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from note4_claude.sample import SAMPLE_NOW, sample_text
from note4_claude.models import ParseFailed, WindowKind
from note4_claude.parser import parse

NY = ZoneInfo("America/New_York")
NOW = SAMPLE_NOW
FIXTURE = sample_text()


def by_kind(u, kind, label=None):
    return [w for w in u.windows if w.kind == kind and (label is None or w.label == label)][0]


def test_parses_real_modal():
    u = parse(FIXTURE, NOW)
    assert u.plan == "Max (20x)"
    assert u.pace_headline.startswith("Heads up.")
    s = by_kind(u, WindowKind.SESSION_5H)
    w = by_kind(u, WindowKind.WEEK)
    f = by_kind(u, WindowKind.MODEL_WEEK, "Fable")
    assert (s.pct, w.pct, f.pct) == (3, 90, 0)
    assert s.resets_at == datetime(2026, 9, 29, 12, 0, tzinfo=NY)
    assert w.resets_at == datetime(2026, 10, 2, 3, 0, tzinfo=NY)  # Friday
    assert f.resets_at == w.resets_at
    assert s.elapsed_fraction == pytest.approx(0.613, abs=0.01)
    assert w.elapsed_fraction == pytest.approx(0.6135, abs=0.01)


def test_parses_money_and_split():
    u = parse(FIXTURE, NOW)
    assert u.money.usage_credits_usd == 12.40
    assert u.money.cloud_credit_usd == 250.0
    assert u.money.cloud_credit_expires == "2:59 AM EST, November 5"
    assert u.money.month_spend_usd == 21.75
    assert u.money.month_cap_usd == 50.0
    assert u.product_split == {"Claude Code": 100, "Chats": 0, "Cowork": 0, "Other": 0}
    assert u.captured_at == NOW


FABLE_NEW = "Fable\nUp to 50% of your weekly limit\nResets Friday 3:00 AM\n0% used\n"
FABLE_OLD = "Fable this week\nSeparate weekly limit for Fable · Resets Friday 3:00 AM\n0% used\n"


def test_new_model_weekly_is_picked_up_automatically():
    u = parse(FIXTURE.replace(FABLE_NEW, FABLE_NEW.replace("Fable", "Opus")), NOW)
    assert by_kind(u, WindowKind.MODEL_WEEK, "Opus").pct == 0


def test_older_this_week_model_layout_still_parses():
    u = parse(FIXTURE.replace(FABLE_NEW, FABLE_OLD), NOW)
    f = by_kind(u, WindowKind.MODEL_WEEK, "Fable")
    assert (f.pct, f.resets_at) == (0, by_kind(u, WindowKind.WEEK).resets_at)


def test_collapsed_weekly_toggle_just_has_no_model_limit():
    u = parse(FIXTURE.replace(FABLE_NEW, ""), NOW)
    assert [w.kind for w in u.windows] == [WindowKind.SESSION_5H, WindowKind.WEEK]


def test_weekly_limit_wording_in_the_headline_is_not_a_model_limit():
    # The pace headline also says "of your weekly limit"; the plan line above it is not a model.
    text = FIXTURE.replace(
        "Heads up. At this pace you’ll run out tonight, before Friday’s reset.",
        "Fresh week. 3% of your weekly limit used.",
    )
    u = parse(text, NOW)
    assert u.plan == "Max (20x)"
    assert u.pace_headline == "Fresh week. 3% of your weekly limit used."
    assert [w.label for w in u.windows if w.kind == WindowKind.MODEL_WEEK] == ["Fable"]


def test_missing_optional_sections_still_parse():
    head = FIXTURE.split("Cloud session credits")[0]
    u = parse(head, NOW)
    assert u.money.usage_credits_usd is None
    assert u.product_split == {}
    assert by_kind(u, WindowKind.WEEK).pct == 90


def test_missing_required_window_fails():
    text = FIXTURE.replace("This week\nResets Friday 3:00 AM\n90% used\n", "")
    with pytest.raises(ParseFailed):
        parse(text, NOW)


def test_reworded_label_fails_instead_of_guessing():
    with pytest.raises(ParseFailed):
        parse(FIXTURE.replace("Current session", "Your session"), NOW)


def test_out_of_range_percent_fails():
    with pytest.raises(ParseFailed):
        parse(FIXTURE.replace("90% used", "140% used"), NOW)


def test_reset_beyond_window_length_fails():
    # 5-hour window claiming to reset in 9 hours is not credible
    with pytest.raises(ParseFailed):
        parse(FIXTURE.replace("Resets at 12:00 PM", "Resets at 7:00 PM"), NOW)


def test_no_usage_heading_fails():
    with pytest.raises(ParseFailed):
        parse("Settings\nGeneral\nAccount", NOW)


# Review Focus 1: idle session
def test_idle_session_without_reset_line_is_not_a_failure():
    text = FIXTURE.replace("Current session\nResets at 12:00 PM\n3% used", "Current session\n0% used")
    u = parse(text, NOW)
    s = by_kind(u, WindowKind.SESSION_5H)
    assert s.pct == 0 and s.resets_at is None and s.elapsed_fraction is None


def test_nonzero_session_without_reset_line_fails():
    text = FIXTURE.replace("Current session\nResets at 12:00 PM\n3% used", "Current session\n3% used")
    with pytest.raises(ParseFailed):
        parse(text, NOW)


# Review Focus 5: clock boundaries (session reset moved inside its 5h window for these clocks)
def test_friday_before_reset_resolves_to_same_day():
    text = FIXTURE.replace("Resets at 12:00 PM", "Resets at 5:00 AM")
    now = datetime(2026, 10, 2, 2, 59, tzinfo=NY)  # Friday 2:59 AM
    w = by_kind(parse(text, now), WindowKind.WEEK)
    assert w.resets_at == datetime(2026, 10, 2, 3, 0, tzinfo=NY)


def test_friday_after_reset_resolves_to_next_week():
    text = FIXTURE.replace("Resets at 12:00 PM", "Resets at 5:00 AM")
    now = datetime(2026, 10, 2, 3, 1, tzinfo=NY)
    w = by_kind(parse(text, now), WindowKind.WEEK)
    assert w.resets_at == datetime(2026, 10, 9, 3, 0, tzinfo=NY)


def test_remaining_time_is_real_elapsed_time_across_dst():
    # US clocks fall back at 2:00 AM on Sunday 2026-11-01.
    # Sat 22:00 EDT -> Sun 03:00 EST is 6 real hours, not 5 wall-clock hours.
    text = FIXTURE.replace("Resets Friday 3:00 AM", "Resets Sunday 3:00 AM").replace(
        "Resets at 12:00 PM", "Resets at 1:00 AM"
    )
    now = datetime(2026, 10, 31, 22, 0, tzinfo=NY)
    w = by_kind(parse(text, now), WindowKind.WEEK)
    assert w.elapsed_fraction == pytest.approx(1 - 6 / 168, abs=0.001)

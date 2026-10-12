from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from claude_eink.collector import STALE_AFTER, Collector
from claude_eink.models import ComponentStatus, NotLoggedIn, StatusData, TransientError
from claude_eink.pusher import PushError
from claude_eink.render.screens import render_login
from claude_eink.render.usage_page import render_usage
from claude_eink.state import State
from claude_eink.sample import sample_status, sample_text

NY = ZoneInfo("America/New_York")


class Clock:
    def __init__(self):
        self.t = datetime(2026, 9, 29, 10, 4, tzinfo=NY)

    def __call__(self):
        return self.t


class FakePusher:
    """Mimics the real Pusher's dedupe: an unchanged content key is not pushed again."""

    def __init__(self):
        self.pushes = []
        self.last_key = {}
        self.fail = False

    def push(self, page, png, key):
        if self.fail:
            raise PushError("boom")
        if self.last_key.get(page) == key:
            return "unchanged"
        self.last_key[page] = key
        self.pushes.append((page, png, key))
        return "pushed"


class Script:
    """Reader that yields scripted results: a str is returned, an Exception is raised."""

    def __init__(self, *items):
        self.items = list(items)

    def __call__(self):
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, Exception):
            raise item
        return item


def make(usage_items, status=None, save_debug=None, state=None, clock=None):
    clock, pusher = clock or Clock(), FakePusher()
    status_reader = (lambda: status) if status else (lambda: sample_status())
    c = Collector(Script(*usage_items), status_reader, pusher, clock, save_debug, state)
    return c, pusher, clock


def pages(pusher):
    return [p for p, *_ in pusher.pushes]


def test_good_read_pushes_usage_page():
    c, pusher, _ = make([sample_text()])
    c.tick_usage()
    assert pages(pusher) == [1]


def test_status_tick_pushes_page_two():
    c, pusher, _ = make([sample_text()])
    c.tick_status()
    assert pages(pusher) == [2]


def test_healthy_status_without_bars_is_held_back_twice_then_pushed():
    c, pusher, _ = make([sample_text()], status=sample_status(bars=False))
    c.tick_status()
    c.tick_status()
    assert pages(pusher) == []
    c.tick_status()
    assert pages(pusher) == [2]


def test_bars_returning_resets_the_hold():
    c, pusher, _ = make([sample_text()], status=sample_status(bars=False))
    c.tick_status()
    c.read_status = lambda: sample_status()
    c.tick_status()
    assert pages(pusher) == [2] and c.barless_skips == 0


def test_an_incident_without_bars_is_pushed_immediately():
    c, pusher, _ = make([sample_text()], status=sample_status(degraded=True, bars=False))
    c.tick_status()
    assert pages(pusher) == [2]


def test_transient_error_pushes_nothing_new_and_keeps_last_good():
    c, pusher, _ = make([sample_text(), TransientError("net")])
    c.tick_usage()
    n = len(pusher.pushes)
    c.tick_usage()
    assert len(pusher.pushes) == n
    assert c.last_good is not None


# Review Focus 4: login lost then restored
def test_login_lost_shows_login_screen_then_recovers():
    c, pusher, clock = make([sample_text(), NotLoggedIn("x"), sample_text()])
    c.tick_usage()
    good_key = pusher.pushes[-1][2]
    c.tick_usage()
    page, png, key = pusher.pushes[-1]
    assert page == 1 and key != good_key
    assert png == render_login(now=clock.t)
    c.tick_usage()
    assert pusher.pushes[-1][2] == good_key      # usage restored


def test_transient_error_never_replaces_the_screen_with_login():
    c, pusher, _ = make([sample_text(), TransientError("net")])
    c.tick_usage()
    c.tick_usage()
    assert c.logged_out is False


def test_garbage_text_keeps_last_good_and_never_pushes_garbage():
    c, pusher, _ = make([sample_text(), "totally different page"])
    c.tick_usage()
    n = len(pusher.pushes)
    c.tick_usage()
    assert len(pusher.pushes) == n
    assert c.failures == 1


def test_three_parse_failures_save_debug_once():
    saved = []
    c, pusher, _ = make(["garbage"], save_debug=lambda text: saved.append(text))
    for _ in range(5):
        c.tick_usage()
    assert saved == ["garbage"]      # at the third consecutive failure only


def test_stale_badge_after_fifteen_minutes():
    c, pusher, clock = make([sample_text(), TransientError("net")])
    c.tick_usage()
    fresh_key = pusher.pushes[-1][2]
    clock.t += STALE_AFTER + timedelta(minutes=1)
    c.tick_usage()
    assert pusher.pushes[-1][2] != fresh_key


def test_active_incident_changes_page_one():
    bad = StatusData("MINOR SERVICE OUTAGE", False, (ComponentStatus("API", 1),), incident="Elevated errors")
    c, pusher, _ = make([sample_text()], status=bad)
    c.tick_usage()
    key_before = pusher.pushes[-1][2]
    c.tick_status()
    pages_pushed = pages(pusher)
    assert 1 in pages_pushed[1:] and 2 in pages_pushed
    assert [k for p, _, k in pusher.pushes if p == 1][-1] != key_before


# a degraded component with no published incident must still raise the alert on the usage page
def test_degradation_without_an_incident_still_alerts_on_page_one():
    degraded = StatusData("PARTIALLY DEGRADED SERVICE", False, (ComponentStatus("API", 1),))   # no incident
    c, pusher, _ = make([sample_text()], status=degraded)
    c.tick_usage()
    key_before = pusher.pushes[-1][2]
    c.tick_status()
    assert [k for p, _, k in pusher.pushes if p == 1][-1] != key_before


def test_the_alert_clears_when_service_recovers():
    degraded = StatusData("PARTIALLY DEGRADED SERVICE", False, (ComponentStatus("API", 1),), incident="Elevated errors")
    c, pusher, _ = make([sample_text()], status=degraded)
    c.tick_usage()
    calm_key = pusher.pushes[-1][2]
    c.tick_status()
    assert pusher.pushes[-1][2] != calm_key or [k for p, _, k in pusher.pushes if p == 1][-1] != calm_key
    c.read_status = lambda: sample_status()                 # service recovers
    c.tick_status()
    assert [k for p, _, k in pusher.pushes if p == 1][-1] == calm_key


def test_push_errors_do_not_crash_the_tick():
    c, pusher, _ = make([sample_text()])
    pusher.fail = True
    c.tick_usage()          # must not raise
    c.tick_status()


# Fix: last-good usage survives a restart, so the STALE rule still applies afterwards
def test_restart_restores_last_good_and_stale_rule(tmp_path):
    path = tmp_path / "state.json"
    c1, p1, clock = make([sample_text()], state=State.load(path))
    c1.tick_usage()
    clock.t += STALE_AFTER + timedelta(minutes=5)          # daemon was down / reads failing
    c2, p2, _ = make([TransientError("net")], state=State.load(path), clock=clock)
    assert c2.last_good is not None                         # restored from disk
    c2.tick_usage()
    assert p2.pushes, "a restarted collector must still push the stale screen"
    expected = render_usage(c2.last_good, now=clock.t, stale_since=c2.last_good_at)
    assert p2.pushes[-1][0] == 1 and p2.pushes[-1][1] == expected


def test_corrupt_saved_text_is_ignored_not_fatal(tmp_path):
    st = State.load(tmp_path / "state.json")
    st.last_good_text, st.last_good_at = "garbage", 1000.0
    c, _, _ = make([TransientError("net")], state=st)
    assert c.last_good is None


# Fix: tick results are visible so callers (push-once) can report them
def test_results_report_what_happened_per_page():
    c, pusher, _ = make([sample_text()])
    c.tick_usage()
    assert c.results[1] == "pushed"
    pusher.fail = True
    c.tick_status()
    assert c.results[2].startswith("error")

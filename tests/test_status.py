from datetime import datetime, timedelta, timezone

import httpx
import pytest

from note4_claude.models import ComponentStatus, StatusData
from note4_claude.readers.status_reader import UptimeCache, parse_summary, parse_uptime, read_status
from note4_claude.sample import SAMPLE_NOW as NOW

IDS = {"claude.ai": "id_ai", "Claude Console (platform.claude.com)": "id_con", "Claude API (api.anthropic.com)": "id_api",
       "Claude Code": "id_code", "Claude Cowork": "id_cow"}


def comps(**status):
    """The five site components, each 'operational' unless overridden by id (id_api='degraded_performance')."""
    return [{"id": i, "name": n, "status": status.get(i, "operational")} for n, i in IDS.items()] + [
        {"id": "id_gov", "name": "Claude for Government", "status": "operational"}
    ]


OK_SUMMARY = {
    "status": {"indicator": "none", "description": "All Systems Operational"},
    "components": comps(),
    "incidents": [],
}
INCIDENT = {"name": "Elevated errors on the API", "status": "monitoring", "started_at": "2026-09-29T14:21:37.180Z"}
BAD_SUMMARY = {
    "status": {"indicator": "minor", "description": "Minor Service Outage"},
    "components": comps(id_api="degraded_performance"),
    "incidents": [INCIDENT],
}
RELEASE = {"tag_name": "v9.9.9", "published_at": "2026-09-27T12:00:00Z"}


def uptime_payload(partial=(), major=(), n=90):
    """A /uptime_showcase body: n days per component; `partial`/`major` are day indexes for id_api."""
    def days(p, m):
        out = []
        for i in range(n):
            o = {}
            if i in p: o["p"] = 600
            if i in m: o["m"] = 300
            out.append({"date": f"2026-07-{i % 28 + 1:02d}", "outages": o, "related_events": []})
        return out
    ids = list(IDS.values())
    return {
        "components": {i: "<svg/>" for i in ids},
        "timelines": {i: {"component": {"code": i}, "days": days(partial, major) if i == "id_api" else days((), ())} for i in ids},
        "values": [{"component": i, "ninety": 99.5 - k * 0.1, "sixty": 99.6, "thirty": 99.7} for k, i in enumerate(ids)],
    }


def test_ok_summary_has_the_five_site_components_in_order():
    s = parse_summary(OK_SUMMARY, RELEASE, NOW)
    assert s.ok and s.headline == "ALL SYSTEMS OK" and s.incident is None and s.alert is None
    assert [c.label for c in s.components] == ["claude.ai", "Console", "API", "Claude Code", "Cowork"]
    assert all(c.operational for c in s.components)
    assert s.release_tag == "v9.9.9" and s.release_age_days == 2


def test_incident_summary_parses_status_and_start_time():
    s = parse_summary(BAD_SUMMARY, None, NOW)
    assert not s.ok and s.headline == "MINOR SERVICE OUTAGE"
    assert s.incident == "Elevated errors on the API" and s.incident_status == "monitoring"
    assert s.incident_since == datetime(2026, 9, 29, 14, 21, 37, 180000, tzinfo=timezone.utc)
    api = next(c for c in s.components if c.label == "API")
    assert api.severity == 1 and not api.operational
    assert s.release_tag is None


def test_component_severity_levels():
    s = parse_summary({**BAD_SUMMARY, "components": comps(id_api="major_outage", id_code="partial_outage",
                                                          id_cow="something_new")}, None, NOW)
    sev = {c.label: c.severity for c in s.components}
    assert sev["API"] == 2 and sev["Claude Code"] == 1
    assert sev["Cowork"] == 1                      # an unknown status is treated as degraded, never as fine
    assert sev["claude.ai"] == 0


# usage-page alert: an incident, or failing that the site's own headline
def test_alert_is_the_incident_title_or_the_headline():
    assert parse_summary(BAD_SUMMARY, None, NOW).alert == "Elevated errors on the API"
    no_incident = {**BAD_SUMMARY, "incidents": []}
    assert parse_summary(no_incident, None, NOW).alert == "MINOR SERVICE OUTAGE"
    assert parse_summary(OK_SUMMARY, None, NOW).alert is None


def test_parse_uptime_reads_percent_and_day_tiers():
    u = parse_uptime(uptime_payload(partial=(3,), major=(5, 7)))
    ninety, days = u["id_api"]
    assert ninety == pytest.approx(99.3) and len(days) == 90
    assert (days[0], days[3], days[5], days[7]) == (0, 1, 2, 2)


def test_a_day_with_both_partial_and_major_counts_as_major():
    p = uptime_payload(partial=(4,), major=(4,))
    assert parse_uptime(p)["id_api"][1][4] == 2


def test_uptime_is_attached_by_component_id():
    u = parse_uptime(uptime_payload(partial=(2,)))
    s = parse_summary(OK_SUMMARY, None, NOW, uptime=u)
    api = next(c for c in s.components if c.label == "API")
    assert api.uptime_90 == pytest.approx(99.3) and api.days[2] == 1 and len(api.days) == 90


def test_without_uptime_components_simply_have_no_bars():
    s = parse_summary(OK_SUMMARY, None, NOW)
    assert all(c.uptime_90 is None and c.days == () for c in s.components)


def mock_client(uptime_status=200, calls=None):
    calls = calls if calls is not None else []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("summary.json"):
            return httpx.Response(200, json=OK_SUMMARY)
        if req.url.path.endswith("/uptime_showcase"):
            return httpx.Response(uptime_status, json=uptime_payload(partial=(1,)) if uptime_status == 200 else {})
        return httpx.Response(200, json=RELEASE)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_read_status_requests_uptime_for_exactly_the_matched_components():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/uptime_showcase"):
            seen["components"] = req.url.params["components"]
            return httpx.Response(200, json=uptime_payload())
        return httpx.Response(200, json=OK_SUMMARY if "summary" in req.url.path else RELEASE)

    s = read_status(httpx.Client(transport=httpx.MockTransport(handler)), NOW, uptime_cache=UptimeCache())
    assert set(seen["components"].split(",")) == set(IDS.values())        # not "id_gov"
    assert s.components[2].uptime_90 is not None


def test_uptime_is_cached_for_thirty_minutes():
    client, calls = mock_client()
    cache = UptimeCache()
    for minutes in (0, 10, 29):
        read_status(client, NOW + timedelta(minutes=minutes), uptime_cache=cache)
    assert calls.count("/uptime_showcase") == 1
    read_status(client, NOW + timedelta(minutes=31), uptime_cache=cache)
    assert calls.count("/uptime_showcase") == 2


def test_uptime_failure_never_breaks_the_status_page(caplog):
    client, _ = mock_client(uptime_status=500)
    with caplog.at_level("WARNING", logger="note4_claude"):
        s = read_status(client, NOW, uptime_cache=UptimeCache())
    assert "uptime fetch failed" in caplog.text
    assert s.ok and all(c.days == () for c in s.components)


def test_uptime_failure_keeps_the_previous_bars():
    good, _ = mock_client()
    cache = UptimeCache()
    read_status(good, NOW, uptime_cache=cache)
    bad, _ = mock_client(uptime_status=500)
    s = read_status(bad, NOW + timedelta(minutes=45), uptime_cache=cache)   # stale cache beats no bars
    assert len(s.components[2].days) == 90


def test_release_failure_does_not_break_status():
    def handler(req: httpx.Request) -> httpx.Response:
        if "summary" in req.url.path:
            return httpx.Response(200, json=OK_SUMMARY)
        if req.url.path.endswith("/uptime_showcase"):
            return httpx.Response(200, json=uptime_payload())
        return httpx.Response(403, json={"message": "rate limited"})

    s = read_status(httpx.Client(transport=httpx.MockTransport(handler)), NOW, uptime_cache=UptimeCache())
    assert s.ok and s.release_tag is None

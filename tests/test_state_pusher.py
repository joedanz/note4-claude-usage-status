import httpx
import pytest

from claude_eink.pusher import PushError, Pusher, device_id_of, list_devices
from claude_eink.state import State


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp_path, handler, clock=None):
    clock = clock or Clock()
    calls = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return handler(req)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    state = State.load(tmp_path / "state.json")
    return Pusher(client, "zt_test", "AA:BB", state, clock=clock), calls, clock, state


OK = lambda req: httpx.Response(200, json={"code": 0, "data": {}})  # noqa: E731


def test_first_push_sends_expected_request(tmp_path):
    p, calls, _, _ = make(tmp_path, OK)
    assert p.push(1, b"PNG1", "k1") == "pushed"
    req = calls[0]
    assert req.method == "POST"
    assert str(req.url) == "https://cloud.zectrix.com/open/v1/devices/AA:BB/display/image"
    assert req.headers["X-API-Key"] == "zt_test"
    body = req.read()
    assert b'name="dither"' in body and b"false" in body
    assert b'name="pageId"' in body


def test_same_key_is_unchanged_until_heartbeat(tmp_path):
    p, calls, clock, _ = make(tmp_path, OK)
    p.push(1, b"PNG1", "k1")
    clock.t += 120
    assert p.push(1, b"PNG1b", "k1") == "unchanged"
    clock.t += 1800
    assert p.push(1, b"PNG1c", "k1") == "pushed"  # heartbeat refresh
    assert len(calls) == 2


def test_changed_key_within_min_interval_is_throttled(tmp_path):
    p, calls, clock, _ = make(tmp_path, OK)
    p.push(1, b"A", "k1")
    clock.t += 10
    assert p.push(1, b"B", "k2") == "throttled"
    clock.t += 60
    assert p.push(1, b"B", "k2") == "pushed"


def test_pages_are_independent(tmp_path):
    p, calls, clock, _ = make(tmp_path, OK)
    p.push(1, b"A", "k1")
    assert p.push(2, b"B", "k2") == "pushed"


def test_error_response_raises_and_backs_off(tmp_path):
    p, calls, clock, _ = make(tmp_path, lambda r: httpx.Response(429, json={"code": 429}))
    with pytest.raises(PushError):
        p.push(1, b"A", "k1")
    clock.t += 5
    assert p.push(1, b"A", "k1") == "backoff"
    assert len(calls) == 1
    clock.t += 60
    with pytest.raises(PushError):
        p.push(1, b"A", "k1")
    assert len(calls) == 2


def test_nonzero_code_in_200_is_an_error(tmp_path):
    p, *_ = make(tmp_path, lambda r: httpx.Response(200, json={"code": 401, "msg": "bad key"}))
    with pytest.raises(PushError):
        p.push(1, b"A", "k1")


def test_state_survives_restart(tmp_path):
    p, calls, clock, state = make(tmp_path, OK)
    p.push(1, b"A", "k1")
    state2 = State.load(tmp_path / "state.json")
    p2 = Pusher(httpx.Client(transport=httpx.MockTransport(OK)), "zt_test", "AA:BB", state2, clock=clock)
    clock.t += 90
    assert p2.push(1, b"A", "k1") == "unchanged"


def test_list_devices_and_id_extraction():
    payload = {"code": 0, "data": [{"deviceId": "AA:BB", "alias": "desk", "boardType": "NOTE4"}]}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    devices = list_devices(client, "zt_test", "https://cloud.zectrix.com")
    assert device_id_of(devices[0]) == "AA:BB"


def test_state_persists_last_good_usage(tmp_path):
    st = State.load(tmp_path / "state.json")
    st.last_good_text = "modal text"
    st.last_good_at = 1234.5
    st.save()
    st2 = State.load(tmp_path / "state.json")
    assert (st2.last_good_text, st2.last_good_at) == ("modal text", 1234.5)

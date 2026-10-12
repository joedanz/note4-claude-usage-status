import re
import threading

import httpx
import pytest

from claude_eink.sample import SAMPLE_NOW
from claude_eink.lan import LanSink
from claude_eink.lan_server import detect_lan_ip, make_server
from claude_eink.render.screens import render_login

NOW = SAMPLE_NOW
KEY = "s3cret-device-key"


@pytest.fixture
def served():
    sink = LanSink(clock=lambda: 1000.0)
    sink.push(1, render_login(now=NOW), "k1")
    server = make_server(sink, "127.0.0.1", 0, KEY, next_poll_s=300)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    yield sink, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url, path, key=KEY, **headers):
    h = dict(headers)
    if key is not None:
        h["X-Device-Key"] = key
    return httpx.get(url + path, headers=h, timeout=5)


def test_page_is_served_with_frame_etag_and_poll_hint(served):
    sink, url = served
    r = get(url, "/v1/page/1.bin")
    assert r.status_code == 200
    assert r.content == sink.get(1).data and len(r.content) == 15000
    assert r.headers["ETag"] == f'"{sink.get(1).etag}"'
    assert r.headers["X-Next-Poll"] == "300"
    assert r.headers["Content-Type"] == "application/octet-stream"


def test_matching_etag_returns_304_without_a_body(served):
    sink, url = served
    r = get(url, "/v1/page/1.bin", **{"If-None-Match": f'"{sink.get(1).etag}"'})
    assert r.status_code == 304 and r.content == b""
    assert r.headers["X-Next-Poll"] == "300"


# Review Focus 2: ETag header variants
@pytest.mark.parametrize("fmt", ['W/"{e}"', '*', '"nope", "{e}"', '"nope" ,   "{e}"'])
def test_etag_header_variants_that_match(served, fmt):
    sink, url = served
    r = get(url, "/v1/page/1.bin", **{"If-None-Match": fmt.format(e=sink.get(1).etag)})
    assert r.status_code == 304


def test_non_matching_etag_returns_the_full_frame(served):
    _, url = served
    r = get(url, "/v1/page/1.bin", **{"If-None-Match": '"deadbeef"'})
    assert r.status_code == 200 and len(r.content) == 15000


# Review Focus 1: device key
def test_missing_or_wrong_key_is_401(served):
    _, url = served
    assert get(url, "/v1/page/1.bin", key=None).status_code == 401
    assert get(url, "/v1/page/1.bin", key="wrong").status_code == 401
    assert get(url, "/v1/page/1.bin", key="").status_code == 401


def test_auth_is_checked_before_page_lookup(served):
    _, url = served
    assert get(url, "/v1/page/99.bin", key=None).status_code == 401       # no page-existence leak
    assert get(url, "/nothing", key=None).status_code == 401


def test_empty_key_refuses_to_start():
    with pytest.raises(ValueError):
        make_server(LanSink(), "127.0.0.1", 0, "")


# Review Focus 3: a restarted daemon has an empty store
def test_unknown_page_is_404_not_an_auth_error(served):
    _, url = served
    assert get(url, "/v1/page/2.bin").status_code == 404


def test_unknown_paths_and_oversized_page_ids_are_404(served):
    _, url = served
    assert get(url, "/v1/other").status_code == 404
    assert get(url, "/v1/page/99999999999999999999.bin").status_code == 404
    assert get(url, "/v1/page/abc.bin").status_code == 404
    assert get(url, "/").status_code == 404


def test_only_get_is_served(served):
    _, url = served
    for method in ("POST", "PUT", "DELETE", "HEAD"):
        r = httpx.request(method, url + "/v1/page/1.bin", headers={"X-Device-Key": KEY}, timeout=5)
        assert r.status_code == 405, method
        assert r.headers["Allow"] == "GET"


def test_query_string_is_ignored(served):
    _, url = served
    assert get(url, "/v1/page/1.bin?x=1").status_code == 200


def test_detect_lan_ip_returns_an_ipv4_address():
    assert re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", detect_lan_ip())


# Final review 2: an idle or half-open client must not hold a server thread forever
def test_half_open_connection_is_closed_by_the_server():
    import socket

    server = make_server(LanSink(), "127.0.0.1", 0, KEY, request_timeout_s=0.3)
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True).start()
    try:
        with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=3) as c:
            c.sendall(b"GET /v1/pa")                 # a request line that never finishes
            c.settimeout(3)
            assert c.recv(100) == b""               # the server gave up and closed the connection
    finally:
        server.shutdown()
        server.server_close()

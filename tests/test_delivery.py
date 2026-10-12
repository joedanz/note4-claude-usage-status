import pytest

from note4_claude.config import Config
from note4_claude.delivery import build_delivery
from note4_claude.lan import LanSink
from note4_claude.pusher import Pusher
from note4_claude.state import State


def lan_cfg(**kw):
    return Config(delivery="lan", lan_bind="127.0.0.1", lan_port=0, device_key="k" * 32, **kw)


def test_lan_delivery_builds_a_sink_and_a_bound_server(tmp_path):
    d = build_delivery(lan_cfg(), state=State.load(tmp_path / "s.json"))
    try:
        assert isinstance(d.sink, LanSink)
        assert d.server.server_address[0] == "127.0.0.1" and d.server.server_address[1] > 0
    finally:
        d.server.server_close()


def test_lan_delivery_without_a_device_key_points_at_setup(tmp_path):
    cfg = Config(delivery="lan", device_key="")
    with pytest.raises(SystemExit, match="setup"):
        build_delivery(cfg, state=State.load(tmp_path / "s.json"))


def test_cloud_delivery_builds_the_pusher(tmp_path):
    cfg = Config(delivery="cloud", device_id="AA:BB")
    d = build_delivery(cfg, state=State.load(tmp_path / "s.json"), api_key_getter=lambda: "zt_x")
    assert isinstance(d.sink, Pusher) and d.server is None


def test_cloud_delivery_without_key_or_device_points_at_setup(tmp_path):
    state = State.load(tmp_path / "s.json")
    with pytest.raises(SystemExit, match="setup"):
        build_delivery(Config(delivery="cloud", device_id="AA:BB"), state=state, api_key_getter=lambda: None)
    with pytest.raises(SystemExit, match="setup"):
        build_delivery(Config(delivery="cloud"), state=state, api_key_getter=lambda: "zt_x")


# Final review 1: push-once must not need the port the running daemon owns
def test_serve_false_builds_only_the_sink(tmp_path):
    d = build_delivery(lan_cfg(), state=State.load(tmp_path / "s.json"), serve=False)
    assert isinstance(d.sink, LanSink) and d.server is None


def test_port_already_in_use_is_a_clear_startup_error(tmp_path):
    import socket

    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    try:
        cfg = Config(delivery="lan", lan_bind="127.0.0.1", lan_port=taken.getsockname()[1], device_key="k" * 32)
        with pytest.raises(SystemExit, match="Cannot listen"):
            build_delivery(cfg, state=State.load(tmp_path / "s.json"))
    finally:
        taken.close()


# Final review 4: never settle for loopback just because the network was not up yet
def test_no_network_route_at_startup_fails_so_launchd_retries(tmp_path, monkeypatch):
    monkeypatch.setattr("note4_claude.delivery.detect_lan_ip", lambda: "127.0.0.1")
    cfg = Config(delivery="lan", lan_bind="", lan_port=0, device_key="k" * 32)
    with pytest.raises(SystemExit, match="network"):
        build_delivery(cfg, state=State.load(tmp_path / "s.json"))

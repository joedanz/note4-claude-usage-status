import note4_claude.collector as collector_mod
from note4_claude.cli import main


def test_preview_writes_all_pngs(tmp_path):
    assert main(["preview", "--out", str(tmp_path)]) == 0
    names = {p.name for p in tmp_path.iterdir()}
    assert {"page1-usage.png", "page2-status.png", "page2-status-degraded.png", "login.png"} <= names


class _FakeCollector:
    def __init__(self, results):
        self.results = results

    def tick_status(self):
        pass

    def tick_usage(self):
        pass


def test_push_once_exits_zero_when_pages_were_sent(monkeypatch, capsys):
    monkeypatch.setattr(collector_mod, "build_collector", lambda **kw: (_FakeCollector({1: "pushed", 2: "unchanged"}), None))
    assert main(["push-once"]) == 0
    out = capsys.readouterr().out
    assert "page 1: pushed" in out and "page 2: unchanged" in out


def test_push_once_fails_loudly_when_a_page_did_not_go_out(monkeypatch, capsys):
    monkeypatch.setattr(collector_mod, "build_collector", lambda **kw: (_FakeCollector({2: "pushed"}), None))
    assert main(["push-once"]) == 1
    assert "page 1: not sent" in capsys.readouterr().out
    monkeypatch.setattr(collector_mod, "build_collector", lambda **kw: (_FakeCollector({1: "error: boom", 2: "pushed"}), None))
    assert main(["push-once"]) == 1


def test_main_reports_a_config_error_instead_of_a_traceback(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "config.toml"
    bad.write_text('delivery = "nope"\n')
    monkeypatch.setattr("note4_claude.paths.config_path", lambda: bad)
    assert main(["doctor"]) == 2
    assert "config error" in capsys.readouterr().err


import stat

from note4_claude import config as config_mod


def test_setup_creates_a_private_device_key_once(tmp_path, monkeypatch, capsys):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("note4_claude.paths.config_path", lambda: cfg_path)
    assert main(["setup"]) == 0
    first = config_mod.load(cfg_path)
    assert first.delivery == "lan" and len(first.device_key) >= 32
    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600
    assert first.device_key not in capsys.readouterr().out          # setup never prints the key
    assert main(["setup"]) == 0
    assert config_mod.load(cfg_path).device_key == first.device_key   # idempotent


def test_device_key_command_prints_the_key(tmp_path, monkeypatch, capsys):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("note4_claude.paths.config_path", lambda: cfg_path)
    config_mod.save(config_mod.Config(device_key="abc-123"), cfg_path)
    assert main(["device-key"]) == 0
    assert capsys.readouterr().out.strip() == "abc-123"


def test_device_key_command_without_setup_fails_helpfully(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("note4_claude.paths.config_path", lambda: tmp_path / "none.toml")
    assert main(["device-key"]) == 1
    assert "setup" in capsys.readouterr().err


def test_doctor_reports_lan_delivery_state(tmp_path, monkeypatch, capsys):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("note4_claude.paths.config_path", lambda: cfg_path)
    monkeypatch.setattr("note4_claude.paths.profile_dir", lambda: tmp_path / "profile")
    monkeypatch.setattr("note4_claude.paths.state_path", lambda: tmp_path / "state.json")
    config_mod.save(config_mod.Config(device_key="abc"), cfg_path)
    main(["doctor"])
    out = capsys.readouterr().out
    assert "delivery: lan" in out and "device key" in out and "GUI session" in out


def test_push_once_never_binds_the_lan_port(monkeypatch):
    seen = {}

    def fake_build(**kw):
        seen.update(kw)
        return _FakeCollector({1: "pushed", 2: "pushed"}), None

    monkeypatch.setattr(collector_mod, "build_collector", fake_build)
    assert main(["push-once"]) == 0
    assert seen.get("serve") is False           # the running daemon owns the port

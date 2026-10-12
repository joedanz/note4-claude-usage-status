import subprocess

from claude_eink import keychain
from claude_eink.config import Config, load, save


def test_config_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = Config(device_id="AA:BB", usage_interval_s=120, status_interval_s=600)
    save(cfg, p)
    assert load(p) == cfg


def test_missing_config_gives_defaults(tmp_path):
    cfg = load(tmp_path / "nope.toml")
    assert cfg.device_id == "" and cfg.usage_interval_s == 240 and cfg.status_interval_s == 300
    assert not hasattr(cfg, "headless")


def test_config_file_does_not_contain_the_zectrix_api_key(tmp_path):
    p = tmp_path / "config.toml"
    save(Config(device_id="AA:BB"), p)
    assert "zt_" not in p.read_text()


def test_get_api_key_reads_keychain(monkeypatch):
    def fake_run(cmd, **kw):
        assert cmd[:2] == ["security", "find-generic-password"]
        return subprocess.CompletedProcess(cmd, 0, stdout="zt_abc\n", stderr="")

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    assert keychain.get_api_key() == "zt_abc"


def test_get_api_key_missing_returns_none(monkeypatch):
    monkeypatch.setattr(
        keychain.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 44, stdout="", stderr="")
    )
    assert keychain.get_api_key() is None


def test_prompt_set_never_puts_the_key_on_the_command_line(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    keychain.prompt_set_api_key()
    assert seen["cmd"][-1] == "-w"          # -w with no value: security prompts on the TTY
    assert "zt_" not in " ".join(seen["cmd"])


import stat

import pytest

from claude_eink.config import ConfigError, new_device_key


def test_saved_config_is_owner_only(tmp_path):
    p = tmp_path / "config.toml"
    save(Config(device_key="abc"), p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_lan_fields_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = Config(delivery="lan", lan_bind="192.168.1.50", lan_port=8123, device_key="k", next_poll_s=120)
    save(cfg, p)
    assert load(p) == cfg


def test_defaults_are_lan_delivery(tmp_path):
    cfg = load(tmp_path / "missing.toml")
    assert (cfg.delivery, cfg.lan_bind, cfg.lan_port, cfg.next_poll_s) == ("lan", "", 8099, 300)


def test_unknown_delivery_is_a_config_error(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('delivery = "carrier-pigeon"\n')
    with pytest.raises(ConfigError, match="delivery"):
        load(p)


def test_wrong_types_are_config_errors(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('usage_interval_s = "240"\n')
    with pytest.raises(ConfigError, match="usage_interval_s"):
        load(p)
    p.write_text("lan_port = 0\n")
    with pytest.raises(ConfigError, match="lan_port"):
        load(p)


def test_toml_syntax_error_is_a_config_error_naming_the_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("this is = = not toml\n")
    with pytest.raises(ConfigError, match="config.toml"):
        load(p)


def test_new_device_keys_are_long_and_unique():
    a, b = new_device_key(), new_device_key()
    assert len(a) >= 32 and a != b

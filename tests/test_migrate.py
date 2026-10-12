import signal
from pathlib import Path

from note4_claude import migrate, paths
from note4_claude.cli import main


def _legacy_install(home: Path) -> dict[str, Path]:
    cfg = home / ".config" / "claude-eink"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text('delivery = "lan"\ndevice_key = "' + "k" * 32 + '"\n')
    (cfg / "state.json").write_text("{}")
    support = home / "Library" / "Application Support" / "claude-eink"
    (support / "profile").mkdir(parents=True)
    (support / "profile" / "Cookies").write_text("signed-in")
    logs = home / "Library" / "Logs"
    logs.mkdir(parents=True)
    (logs / "claude-eink.log").write_text("old log\n")
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "net.ticc.claude-eink.plist"
    plist.write_text("<plist/>")
    return {"cfg": cfg, "support": support, "plist": plist}


class _Calls:
    def __init__(self):
        self.run, self.quit = [], []

    def run_fn(self, cmd, **kw):
        self.run.append(cmd)

    def quit_fn(self, profile):
        self.quit.append(profile)
        return True


def test_moves_config_profile_and_log_and_retires_the_old_agent():
    home = Path.home()   # a temporary HOME, from conftest
    old = _legacy_install(home)
    calls = _Calls()
    done = migrate.migrate_legacy(run=calls.run_fn, quit_chrome=calls.quit_fn, out=lambda *a: None)
    assert done
    assert (paths.config_path()).read_text().count("k" * 32) == 1          # the device key survives
    assert (paths.profile_dir() / "Cookies").read_text() == "signed-in"     # so does the sign-in
    assert paths.log_path().read_text() == "old log\n"
    assert not old["cfg"].exists() and not old["support"].exists() and not old["plist"].exists()
    assert calls.run == [["launchctl", "bootout", migrate.gui_domain(), str(old["plist"])]]
    assert calls.quit == [old["support"] / "profile"]                       # Chrome quit before the move


def test_nothing_to_do_without_a_legacy_install():
    calls = _Calls()
    assert migrate.migrate_legacy(run=calls.run_fn, quit_chrome=calls.quit_fn, out=lambda *a: None) == []
    assert calls.run == [] and calls.quit == []


def test_is_idempotent():
    _legacy_install(Path.home())
    calls = _Calls()
    assert migrate.migrate_legacy(run=calls.run_fn, quit_chrome=calls.quit_fn, out=lambda *a: None)
    assert migrate.migrate_legacy(run=calls.run_fn, quit_chrome=calls.quit_fn, out=lambda *a: None) == []


def test_never_overwrites_a_new_folder_that_has_content():
    old = _legacy_install(Path.home())
    new_cfg = paths.config_path().parent
    new_cfg.mkdir(parents=True)
    (new_cfg / "config.toml").write_text('delivery = "lan"\n')
    migrate.migrate_legacy(run=_Calls().run_fn, quit_chrome=_Calls().quit_fn, out=lambda *a: None)
    assert (new_cfg / "config.toml").read_text() == 'delivery = "lan"\n'
    assert (old["cfg"] / "config.toml").exists()                            # left for a human to sort out
    assert (paths.profile_dir() / "Cookies").exists()                       # the other moves still happen


def test_an_empty_new_folder_does_not_block_the_move():
    _legacy_install(Path.home())
    paths.profile_dir().mkdir(parents=True)                                 # e.g. created by a first `run`
    migrate.migrate_legacy(run=_Calls().run_fn, quit_chrome=_Calls().quit_fn, out=lambda *a: None)
    assert (paths.profile_dir() / "Cookies").read_text() == "signed-in"


def test_setup_after_migration_keeps_the_old_device_key(monkeypatch):
    """deploy.sh runs `setup` when the new config is missing; it must not mint a new key."""
    _legacy_install(Path.home())
    monkeypatch.setattr(migrate, "quit_profile_chrome", lambda profile: True)
    monkeypatch.setattr(migrate, "_run", lambda *a, **kw: None)
    assert main(["setup"]) == 0
    assert "k" * 32 in paths.config_path().read_text()


def test_preview_never_migrates(tmp_path, monkeypatch):
    _legacy_install(Path.home())
    monkeypatch.setattr(migrate, "migrate_legacy", lambda **kw: (_ for _ in ()).throw(AssertionError("migrated")))
    assert main(["preview", "--out", str(tmp_path / "p")]) == 0


PS = """\
  101 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir=/h/Library/Application Support/claude-eink/profile --remote-debugging-port=9333
  102 /Applications/Google Chrome.app/Contents/Frameworks/Helper --type=renderer --user-data-dir=/h/Library/Application Support/claude-eink/profile
  103 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
"""


def test_quit_chrome_terminates_only_the_main_process_for_that_profile():
    profile = Path("/h/Library/Application Support/claude-eink/profile")
    killed, listings = [], [PS, ""]
    ok = migrate.quit_profile_chrome(
        profile, ps=lambda: listings.pop(0), kill=lambda pid, sig: killed.append((pid, sig)), sleep=lambda s: None
    )
    assert ok and killed == [(101, signal.SIGTERM)]


def test_quit_chrome_gives_up_after_the_timeout():
    profile = Path("/h/Library/Application Support/claude-eink/profile")
    ok = migrate.quit_profile_chrome(profile, ps=lambda: PS, kill=lambda pid, sig: None, sleep=lambda s: None, tries=3)
    assert not ok


def test_chrome_that_will_not_quit_stops_the_command_before_anything_moves():
    import pytest

    old = _legacy_install(Path.home())
    with pytest.raises(SystemExit):
        migrate.migrate_legacy(run=_Calls().run_fn, quit_chrome=lambda profile: False, out=lambda *a: None)
    assert (old["support"] / "profile" / "Cookies").exists() and not paths.profile_dir().exists()


def test_api_key_falls_back_to_the_old_keychain_service(monkeypatch):
    from types import SimpleNamespace

    from note4_claude import keychain

    def fake(cmd, **kw):
        found = cmd[cmd.index("-s") + 1] == "claude-eink-zectrix"
        return SimpleNamespace(returncode=0 if found else 44, stdout="zt_old\n" if found else "")

    monkeypatch.setattr(keychain.subprocess, "run", fake)
    assert keychain.get_api_key() == "zt_old"

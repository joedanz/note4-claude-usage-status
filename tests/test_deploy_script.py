import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "deploy.sh"
TARGET = "user@mac.example"


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)


def test_script_is_valid_bash():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_missing_target_prints_usage_and_exits_2():
    r = run()
    assert r.returncode == 2 and "usage" in (r.stdout + r.stderr).lower()


def test_dry_run_prints_the_plan_and_changes_nothing():
    r = run("--dry-run", TARGET)
    out = r.stdout
    assert r.returncode == 0
    assert "+ rsync" in out and f"{TARGET}:claude-eink/" in out
    assert "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" in out   # explicit interpreter
    assert "claude-eink install" in out
    assert "dry run" in out.lower()


def test_secrets_and_firmware_are_never_copied():
    out = run("--dry-run", TARGET).stdout
    assert "--exclude firmware" in out            # the whole firmware tree, so no secrets.local.h leaves this Mac
    assert "--exclude secrets.local.h" in out
    assert "--exclude .venv" in out and "--exclude .git" in out


def test_python_path_can_be_overridden():
    out = run("--dry-run", "--python", "/opt/py/bin/python3", TARGET).stdout
    assert "/opt/py/bin/python3" in out


def test_no_install_only_syncs_and_builds_the_venv():
    out = run("--dry-run", "--no-install", TARGET).stdout
    assert "+ rsync" in out and "pip install" in out
    assert "claude-eink install" not in out      # nothing is started until the first sign-in is done
    assert "claude-eink doctor" not in out


def test_default_run_creates_the_device_key_only_if_there_is_no_config():
    out = run("--dry-run", TARGET).stdout
    assert "config.toml" in out and "claude-eink setup" in out
    # the guard must come before setup so an existing (for example cloud) config is never overwritten
    assert out.index("config.toml") < out.index("claude-eink setup") < out.index("claude-eink install")

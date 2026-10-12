import plistlib

from claude_eink.launchd import LABEL, render_plist


def test_plist_runs_the_daemon_and_restarts_it():
    data = plistlib.loads(render_plist("/x/.venv/bin/python", "/x/claude-eink.log"))
    assert data["Label"] == LABEL
    assert data["ProgramArguments"] == ["/x/.venv/bin/python", "-m", "claude_eink", "run"]
    assert data["KeepAlive"] is True
    assert data["RunAtLoad"] is True
    assert data["StandardErrorPath"] == "/x/claude-eink.log"

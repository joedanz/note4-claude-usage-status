import plistlib

from note4_claude.launchd import LABEL, render_plist


def test_plist_runs_the_daemon_and_restarts_it():
    data = plistlib.loads(render_plist("/x/.venv/bin/python", "/x/note4-claude.log"))
    assert data["Label"] == LABEL
    assert data["ProgramArguments"] == ["/x/.venv/bin/python", "-m", "note4_claude", "run"]
    assert data["KeepAlive"] is True
    assert data["RunAtLoad"] is True
    assert data["StandardErrorPath"] == "/x/note4-claude.log"

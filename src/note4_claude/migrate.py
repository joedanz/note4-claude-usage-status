"""One-time move from the project's first name, claude-eink, to note4-claude.

An install made under the old name keeps its device key (which the firmware holds) and its signed-in Chrome profile
in folders named after it. Moving them, rather than starting fresh, keeps the display and the sign-in working.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from note4_claude import paths
from note4_claude.launchd import gui_domain

LEGACY_APP = "claude-eink"
LEGACY_LABEL = "net.ticc.claude-eink"

_run = subprocess.run


def _legacy_support() -> Path:
    return Path.home() / "Library" / "Application Support" / LEGACY_APP


def _moves() -> list[tuple[Path, Path]]:
    home = Path.home()
    return [
        (home / ".config" / LEGACY_APP, paths.config_path().parent),
        (_legacy_support(), paths.profile_dir().parent),
        (home / "Library" / "Logs" / f"{LEGACY_APP}.log", paths.log_path()),
    ]


def _vacant(path: Path) -> bool:
    """Missing, or a folder holding no files at all (only empty folders, as a first run can leave)."""
    return not path.exists() or (path.is_dir() and not any(not q.is_dir() for q in path.rglob("*")))


def _ps() -> str:
    return subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout


def quit_profile_chrome(profile: Path, *, ps=_ps, kill=os.kill, sleep=time.sleep, tries: int = 30) -> bool:
    """Quit the Chrome running on `profile` (SIGTERM lets it save its state) and wait until it has exited."""
    marker = f"--user-data-dir={profile}"

    def mains() -> list[int]:
        return [
            int(line.split(None, 1)[0])
            for line in ps().splitlines()
            if marker in line and "--type=" not in line   # helpers exit with their browser process
        ]

    for pid in mains():
        try:
            kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(tries):
        if not mains():
            return True
        sleep(0.5)
    return False


def migrate_legacy(*, run=None, quit_chrome=None, out=print) -> list[str]:
    """Move a claude-eink install over to note4-claude. Returns what was done; a no-op once nothing is left to move."""
    run = run or _run
    quit_chrome = quit_chrome or quit_profile_chrome
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LEGACY_LABEL}.plist"
    pending = [(old, new) for old, new in _moves() if old.exists() and _vacant(new)]
    if not pending and not plist.exists():
        return []
    done = []
    if plist.exists():
        run(["launchctl", "bootout", gui_domain(), str(plist)], capture_output=True)
        plist.unlink()
        done.append(f"stopped and removed the old LaunchAgent {LEGACY_LABEL}")
    if any(old == _legacy_support() for old, _ in pending):
        if not quit_chrome(_legacy_support() / "profile"):   # moving a profile under a running Chrome loses the sign-in
            raise SystemExit("The collector's Chrome did not quit. Quit it (Cmd+Q) and run the command again.")
    for old, new in pending:
        new.parent.mkdir(parents=True, exist_ok=True)
        if new.exists():
            shutil.rmtree(new)   # vacant: no files in it
        old.rename(new)
        done.append(f"moved {old} -> {new}")
    for line in done:
        out(f"migrated from {LEGACY_APP}: {line}")
    return done

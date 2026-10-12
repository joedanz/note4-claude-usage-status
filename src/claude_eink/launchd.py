from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from claude_eink import paths

LABEL = "net.ticc.claude-eink"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def render_plist(python: str, log_path: str) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [python, "-m", "claude_eink", "run"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 30,
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
        }
    )


def gui_domain() -> str:
    return f"gui/{os.getuid()}"


def install() -> Path:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_plist(sys.executable, str(paths.log_path())))
    subprocess.run(["launchctl", "bootout", gui_domain(), str(path)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", gui_domain(), str(path)], check=True)
    return path


def uninstall() -> None:
    path = plist_path()
    subprocess.run(["launchctl", "bootout", gui_domain(), str(path)], capture_output=True)
    path.unlink(missing_ok=True)

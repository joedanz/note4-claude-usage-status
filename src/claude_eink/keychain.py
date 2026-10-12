from __future__ import annotations

import subprocess

SERVICE = "claude-eink-zectrix"
ACCOUNT = "api-key"


def prompt_set_api_key() -> None:
    """Let `security` prompt for the key on the TTY, so it never appears in argv."""
    subprocess.run(
        ["security", "add-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-U", "-w"],
        check=True,
    )


def get_api_key() -> str | None:
    r = subprocess.run(
        ["security", "find-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-w"],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None

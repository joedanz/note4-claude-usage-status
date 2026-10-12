from __future__ import annotations

import subprocess

SERVICE = "note4-claude-zectrix"
LEGACY_SERVICE = "claude-eink-zectrix"   # the project's first name; read as a fallback
ACCOUNT = "api-key"


def prompt_set_api_key() -> None:
    """Let `security` prompt for the key on the TTY, so it never appears in argv."""
    subprocess.run(
        ["security", "add-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-U", "-w"],
        check=True,
    )


def get_api_key() -> str | None:
    for service in (SERVICE, LEGACY_SERVICE):
        r = subprocess.run(
            ["security", "find-generic-password", "-a", ACCOUNT, "-s", service, "-w"],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None

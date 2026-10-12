from __future__ import annotations

from pathlib import Path

APP = "note4-claude"


def config_path() -> Path:
    return Path.home() / ".config" / APP / "config.toml"


def state_path() -> Path:
    return Path.home() / ".config" / APP / "state.json"


def profile_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP / "profile"


def debug_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP / "debug"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / f"{APP}.log"

from __future__ import annotations

import json
import secrets
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from note4_claude import paths

DELIVERIES = ("lan", "cloud")
DEFAULT_API_BASE = "https://cloud.zectrix.com"


class ConfigError(ValueError):
    """The config file is unreadable or has an invalid value."""


@dataclass
class Config:
    device_id: str = ""
    usage_interval_s: int = 240
    status_interval_s: int = 300
    api_base: str = DEFAULT_API_BASE
    delivery: str = "lan"
    lan_bind: str = ""
    lan_port: int = 8099
    device_key: str = ""
    next_poll_s: int = 300


def new_device_key() -> str:
    return secrets.token_urlsafe(24)


def _validate(cfg: Config, path: Path) -> None:
    defaults = Config()
    for f in fields(Config):
        value = getattr(cfg, f.name)
        if isinstance(getattr(defaults, f.name), int):  # decided by the default's type, not annotation strings
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(f"{path}: {f.name} must be a positive integer, got {value!r}")
        elif not isinstance(value, str):
            raise ConfigError(f"{path}: {f.name} must be a string, got {value!r}")
    if cfg.delivery not in DELIVERIES:
        raise ConfigError(f"{path}: delivery must be one of {DELIVERIES}, got {cfg.delivery!r}")


def load(path: Path | None = None) -> Config:
    path = Path(path or paths.config_path())
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Config()
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: not valid TOML ({e})") from e
    names = {f.name for f in fields(Config)}
    cfg = Config(**{k: v for k, v in data.items() if k in names})
    _validate(cfg, path)
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return json.dumps(v)  # JSON strings are valid TOML basic strings


def save(cfg: Config, path: Path | None = None) -> None:
    path = Path(path or paths.config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k} = {_toml_value(v)}\n" for k, v in asdict(cfg).items()))
    path.chmod(0o600)  # holds the device key

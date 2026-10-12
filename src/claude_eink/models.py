from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ReaderError(Exception):
    """Base class for failures while reading a source."""


class NotLoggedIn(ReaderError):
    """The dedicated profile is not signed in to claude.ai."""


class TransientError(ReaderError):
    """Timeout or network problem; worth retrying silently."""


class ParseFailed(Exception):
    """The modal text did not contain valid required data."""


class WindowKind(str, Enum):
    SESSION_5H = "session_5h"
    WEEK = "week"
    MODEL_WEEK = "model_week"


@dataclass(frozen=True)
class Window:
    label: str
    kind: WindowKind
    pct: int
    resets_at: datetime | None
    elapsed_fraction: float | None


@dataclass(frozen=True)
class Money:
    usage_credits_usd: float | None = None
    cloud_credit_usd: float | None = None
    cloud_credit_expires: str | None = None
    month_spend_usd: float | None = None
    month_cap_usd: float | None = None


@dataclass(frozen=True)
class Usage:
    plan: str
    pace_headline: str | None
    windows: tuple[Window, ...]
    money: Money
    product_split: dict[str, int] = field(default_factory=dict)
    captured_at: datetime | None = None


@dataclass(frozen=True)
class ComponentStatus:
    label: str
    severity: int = 0                      # 0 operational, 1 degraded / partial outage, 2 major outage
    uptime_90: float | None = None         # percent over the past 90 days, when known
    days: tuple[int, ...] = ()             # one entry per day, oldest first: 0 normal, 1 partial outage, 2 major outage

    @property
    def operational(self) -> bool:
        return self.severity == 0


@dataclass(frozen=True)
class StatusData:
    headline: str
    ok: bool
    components: tuple[ComponentStatus, ...]
    incident: str | None = None
    incident_status: str | None = None     # e.g. "investigating", "monitoring"
    incident_since: datetime | None = None
    release_tag: str | None = None
    release_age_days: int | None = None

    @property
    def alert(self) -> str | None:
        """What the usage page should warn about: the incident title, or failing that the site's headline."""
        if self.incident:
            return self.incident
        return None if self.ok else self.headline

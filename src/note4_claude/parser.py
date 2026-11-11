from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from itertools import pairwise

from note4_claude.models import LimitReset, Money, ParseFailed, Usage, Window, WindowKind

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
RESET_RE = re.compile(
    r"Resets\s+(?:at\s+)?(?:(?P<day>Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+)?"
    r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>AM|PM)",
    re.I,
)
PCT_RE = re.compile(r"(\d{1,3})%\s+used")
ICON_RE = re.compile("[\ue000-\uf8ff]")
# A model limit nested under "This week": its name on one line, then this caption.
MODEL_CAP_RE = re.compile(r"Up to \d{1,3}% of your weekly limit", re.I)
WINDOW_LEN = {
    WindowKind.SESSION_5H: timedelta(hours=5),
    WindowKind.WEEK: timedelta(days=7),
    WindowKind.MODEL_WEEK: timedelta(days=7),
}
TOLERANCE = timedelta(minutes=1)


def _label(lines: list[str], i: int) -> tuple[WindowKind, str] | None:
    s = lines[i].strip()
    if s.lower() == "current session":
        return WindowKind.SESSION_5H, "5-hour"
    m = re.fullmatch(r"(?:(.+?)\s+)?this week", s, re.I)
    if m:
        if m.group(1):
            return WindowKind.MODEL_WEEK, m.group(1)
        return WindowKind.WEEK, "Weekly"
    if i + 1 < len(lines) and MODEL_CAP_RE.fullmatch(lines[i + 1].strip()):
        return WindowKind.MODEL_WEEK, s
    return None


def _resolve_reset(m: re.Match, now: datetime) -> datetime:
    hour = int(m["h"]) % 12 + (12 if m["ap"].upper() == "PM" else 0)
    cand = now.replace(hour=hour, minute=int(m["m"]), second=0, microsecond=0)
    if m["day"]:
        target = WEEKDAYS[m["day"][:3].lower()]
        cand += timedelta(days=(target - now.weekday()) % 7)
        if cand <= now:
            cand += timedelta(days=7)
    elif cand <= now:
        cand += timedelta(days=1)
    return cand


def _remaining(resets_at: datetime, now: datetime) -> timedelta:
    # Subtract in UTC: same-tzinfo subtraction ignores DST offsets.
    return resets_at.astimezone(timezone.utc) - now.astimezone(timezone.utc)


def _parse_window(lines: list[str], i: int, now: datetime) -> Window:
    kind, label = _label(lines, i)
    reset_m, pct = None, None
    for j in range(i + 1, min(i + 5, len(lines))):
        if _label(lines, j):
            break
        reset_m = reset_m or RESET_RE.search(lines[j])
        pm = PCT_RE.search(lines[j])
        if pm:
            pct = int(pm.group(1))
            break
    if pct is None:
        raise ParseFailed(f"no '% used' for {lines[i]!r}")
    if not 0 <= pct <= 100:
        raise ParseFailed(f"percent out of range for {lines[i]!r}: {pct}")
    if reset_m is None:
        if pct > 0:
            raise ParseFailed(f"no reset time for active window {lines[i]!r}")
        return Window(label, kind, pct, None, None)
    resets_at = _resolve_reset(reset_m, now)
    length = WINDOW_LEN[kind]
    remaining = _remaining(resets_at, now)
    if not timedelta(0) < remaining <= length + TOLERANCE:
        raise ParseFailed(f"reset for {lines[i]!r} outside its window: {remaining}")
    elapsed = min(1.0, max(0.0, 1 - remaining / length))
    return Window(label, kind, pct, resets_at, elapsed)


def _money_value(s: str) -> float:
    return float(s.replace(",", ""))


def _parse_money(lines: list[str]) -> Money:
    joined = "\n".join(lines)
    usage_credits = None
    for i, ln in enumerate(lines):
        if ln == "Usage credits":
            for nxt in lines[i + 1 : i + 4]:
                m = re.fullmatch(r"\$([\d,]+(?:\.\d+)?)", nxt)
                if m:
                    usage_credits = _money_value(m.group(1))
                    break
            break
    cloud = re.search(
        r"Included credit\nExpires ([^\n]+)\n\$([\d,.]+) of \$([\d,.]+) left", joined
    )
    spend = re.search(r"\$([\d,.]+) of \$([\d,.]+) this month", joined)
    return Money(
        usage_credits_usd=usage_credits,
        cloud_credit_usd=_money_value(cloud.group(2)) if cloud else None,
        cloud_credit_expires=cloud.group(1) if cloud else None,
        month_spend_usd=_money_value(spend.group(1)) if spend else None,
        month_cap_usd=_money_value(spend.group(2)) if spend else None,
    )


def _parse_split(lines: list[str]) -> dict[str, int]:
    for i, ln in enumerate(lines):
        if re.search(r"usage by product", ln, re.I):
            out: dict[str, int] = {}
            j = i + 1
            while j + 1 < len(lines):
                pct = re.fullmatch(r"(\d{1,3})%", lines[j + 1])
                if not pct:
                    break
                out[lines[j]] = int(pct.group(1))
                j += 2
            return out
    return {}


# "Limit resets": each type is a "<Kind> reset[ · N]" line followed by its expiry line: "Expires ..." for one reset,
# "All expire ..." for several on the same date, "First expires ..." (the soonest) for several on different dates.
# Only the type line is required, so a new wording loses at most the date, never the reset.
RESET_TYPE_RE = re.compile(r"(?P<kind>.+?) reset(?: · (?P<n>\d+))?", re.I)
EXPIRY_RE = re.compile(
    r"(?P<mon>[a-z]{3})[a-z]* (?P<d>\d{1,2})(?:, (?P<y>\d{4}))?, (?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[ap]m)", re.I
)


def _parse_expiry(s: str, now: datetime) -> datetime | None:
    """The date in 'All expire Mar 9, 2027, 2:59 AM EST' or 'Expires Dec 15, 11:59 PM EST', in the Mac's own zone
    like the reset times."""
    m = EXPIRY_RE.search(s)
    if not m:
        return None
    try:
        dt = datetime.strptime(
            f"{m['mon']} {m['d']} {m['y'] or now.year} {m['h']}:{m['m']} {m['ap']}", "%b %d %Y %I:%M %p"
        ).replace(tzinfo=now.tzinfo)
        if not m["y"] and dt < now - timedelta(days=1):  # no year shown: the next such date
            dt = dt.replace(year=dt.year + 1)
    except ValueError:
        return None
    return dt


def _parse_resets(lines: list[str], now: datetime, windows: tuple[Window, ...]) -> tuple[LimitReset, ...]:
    """Best effort: a section that changed shape yields no resets, never a failed read."""
    start = next((i for i, ln in enumerate(lines) if ln.lower() in ("limit resets", "resets")), None)
    if start is None:
        return ()
    # Each type refills the gauge of the same name: "Weekly reset" the gauge _label() calls "Weekly", "Fable reset" Fable's.
    gauges = {w.label.lower(): w.label for w in windows}
    out = []
    for ln, nxt in pairwise(lines[start + 1 :]):
        if t := RESET_TYPE_RE.fullmatch(ln):
            kind = t["kind"]
            out.append(LimitReset(kind, int(t["n"] or 1), _parse_expiry(nxt, now), gauges.get(kind.lower())))
    return tuple(out)


def parse(text: str, now: datetime) -> Usage:
    # claude.ai's icon font (chevrons, info buttons) shows up as private-use glyphs, often on lines of their own.
    lines = [s for s in (ln.strip() for ln in ICON_RE.sub("", text).splitlines()) if s]
    if "Your usage" not in lines:
        raise ParseFailed("no 'Your usage' heading")
    lines = lines[lines.index("Your usage") + 1 :]
    if not lines:
        raise ParseFailed("nothing after 'Your usage'")
    plan = lines[0]

    headline = None
    for i, ln in enumerate(lines[1:], start=1):
        if _label(lines, i):
            break
        if ln != "Buy more usage":
            headline = ln
            break

    windows = tuple(_parse_window(lines, i, now) for i in range(len(lines)) if _label(lines, i))
    # Every plan has a weekly limit; some (Ultra) have no session limit at all.
    if not any(w.kind == WindowKind.WEEK for w in windows):
        raise ParseFailed("missing required weekly window")

    return Usage(
        plan=plan,
        pace_headline=headline,
        windows=windows,
        money=_parse_money(lines),
        product_split=_parse_split(lines),
        captured_at=now,
        resets=_parse_resets(lines, now, windows),
    )

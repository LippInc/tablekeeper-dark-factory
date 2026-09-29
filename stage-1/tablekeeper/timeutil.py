"""Wall-clock time at a restaurant versus absolute instants (§9).

Instants are held as UTC datetimes and every sum or comparison is made on them. Python
adds a timedelta to an aware datetime as wall-clock time when the zone stays the same,
which is wrong across a DST transition; UTC has none.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The largest duration or cutoff a restaurant may state (100 years), and the local years
# a date may fall in, so that any local time on it, plus any stated duration, stays
# within the range a datetime can hold.
MAX_MINUTES = 100 * 366 * 24 * 60
EARLIEST_YEAR = 2
LATEST_YEAR = 9800

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_LOCAL = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
_HHMM = re.compile(r"[0-9]{2}:[0-9]{2}")


def zone(name: str) -> ZoneInfo | None:
    """The IANA zone called `name`, or None when there is none."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _supported(value: date) -> bool:
    return EARLIEST_YEAR <= value.year <= LATEST_YEAR


def parse_date(text: str) -> date | None:
    """A calendar date `YYYY-MM-DD`."""
    if not _DATE.fullmatch(text):
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return day if _supported(day) else None


def parse_local(text: str) -> datetime | None:
    """A bare local `YYYY-MM-DDTHH:MM` (no seconds, no offset) as a naive datetime."""
    if not _LOCAL.fullmatch(text):
        return None
    try:
        local = datetime.fromisoformat(text)
    except ValueError:
        return None
    return local if _supported(local) else None


def parse_hhmm(text: str) -> time | None:
    """A 24-hour local `HH:MM` time of day."""
    if not _HHMM.fullmatch(text):
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        return None


def instant_of(local: datetime, tz: ZoneInfo) -> datetime:
    """The UTC instant a local wall time at `tz` stands for.

    A repeated wall time (fall back) is its first occurrence. A skipped one (spring
    forward) is read with the offset in force before the transition, so it lands as far
    past the gap's end as it is past the gap's start: 02:30 in a 02:00-03:00 gap is 03:30.
    """
    return local.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)


def resolve(local: datetime, tz: ZoneInfo) -> datetime | None:
    """The UTC instant of a local wall time that exists at `tz`, else None (§9)."""
    instant = instant_of(local, tz)
    if instant.astimezone(tz).replace(tzinfo=None) != local:
        return None
    return instant


def now() -> datetime:
    return datetime.now(timezone.utc)


def rfc3339(instant: datetime, tz: ZoneInfo | timezone = timezone.utc) -> str:
    """`instant` as RFC 3339 with seconds and the offset in force at `tz` then."""
    return instant.astimezone(tz).isoformat(timespec="seconds")


def wall_time(instant: datetime, tz: ZoneInfo) -> datetime:
    """The naive wall time the clocks at `tz` show at `instant`."""
    return instant.astimezone(tz).replace(tzinfo=None)


def local_text(instant: datetime, tz: ZoneInfo) -> str:
    """`instant` as the bare local `YYYY-MM-DDTHH:MM` at `tz`."""
    return wall_time(instant, tz).isoformat(timespec="minutes")


def hhmm(value: time) -> str:
    return value.isoformat(timespec="minutes")

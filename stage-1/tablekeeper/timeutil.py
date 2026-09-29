"""Wall-clock time at a restaurant versus absolute instants (§9).

Instants are held as UTC datetimes and every sum or comparison is made on them. Python
adds a timedelta to an aware datetime as wall-clock time when the zone stays the same,
which is wrong across a DST transition; UTC has none.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The largest duration or cutoff a restaurant may state (100 years), and the last local
# year a booking may start in, so that a start plus any stated duration stays within
# the range a datetime can hold.
MAX_MINUTES = 100 * 366 * 24 * 60
LATEST_YEAR = 9800

_LOCAL = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
_HHMM = re.compile(r"[0-9]{2}:[0-9]{2}")


def zone(name: str) -> ZoneInfo | None:
    """The IANA zone called `name`, or None when there is none."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def parse_local(text: str) -> datetime | None:
    """A bare local `YYYY-MM-DDTHH:MM` (no seconds, no offset) as a naive datetime."""
    if not _LOCAL.fullmatch(text):
        return None
    try:
        local = datetime.fromisoformat(text)
    except ValueError:
        return None
    return local if local.year <= LATEST_YEAR else None


def parse_hhmm(text: str) -> time | None:
    """A 24-hour local `HH:MM` time of day."""
    if not _HHMM.fullmatch(text):
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        return None


def resolve(local: datetime, tz: ZoneInfo) -> datetime | None:
    """The UTC instant of a local wall time at `tz`.

    A repeated wall time (fall back) resolves to its first occurrence. A skipped one
    (spring forward) does not exist and gives None, as does one before the first instant
    a datetime can hold.
    """
    try:
        instant = local.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
    except OverflowError:
        return None
    if instant.astimezone(tz).replace(tzinfo=None) != local:
        return None
    return instant


def now() -> datetime:
    return datetime.now(timezone.utc)


def rfc3339(instant: datetime, tz: ZoneInfo | timezone = timezone.utc) -> str:
    """`instant` as RFC 3339 with seconds and the offset in force at `tz` then."""
    return instant.astimezone(tz).isoformat(timespec="seconds")


def local_text(instant: datetime, tz: ZoneInfo) -> str:
    """`instant` as the bare local `YYYY-MM-DDTHH:MM` at `tz`."""
    return instant.astimezone(tz).replace(tzinfo=None).isoformat(timespec="minutes")


def hhmm(value: time) -> str:
    return value.isoformat(timespec="minutes")

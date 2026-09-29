"""A restaurant's opening windows, slot grid and availability on one local date (§4, §8, §9).

Every opening-hours entry for the date's weekday is a window of its own. A window's grid
runs in wall-clock steps of `slot_minutes` from its `opens`. A step is a slot when that
wall time exists and a reservation starting then ends, in absolute time, no later than
the window's `closes`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from . import timeutil
from .domain import WEEKDAYS, Restaurant, is_free

if TYPE_CHECKING:
    from .store import State


@dataclass(frozen=True)
class Window:
    opens: datetime      # wall time at the restaurant, naive
    closes: datetime     # wall time at the restaurant, naive
    closes_at: datetime  # UTC

    def fits(self, starts_at: datetime, duration: timedelta) -> bool:
        """Whether a reservation from `starts_at` ends by closing time."""
        return starts_at + duration <= self.closes_at


def windows(restaurant: Restaurant, day: date) -> list[Window]:
    """The restaurant's opening windows on `day`, earliest first; none on a closed day."""
    weekday = WEEKDAYS[day.weekday()]
    hours = sorted((h for h in restaurant.opening_hours if h.weekday == weekday),
                   key=lambda h: h.opens)
    found = []
    for entry in hours:
        closes = datetime.combine(day, entry.closes)
        found.append(Window(opens=datetime.combine(day, entry.opens), closes=closes,
                            closes_at=timeutil.instant_of(closes, restaurant.zone)))
    return found


def slots(restaurant: Restaurant, day: date) -> list[datetime]:
    """The UTC instant of every start a booking may take on `day`, window by window,
    each wall time once."""
    step = timedelta(minutes=restaurant.slot_minutes)
    found = []
    for window in windows(restaurant, day):
        local = window.opens
        while local < window.closes:
            starts_at = timeutil.resolve(local, restaurant.zone)
            if starts_at is not None and window.fits(starts_at, restaurant.duration):
                found.append(starts_at)
            local += step  # naive, so the grid steps in wall-clock time
    return found


def availability(state: State, restaurant: Restaurant, day: date, party_size: int) -> dict:
    """Every slot on `day` with the tables, in fixture order, that seat the party and are
    free for a whole booking from that slot. A slot with no such table is still listed."""
    tables = [table for table in restaurant.tables if table.capacity >= party_size]
    zone = restaurant.zone
    return {
        "restaurant_id": restaurant.id,
        "date": day.isoformat(),
        "timezone": restaurant.timezone,
        "slots": [
            {"starts_at_local": timeutil.local_text(starts_at, zone),
             "starts_at": timeutil.rfc3339(starts_at, zone),
             "available_table_ids": [table.id for table in tables
                                     if is_free(state, restaurant, table.id, starts_at)]}
            for starts_at in slots(restaurant, day)],
    }

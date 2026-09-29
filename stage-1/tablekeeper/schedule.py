"""A restaurant's opening windows, slot grid and availability on one local date (§4, §8, §9).

Every opening-hours entry for the date's weekday is a window of its own. A window's grid
runs in wall-clock steps of `slot_minutes` from its `opens`. A step is a slot when that
wall time exists and a reservation starting then ends, in absolute time, no later than
the window's `closes`.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from . import timeutil
from .domain import WEEKDAYS, Restaurant, clash_window

if TYPE_CHECKING:
    from .store import State

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)  # the common origin of slot and booking offsets


@dataclass(frozen=True)
class Window:
    opens: datetime      # wall time at the restaurant, naive
    closes: datetime     # wall time at the restaurant, naive
    closes_at: datetime  # UTC

    def fits(self, starts_at: datetime, duration: timedelta) -> bool:
        """Whether a reservation from `starts_at` ends by closing time."""
        return starts_at + duration <= self.closes_at

    def on_grid(self, local: datetime, slot_minutes: int) -> bool:
        """Whether the wall time `local` is a whole number of slots after opening."""
        return (local - self.opens) % timedelta(minutes=slot_minutes) == timedelta(0)


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


def window_at(restaurant: Restaurant, local: datetime) -> Window | None:
    """The opening window whose wall-clock hours contain `local`, if any."""
    return next((window for window in windows(restaurant, local.date())
                 if window.opens <= local < window.closes), None)


def slots(restaurant: Restaurant, day: date) -> list[datetime]:
    """The UTC instant of every start a booking may take on `day`, window by window,
    each wall time once. Windows follow one another and a later wall time is never an
    earlier instant, so the instants ascend."""
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
    starts = slots(restaurant, day)
    offsets = [starts_at - _EPOCH for starts_at in starts]
    tables = [table for table in restaurant.tables if table.capacity >= party_size]
    taken = [_taken_slots(state, restaurant, table.id, offsets) for table in tables]
    zone = restaurant.zone
    return {
        "restaurant_id": restaurant.id,
        "date": day.isoformat(),
        "timezone": restaurant.timezone,
        "slots": [
            {"starts_at_local": timeutil.local_text(starts_at, zone),
             "starts_at": timeutil.rfc3339(starts_at, zone),
             "available_table_ids": [table.id for table, table_taken in zip(tables, taken)
                                     if not table_taken[index]]}
            for index, starts_at in enumerate(starts)],
    }


def _taken_slots(state: State, restaurant: Restaurant, table_id: str,
                 offsets: list[timedelta]) -> bytearray:
    """Marks, per slot, whether a confirmed booking holds the table for part of a booking
    from that slot. Each booking marks the slots inside its clash window, found by bisection
    in the ascending `offsets`, so the cost grows with the table's bookings, not with them
    times the slots."""
    taken = bytearray(len(offsets))
    for booked in state.confirmed_on(restaurant.id, table_id):
        low, high = clash_window(booked.starts_at - _EPOCH, restaurant.duration)
        first, last = bisect_right(offsets, low), bisect_left(offsets, high)
        taken[first:last] = b"\x01" * (last - first)
    return taken

"""A restaurant's opening windows, slot grid and availability on one local date (§4, §8, §9).

The rules are those of the policy in force on the date. Every opening-hours entry for the
date's weekday is a window of its own. A window's grid runs in wall-clock steps of
`slot_minutes` from its `opens`. A step is a slot when that wall time exists and a
reservation starting then ends, in absolute time, no later than the window's `closes`.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import repeat
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from . import timeutil
from .domain import WEEKDAYS, Policy, Restaurant, Table, clash_window
from .policies import policy_for

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


def windows(restaurant: Restaurant, policy: Policy, day: date) -> list[Window]:
    """The restaurant's opening windows on `day` under `policy`, earliest first; none on a
    closed day."""
    weekday = WEEKDAYS[day.weekday()]
    hours = sorted((h for h in policy.opening_hours if h.weekday == weekday),
                   key=lambda h: h.opens)
    found = []
    for entry in hours:
        closes = datetime.combine(day, entry.closes)
        found.append(Window(opens=datetime.combine(day, entry.opens), closes=closes,
                            closes_at=timeutil.instant_of(closes, restaurant.zone)))
    return found


def window_at(restaurant: Restaurant, policy: Policy, local: datetime) -> Window | None:
    """The opening window whose wall-clock hours contain `local`, if any."""
    return next((window for window in windows(restaurant, policy, local.date())
                 if window.opens <= local < window.closes), None)


def slots(restaurant: Restaurant, policy: Policy, day: date) -> list[datetime]:
    """The UTC instant of every start a booking may take on `day` under `policy`, window by
    window, each wall time once. Windows follow one another and a later wall time is never
    an earlier instant, so the instants ascend."""
    step = timedelta(minutes=policy.slot_minutes)
    found = []
    for window in windows(restaurant, policy, day):
        local = window.opens
        while local < window.closes:
            starts_at = timeutil.resolve(local, restaurant.zone)
            if starts_at is not None and window.fits(starts_at, policy.duration):
                found.append(starts_at)
            local += step  # naive, so the grid steps in wall-clock time
    return found


def availability(state: State, restaurant: Restaurant, day: date, party_size: int, *,
                 explain: bool = False) -> dict:
    """Every slot on `day` with the single tables, in fixture order, that seat the party and
    are free for a whole booking from that slot, and the options: those singles, then the
    declared pairs whose summed capacity seats the party and whose tables are both free. A
    slot with nothing free is still listed. The rules are the day's policy's. With `explain`,
    each slot also says why every table is or is not available.

    What a slot offers depends only on which tables are held from it, so slots held alike
    share one set of those lists: a dense day costs its distinct occupancies, not its slots
    times its tables, and each shared list is encoded once (`http.AvailabilityResponse`)."""
    policy = policy_for(state, restaurant, day)
    starts = slots(restaurant, policy, day)
    offsets = [starts_at - _EPOCH for starts_at in starts]

    def seats_party(option: tuple[Table, ...]) -> bool:
        return policy.seats(option) >= party_size

    held = [_taken_slots(state, restaurant, table.id, offsets, policy.duration) for table in restaurant.tables]
    position = {table.id: index for index, table in enumerate(restaurant.tables)}
    options = [option for option in [(table,) for table in restaurant.tables] + restaurant.pairs
               if seats_party(option)]
    views = [({"table_ids": [t.id for t in option], "capacity": policy.seats(option)},
              [position[t.id] for t in option]) for option in options]
    entries = [_explanations(table, policy, seats_party((table,))) for table in restaurant.tables]
    shared: dict[tuple[int, ...], dict] = {}

    def offered(marks: tuple[int, ...]) -> dict:
        """What a slot offers when the tables are held as `marks` (one per table, in fixture
        order): the free options, the single tables among them and, with `explain`, each
        table's explanation. An option is free when none of its tables is held."""
        if marks not in shared:
            free = [view for view, members in views if not any(marks[member] for member in members)]
            shared[marks] = {"available_table_ids": [view["table_ids"][0] for view in free
                                                     if len(view["table_ids"]) == 1],
                             "available_options": free,
                             **({"explain": [entry[mark] for entry, mark in zip(entries, marks)]} if explain else {})}
        return shared[marks]

    zone = restaurant.zone
    return {
        "restaurant_id": restaurant.id,
        "date": day.isoformat(),
        "timezone": restaurant.timezone,
        "slots": [
            {"starts_at_local": local, "starts_at": text, **offered(marks)}
            for (local, text), marks in zip((timeutil.stamps(starts_at, zone) for starts_at in starts),
                                            zip(*held) if held else repeat(()))],
    }


def _explanations(table: Table, policy: Policy, seats_party: bool) -> tuple[dict, dict]:
    """Why `table` is or is not available at a slot where it is free, and where it is taken:
    both rules, each judged on its own, under the policy in force (R306-R309). A slot uses the
    one its occupancy mark selects, so the explanation and the availability share one source."""
    def entry(free: bool) -> dict:
        rules = {"capacity": seats_party, "no_overlap": free}
        return {"table_id": table.id, "policy_version": policy.version,
                "available": all(rules.values()),
                "rules": [{"rule": rule, "holds": holds} for rule, holds in rules.items()]}

    return entry(free=True), entry(free=False)



def _taken_slots(state: State, restaurant: Restaurant, table_id: str,
                 offsets: list[timedelta], duration: timedelta) -> bytearray:
    """Marks, per slot, whether a confirmed booking holds the table for part of a booking of
    `duration` from that slot. Each booking, for its own accepted duration, marks the slots
    inside its clash window, found by bisection in the ascending `offsets`, so the cost grows
    with the table's bookings, not with them times the slots."""
    taken = bytearray(len(offsets))
    for booked in state.confirmed_on(restaurant.id, table_id):
        low, high = clash_window(booked.starts_at - _EPOCH, booked.terms.duration, duration)
        first, last = bisect_right(offsets, low), bisect_left(offsets, high)
        taken[first:last] = b"\x01" * (last - first)
    return taken

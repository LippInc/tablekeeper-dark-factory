"""The seating planner (stage 4): the best way to seat the bookings a table closure touches.

A pure search over plain values; it never reads the service state. Every booking is given one
option, a single table or a declared pair, that seats its party under the booking's own
accepted terms and is free, over the booking's own time, of every block (a fixed booking or a
closure) and of the options given to the other bookings. Of all such plans the planner returns
the least by, in order: the number of bookings whose table set changes, the total unused seats,
and the vector of option ranks in ascending reference order.

The search is depth first over the bookings in reference order and each booking's options in
rank order, so plans are met in the order of their rank vectors and the first one found at the
least (moved, unused) is the answer. A branch stops as soon as its bound, the cost so far plus
each remaining booking's cheapest option, cannot beat the best plan found, or as soon as a later
booking sharing time with the ones seated has no option left.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Option:
    """A way to seat a party: one table, or a declared pair in declared order. Singles rank
    first in fixture order, then pairs in declared order, from 0."""
    rank: int
    table_ids: tuple[str, ...]


@dataclass(frozen=True)
class Booking:
    """A booking to seat: its own interval, the capacities of its accepted terms and its
    current table set."""
    reference: str
    party_size: int
    start: datetime
    end: datetime
    capacities: Mapping[str, int]
    table_ids: tuple[str, ...]


@dataclass(frozen=True)
class Block:
    """A table that is not free over [start, end): a fixed booking on it, or a closure."""
    table_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Seat:
    """Where a plan seats a booking, and whether that changes its table set."""
    reference: str
    table_ids: tuple[str, ...]
    changed: bool


@dataclass(frozen=True)
class Seating:
    """The best plan: a seat per booking, in ascending reference order, and its cost."""
    seats: tuple[Seat, ...]
    moved: int
    unused: int


@dataclass(frozen=True)
class _Choice:
    """An option a booking can take, with what it costs that booking."""
    option: Option
    moved: int  # 1 when the option changes the booking's table set, else 0
    unused: int
    tables: frozenset[str]


def share_time(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Whether the half-open intervals [a_start, a_end) and [b_start, b_end) meet."""
    return a_start < b_end and b_start < a_end


def _choices(booking: Booking, options: Sequence[Option], blocks: list[Block]) -> list[_Choice]:
    """The options that seat `booking` and touch no block over its time, in rank order."""
    blocked = {block.table_id for block in blocks
               if share_time(block.start, block.end, booking.start, booking.end)}
    current = set(booking.table_ids)
    found = []
    for option in options:
        capacity = sum(booking.capacities[table_id] for table_id in option.table_ids)
        if capacity >= booking.party_size and blocked.isdisjoint(option.table_ids):
            found.append(_Choice(option, int(set(option.table_ids) != current),
                                 capacity - booking.party_size, frozenset(option.table_ids)))
    return found


def best(options: Sequence[Option], bookings: Iterable[Booking],
         blocks: Iterable[Block]) -> Seating | None:
    """The least feasible plan for `bookings` over `options` (given in rank order), or None
    when there is none."""
    ordered = sorted(bookings, key=lambda booking: booking.reference)
    blocks = list(blocks)
    choices = [_choices(booking, options, blocks) for booking in ordered]
    if not all(choices):
        return None
    count = len(ordered)
    # For each booking, the earlier bookings sharing time with it: they cannot share a table.
    rivals = [[j for j in range(i) if share_time(ordered[i].start, ordered[i].end,
                                                 ordered[j].start, ordered[j].end)]
              for i in range(count)]
    # floor[i]: the least (moved, unused) the bookings from i on could add, each on its own.
    floor = [(0, 0)] * (count + 1)
    for i in range(count - 1, -1, -1):
        floor[i] = (floor[i + 1][0] + min(choice.moved for choice in choices[i]),
                    floor[i + 1][1] + min(choice.unused for choice in choices[i]))
    chosen: list[_Choice] = []
    found: list[Seating] = []

    def free(i: int, choice: _Choice) -> bool:
        """Whether `choice` shares no table with a seated booking sharing time with booking i."""
        return all(choice.tables.isdisjoint(chosen[j].tables) for j in rivals[i] if j < len(chosen))

    def search(moved: int, unused: int) -> None:
        i = len(chosen)
        if found and (moved + floor[i][0], unused + floor[i][1]) >= (found[0].moved, found[0].unused):
            return
        if i == count:
            seats = tuple(Seat(booking.reference, choice.option.table_ids, bool(choice.moved))
                          for booking, choice in zip(ordered, chosen))
            found[:] = [Seating(seats, moved, unused)]
            return
        for choice in choices[i]:
            if not free(i, choice):
                continue
            chosen.append(choice)
            if all(any(free(k, later) for later in choices[k]) for k in range(i + 1, count)):
                search(moved + choice.moved, unused + choice.unused)
            chosen.pop()

    search(0, 0)
    return found[0] if found else None

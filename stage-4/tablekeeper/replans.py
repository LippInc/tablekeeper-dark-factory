"""Seating changes after a table closure (stage 4): a manager previews how the bookings a
proposed closure touches would be seated, as a stored plan.

The bookings considered are every confirmed booking at the restaurant whose own time overlaps
the closure, on any table (Q1); every other confirmed booking keeps its tables and blocks them.
A preview stores the plan and changes nothing else (Q12).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime

from . import planner, timeutil
from .domain import Reservation, Restaurant, User, managed_restaurant
from .errors import ApiError, not_found
from .fields import FieldReader, at
from .store import State, fresh

MAX_TABLES = 6
MAX_PAIRS = 4
MAX_BOOKINGS = 6


@dataclass(frozen=True)
class Plan:
    """A previewed seating: the proposed closure as the request wrote it (Q7), an assignment
    per considered booking in reference order, and the restaurant's revision it was made at."""
    id: str
    restaurant_id: str
    table_id: str
    written_from: str
    written_to: str
    assignments: tuple[planner.Seat, ...]
    unused_seats: int
    restaurant_revision: int

    @property
    def moved_count(self) -> int:
        return sum(assignment.changed for assignment in self.assignments)


def read_closure(reader: FieldReader, obj: dict, path: str) -> tuple[str, datetime, datetime] | None:
    """A closure's `table_id` and its `from` and `to` instants, each with an explicit offset,
    `from` before `to`. Problems are recorded on `reader`; None when there is one."""
    table_id = reader.identifier(obj, "table_id", path)
    start, end = (reader.parsed(obj, name, path, timeutil.parse_instant,
                                "must be a timestamp with an explicit offset")
                  for name in ("from", "to"))
    if start is not None and end is not None and not start < end:
        reader.reject(at(path, "to"), "must be later than from")
        return None
    return None if None in (table_id, start, end) else (table_id, start, end)


def _options(restaurant: Restaurant) -> list[planner.Option]:
    """The ways to seat a party, ranked: the tables in fixture order, then the pairs."""
    sets = [(table.id,) for table in restaurant.tables] + list(restaurant.combinable)
    return [planner.Option(rank, table_ids) for rank, table_ids in enumerate(sets)]


def _confirmed_at(state: State, restaurant: Restaurant) -> list[Reservation]:
    """The restaurant's confirmed bookings, each once, a pair's included."""
    return list({booking.reference: booking for table in restaurant.tables
                 for booking in state.confirmed_on(restaurant.id, table.id)}.values())


def _blocks(booking: Reservation) -> list[planner.Block]:
    return [planner.Block(table_id, booking.starts_at, booking.ends_at) for table_id in booking.table_ids]


def preview(state: State, user: User, restaurant_id: str, body: dict) -> dict:
    """Plan the seating for closing a table over [from, to) (Q3 order after the keyed write's
    own checks: 404 restaurant, 403 not a manager, 422 fields, 404 table, 422 planning limit,
    409 no feasible plan) and store the plan."""
    restaurant = managed_restaurant(state, user, restaurant_id)
    reader = FieldReader()
    closure = read_closure(reader, body, "")
    reader.raise_as_invalid()
    table_id, start, end = closure
    if restaurant.table(table_id) is None:
        raise not_found(f"no table {table_id!r} at this restaurant")
    considered, fixed = [], []
    for booking in _confirmed_at(state, restaurant):
        overlapping = planner.share_time(booking.starts_at, booking.ends_at, start, end)
        (considered if overlapping else fixed).append(booking)
    if (len(restaurant.tables) > MAX_TABLES or len(restaurant.combinable) > MAX_PAIRS
            or len(considered) > MAX_BOOKINGS):
        raise ApiError(422, "planning_limit", f"plans cover at most {MAX_TABLES} tables, "
                       f"{MAX_PAIRS} pairs and {MAX_BOOKINGS} bookings")
    seating = planner.best(
        _options(restaurant),
        [planner.Booking(booking.reference, booking.party_size, booking.starts_at, booking.ends_at,
                         booking.terms.capacities, booking.table_ids) for booking in considered],
        [planner.Block(table_id, start, end)] + [block for booking in fixed for block in _blocks(booking)])
    if seating is None:
        raise ApiError(409, "no_feasible_plan", "the bookings cannot all be seated without that table")
    plan = Plan(
        id=fresh(lambda: f"plan_{secrets.token_hex(12)}", state.plans), restaurant_id=restaurant.id,
        table_id=table_id, written_from=body["from"], written_to=body["to"], assignments=seating.seats,
        unused_seats=seating.unused, restaurant_revision=state.restaurant_revision(restaurant.id))
    state.plans[plan.id] = plan
    return view(plan)


def view(plan: Plan) -> dict:
    return {"plan_id": plan.id, "restaurant_revision": plan.restaurant_revision,
            "closure": {"table_id": plan.table_id, "from": plan.written_from, "to": plan.written_to},
            "assignments": [{"reference": assignment.reference, "table_ids": list(assignment.table_ids),
                             "changed": assignment.changed} for assignment in plan.assignments],
            "moved_count": plan.moved_count, "unused_seats": plan.unused_seats}

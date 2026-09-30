"""Seating changes after a table closure (stage 4): a manager previews how the bookings a
proposed closure touches would be seated, as a stored plan, and applies it.

The bookings considered are every confirmed booking at the restaurant whose own time overlaps
the closure, on any table (Q1); every other confirmed booking keeps its tables and, like the
closures already applied, blocks them. A preview stores the plan and changes nothing else
(Q12). Applying it records the closure and moves the bookings in one operation, as long as
nothing at the restaurant has changed since the preview (Q17).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import datetime

from . import booking, planner, timeutil
from .domain import Closure, Reservation, Restaurant, User, managed_restaurant, show
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

    def closure(self) -> Closure:
        """The closure applying the plan records."""
        return Closure(self.restaurant_id, self.table_id, timeutil.parse_instant(self.written_from),
                       timeutil.parse_instant(self.written_to), self.id)


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
    return list({reservation.reference: reservation for table in restaurant.tables
                 for reservation in state.confirmed_on(restaurant.id, table.id)}.values())


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
    considered = [held for held in _confirmed_at(state, restaurant)
                  if planner.share_time(held.starts_at, held.ends_at, start, end)]
    if (len(restaurant.tables) > MAX_TABLES or len(restaurant.combinable) > MAX_PAIRS
            or len(considered) > MAX_BOOKINGS):
        raise ApiError(422, "planning_limit", f"plans cover at most {MAX_TABLES} tables, "
                       f"{MAX_PAIRS} pairs and {MAX_BOOKINGS} bookings")
    references = {held.reference for held in considered}
    seating = planner.best(
        _options(restaurant),
        [planner.Booking(held.reference, held.party_size, held.starts_at, held.ends_at,
                         held.terms.capacities, held.table_ids) for held in considered],
        [planner.Block(table_id, start, end)]
        + [planner.Block(table.id, held.starts_at, held.ends_at) for table in restaurant.tables
           for held in state.holds_on(restaurant.id, table.id, excluding=references)])
    if seating is None:
        raise ApiError(409, "no_feasible_plan", "the bookings cannot all be seated without that table")
    plan = Plan(
        id=fresh(lambda: f"plan_{secrets.token_hex(12)}", state.plans), restaurant_id=restaurant.id,
        table_id=table_id, written_from=body["from"], written_to=body["to"], assignments=seating.seats,
        unused_seats=seating.unused, restaurant_revision=state.restaurant_revision(restaurant.id))
    state.plans[plan.id] = plan
    return view(plan)


def apply_plan(state: State, user: User, restaurant_id: str, plan_id: str) -> dict:
    """Apply a stored plan (Q4 order after the keyed write's own checks: 404 restaurant, 403
    not a manager, 404 no such plan here, 409 already applied, 409 stale): record its closure
    and move its bookings in one operation (Q13). It is the operator's repair, not a diner's
    amendment, so no cutoff applies; every write that could make it infeasible has raised the
    restaurant revision, so it is never re-planned (Q17)."""
    restaurant = managed_restaurant(state, user, restaurant_id)
    plan = state.plans.get(plan_id)
    if plan is None or plan.restaurant_id != restaurant.id:
        raise not_found(f"no plan {plan_id!r} at this restaurant")
    if any(closure.plan_id == plan.id for closure in state.closures.get(restaurant.id, [])):
        raise ApiError(409, "plan_already_applied", "the plan has already been applied")
    if plan.restaurant_revision != state.restaurant_revision(restaurant.id):
        raise ApiError(409, "stale_plan", "the restaurant has changed since the plan was made")
    booking.apply(state, [replace(state.reservations[seat.reference], table_ids=seat.table_ids)
                          for seat in plan.assignments if seat.changed], plan.closure())
    return {"plan_id": plan.id, "restaurant_revision": state.restaurant_revision(restaurant.id),
            "reservations": [show(state, state.reservations[seat.reference]) for seat in plan.assignments]}


def view(plan: Plan) -> dict:
    return {"plan_id": plan.id, "restaurant_revision": plan.restaurant_revision,
            "closure": {"table_id": plan.table_id, "from": plan.written_from, "to": plan.written_to},
            "assignments": [{"reference": assignment.reference, "table_ids": list(assignment.table_ids),
                             "changed": assignment.changed} for assignment in plan.assignments],
            "moved_count": plan.moved_count, "unused_seats": plan.unused_seats}

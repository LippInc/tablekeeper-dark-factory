"""Creating, amending, moving and cancelling bookings (§1, §8, §9, §11).

Every change to a booking's table, time or party goes through `commit`, which checks the
resulting bookings for overlaps and stores all of them or none.
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from . import schedule, timeutil
from .domain import (CANCELLED, CONFIRMED, Reservation, Restaurant, User, find_restaurant,
                     overlaps, own_reservation, read_local, read_party_size, read_table_ids,
                     select_tables, show)
from .errors import ApiError, invalid
from .fields import FieldReader, at, is_identifier
from .store import State, fresh

REFERENCE_ALPHABET = string.ascii_uppercase + string.digits
REFERENCE_LENGTH = 8
MAX_MOVES = 8


@dataclass(frozen=True)
class Changes:
    """The booking values a request asks for; None keeps the current value."""
    table_ids: tuple[str, ...] | None = None
    local: datetime | None = None
    party_size: int | None = None


def read_changes(reader: FieldReader, obj: dict, path: str, *, partial: bool) -> Changes:
    """The table set, `starts_at_local` and `party_size` of a create body (every field
    required) or of an amendment (`partial`: only the fields present)."""
    def wanted(name: str) -> bool:
        return not partial or name in obj

    return Changes(
        table_ids=read_table_ids(reader, obj, path, required=not partial),
        local=read_local(reader, obj, path) if wanted("starts_at_local") else None,
        party_size=read_party_size(reader, obj, path) if wanted("party_size") else None)


# ---- rules -----------------------------------------------------------------

def _placed(restaurant: Restaurant, table_ids: tuple[str, ...], local: datetime,
            party_size: int) -> tuple[tuple[str, ...], datetime]:
    """The table set in declared order and the UTC start of a booking the restaurant's rules
    allow, checked in D5 order with the table-set rules (E3) in the place of the table's."""
    tables = select_tables(restaurant, table_ids)
    starts_at = timeutil.resolve(local, restaurant.zone)
    if starts_at is None:
        raise ApiError(422, "invalid_local_time", "that local time does not exist")
    window = schedule.window_at(restaurant, local)
    if window is None or not window.fits(starts_at, restaurant.duration):
        raise ApiError(422, "outside_opening_hours", "the booking is not within opening hours")
    if not window.on_grid(local, restaurant.slot_minutes):
        raise ApiError(422, "not_on_slot_grid", "the start is not on the slot grid")
    if party_size > sum(table.capacity for table in tables):
        raise ApiError(422, "party_exceeds_capacity", "the party does not fit those tables")
    return tuple(table.id for table in tables), starts_at


def _require_before_cutoff(reservation: Reservation, restaurant: Restaurant) -> None:
    """A booking cannot change within `cancellation_cutoff_minutes` of its start, or later."""
    cutoff = timedelta(minutes=restaurant.cancellation_cutoff_minutes)
    if reservation.starts_at - timeutil.now() <= cutoff:
        raise ApiError(409, "cutoff_passed", "the booking is too close to its start to change")


def amended(state: State, current: Reservation, changes: Changes,
            reader: FieldReader) -> Reservation:
    """`current` with `changes` applied, once the booking may change at all (D6).

    Field problems recorded in `reader` rank after the cancelled and cutoff checks.
    """
    restaurant = state.restaurants[current.restaurant_id]
    if current.status == CANCELLED:
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    _require_before_cutoff(current, restaurant)
    reader.raise_first()
    current_local = timeutil.wall_time(current.starts_at, restaurant.zone)
    table_ids = current.table_ids if changes.table_ids is None else changes.table_ids
    local = current_local if changes.local is None else changes.local
    party_size = current.party_size if changes.party_size is None else changes.party_size
    # A set named in another order is the same set (E9).
    if (set(table_ids), local, party_size) == (set(current.table_ids), current_local,
                                               current.party_size):
        return current  # a no-op keeps every value and the booking's occupancy
    table_ids, starts_at = _placed(restaurant, table_ids, local, party_size)
    return replace(current, table_ids=table_ids, party_size=party_size, starts_at=starts_at)


def commit(state: State, bookings: list[Reservation]) -> None:
    """Store `bookings` together: new bookings, or new versions of existing ones.

    Each must be free, on every one of its tables, of every other confirmed booking there:
    those in `bookings`, and those not listed. A listed booking's previous occupancy no
    longer counts. If any overlaps, 409 `table_unavailable` and nothing is stored.
    """
    listed = {booking.reference for booking in bookings}
    for index, booking in enumerate(bookings):
        duration = state.restaurants[booking.restaurant_id].duration
        for table_id in booking.table_ids:
            rivals = [b for b in state.confirmed_on(booking.restaurant_id, table_id)
                      if b.reference not in listed]
            rivals += [b for b in bookings[:index] if b.restaurant_id == booking.restaurant_id
                       and table_id in b.table_ids]
            if any(overlaps(booking.starts_at, rival.starts_at, duration) for rival in rivals):
                raise ApiError(409, "table_unavailable", "a table is taken at that time")
    for booking in bookings:
        state.put_reservation(booking)


# ---- operations --------------------------------------------------------------

def create(state: State, user: User, body: dict) -> dict:
    reader = FieldReader()
    restaurant_id = reader.identifier(body, "restaurant_id", "")
    changes = read_changes(reader, body, "", partial=False)
    reader.raise_first()
    restaurant = find_restaurant(state, restaurant_id)
    table_ids, starts_at = _placed(restaurant, changes.table_ids, changes.local, changes.party_size)
    booking = Reservation(
        id=fresh(lambda: f"res_{secrets.token_hex(8)}", {r.id for r in state.reservations.values()}),
        reference=fresh(lambda: "".join(secrets.choice(REFERENCE_ALPHABET)
                                        for _ in range(REFERENCE_LENGTH)), state.reservations),
        user_id=user.id, restaurant_id=restaurant.id, table_ids=table_ids,
        party_size=changes.party_size, starts_at=starts_at, status=CONFIRMED,
        created_at=timeutil.now())
    commit(state, [booking])
    return show(state, booking)


def amend(state: State, user: User, reference: str, body: dict) -> dict:
    current = own_reservation(state, user, reference)
    reader = FieldReader()
    booking = amended(state, current, read_changes(reader, body, "", partial=True), reader)
    commit(state, [booking])
    return show(state, booking)


def _read_moves(body: dict) -> list[tuple[str, dict]]:
    """The move items with their display paths. Any shape problem is 422 (§11): `moves`
    must be a list of 1 to 8 objects whose `reference`s are distinct IDs."""
    moves = body.get("moves")
    if not isinstance(moves, list) or not 1 <= len(moves) <= MAX_MOVES:
        raise invalid(f"moves must be a list of 1 to {MAX_MOVES} objects")
    references = set()
    for index, item in enumerate(moves):
        reference = item.get("reference") if isinstance(item, dict) else None
        if not isinstance(reference, str) or not is_identifier(reference):
            raise invalid(f"{at('moves', index)} must be an object with a string reference")
        if reference in references:
            raise invalid(f"{at('moves', index)}.reference repeats an earlier move")
        references.add(reference)
    return [(at("moves", index), item) for index, item in enumerate(moves)]


def move(state: State, user: User, body: dict) -> dict:
    """Amend several of the caller's bookings at one restaurant together, or none (§11).

    Items are judged in input order (D9); overlaps are judged on the whole resulting set.
    """
    bookings: list[Reservation] = []
    for path, item in _read_moves(body):
        current = own_reservation(state, user, item["reference"])
        if bookings and current.restaurant_id != bookings[0].restaurant_id:
            raise invalid(f"{path} is at a different restaurant from the first move")
        reader = FieldReader()
        bookings.append(amended(state, current, read_changes(reader, item, path, partial=True), reader))
    commit(state, bookings)
    return {"reservations": [show(state, booking) for booking in bookings]}


def cancel(state: State, user: User, reference: str) -> dict:
    """Cancel and free the table at once; cancelling twice returns the current state."""
    current = own_reservation(state, user, reference)
    if current.status == CANCELLED:
        return show(state, current)
    _require_before_cutoff(current, state.restaurants[current.restaurant_id])
    cancelled = replace(current, status=CANCELLED)
    state.put_reservation(cancelled)
    return show(state, cancelled)

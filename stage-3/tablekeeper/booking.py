"""Creating, amending, moving and cancelling bookings (§1, §8, §9, §11).

A booking is placed under the policy in force on its local start date and keeps that
policy as its accepted terms: its duration and its cancellation cutoff. Every change goes
through `apply` in two phases (H2): the first checks the resulting bookings for overlaps,
each for its own duration, and the second alone stores them, all or none, one revision
further on.
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, replace
from datetime import datetime

from . import schedule, timeutil
from .domain import (CANCELLED, CONFIRMED, Policy, Reservation, Restaurant, User,
                     find_restaurant, overlaps, own_reservation, read_local, read_party_size,
                     read_table_ids, select_tables, show)
from .errors import ApiError, invalid
from .fields import FieldReader, at, is_identifier
from .policies import policy_for
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


def read_expected_revision(obj: dict, path: str) -> int | None:
    """`expected_revision`, when given: a positive integer, a boolean not being one; any other
    value is 422 (H3), ranked before every other check on the booking but its existence."""
    if "expected_revision" not in obj:
        return None
    value = obj["expected_revision"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise invalid(f"{at(path, 'expected_revision')} must be a positive integer")
    return value


# ---- rules -----------------------------------------------------------------

def _placed(state: State, restaurant: Restaurant, table_ids: tuple[str, ...], local: datetime,
            party_size: int) -> tuple[tuple[str, ...], datetime, Policy]:
    """The table set in declared order, the UTC start and the policy of a booking the rules
    in force on its local start date allow, checked in D5 order with the table-set rules
    (E3) in the place of the table's."""
    tables = select_tables(restaurant, table_ids)
    starts_at = timeutil.resolve(local, restaurant.zone)
    if starts_at is None:
        raise ApiError(422, "invalid_local_time", "that local time does not exist")
    policy = policy_for(state, restaurant, local.date())
    window = schedule.window_at(restaurant, policy, local)
    if window is None or not window.fits(starts_at, policy.duration):
        raise ApiError(422, "outside_opening_hours", "the booking is not within opening hours")
    if not window.on_grid(local, policy.slot_minutes):
        raise ApiError(422, "not_on_slot_grid", "the start is not on the slot grid")
    if party_size > policy.seats(tables):
        raise ApiError(422, "party_exceeds_capacity", "the party does not fit those tables")
    return tuple(table.id for table in tables), starts_at, policy


def _require_before_cutoff(reservation: Reservation) -> None:
    """A booking cannot change within its accepted cutoff of its current start, or later."""
    if reservation.starts_at - timeutil.now() <= reservation.terms.cutoff:
        raise ApiError(409, "cutoff_passed", "the booking is too close to its start to change")


def amended(state: State, current: Reservation, changes: Changes, reader: FieldReader,
            expected_revision: int | None) -> Reservation:
    """`current` with `changes` applied, once the booking may change at all (D6, H3).

    A stale `expected_revision` is refused first; field problems recorded in `reader` rank
    after the cancelled and cutoff checks. A real change is placed under the policy of its
    resulting start date, which becomes its accepted terms.
    """
    restaurant = state.restaurants[current.restaurant_id]
    if expected_revision is not None and expected_revision != current.revision:
        raise ApiError(409, "stale_revision", "the reservation has changed since that revision")
    if current.status == CANCELLED:
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    _require_before_cutoff(current)
    reader.raise_first()
    current_local = timeutil.wall_time(current.starts_at, restaurant.zone)
    table_ids = current.table_ids if changes.table_ids is None else changes.table_ids
    local = current_local if changes.local is None else changes.local
    party_size = current.party_size if changes.party_size is None else changes.party_size
    # A set named in another order is the same set (E9).
    if (set(table_ids), local, party_size) == (set(current.table_ids), current_local,
                                               current.party_size):
        return current  # a no-op keeps every value, the terms and the booking's occupancy
    table_ids, starts_at, terms = _placed(state, restaurant, table_ids, local, party_size)
    return replace(current, table_ids=table_ids, party_size=party_size, starts_at=starts_at,
                   terms=terms)


def apply(state: State, bookings: list[Reservation]) -> list[Reservation]:
    """Store `bookings` together, all or none: new bookings, or new versions of existing
    ones. Returns the stored bookings in the same order.

    A version equal to the stored booking is a no-op and is left as it is. Phase one checks
    that every other confirmed version is free, on each of its tables and for its own
    duration, of every other confirmed booking there: those listed, and those not listed,
    whose previous occupancy no longer counts. If any overlaps, 409 `table_unavailable`.
    Phase two alone changes the state: each changed booking is stored one revision further.
    """
    changed = [booking for booking in bookings if state.reservations.get(booking.reference) != booking]
    confirmed = [booking for booking in changed if booking.status == CONFIRMED]
    listed = {booking.reference for booking in changed}
    for index, booking in enumerate(confirmed):
        for table_id in booking.table_ids:
            rivals = [b for b in state.confirmed_on(booking.restaurant_id, table_id)
                      if b.reference not in listed]
            rivals += [b for b in confirmed[:index] if b.restaurant_id == booking.restaurant_id
                       and table_id in b.table_ids]
            if any(overlaps(booking, rival) for rival in rivals):
                raise ApiError(409, "table_unavailable", "a table is taken at that time")
    stored = {}
    for booking in changed:
        previous = state.reservations.get(booking.reference)
        version = booking if previous is None else replace(booking, revision=previous.revision + 1)
        state.put_reservation(version)
        stored[version.reference] = version
    return [stored.get(booking.reference, booking) for booking in bookings]


# ---- operations --------------------------------------------------------------

def create(state: State, user: User, body: dict) -> dict:
    reader = FieldReader()
    restaurant_id = reader.identifier(body, "restaurant_id", "")
    changes = read_changes(reader, body, "", partial=False)
    reader.raise_first()
    restaurant = find_restaurant(state, restaurant_id)
    table_ids, starts_at, terms = _placed(state, restaurant, changes.table_ids, changes.local,
                                          changes.party_size)
    booking = Reservation(
        id=fresh(lambda: f"res_{secrets.token_hex(8)}", {r.id for r in state.reservations.values()}),
        reference=fresh(lambda: "".join(secrets.choice(REFERENCE_ALPHABET)
                                        for _ in range(REFERENCE_LENGTH)), state.reservations),
        user_id=user.id, restaurant_id=restaurant.id, table_ids=table_ids,
        party_size=changes.party_size, starts_at=starts_at, status=CONFIRMED,
        created_at=timeutil.now(), revision=1, terms=terms)
    [stored] = apply(state, [booking])
    return show(state, stored)


def amend(state: State, user: User, reference: str, body: dict) -> dict:
    current = own_reservation(state, user, reference)
    expected_revision = read_expected_revision(body, "")
    reader = FieldReader()
    booking = amended(state, current, read_changes(reader, body, "", partial=True), reader,
                      expected_revision)
    [stored] = apply(state, [booking])
    return show(state, stored)


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

    Items are judged in input order (D9, H3); overlaps are judged on the whole resulting set.
    """
    bookings: list[Reservation] = []
    for path, item in _read_moves(body):
        current = own_reservation(state, user, item["reference"])
        if bookings and current.restaurant_id != bookings[0].restaurant_id:
            raise invalid(f"{path} is at a different restaurant from the first move")
        expected_revision = read_expected_revision(item, path)
        reader = FieldReader()
        bookings.append(amended(state, current, read_changes(reader, item, path, partial=True),
                                reader, expected_revision))
    return {"reservations": [show(state, booking) for booking in apply(state, bookings)]}


def cancel(state: State, user: User, reference: str) -> dict:
    """Cancel and free the table at once, within the accepted cutoff; cancelling twice
    returns the current state and changes nothing."""
    current = own_reservation(state, user, reference)
    if current.status == CANCELLED:
        return show(state, current)
    _require_before_cutoff(current)
    [cancelled] = apply(state, [replace(current, status=CANCELLED)])
    return show(state, cancelled)

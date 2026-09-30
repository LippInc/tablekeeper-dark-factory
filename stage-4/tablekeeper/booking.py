"""Creating, amending, moving and cancelling bookings (§1, §8, §9, §11).

A booking is placed under the policy in force on its local start date and keeps that
policy as its accepted terms: its duration and its cancellation cutoff. Every change goes
through `apply` in two phases (H2): the first checks the resulting bookings for overlaps,
each for its own duration, and the second alone stores them, all or none, one revision
further on, with their history and their series' effects. A booking adopted as a series
anchor generates the series' later occurrences, whose clock time the series' owner can then
change together.
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from . import history, schedule, series, timeutil
from .domain import (CANCELLED, CONFIRMED, Closure, Policy, Reservation, Restaurant, User,
                     find_restaurant, overlaps, own_reservation, read_local, read_party_size,
                     read_table_ids, select_tables, show)
from .errors import ApiError, invalid
from .fields import FieldReader, at, is_identifier
from .policies import policy_for
from .store import State, fresh

REFERENCE_ALPHABET = string.ascii_uppercase + string.digits
REFERENCE_LENGTH = 8
MAX_MOVES = 8
MAX_OCCURRENCES = 12
MAX_INTERVAL_WEEKS = 4


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


def _check_free(state: State, bookings: list[Reservation]) -> None:
    """409 `table_unavailable` unless every confirmed booking listed is free, on each of its
    tables and for its own duration, of every closure and every other confirmed booking there:
    those listed, and those not listed, whose previous occupancy no longer counts."""
    confirmed = [booking for booking in bookings if booking.status == CONFIRMED]
    listed = {booking.reference for booking in bookings}
    for index, booking in enumerate(confirmed):
        for table_id in booking.table_ids:
            rivals = state.holds_on(booking.restaurant_id, table_id, excluding=listed)
            rivals += [b for b in confirmed[:index] if b.restaurant_id == booking.restaurant_id
                       and table_id in b.table_ids]
            if any(overlaps(booking, rival) for rival in rivals):
                raise ApiError(409, "table_unavailable", "a table is taken at that time")


def apply(state: State, bookings: list[Reservation], closure: Closure | None = None, *,
          whole_series: bool = False) -> list[Reservation]:
    """Store `bookings` together, all or none: new bookings, or new versions of existing
    ones. Returns the stored bookings in the same order. With a `closure` the operation is a
    seating repair: an applied plan's moved bookings and the closure it records. A repair,
    like an amendment of a `whole_series`, marks no occurrence an exception.

    A version equal to the stored booking is a no-op and is left as it is. Phase one checks
    the changed versions' occupancy (`_check_free`). Phase two alone changes the state: each
    changed booking is stored one revision further and its history gains one entry (a
    repair's names its plan), all of the operation's entries at one time; each series with a
    changed occurrence records the operation once; the closure is recorded; and each
    restaurant with a changed booking or the closure records the operation once.
    """
    changed = [booking for booking in bookings if state.reservations.get(booking.reference) != booking]
    _check_free(state, changed)
    stored = {}
    changes = []
    at = timeutil.now()
    plan_id = None if closure is None else closure.plan_id
    for booking in changed:
        previous = state.reservations.get(booking.reference)
        version = booking if previous is None else replace(booking, revision=previous.revision + 1)
        state.put_reservation(version)
        history.record(state, previous, version, at, plan_id)
        changes.append((previous, version))
        stored[version.reference] = version
    series.record(state, changes, marks_exceptions=closure is None and not whole_series)
    restaurant_ids = [booking.restaurant_id for booking in changed]
    if closure is not None:
        state.closures.setdefault(closure.restaurant_id, []).append(closure)
        restaurant_ids.append(closure.restaurant_id)
    state.changed(restaurant_ids)
    return [stored.get(booking.reference, booking) for booking in bookings]


# ---- operations --------------------------------------------------------------

def _new_booking(state: State, user: User, restaurant: Restaurant, table_ids: tuple[str, ...],
                 local: datetime, party_size: int,
                 pending: tuple[Reservation, ...] = ()) -> Reservation:
    """A new booking the rules in force on its date allow, at revision 1 under that policy,
    with an ID and a reference no stored or `pending` booking has."""
    table_ids, starts_at, terms = _placed(state, restaurant, table_ids, local, party_size)
    taken = [*state.reservations.values(), *pending]
    return Reservation(
        id=fresh(lambda: f"res_{secrets.token_hex(8)}", {r.id for r in taken}),
        reference=fresh(lambda: "".join(secrets.choice(REFERENCE_ALPHABET)
                                        for _ in range(REFERENCE_LENGTH)), {r.reference for r in taken}),
        user_id=user.id, restaurant_id=restaurant.id, table_ids=table_ids,
        party_size=party_size, starts_at=starts_at, status=CONFIRMED,
        created_at=timeutil.now(), revision=1, terms=terms)


def create(state: State, user: User, body: dict) -> dict:
    reader = FieldReader()
    restaurant_id = reader.identifier(body, "restaurant_id", "")
    changes = read_changes(reader, body, "", partial=False)
    reader.raise_first()
    restaurant = find_restaurant(state, restaurant_id)
    booking = _new_booking(state, user, restaurant, changes.table_ids, changes.local, changes.party_size)
    [stored] = apply(state, [booking])
    return show(state, stored)


def adopt(state: State, user: User, body: dict) -> dict:
    """Adopt one of the caller's bookings as occurrence zero of a series and book the later
    occurrences, all or none (H4). Occurrence i starts i x interval weeks after the anchor at
    the same local clock time, under its own date's policy, with the anchor's party and
    tables; the first occurrence in index order that cannot be booked decides the error (P5).
    The anchor itself is left exactly as it is."""
    reader = FieldReader()
    anchor_reference = reader.identifier(body, "anchor_reference", "")
    count = reader.integer(body, "count", "", minimum=2, maximum=MAX_OCCURRENCES)
    interval_weeks = reader.integer(body, "interval_weeks", "", minimum=1, maximum=MAX_INTERVAL_WEEKS)
    reader.raise_as_invalid()
    anchor = own_reservation(state, user, anchor_reference)
    if anchor.status == CANCELLED:
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    if anchor.reference in state.series_by_reference:
        raise ApiError(409, "already_in_series", "the reservation already belongs to a series")
    _require_before_cutoff(anchor)
    restaurant = state.restaurants[anchor.restaurant_id]
    local = timeutil.wall_time(anchor.starts_at, restaurant.zone)
    occurrences: list[Reservation] = []
    for index in range(1, count):
        occurrence = _new_booking(state, user, restaurant, anchor.table_ids,
                                  local + timedelta(weeks=index * interval_weeks),
                                  anchor.party_size, tuple(occurrences))
        _check_free(state, [*occurrences, occurrence])
        occurrences.append(occurrence)
    apply(state, occurrences)
    adopted = series.Series(
        id=fresh(lambda: f"ser_{secrets.token_hex(8)}", state.series), user_id=user.id,
        interval_weeks=interval_weeks, revision=1,
        occurrences=tuple(series.Occurrence(index, booking.reference)
                          for index, booking in enumerate([anchor, *occurrences])))
    series.add(state, adopted)
    return series.view(state, adopted)


def amend_series(state: State, user: User, series_id: str, body: dict) -> dict:
    """Move the series' occurrences from `from_index` on, but cancelled ones and exceptions,
    to `local_time` on their scheduled dates, all or none (Q18 order after the keyed write's
    own checks: 404, 422 fields, 409 stale_revision, then per occurrence in index order what a
    PATCH checks - the old accepted cutoff, the rules of the new date's policy - and last the
    occupancy of the whole changed set). An occurrence already at that time is left as it is.
    A scheduled date is the one an occurrence was adopted on; one that is not an exception
    still has it (Q19)."""
    adopted = series.own_series(state, user, series_id)
    reader = FieldReader()
    expected_revision = reader.integer(body, "expected_revision", "", minimum=1)
    from_index = reader.integer(body, "from_index", "", minimum=0, maximum=len(adopted.occurrences) - 1)
    clock = reader.parsed(body, "local_time", "", timeutil.parse_hhmm, "must be a 24-hour time HH:MM")
    reader.raise_as_invalid()
    if expected_revision != adopted.revision:
        raise ApiError(409, "stale_revision", "the series has changed since that revision")
    zone = state.restaurants[state.reservations[adopted.occurrences[0].reference].restaurant_id].zone
    changed = []
    for occurrence in adopted.occurrences[from_index:]:
        current = state.reservations[occurrence.reference]
        if occurrence.exception or current.status == CANCELLED:
            continue
        starts = timeutil.wall_time(current.starts_at, zone)
        local = datetime.combine(starts.date(), clock)
        if local != starts:
            changed.append(amended(state, current, Changes(local=local), reader, None))
    apply(state, changed, whole_series=True)
    return series.view(state, state.series[adopted.id])


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

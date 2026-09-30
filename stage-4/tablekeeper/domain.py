"""Restaurants, tables, diners, booking policies and reservations (§4, §8), and how the API
shows them."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from . import timeutil
from .errors import ApiError, not_found
from .fields import FieldReader, at, is_identifier

if TYPE_CHECKING:
    from .store import State

CONFIRMED = "confirmed"
CANCELLED = "cancelled"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # date.weekday() order


@dataclass(frozen=True)
class User:
    id: str
    email: str
    display_name: str
    password_hash: dict


@dataclass(frozen=True)
class Table:
    """A table's identity. How many it seats is a rule of the policy in force (H1)."""
    id: str
    label: str


@dataclass(frozen=True)
class OpeningHours:
    weekday: str
    opens: time
    closes: time


@dataclass(frozen=True)
class Policy:
    """A restaurant's booking rules from a local date on (H1). Version 0 is the fixture's own
    rules, in force before any published policy, and has no effective date. A booking keeps
    the policy it was accepted under as its terms."""
    version: int
    effective_from: date | None
    slot_minutes: int
    reservation_duration_minutes: int
    cancellation_cutoff_minutes: int
    opening_hours: tuple[OpeningHours, ...]
    capacities: Mapping[str, int]  # per table id, in fixture order; never changed

    @property
    def duration(self) -> timedelta:
        return timedelta(minutes=self.reservation_duration_minutes)

    @property
    def cutoff(self) -> timedelta:
        return timedelta(minutes=self.cancellation_cutoff_minutes)

    def seats(self, tables: Iterable[Table]) -> int:
        """How many `tables` seat together: the sum of their capacities."""
        return sum(self.capacities[table.id] for table in tables)


@dataclass(frozen=True)
class Restaurant:
    id: str
    name: str
    timezone: str
    initial: Policy  # policy 0: the fixture's rules
    tables: tuple[Table, ...]
    combinable: tuple[tuple[str, str], ...]  # declared pairs of table ids, in declared order
    manager_user_ids: tuple[str, ...]  # the users who may publish policies

    def table(self, table_id: str) -> Table | None:
        return next((table for table in self.tables if table.id == table_id), None)

    @property
    def pairs(self) -> list[tuple[Table, Table]]:
        """The declared combinations, in declared order."""
        return [(self.table(first), self.table(second)) for first, second in self.combinable]

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(frozen=True)
class Reservation:
    id: str
    reference: str
    user_id: str
    restaurant_id: str
    table_ids: tuple[str, ...]  # one table, or a declared pair in declared order
    party_size: int
    starts_at: datetime  # UTC
    status: str
    created_at: datetime  # UTC
    revision: int  # 1 at creation, one more for each real change or cancellation
    terms: Policy  # the policy it was accepted under: its duration and cutoff

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + self.terms.duration


def clash_window(offset: timedelta, duration: timedelta,
                 other: timedelta) -> tuple[timedelta, timedelta]:
    """The open interval of start offsets at which a booking lasting `other` shares time with
    one from `offset` lasting `duration`, all offsets measured from one common instant.

    Each booking occupies the half-open [start, start + its own duration), so the other
    booking must start before this one ends and end after it starts. Offsets, unlike
    instants, never leave a datetime's range.
    """
    return offset - other, offset + duration


def overlaps(a: Reservation, b: Reservation) -> bool:
    """Whether bookings `a` and `b`, each for its own accepted duration, share any time."""
    low, high = clash_window(b.starts_at - a.starts_at, b.terms.duration, a.terms.duration)
    return low < timedelta(0) < high


def select_tables(restaurant: Restaurant, table_ids: tuple[str, ...]) -> tuple[Table, ...]:
    """The tables a booking holds (E3 steps 5-7): one table, or a pair the restaurant declared
    combinable, named in either order and returned in declared order (E2)."""
    if len(table_ids) > 2:
        raise ApiError(422, "combination_not_allowed", "at most two tables can be combined")
    tables = tuple(restaurant.table(table_id) for table_id in table_ids)
    if None in tables:
        raise not_found("no such table at this restaurant")
    if len(tables) == 1:
        return tables
    pair = next((pair for pair in restaurant.pairs if set(pair) == set(tables)), None)
    if pair is None:
        raise ApiError(422, "combination_not_allowed", "those tables are not combinable")
    return pair


def read_table_ids(reader: FieldReader, obj: dict, path: str, *,
                   required: bool) -> tuple[str, ...] | None:
    """The table set a body names (E3 steps 1-4): `table_id` as a set of one, or
    `table_ids`, never both (a 422 ranked before any wrong type); the set is 1 or more IDs
    without repeats. The rules that need the restaurant are `select_tables`'."""
    if "table_id" in obj and "table_ids" in obj:
        reader.reject_foremost(at(path, "table_id"), "and table_ids cannot both be given")
        return None
    if "table_ids" not in obj:
        if not required and "table_id" not in obj:
            return None
        table_id = reader.identifier(obj, "table_id", path)
        return None if table_id is None else (table_id,)
    where = at(path, "table_ids")
    listed = reader.read(obj, "table_ids", "array", path)
    table_ids = None if listed is None else reader.strings(listed, where)
    if table_ids is None:
        return None
    if not table_ids or not all(is_identifier(table_id) for table_id in table_ids):
        reader.reject(where, "must list one or more table ids of 1 to 64 characters")
    elif len(set(table_ids)) != len(table_ids):
        reader.reject(where, "must not name a table twice")
    else:
        return tuple(table_ids)
    return None


def read_party_size(reader: FieldReader, obj: dict, path: str) -> int | None:
    """A party size: an integer of at least 1. Any other value, a string or a boolean
    included, is 422 rather than a wrong-type 400 (§5)."""
    value = obj.get("party_size")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        reader.reject(at(path, "party_size"), "must be an integer of at least 1")
        return None
    return value


def read_local(reader: FieldReader, obj: dict, path: str) -> datetime | None:
    """`starts_at_local`: a string (400 otherwise) holding a bare local `YYYY-MM-DDTHH:MM`
    with no seconds and no offset (422 otherwise, §5)."""
    return reader.parsed(obj, "starts_at_local", path, timeutil.parse_local,
                         "must be a bare local YYYY-MM-DDTHH:MM")


# ---- views -----------------------------------------------------------------

def restaurant_summary(restaurant: Restaurant) -> dict:
    return {"id": restaurant.id, "name": restaurant.name, "timezone": restaurant.timezone}


def _rules(policy: Policy) -> dict:
    """A policy's rules in the fixture's field names."""
    return {
        "slot_minutes": policy.slot_minutes,
        "reservation_duration_minutes": policy.reservation_duration_minutes,
        "cancellation_cutoff_minutes": policy.cancellation_cutoff_minutes,
        "opening_hours": [
            {"weekday": hours.weekday, "opens": timeutil.hhmm(hours.opens),
             "closes": timeutil.hhmm(hours.closes)}
            for hours in policy.opening_hours],
    }


def accepted_terms(policy: Policy) -> dict:
    """The snapshot of a policy a booking carries: everything but its effective date."""
    return {"policy_version": policy.version, **_rules(policy),
            "capacities": dict(policy.capacities)}


def published_policy(policy: Policy) -> dict:
    """A published policy as it was supplied, with its version."""
    return {"effective_from": policy.effective_from.isoformat(), **_rules(policy),
            "capacities": dict(policy.capacities), "policy_version": policy.version}


def restaurant_detail(restaurant: Restaurant) -> dict:
    """The restaurant in the fixture's shape: its original configuration, policy 0."""
    initial = restaurant.initial
    return {
        **restaurant_summary(restaurant),
        **_rules(initial),
        "tables": [{"id": table.id, "label": table.label, "capacity": initial.capacities[table.id]}
                   for table in restaurant.tables],
        "combinable": [list(pair) for pair in restaurant.combinable],
    }


def show(state: State, reservation: Reservation) -> dict:
    """A reservation as every reservation endpoint returns it (§8): `table_ids` always,
    `table_id` too when the set has one member, and its revision and accepted terms."""
    zone = state.restaurants[reservation.restaurant_id].zone
    single = {"table_id": reservation.table_ids[0]} if len(reservation.table_ids) == 1 else {}
    return {
        "reservation_id": reservation.id,
        "reference": reservation.reference,
        "restaurant_id": reservation.restaurant_id,
        **single,
        "table_ids": list(reservation.table_ids),
        "party_size": reservation.party_size,
        "status": reservation.status,
        "starts_at_local": timeutil.local_text(reservation.starts_at, zone),
        "starts_at": timeutil.rfc3339(reservation.starts_at, zone),
        "ends_at": timeutil.rfc3339(reservation.ends_at, zone),
        "created_at": timeutil.rfc3339(reservation.created_at),
        "revision": reservation.revision,
        "accepted_terms": accepted_terms(reservation.terms),
    }


def decision(reservation: Reservation) -> dict:
    """What a booking was accepted under: its current revision and terms."""
    return {"reference": reservation.reference, "revision": reservation.revision,
            "accepted_terms": accepted_terms(reservation.terms)}


# ---- reads -----------------------------------------------------------------

def find_restaurant(state: State, restaurant_id: str) -> Restaurant:
    restaurant = state.restaurants.get(restaurant_id)
    if restaurant is None:
        raise not_found(f"no restaurant {restaurant_id!r}")
    return restaurant


def managed_restaurant(state: State, user: User, restaurant_id: str) -> Restaurant:
    """A restaurant the caller manages: 404 when there is none, 403 when not a manager."""
    restaurant = find_restaurant(state, restaurant_id)
    if user.id not in restaurant.manager_user_ids:
        raise ApiError(403, "forbidden", "only the restaurant's managers may do that")
    return restaurant


def own_reservation(state: State, user: User | None, reference: str) -> Reservation:
    """The caller's reservation; someone else's is as unknown as a missing one (§8), and so
    is any reservation to a caller who is not signed in."""
    reservation = state.reservations.get(reference)
    if reservation is None or user is None or reservation.user_id != user.id:
        raise not_found(f"no reservation {reference!r}")
    return reservation


def reservations_of(state: State, user: User) -> list[dict]:
    """The caller's reservations, latest start first, then most recently created first."""
    mine = [r for r in state.reservations.values() if r.user_id == user.id]
    mine.reverse()  # newest first; the stable sort below keeps that order among equal starts
    mine.sort(key=lambda r: r.starts_at, reverse=True)
    return [show(state, r) for r in mine]

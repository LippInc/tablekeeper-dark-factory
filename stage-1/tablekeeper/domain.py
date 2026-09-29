"""Restaurants, tables, diners and reservations (§4, §8), and how the API shows them."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from . import timeutil
from .errors import not_found
from .fields import FieldReader, at

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
    id: str
    label: str
    capacity: int


@dataclass(frozen=True)
class OpeningHours:
    weekday: str
    opens: time
    closes: time


@dataclass(frozen=True)
class Restaurant:
    id: str
    name: str
    timezone: str
    slot_minutes: int
    reservation_duration_minutes: int
    cancellation_cutoff_minutes: int
    opening_hours: tuple[OpeningHours, ...]
    tables: tuple[Table, ...]

    def table(self, table_id: str) -> Table | None:
        return next((table for table in self.tables if table.id == table_id), None)

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def duration(self) -> timedelta:
        return timedelta(minutes=self.reservation_duration_minutes)


@dataclass(frozen=True)
class Reservation:
    id: str
    reference: str
    user_id: str
    restaurant_id: str
    table_id: str
    party_size: int
    starts_at: datetime  # UTC
    status: str
    created_at: datetime  # UTC


def overlaps(a: datetime, b: datetime, duration: timedelta) -> bool:
    """Whether bookings on one table starting at instants `a` and `b` share any time.

    Each occupies the half-open [start, start + duration), and every booking at a
    restaurant lasts the same `duration`, so two overlap exactly when their starts are
    less than `duration` apart.
    """
    return abs(a - b) < duration


def is_free(state: State, restaurant: Restaurant, table_id: str, starts_at: datetime) -> bool:
    """Whether no confirmed booking holds the table during a booking from `starts_at`."""
    return not any(overlaps(starts_at, booked.starts_at, restaurant.duration)
                   for booked in state.confirmed_on(restaurant.id, table_id))


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


def restaurant_detail(restaurant: Restaurant) -> dict:
    """The restaurant in the fixture's shape."""
    return {
        **restaurant_summary(restaurant),
        "slot_minutes": restaurant.slot_minutes,
        "reservation_duration_minutes": restaurant.reservation_duration_minutes,
        "cancellation_cutoff_minutes": restaurant.cancellation_cutoff_minutes,
        "opening_hours": [
            {"weekday": hours.weekday, "opens": timeutil.hhmm(hours.opens),
             "closes": timeutil.hhmm(hours.closes)}
            for hours in restaurant.opening_hours],
        "tables": [{"id": table.id, "label": table.label, "capacity": table.capacity}
                   for table in restaurant.tables],
    }


def show(state: State, reservation: Reservation) -> dict:
    """A reservation as every reservation endpoint returns it (§8)."""
    restaurant = state.restaurants[reservation.restaurant_id]
    zone = restaurant.zone
    return {
        "reservation_id": reservation.id,
        "reference": reservation.reference,
        "restaurant_id": reservation.restaurant_id,
        "table_id": reservation.table_id,
        "party_size": reservation.party_size,
        "status": reservation.status,
        "starts_at_local": timeutil.local_text(reservation.starts_at, zone),
        "starts_at": timeutil.rfc3339(reservation.starts_at, zone),
        "ends_at": timeutil.rfc3339(reservation.starts_at + restaurant.duration, zone),
        "created_at": timeutil.rfc3339(reservation.created_at),
    }


# ---- reads -----------------------------------------------------------------

def find_restaurant(state: State, restaurant_id: str) -> Restaurant:
    restaurant = state.restaurants.get(restaurant_id)
    if restaurant is None:
        raise not_found(f"no restaurant {restaurant_id!r}")
    return restaurant


def own_reservation(state: State, user: User, reference: str) -> Reservation:
    """The caller's reservation; someone else's is as unknown as a missing one (§8)."""
    reservation = state.reservations.get(reference)
    if reservation is None or reservation.user_id != user.id:
        raise not_found(f"no reservation {reference!r}")
    return reservation


def reservations_of(state: State, user: User) -> list[dict]:
    """The caller's reservations, latest start first, then most recently created first."""
    mine = [r for r in state.reservations.values() if r.user_id == user.id]
    mine.reverse()  # newest first; the stable sort below keeps that order among equal starts
    mine.sort(key=lambda r: r.starts_at, reverse=True)
    return [show(state, r) for r in mine]

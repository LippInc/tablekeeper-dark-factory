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


def overlaps(a: Reservation, b: Reservation, duration: timedelta) -> bool:
    """Whether two bookings on one table share any time.

    Each occupies the half-open [starts_at, starts_at + duration), and every booking
    at a restaurant lasts the same `duration`, so two overlap exactly when their starts
    are less than `duration` apart.
    """
    return abs(a.starts_at - b.starts_at) < duration


def read_party_size(reader: FieldReader, obj: dict, path: str) -> int | None:
    """A party size: an integer of at least 1. Any other value, a string or a boolean
    included, is 422 rather than a wrong-type 400 (§5)."""
    value = obj.get("party_size")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        reader.reject(at(path, "party_size"), "must be an integer of at least 1")
        return None
    return value


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


def reservation_view(reservation: Reservation, restaurant: Restaurant) -> dict:
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


def show(state: State, reservation: Reservation) -> dict:
    return reservation_view(reservation, state.restaurants[reservation.restaurant_id])


def reservations_of(state: State, user: User) -> list[dict]:
    """The caller's reservations, latest start first, then most recently created first."""
    mine = [r for r in state.reservations.values() if r.user_id == user.id]
    mine.reverse()  # newest first; the stable sort below keeps that order among equal starts
    mine.sort(key=lambda r: r.starts_at, reverse=True)
    return [show(state, r) for r in mine]

"""Loading a reset fixture (§3.3, §4) into a new State.

The whole fixture is validated before any password is hashed or any state replaced, so
a rejected reset leaves the running state as it was. Seeded bookings are existing state:
they must be well-formed and must not overlap, but the booking policy (slot grid, opening
hours, capacity) is not applied to them.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import time
from itertools import pairwise

from . import timeutil
from .auth import hash_password, is_email
from .domain import (CONFIRMED, OpeningHours, Reservation, Restaurant, Table, User, overlaps,
                     read_party_size)
from .fields import FieldReader, at
from .store import State, email_key

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
REFERENCE = re.compile(r"[A-Z0-9]{6,12}")


@dataclass(frozen=True)
class SeedUser:
    id: str
    email: str
    password: str
    display_name: str


@dataclass(frozen=True)
class Fixture:
    users: list[SeedUser]
    restaurants: dict[str, Restaurant]
    reservations: list[Reservation]


def parse(body: dict) -> Fixture:
    """Validate a fixture; raises 400/422 on the first problem, ranked as §5 ranks them."""
    reader = FieldReader()
    users = _users(reader, body)
    restaurants = _restaurants(reader, body)
    reservations = _reservations(reader, body, {u.id for u in users}, restaurants)
    reader.raise_first()
    return Fixture(users, restaurants, reservations)


async def seed(fixture: Fixture) -> State:
    """A State holding exactly the fixture; seeded passwords are hashed here."""
    hashes = await asyncio.gather(*(hash_password(u.password) for u in fixture.users))
    state = State(restaurants=fixture.restaurants,
                  reservations={r.reference: r for r in fixture.reservations})
    for spec, password_hash in zip(fixture.users, hashes):
        state.add_user(User(id=spec.id, email=spec.email, display_name=spec.display_name,
                            password_hash=password_hash))
    return state


def _users(reader: FieldReader, body: dict) -> list[SeedUser]:
    users: list[SeedUser] = []
    ids: set[str] = set()
    emails: set[str] = set()
    for path, item in reader.objects(body, "users", required=False):
        user_id = reader.identifier(item, "id", path)
        email = reader.read(item, "email", "string", path)
        password = reader.read(item, "password", "string", path)
        display_name = reader.read(item, "display_name", "string", path)
        if user_id in ids:
            reader.reject(at(path, "id"), "is not unique")
        if email is not None and not is_email(email):
            reader.reject(at(path, "email"), "must have the form local@domain")
        elif email is not None and email_key(email) in emails:
            reader.reject(at(path, "email"), "is not unique")
        if display_name == "":
            reader.reject(at(path, "display_name"), "must not be empty")
        if None not in (user_id, email, password, display_name):
            ids.add(user_id)
            emails.add(email_key(email))
            users.append(SeedUser(user_id, email, password, display_name))
    return users


def _restaurants(reader: FieldReader, body: dict) -> dict[str, Restaurant]:
    restaurants: dict[str, Restaurant] = {}
    for path, item in reader.objects(body, "restaurants", required=False):
        restaurant_id = reader.identifier(item, "id", path)
        name = reader.read(item, "name", "string", path)
        timezone = reader.read(item, "timezone", "string", path)
        if timezone is not None and timeutil.zone(timezone) is None:
            reader.reject(at(path, "timezone"), "is not an IANA time zone")
            timezone = None
        slot = reader.integer(item, "slot_minutes", path, minimum=1, maximum=timeutil.MAX_MINUTES)
        duration = reader.integer(item, "reservation_duration_minutes", path,
                                  minimum=1, maximum=timeutil.MAX_MINUTES)
        cutoff = reader.integer(item, "cancellation_cutoff_minutes", path,
                                minimum=0, maximum=timeutil.MAX_MINUTES)
        hours = _opening_hours(reader, item, path)
        tables = _tables(reader, item, path)
        if restaurant_id in restaurants:
            reader.reject(at(path, "id"), "is not unique")
        elif None not in (restaurant_id, name, timezone, slot, duration, cutoff):
            restaurants[restaurant_id] = Restaurant(
                id=restaurant_id, name=name, timezone=timezone, slot_minutes=slot,
                reservation_duration_minutes=duration, cancellation_cutoff_minutes=cutoff,
                opening_hours=hours, tables=tables)
    return restaurants


def _opening_hours(reader: FieldReader, restaurant: dict, path: str) -> tuple[OpeningHours, ...]:
    """Opening hours in fixture order. A weekday may have several entries, which must not
    overlap one another; entries that only touch are allowed."""
    entries: list[OpeningHours] = []
    for where, item in reader.objects(restaurant, "opening_hours", path):
        weekday = reader.read(item, "weekday", "string", where)
        opens = _time_of_day(reader, item, "opens", where)
        closes = _time_of_day(reader, item, "closes", where)
        if weekday is not None and weekday not in WEEKDAYS:
            reader.reject(at(where, "weekday"), f"must be one of {' '.join(WEEKDAYS)}")
        elif opens is not None and closes is not None and closes <= opens:
            reader.reject(at(where, "closes"), "must be later than opens on the same day")
        elif None not in (weekday, opens, closes):
            entries.append(OpeningHours(weekday, opens, closes))
    for weekday in WEEKDAYS:
        day = sorted((e for e in entries if e.weekday == weekday), key=lambda e: e.opens)
        if any(later.opens < earlier.closes for earlier, later in pairwise(day)):
            reader.reject(at(path, "opening_hours"), f"has overlapping entries on {weekday}")
    return tuple(entries)


def _time_of_day(reader: FieldReader, item: dict, name: str, path: str) -> time | None:
    text = reader.read(item, name, "string", path)
    value = None if text is None else timeutil.parse_hhmm(text)
    if text is not None and value is None:
        reader.reject(at(path, name), "must be a 24-hour HH:MM time")
    return value


def _tables(reader: FieldReader, restaurant: dict, path: str) -> tuple[Table, ...]:
    tables: dict[str, Table] = {}
    for where, item in reader.objects(restaurant, "tables", path):
        table_id = reader.identifier(item, "id", where)
        label = reader.read(item, "label", "string", where)
        capacity = reader.integer(item, "capacity", where, minimum=1)
        if table_id in tables:
            reader.reject(at(where, "id"), "is not unique within its restaurant")
        elif None not in (table_id, label, capacity):
            tables[table_id] = Table(table_id, label, capacity)
    return tuple(tables.values())


def _reservations(reader: FieldReader, body: dict, user_ids: set[str],
                  restaurants: dict[str, Restaurant]) -> list[Reservation]:
    reservations: list[Reservation] = []
    ids: set[str] = set()
    references: set[str] = set()
    created_at = timeutil.now()
    for path, item in reader.objects(body, "reservations", required=False):
        reservation_id = reader.identifier(item, "id", path)
        reference = reader.read(item, "reference", "string", path)
        user_id = reader.identifier(item, "user_id", path)
        restaurant_id = reader.identifier(item, "restaurant_id", path)
        table_id = reader.identifier(item, "table_id", path)
        starts_at_local = reader.read(item, "starts_at_local", "string", path)
        party_size = read_party_size(reader, item, path)
        if reservation_id in ids:
            reader.reject(at(path, "id"), "is not unique")
        if reference is not None and not REFERENCE.fullmatch(reference):
            reader.reject(at(path, "reference"), "must be 6 to 12 characters of A-Z0-9")
        elif reference in references:
            reader.reject(at(path, "reference"), "is not unique")
        if user_id is not None and user_id not in user_ids:
            reader.reject(at(path, "user_id"), "is not a seeded user")
        restaurant = restaurants.get(restaurant_id)
        if restaurant_id is not None and restaurant is None:
            reader.reject(at(path, "restaurant_id"), "is not a seeded restaurant")
        elif restaurant is not None and table_id is not None and restaurant.table(table_id) is None:
            reader.reject(at(path, "table_id"), "is not a table of that restaurant")
        starts_at = None
        if starts_at_local is not None and restaurant is not None:
            local = timeutil.parse_local(starts_at_local)
            starts_at = None if local is None else timeutil.resolve(local, restaurant.zone)
            if starts_at is None:
                reader.reject(at(path, "starts_at_local"),
                              "must be an existing local YYYY-MM-DDTHH:MM")
        if None not in (reservation_id, reference, user_id, table_id, starts_at, party_size):
            ids.add(reservation_id)
            references.add(reference)
            reservations.append(Reservation(
                id=reservation_id, reference=reference, user_id=user_id,
                restaurant_id=restaurant_id, table_id=table_id, party_size=party_size,
                starts_at=starts_at, status=CONFIRMED, created_at=created_at))
    _reject_overlaps(reader, reservations, restaurants)
    return reservations


def _reject_overlaps(reader: FieldReader, reservations: list[Reservation],
                     restaurants: dict[str, Restaurant]) -> None:
    """Two seeded bookings may not hold one table at overlapping times (§1)."""
    by_table: dict[tuple[str, str], list[Reservation]] = {}
    for reservation in reservations:
        by_table.setdefault((reservation.restaurant_id, reservation.table_id), []).append(reservation)
    for (restaurant_id, table_id), booked in by_table.items():
        booked.sort(key=lambda r: r.starts_at)
        duration = restaurants[restaurant_id].duration
        if any(overlaps(a, b, duration) for a, b in pairwise(booked)):
            reader.reject("reservations", f"overlap on table {table_id!r} of {restaurant_id!r}")

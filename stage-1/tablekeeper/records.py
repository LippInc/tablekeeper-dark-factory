"""Reading stored records: accounts, restaurants and reservations (§3.4, §4).

A reset fixture and an imported snapshot hold the same records in nearly the same shape.
`Records` reads them the same way for both, keeps IDs, emails and references unique, and
checks that every reference between records resolves. Problems are recorded on the
`FieldReader`; nothing is raised here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from . import timeutil
from .auth import read_identity
from .domain import (CONFIRMED, WEEKDAYS, OpeningHours, Reservation, Restaurant, Table,
                     overlaps, read_party_size)
from .fields import FieldReader, at
from .store import email_key

REFERENCE = re.compile(r"[A-Z0-9]{6,12}")


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    display_name: str


@dataclass(frozen=True)
class Booking:
    """A reservation record's fields other than its start, status and creation time."""
    id: str
    reference: str
    user_id: str
    restaurant: Restaurant
    table_id: str
    party_size: int

    def reservation(self, starts_at: datetime, status: str, created_at: datetime) -> Reservation:
        return Reservation(id=self.id, reference=self.reference, user_id=self.user_id,
                           restaurant_id=self.restaurant.id, table_id=self.table_id,
                           party_size=self.party_size, starts_at=starts_at, status=status,
                           created_at=created_at)


class Records:
    def __init__(self, reader: FieldReader) -> None:
        self.reader = reader
        self.user_ids: set[str] = set()
        self.restaurants: dict[str, Restaurant] = {}
        self._emails: set[str] = set()
        self._reservation_ids: set[str] = set()
        self._references: set[str] = set()

    def account(self, item: dict, path: str) -> Account | None:
        reader = self.reader
        user_id = reader.identifier(item, "id", path)
        email, display_name = read_identity(reader, item, path)
        if user_id in self.user_ids:
            reader.reject(at(path, "id"), "is not unique")
        elif email is not None and email_key(email) in self._emails:
            reader.reject(at(path, "email"), "is not unique")
        elif None not in (user_id, email, display_name):
            self.user_ids.add(user_id)
            self._emails.add(email_key(email))
            return Account(user_id, email, display_name)
        return None

    def restaurant(self, item: dict, path: str) -> None:
        reader = self.reader
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
        hours = self._opening_hours(item, path)
        tables = self._tables(item, path)
        if restaurant_id in self.restaurants:
            reader.reject(at(path, "id"), "is not unique")
        elif None not in (restaurant_id, name, timezone, slot, duration, cutoff):
            self.restaurants[restaurant_id] = Restaurant(
                id=restaurant_id, name=name, timezone=timezone, slot_minutes=slot,
                reservation_duration_minutes=duration, cancellation_cutoff_minutes=cutoff,
                opening_hours=hours, tables=tables)

    def _opening_hours(self, restaurant: dict, path: str) -> tuple[OpeningHours, ...]:
        """Opening hours in fixture order. A weekday may have several entries, which must
        not overlap one another; entries that only touch are allowed."""
        reader = self.reader
        entries: list[OpeningHours] = []
        for where, item in reader.objects(restaurant, "opening_hours", path):
            weekday = reader.read(item, "weekday", "string", where)
            opens, closes = (reader.parsed(item, name, where, timeutil.parse_hhmm,
                                           "must be a 24-hour HH:MM time")
                             for name in ("opens", "closes"))
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

    def _tables(self, restaurant: dict, path: str) -> tuple[Table, ...]:
        reader = self.reader
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

    def booking(self, item: dict, path: str) -> Booking | None:
        """A reservation record's identity, owner, restaurant, table and party."""
        reader = self.reader
        reservation_id = reader.identifier(item, "id", path)
        reference = reader.read(item, "reference", "string", path)
        user_id = reader.identifier(item, "user_id", path)
        restaurant_id = reader.identifier(item, "restaurant_id", path)
        table_id = reader.identifier(item, "table_id", path)
        party_size = read_party_size(reader, item, path)
        restaurant = self.restaurants.get(restaurant_id)
        if reservation_id in self._reservation_ids:
            reader.reject(at(path, "id"), "is not unique")
        elif reference is not None and not REFERENCE.fullmatch(reference):
            reader.reject(at(path, "reference"), "must be 6 to 12 characters of A-Z0-9")
        elif reference in self._references:
            reader.reject(at(path, "reference"), "is not unique")
        elif user_id is not None and user_id not in self.user_ids:
            reader.reject(at(path, "user_id"), "is not a known user")
        elif restaurant_id is not None and restaurant is None:
            reader.reject(at(path, "restaurant_id"), "is not a known restaurant")
        elif restaurant is not None and table_id is not None and restaurant.table(table_id) is None:
            reader.reject(at(path, "table_id"), "is not a table of that restaurant")
        elif None not in (reservation_id, reference, user_id, restaurant, table_id, party_size):
            self._reservation_ids.add(reservation_id)
            self._references.add(reference)
            return Booking(reservation_id, reference, user_id, restaurant, table_id, party_size)
        return None

    def reject_overlaps(self, reservations: list[Reservation]) -> None:
        """No two confirmed bookings may hold one table at overlapping times (§1)."""
        by_table: dict[tuple[str, str], list[Reservation]] = {}
        for reservation in reservations:
            if reservation.status == CONFIRMED:
                key = (reservation.restaurant_id, reservation.table_id)
                by_table.setdefault(key, []).append(reservation)
        for (restaurant_id, table_id), booked in by_table.items():
            booked.sort(key=lambda r: r.starts_at)
            duration = self.restaurants[restaurant_id].duration
            if any(overlaps(a.starts_at, b.starts_at, duration) for a, b in pairwise(booked)):
                self.reader.reject("reservations",
                                   f"overlap on table {table_id!r} of {restaurant_id!r}")

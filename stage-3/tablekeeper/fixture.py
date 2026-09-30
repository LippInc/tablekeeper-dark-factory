"""Loading a reset fixture (§3.3, §4) into a new State.

The whole fixture is validated before any password is hashed or any state replaced, so
a rejected reset leaves the running state as it was. Seeded bookings are existing state:
they must be well-formed and must not overlap, but the booking policy (slot grid, opening
hours, capacity) is not applied to them.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from . import history, timeutil
from .auth import hash_password
from .domain import Reservation, Restaurant, User, read_local
from .fields import FieldReader, at
from .records import Account, Records
from .store import State


@dataclass(frozen=True)
class Fixture:
    accounts: list[tuple[Account, str]]  # with each account's password
    restaurants: dict[str, Restaurant]
    reservations: list[Reservation]


def parse(body: dict) -> Fixture:
    """Validate a fixture; raises 400/422 on the first problem, ranked as §5 ranks them."""
    reader = FieldReader()
    records = Records(reader)
    accounts = []
    for path, item in reader.objects(body, "users", required=False):
        account = records.account(item, path)
        password = reader.read(item, "password", "string", path)
        if account is not None and password is not None:
            accounts.append((account, password))
    for path, item in reader.objects(body, "restaurants", required=False):
        records.restaurant(item, path)
    reservations = []
    created_at = timeutil.now()
    for path, item in reader.objects(body, "reservations", required=False):
        booking = records.booking(item, path)
        local = read_local(reader, item, path)
        if booking is not None and local is not None:
            starts_at = timeutil.resolve(local, booking.restaurant.zone)
            if starts_at is None:
                reader.reject(at(path, "starts_at_local"), "is a local time that does not exist")
            else:
                reservations.append(booking.reservation(starts_at, created_at))
    records.reject_overlaps(reservations)
    reader.raise_first()
    return Fixture(accounts, records.restaurants, reservations)


async def seed(fixture: Fixture) -> State:
    """A State holding exactly the fixture; seeded passwords are hashed here."""
    hashes = await asyncio.gather(*(hash_password(password) for _, password in fixture.accounts))
    state = State(restaurants=fixture.restaurants)
    for reservation in fixture.reservations:  # each created at the reset, under policy 0 (P4)
        state.put_reservation(reservation)
        history.record(state, None, reservation, reservation.created_at)
    for (account, _), password_hash in zip(fixture.accounts, hashes):
        state.add_user(User(id=account.id, email=account.email,
                            display_name=account.display_name, password_hash=password_hash))
    return state

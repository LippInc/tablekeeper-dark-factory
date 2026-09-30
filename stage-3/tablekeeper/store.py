"""All service state, held in memory behind one lock (§2: state need not survive a restart)."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Container, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from .domain import CONFIRMED, Policy, Reservation, Restaurant, User
from .history import Entry
from .series import Series

# An idempotency scope: (user id, method, path, key) (§7).
Scope = tuple[str, str, str, str]


def email_key(email: str) -> str:
    """Emails compare without regard to case."""
    return email.casefold()


@dataclass(frozen=True)
class Receipt:
    """A completed keyed write: its request body (canonical JSON) and original response."""
    request: str
    response: dict


def _table_keys(reservation: Reservation) -> list[tuple[str, str]]:
    return [(reservation.restaurant_id, table_id) for table_id in reservation.table_ids]


@dataclass
class State:
    users: dict[str, User] = field(default_factory=dict)
    user_ids_by_email: dict[str, str] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)            # token -> user id
    restaurants: dict[str, Restaurant] = field(default_factory=dict)  # fixture order
    policies: dict[str, list[Policy]] = field(default_factory=dict)  # published, per restaurant
    reservations: dict[str, Reservation] = field(default_factory=dict)  # by reference, creation order
    # Confirmed bookings per (restaurant id, table id), by reference: the occupancy index.
    # A booking of a pair is listed under both of its tables.
    table_bookings: dict[tuple[str, str], dict[str, Reservation]] = field(default_factory=dict)
    receipts: dict[Scope, Receipt] = field(default_factory=dict)
    history: dict[str, list[Entry]] = field(default_factory=dict)  # per reference, in seq order
    series: dict[str, Series] = field(default_factory=dict)  # by series id
    series_by_reference: dict[str, str] = field(default_factory=dict)  # occurrence -> series id

    def add_user(self, user: User) -> None:
        self.users[user.id] = user
        self.user_ids_by_email[email_key(user.email)] = user.id

    def user_by_email(self, email: str) -> User | None:
        user_id = self.user_ids_by_email.get(email_key(email))
        return None if user_id is None else self.users[user_id]

    def put_reservation(self, reservation: Reservation) -> None:
        """Add a reservation, or replace the one with its reference, keeping the occupancy
        index current."""
        previous = self.reservations.get(reservation.reference)
        if previous is not None:
            for key in _table_keys(previous):
                self.table_bookings.get(key, {}).pop(previous.reference, None)
        self.reservations[reservation.reference] = reservation
        if reservation.status == CONFIRMED:
            for key in _table_keys(reservation):
                self.table_bookings.setdefault(key, {})[reservation.reference] = reservation

    def confirmed_on(self, restaurant_id: str, table_id: str) -> Iterable[Reservation]:
        return self.table_bookings.get((restaurant_id, table_id), {}).values()


def fresh(generate: Callable[[], str], taken: Container[str]) -> str:
    """A generated value not already in `taken`."""
    while (value := generate()) in taken:
        pass
    return value


class Store:
    """The current State and the one lock over it.

    A request reads, decides and writes inside a single `transaction()` and never
    awaits inside it, so requests take effect one at a time. Slow work (password
    hashing) happens before or after, outside the lock.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state = State()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[State]:
        async with self._lock:
            yield self._state

    async def replace(self, state: State) -> None:
        """Swap in a fully built state in one step (reset)."""
        async with self._lock:
            self._state = state

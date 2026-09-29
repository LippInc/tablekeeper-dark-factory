"""All service state, held in memory behind one lock (§2: state need not survive a restart)."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Container, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from .domain import CONFIRMED, Reservation, Restaurant, User


def email_key(email: str) -> str:
    """Emails compare without regard to case."""
    return email.casefold()


@dataclass
class State:
    users: dict[str, User] = field(default_factory=dict)
    user_ids_by_email: dict[str, str] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)            # token -> user id
    restaurants: dict[str, Restaurant] = field(default_factory=dict)  # fixture order
    reservations: dict[str, Reservation] = field(default_factory=dict)  # by reference, creation order
    # Confirmed bookings per (restaurant id, table id), by reference: the occupancy index.
    table_bookings: dict[tuple[str, str], dict[str, Reservation]] = field(default_factory=dict)

    def add_user(self, user: User) -> None:
        self.users[user.id] = user
        self.user_ids_by_email[email_key(user.email)] = user.id

    def user_by_email(self, email: str) -> User | None:
        user_id = self.user_ids_by_email.get(email_key(email))
        return None if user_id is None else self.users[user_id]

    def add_reservation(self, reservation: Reservation) -> None:
        self.reservations[reservation.reference] = reservation
        if reservation.status == CONFIRMED:
            key = (reservation.restaurant_id, reservation.table_id)
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

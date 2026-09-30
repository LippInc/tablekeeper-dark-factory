"""All service state, held in memory behind one lock (§2: state need not survive a restart)."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Container, Hashable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from .domain import CONFIRMED, Closure, Policy, Reservation, Restaurant, User
from .history import Entry
from .series import Series

if TYPE_CHECKING:
    from .replans import Plan

# An idempotency scope: (user id, method, path, key) (§7).
Scope = tuple[str, str, str, str]

T = TypeVar("T")

MAX_ANSWERS = 16  # rendered answers kept at their restaurants' current revisions


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
    # Per restaurant: one more for each successful operation that changed something there
    # (`changed`); 0 when absent, as after a reset. An import restores the exported values.
    restaurant_revisions: dict[str, int] = field(default_factory=dict)
    plans: dict[str, Plan] = field(default_factory=dict)  # previewed seatings, by plan id
    closures: dict[str, list[Closure]] = field(default_factory=dict)  # applied, per restaurant
    # Rendered answers, each with the revision of the restaurant it describes at rendering.
    answers: dict[Hashable, tuple[int, bytes]] = field(default_factory=dict)

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

    def publish_policy(self, restaurant_id: str, policy: Policy) -> None:
        self.policies.setdefault(restaurant_id, []).append(policy)
        self.changed([restaurant_id])

    def restaurant_revision(self, restaurant_id: str) -> int:
        return self.restaurant_revisions.get(restaurant_id, 0)

    def changed(self, restaurant_ids: Iterable[str]) -> None:
        """The second phase of one successful operation that changed something at each of
        `restaurant_ids`: each of those restaurants' revisions moves on once, however many of
        its records the operation changed (Q5)."""
        for restaurant_id in set(restaurant_ids):
            self.restaurant_revisions[restaurant_id] = self.restaurant_revision(restaurant_id) + 1

    def answer(self, restaurant_id: str, key: Hashable, render: Callable[[], bytes]) -> bytes:
        """The answer `render` gives about restaurant `restaurant_id` in this state, rendered
        once per revision of that restaurant: every write an answer can depend on raises it, so
        identical reads between two writes share one rendering (a burst of the same question
        costs one). Only the latest few are kept."""
        revision = self.restaurant_revision(restaurant_id)
        cached = self.answers.pop(key, None)
        body = cached[1] if cached is not None and cached[0] == revision else render()
        self.answers[key] = (revision, body)
        if len(self.answers) > MAX_ANSWERS:
            del self.answers[next(iter(self.answers))]
        return body

    def confirmed_on(self, restaurant_id: str, table_id: str) -> Iterable[Reservation]:
        return self.table_bookings.get((restaurant_id, table_id), {}).values()

    def holds_on(self, restaurant_id: str, table_id: str,
                 excluding: Container[str] = ()) -> list[Reservation | Closure]:
        """What keeps the table from a booking for part of its time (the one occupancy rule):
        its confirmed bookings but those whose references are in `excluding`, and its closures."""
        return [*(booking for booking in self.confirmed_on(restaurant_id, table_id)
                  if booking.reference not in excluding),
                *(closure for closure in self.closures.get(restaurant_id, []) if closure.table_id == table_id)]


def fresh(generate: Callable[[], str], taken: Container[str]) -> str:
    """A generated value not already in `taken`."""
    while (value := generate()) in taken:
        pass
    return value


class Store:
    """The current State and the one lock over it.

    A request reads, decides and writes inside a single `transaction()` and never
    awaits inside it but for `in_thread`, which keeps the lock, so requests take effect one
    at a time. Slow work (password hashing) happens before or after, outside the lock.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state = State()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[State]:
        async with self._lock:
            yield self._state

    @staticmethod
    async def in_thread(work: Callable[[], T]) -> T:
        """`work` (heavy, reading the state) done in a worker thread while the caller's
        transaction keeps the lock, so the event loop goes on sending the answers already
        made meanwhile. The lock is not given up before `work` ends, even if the request is
        cancelled, so no write can change the state under it."""
        done = asyncio.ensure_future(asyncio.to_thread(work))
        try:
            return await asyncio.shield(done)
        except asyncio.CancelledError:
            await asyncio.wait([done])
            raise

    async def replace(self, state: State) -> None:
        """Swap in a fully built state in one step (reset)."""
        async with self._lock:
            self._state = state

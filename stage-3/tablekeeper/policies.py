"""Dated booking policies (stage 3): publishing, listing, and the policy in force on a date.

A restaurant's managers publish complete policies, each from an effective local date on.
Policies never change once published. Policy 0 is the fixture's own rules
(`Restaurant.initial`), in force before any published policy.
"""
from __future__ import annotations

from datetime import date

from . import timeutil
from .domain import Policy, Restaurant, User, find_restaurant, published_policy
from .errors import ApiError
from .fields import FieldReader, at
from .records import read_opening_hours
from .store import State

MAX_STEP_MINUTES = 1440  # slot grid and duration
MAX_CUTOFF_MINUTES = 10080
MAX_CAPACITY = 100


def policy_for(state: State, restaurant: Restaurant, day: date) -> Policy:
    """The policy for bookings starting on local date `day`: of those in effect by then, the
    latest effective date, and of those the latest published; policy 0 before any."""
    in_effect = [policy for policy in state.policies.get(restaurant.id, [])
                 if policy.effective_from <= day]
    return max(in_effect, key=lambda policy: (policy.effective_from, policy.version),
               default=restaurant.initial)


def listed(state: State, restaurant_id: str) -> dict:
    """The published policies in publication order; policy 0 is not one of them."""
    restaurant = find_restaurant(state, restaurant_id)
    return {"policies": [published_policy(policy)
                         for policy in state.policies.get(restaurant.id, [])]}


def publish(state: State, user: User, restaurant_id: str, body: dict) -> dict:
    """Publish a complete policy as the restaurant's next version (P2 order after the keyed
    write's own checks: 404 restaurant, 403 not a manager, 422 any policy field)."""
    restaurant = find_restaurant(state, restaurant_id)
    if user.id not in restaurant.manager_user_ids:
        raise ApiError(403, "forbidden", "only the restaurant's managers may publish policies")
    published = state.policies.setdefault(restaurant.id, [])
    reader = FieldReader()
    policy = read_policy(reader, body, "", restaurant, version=len(published) + 1)
    reader.raise_as_invalid()
    published.append(policy)
    return published_policy(policy)


def read_policy(reader: FieldReader, obj: dict, path: str, restaurant: Restaurant,
                version: int) -> Policy | None:
    """A complete policy for `restaurant` (P1, P7): every field required, in range, and no
    weekday twice. Problems are recorded on `reader`; None when there is one."""
    effective_from = reader.parsed(obj, "effective_from", path, timeutil.parse_date,
                                   "must be a calendar date YYYY-MM-DD")
    slot = reader.integer(obj, "slot_minutes", path, minimum=1, maximum=MAX_STEP_MINUTES)
    duration = reader.integer(obj, "reservation_duration_minutes", path, minimum=1,
                              maximum=MAX_STEP_MINUTES)
    cutoff = reader.integer(obj, "cancellation_cutoff_minutes", path, minimum=0,
                            maximum=MAX_CUTOFF_MINUTES)
    hours = read_opening_hours(reader, obj, path)
    weekdays = [entry.weekday for entry in hours]
    if len(set(weekdays)) != len(weekdays):
        reader.reject(at(path, "opening_hours"), "must not name a weekday twice")
    capacities = _read_capacities(reader, obj, path, restaurant)
    if None in (effective_from, slot, duration, cutoff, capacities):
        return None
    return Policy(version=version, effective_from=effective_from, slot_minutes=slot,
                  reservation_duration_minutes=duration, cancellation_cutoff_minutes=cutoff,
                  opening_hours=hours, capacities=capacities)


def _read_capacities(reader: FieldReader, obj: dict, path: str,
                     restaurant: Restaurant) -> dict[str, int] | None:
    """`capacities`: exactly the restaurant's tables, each seating 1 to 100; kept in the
    restaurant's table order."""
    where = at(path, "capacities")
    listed_capacities = reader.read(obj, "capacities", "object", path) or {}
    table_ids = [table.id for table in restaurant.tables]
    if set(listed_capacities) != set(table_ids):
        reader.reject(where, "must name exactly the restaurant's tables")
        return None
    capacities = {table_id: reader.integer(listed_capacities, table_id, where, minimum=1,
                                           maximum=MAX_CAPACITY)
                  for table_id in table_ids}
    return None if None in capacities.values() else capacities


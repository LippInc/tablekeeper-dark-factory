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
from .fields import FieldReader
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
    policy = _read_policy(body, restaurant, version=len(published) + 1)
    published.append(policy)
    return published_policy(policy)


def _read_policy(body: dict, restaurant: Restaurant, version: int) -> Policy:
    """Every field is required, and any problem with one is 422 (P1)."""
    reader = FieldReader()
    effective_from = reader.parsed(body, "effective_from", "", timeutil.parse_date,
                                   "must be a calendar date YYYY-MM-DD")
    slot = reader.integer(body, "slot_minutes", "", minimum=1, maximum=MAX_STEP_MINUTES)
    duration = reader.integer(body, "reservation_duration_minutes", "", minimum=1,
                              maximum=MAX_STEP_MINUTES)
    cutoff = reader.integer(body, "cancellation_cutoff_minutes", "", minimum=0,
                            maximum=MAX_CUTOFF_MINUTES)
    hours = read_opening_hours(reader, body, "")
    weekdays = [entry.weekday for entry in hours]
    if len(set(weekdays)) != len(weekdays):
        reader.reject("opening_hours", "must not name a weekday twice")
    capacities = _read_capacities(reader, body, restaurant)
    reader.raise_as_invalid()
    return Policy(version=version, effective_from=effective_from, slot_minutes=slot,
                  reservation_duration_minutes=duration, cancellation_cutoff_minutes=cutoff,
                  opening_hours=hours, capacities=capacities)


def _read_capacities(reader: FieldReader, body: dict, restaurant: Restaurant) -> dict[str, int]:
    """`capacities`: exactly the restaurant's tables, each seating 1 to 100; kept in the
    restaurant's table order."""
    listed_capacities = reader.read(body, "capacities", "object") or {}
    table_ids = [table.id for table in restaurant.tables]
    if set(listed_capacities) != set(table_ids):
        reader.reject("capacities", "must name exactly the restaurant's tables")
    for table_id in table_ids:
        if table_id in listed_capacities:
            reader.integer(listed_capacities, table_id, "capacities", minimum=1, maximum=MAX_CAPACITY)
    return {table_id: listed_capacities.get(table_id) for table_id in table_ids}


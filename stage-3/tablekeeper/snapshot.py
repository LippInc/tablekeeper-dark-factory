"""Export and import of the whole service state (§10).

The export is a frozen contract that the next stage imports. Everything is stored as data
and nothing is recomputed on import: password hash records with their parameters and salt,
bearer tokens, references, timestamps, and every completed keyed write's canonical request
and original response exactly as sent. `schema` numbers this state layout; an export of an
earlier schema is migrated to the current one before it is restored (`migrations`).
"""
from __future__ import annotations

from typing import Any

from . import timeutil
from .auth import is_hash_record
from .domain import Policy, Reservation, Restaurant, User, published_policy, restaurant_detail
from .errors import invalid
from .fields import FieldReader, at
from .idempotency import MAX_KEY_LENGTH, is_canonical_request
from .migrations import SCHEMA, upgraded
from .policies import read_policy
from .records import Records
from .store import Receipt, Scope, State

TRACK = "tablekeeper"
FORMAT_VERSION = 1


def export(state: State) -> dict:
    """The state as plain JSON. Take it inside one transaction: it is one snapshot."""
    return {"track": TRACK, "format_version": FORMAT_VERSION, "state": {
        "schema": SCHEMA,
        "users": [{"id": u.id, "email": u.email, "display_name": u.display_name,
                   "password_hash": u.password_hash} for u in state.users.values()],
        "tokens": dict(state.tokens),
        "restaurants": [_restaurant_record(state, r) for r in state.restaurants.values()],
        "reservations": [_reservation_record(r) for r in state.reservations.values()],
        "receipts": [{"user_id": user_id, "method": method, "path": path, "key": key,
                      "request": receipt.request, "response": receipt.response}
                     for (user_id, method, path, key), receipt in state.receipts.items()],
    }}


def _restaurant_record(state: State, restaurant: Restaurant) -> dict:
    """The fixture's shape, with the managers and the published policies."""
    return {**restaurant_detail(restaurant), "manager_user_ids": list(restaurant.manager_user_ids),
            "policies": [published_policy(p) for p in state.policies.get(restaurant.id, [])]}


def _reservation_record(reservation: Reservation) -> dict:
    """A reservation with its revision and the version of the policy it was accepted under."""
    return {"id": reservation.id, "reference": reservation.reference,
            "user_id": reservation.user_id, "restaurant_id": reservation.restaurant_id,
            "table_ids": list(reservation.table_ids), "party_size": reservation.party_size,
            "starts_at": reservation.starts_at.isoformat(), "status": reservation.status,
            "created_at": reservation.created_at.isoformat(), "revision": reservation.revision,
            "policy_version": reservation.terms.version}


def restore(body: Any) -> State:
    """A new State holding exactly an export. Every problem, a body that is not an object
    included, is 422 `validation_failed` (§10, D20) and changes nothing, since the running
    state is only replaced after this returns."""
    if not isinstance(body, dict):
        raise invalid("the body must be an exported object")
    if body.get("track") != TRACK or not _is_int(body.get("format_version"), FORMAT_VERSION):
        raise invalid(f"track must be {TRACK!r} and format_version {FORMAT_VERSION}")
    data = body.get("state")
    data = upgraded(data) if isinstance(data, dict) else None
    if data is None:
        raise invalid(f"state must be an object with a schema from 1 to {SCHEMA}")
    reader = FieldReader()
    records = Records(reader)
    state = State()
    for path, item in reader.objects(data, "users"):
        account = records.account(item, path)
        password_hash = reader.read(item, "password_hash", "object", path)
        if password_hash is not None and not is_hash_record(password_hash):
            reader.reject(at(path, "password_hash"), "is not a usable scrypt hash record")
        elif account is not None and password_hash is not None:
            state.add_user(User(account.id, account.email, account.display_name, password_hash))
    state.tokens = _tokens(reader, data, records.user_ids)
    for path, item in reader.objects(data, "restaurants"):
        restaurant = records.restaurant(item, path)
        if restaurant is not None:
            state.policies[restaurant.id] = _policies(reader, item, path, restaurant)
    state.restaurants = records.restaurants
    reservations = _reservations(reader, records, data, state)
    records.reject_overlaps(reservations)
    for reservation in reservations:
        state.put_reservation(reservation)
    state.receipts = _receipts(reader, data, records.user_ids)
    reader.raise_as_invalid()
    return state


def _is_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _tokens(reader: FieldReader, data: dict, user_ids: set[str]) -> dict[str, str]:
    tokens = reader.read(data, "tokens", "object") or {}
    if not all(token and isinstance(user_id, str) and user_id in user_ids
               for token, user_id in tokens.items()):
        reader.reject("tokens", "must map each token to a known user")
    return tokens


def _policies(reader: FieldReader, item: dict, path: str, restaurant: Restaurant) -> list[Policy]:
    """A restaurant's published policies, numbered 1, 2, ... in publication order."""
    found = []
    for index, (where, record) in enumerate(reader.objects(item, "policies", path), start=1):
        version = reader.integer(record, "policy_version", where, minimum=index, maximum=index)
        policy = read_policy(reader, record, where, restaurant, version=index)
        if None not in (version, policy):
            found.append(policy)
    return found


def _reservations(reader: FieldReader, records: Records, data: dict,
                  state: State) -> list[Reservation]:
    """The reservations, each at its revision under the policy it was accepted under."""
    reservations = []
    for path, item in reader.objects(data, "reservations"):
        booking = records.booking(item, path)
        starts_at, created_at = (reader.parsed(item, name, path, timeutil.parse_instant,
                                               "must be a timestamp with an offset")
                                 for name in ("starts_at", "created_at"))
        revision = reader.integer(item, "revision", path, minimum=1)
        version = reader.integer(item, "policy_version", path, minimum=0)
        if None in (booking, starts_at, created_at, revision, version):
            continue
        policies = [booking.restaurant.initial, *state.policies.get(booking.restaurant.id, [])]
        if version >= len(policies):
            reader.reject(at(path, "policy_version"), "is not a policy of its restaurant")
            continue
        reservations.append(booking.reservation(starts_at, created_at, revision=revision,
                                                terms=policies[version]))
    return reservations


def _receipts(reader: FieldReader, data: dict, user_ids: set[str]) -> dict[Scope, Receipt]:
    receipts: dict[Scope, Receipt] = {}
    for path, item in reader.objects(data, "receipts"):
        user_id, method, route, key, request = (
            reader.read(item, name, "string", path)
            for name in ("user_id", "method", "path", "key", "request"))
        response = reader.read(item, "response", "object", path)
        scope = (user_id, method, route, key)
        if user_id is not None and user_id not in user_ids:
            reader.reject(at(path, "user_id"), "is not a known user")
        elif key is not None and not 1 <= len(key) <= MAX_KEY_LENGTH:
            reader.reject(at(path, "key"), f"must be 1 to {MAX_KEY_LENGTH} characters")
        elif request is not None and not is_canonical_request(request):
            reader.reject(at(path, "request"), "must be a canonical JSON object")
        elif scope in receipts:
            reader.reject(path, "repeats an earlier receipt's user, method, path and key")
        elif None not in (*scope, request, response):
            receipts[scope] = Receipt(request=request, response=response)
    return receipts

"""Export and import of the whole service state (§10).

The export is a frozen contract that the next stage imports. Everything is stored as data
and nothing is recomputed on import: password hash records with their parameters and salt,
bearer tokens, references, timestamps, and every completed keyed write's canonical request
and original response exactly as sent. `schema` numbers this state layout; an export of an
earlier schema is migrated to the current one before it is restored (`migrations`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import planner, timeutil
from .auth import is_hash_record
from .history import EVENTS, FIELDS, Change, Entry
from .series import Occurrence, Series, add
from .domain import Policy, Reservation, Restaurant, User, published_policy, restaurant_detail
from .errors import invalid
from .fields import FieldReader, at
from .idempotency import MAX_KEY_LENGTH, is_canonical_request
from .migrations import SCHEMA, upgraded
from .policies import read_policy
from .records import Records
from .replans import Plan, read_closure, view
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
        "reservations": [_reservation_record(state, r) for r in state.reservations.values()],
        "series": [{"id": s.id, "user_id": s.user_id, "interval_weeks": s.interval_weeks,
                    "revision": s.revision,
                    "occurrences": [{"index": o.index, "reference": o.reference, "exception": o.exception}
                                    for o in s.occurrences]}
                   for s in state.series.values()],
        "plans": [{"restaurant_id": plan.restaurant_id, **view(plan)} for plan in state.plans.values()],
        "receipts": [{"user_id": user_id, "method": method, "path": path, "key": key,
                      "request": receipt.request, "response": receipt.response}
                     for (user_id, method, path, key), receipt in state.receipts.items()],
    }}


def _restaurant_record(state: State, restaurant: Restaurant) -> dict:
    """The fixture's shape, with the managers, the published policies and the restaurant's
    revision."""
    return {**restaurant_detail(restaurant), "manager_user_ids": list(restaurant.manager_user_ids),
            "policies": [published_policy(p) for p in state.policies.get(restaurant.id, [])],
            "revision": state.restaurant_revision(restaurant.id)}


def _reservation_record(state: State, reservation: Reservation) -> dict:
    """A reservation with its revision, the version of the policy it was accepted under and
    its history, each entry with the version of the terms it recorded."""
    return {"id": reservation.id, "reference": reservation.reference,
            "user_id": reservation.user_id, "restaurant_id": reservation.restaurant_id,
            "table_ids": list(reservation.table_ids), "party_size": reservation.party_size,
            "starts_at": reservation.starts_at.isoformat(), "status": reservation.status,
            "created_at": reservation.created_at.isoformat(), "revision": reservation.revision,
            "policy_version": reservation.terms.version,
            "history": [{"seq": entry.seq, "at": entry.at.isoformat(), "event": entry.event,
                         "changes": [{"field": change.field, "from": _value(change.before),
                                      "to": _value(change.after)} for change in entry.changes],
                         "revision": entry.revision, "policy_version": entry.terms.version}
                        for entry in state.history[reservation.reference]]}


def _value(value: object) -> object:
    """A recorded field value as JSON: a table set as a list, a start as a timestamp."""
    if isinstance(value, tuple):
        return list(value)
    return value.isoformat() if isinstance(value, datetime) else value


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
        revision = reader.integer(item, "revision", path, minimum=0)
        if restaurant is not None:
            state.policies[restaurant.id] = _policies(reader, item, path, restaurant)
            state.restaurant_revisions[restaurant.id] = revision
    state.restaurants = records.restaurants
    reservations = _reservations(reader, records, data, state)
    records.reject_overlaps(reservations)
    for reservation in reservations:
        state.put_reservation(reservation)
    for path, item in reader.objects(data, "series"):
        _series(reader, item, path, state)
    for path, item in reader.objects(data, "plans"):
        _plan(reader, item, path, state)
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
        entries = _history(reader, item, path, policies)
        if entries:
            reservations.append(booking.reservation(starts_at, created_at, revision=revision,
                                                    terms=policies[version]))
            state.history[booking.reference] = entries
    return reservations


def _history(reader: FieldReader, item: dict, path: str, policies: list[Policy]) -> list[Entry]:
    """A reservation's history, numbered 1, 2, ...; it records at least the creation."""
    entries = []
    listed = reader.objects(item, "history", path)
    if not listed:
        reader.reject(at(path, "history"), "must record at least the creation")
    for index, (where, record) in enumerate(listed, start=1):
        seq = reader.integer(record, "seq", where, minimum=index, maximum=index)
        when = reader.parsed(record, "at", where, timeutil.parse_instant, "must be a timestamp with an offset")
        event = reader.read(record, "event", "string", where)
        revision = reader.integer(record, "revision", where, minimum=1)
        version = reader.integer(record, "policy_version", where, minimum=0, maximum=len(policies) - 1)
        changes = [_change(reader, change, place) for place, change in reader.objects(record, "changes", where)]
        if event is not None and event not in EVENTS:
            reader.reject(at(where, "event"), f"must be one of {', '.join(EVENTS)}")
        elif None not in (seq, when, event, revision, version, *changes):
            entries.append(Entry(seq=seq, at=when, event=event, changes=tuple(changes),
                                 revision=revision, terms=policies[version]))
    return entries


def _change(reader: FieldReader, record: dict, where: str) -> Change | None:
    """One recorded change: a table set, a start or a party size, before (None at creation)
    and after."""
    name = reader.read(record, "field", "string", where)
    if name not in FIELDS:
        reader.reject(at(where, "field"), f"must be one of {', '.join(FIELDS)}")
        return None
    before, after = (_recorded(record.get(side), name) for side in ("from", "to"))
    if after is None or (before is None and record.get("from") is not None):
        reader.reject(where, "must record a value after the change, and a valid one before")
        return None
    return Change(name, before, after)


def _recorded(value: Any, name: str) -> Any:
    """A recorded value of field `name`, or None when absent, null or invalid."""
    if name == "table_ids":
        return tuple(value) if isinstance(value, list) and value and all(isinstance(v, str) for v in value) else None
    if name == "starts_at":
        return timeutil.parse_instant(value) if isinstance(value, str) else None
    return value if type(value) is int and value >= 1 else None


def _series(reader: FieldReader, item: dict, path: str, state: State) -> None:
    """A series: its owner's bookings at one restaurant as occurrences 0, 1, ..., each in no
    other series, 2 to 12 of them."""
    series_id = reader.identifier(item, "id", path)
    user_id = reader.identifier(item, "user_id", path)
    interval_weeks = reader.integer(item, "interval_weeks", path, minimum=1, maximum=4)
    revision = reader.integer(item, "revision", path, minimum=1)
    occurrences = []
    for index, (where, record) in enumerate(reader.objects(item, "occurrences", path)):
        reader.integer(record, "index", where, minimum=index, maximum=index)
        reference = reader.read(record, "reference", "string", where)
        exception = record.get("exception")
        booking = state.reservations.get(reference)
        if booking is None or booking.user_id != user_id or reference in state.series_by_reference:
            reader.reject(at(where, "reference"), "must be one of the owner's bookings in no other series")
        elif not isinstance(exception, bool):
            reader.reject(at(where, "exception"), "must be true or false")
        else:
            occurrences.append(Occurrence(index, reference, exception))
    if len({state.reservations[o.reference].restaurant_id for o in occurrences}) > 1:
        reader.reject(at(path, "occurrences"), "must all be at one restaurant")
    elif not 2 <= len(occurrences) <= 12:
        reader.reject(at(path, "occurrences"), "must number 2 to 12")
    elif series_id in state.series:
        reader.reject(at(path, "id"), "is not unique")
    elif None not in (series_id, user_id, interval_weeks, revision):
        add(state, Series(series_id, user_id, interval_weeks, revision, tuple(occurrences)))


def _plan(reader: FieldReader, item: dict, path: str, state: State) -> None:
    """A stored plan: a closure of one of its restaurant's tables, and a seat - a table or a
    declared pair in declared order - for each of that restaurant's bookings it names, in
    ascending reference order, its counts agreeing with its seats."""
    plan_id = reader.identifier(item, "plan_id", path)
    restaurant = state.restaurants.get(reader.identifier(item, "restaurant_id", path))
    closure = reader.read(item, "closure", "object", path)
    closed = None if closure is None else read_closure(reader, closure, at(path, "closure"))
    revision = reader.integer(item, "restaurant_revision", path, minimum=0)
    unused = reader.integer(item, "unused_seats", path, minimum=0)
    moved = reader.integer(item, "moved_count", path, minimum=0)
    if restaurant is None:
        reader.reject(at(path, "restaurant_id"), "is not a known restaurant")
        return
    options = {(table.id,) for table in restaurant.tables} | set(restaurant.combinable)
    seats = []
    for where, record in reader.objects(item, "assignments", path):
        reference = reader.read(record, "reference", "string", where)
        listed = reader.read(record, "table_ids", "array", where)
        table_ids = None if listed is None else reader.strings(listed, at(where, "table_ids"))
        changed = record.get("changed")
        booking = state.reservations.get(reference)
        if booking is None or booking.restaurant_id != restaurant.id:
            reader.reject(at(where, "reference"), "is not a booking of the plan's restaurant")
        elif table_ids is not None and tuple(table_ids) not in options:
            reader.reject(at(where, "table_ids"), "must be a table or a declared pair in declared order")
        elif not isinstance(changed, bool):
            reader.reject(at(where, "changed"), "must be true or false")
        elif table_ids is not None:
            seats.append(planner.Seat(reference, tuple(table_ids), changed))
    if closed is not None and restaurant.table(closed[0]) is None:
        reader.reject(at(path, "closure.table_id"), "is not a table of the plan's restaurant")
    elif [seat.reference for seat in seats] != sorted({seat.reference for seat in seats}):
        reader.reject(at(path, "assignments"), "must name each booking once, in ascending reference order")
    elif moved is not None and moved != sum(seat.changed for seat in seats):
        reader.reject(at(path, "moved_count"), "must count the changed assignments")
    elif plan_id in state.plans:
        reader.reject(at(path, "plan_id"), "is not unique")
    elif None not in (plan_id, closed, revision, unused, moved):
        state.plans[plan_id] = Plan(plan_id, restaurant.id, closed[0], closure["from"], closure["to"],
                                    tuple(seats), unused, revision)


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

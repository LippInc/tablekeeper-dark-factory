"""Migrations of exported states between schemas (§10).

`MIGRATIONS[n]` turns a schema-n state into schema n + 1. An import runs every step from
the export's schema up to the current one and then validates the result like any other
state, so each step only reshapes records and leaves checking to the import. Credentials,
tokens and receipts pass through untouched: a replay after an upgrade returns the original
response exactly as it was sent.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _each(state: dict, name: str, migrate: Callable[[Any], Any]) -> Any:
    """The records listed under `name`, each migrated; anything else is left for the import
    to refuse."""
    records = state.get(name)
    return [migrate(record) for record in records] if isinstance(records, list) else records


def _extended(record: Any, **fields: Any) -> Any:
    """A record with new fields added; anything that is not a record is left as it is."""
    return {**record, **fields} if isinstance(record, dict) else record


def _schema_1_to_2(state: dict) -> dict:
    """Stage 2 adds combined tables: a reservation's `table_id` becomes the set
    `table_ids`, and a restaurant declares its `combinable` pairs (none before)."""
    def reservation(record: Any) -> Any:
        # Schema 1 knows only table_id; a table_ids field there is unknown and ignored (E10),
        # so a record without table_id stays without a table and is refused.
        if not isinstance(record, dict):
            return record
        moved = {name: value for name, value in record.items() if name not in ("table_id", "table_ids")}
        return {**moved, "table_ids": [record["table_id"]]} if "table_id" in record else moved

    return {**state, "schema": 2, "reservations": _each(state, "reservations", reservation),
            "restaurants": _each(state, "restaurants", lambda record: _extended(record, combinable=[]))}


def _schema_2_to_3(state: dict) -> dict:
    """Stage 3 adds dated policies, revisions and history (H6, P4): a restaurant has managers
    and published policies (none before), and every reservation stands at revision 1 under
    policy 0, the exported restaurant's own rules, which it was booked under, with one
    `created` entry at its creation holding its fields as they are; there are no series."""
    def reservation(record: Any) -> Any:
        if not isinstance(record, dict):
            return record
        created = {"seq": 1, "at": record.get("created_at"), "event": "created",
                   "changes": [{"field": name, "from": None, "to": record.get(name)}
                               for name in ("table_ids", "starts_at", "party_size")],
                   "revision": 1, "policy_version": 0}
        return {**record, "revision": 1, "policy_version": 0, "history": [created]}

    return {**state, "schema": 3, "series": [],
            "restaurants": _each(state, "restaurants", lambda record: _extended(
                record, manager_user_ids=[], policies=[])),
            "reservations": _each(state, "reservations", reservation)}


def _schema_3_to_4(state: dict) -> dict:
    """Stage 4 counts each restaurant's changes and plans seatings (Q5, Q24): an earlier
    stage's restaurant stands at revision 0, as after a reset, and there are no plans."""
    return {**state, "schema": 4, "plans": [],
            "restaurants": _each(state, "restaurants", lambda record: _extended(record, revision=0))}


MIGRATIONS = {1: _schema_1_to_2, 2: _schema_2_to_3, 3: _schema_3_to_4}
SCHEMA = max(MIGRATIONS) + 1  # the schema this service exports


def upgraded(state: dict) -> dict | None:
    """`state` migrated to the current schema, or None when its schema is not one this
    service knows."""
    schema = state.get("schema")
    if type(schema) is not int or not 1 <= schema <= SCHEMA:
        return None
    for step in range(schema, SCHEMA):
        state = MIGRATIONS[step](state)
    return state

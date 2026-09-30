"""Migrations of exported states between schemas (§10).

`MIGRATIONS[n]` turns a schema-n state into schema n + 1. An import runs every step from
the export's schema up to the current one and then validates the result like any other
state, so each step only reshapes records and leaves checking to the import. Credentials,
tokens and receipts pass through untouched: a replay after an upgrade returns the original
response exactly as it was sent.
"""
from __future__ import annotations

from typing import Any


def _schema_1_to_2(state: dict) -> dict:
    """Stage 2 adds combined tables: a reservation's `table_id` becomes the set
    `table_ids`, and a restaurant declares its `combinable` pairs (none before)."""
    def reservation(record: Any) -> Any:
        if not isinstance(record, dict) or "table_id" not in record:
            return record
        moved = {name: value for name, value in record.items() if name != "table_id"}
        return {**moved, "table_ids": [record["table_id"]]}

    def restaurant(record: Any) -> Any:
        return {**record, "combinable": []} if isinstance(record, dict) else record

    def each(name: str, migrate) -> Any:
        records = state.get(name)
        return [migrate(record) for record in records] if isinstance(records, list) else records

    return {**state, "schema": 2, "reservations": each("reservations", reservation),
            "restaurants": each("restaurants", restaurant)}


MIGRATIONS = {1: _schema_1_to_2}
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

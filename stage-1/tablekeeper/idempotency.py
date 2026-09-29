"""Idempotency keys for keyed writes (§7).

A key is scoped to one user, method and path. Only a successful outcome is recorded, so a
key whose request failed stays unused. A replay is the same body as a JSON value: key
order and whitespace do not matter, but `4` and `4.0` or `1` and `true` differ.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from .errors import ApiError, invalid
from .store import Receipt, Scope, State

MAX_KEY_LENGTH = 255


def read_key(headers: Mapping[str, str]) -> str:
    key = headers.get("idempotency-key")
    if not key:
        raise ApiError(400, "missing_idempotency_key", "an Idempotency-Key header is required")
    if len(key) > MAX_KEY_LENGTH:
        raise invalid(f"Idempotency-Key must be at most {MAX_KEY_LENGTH} characters")
    return key


def _canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def original_response(state: State, scope: Scope, body: dict) -> dict | None:
    """The response recorded for a replay of this request, or None on a key's first use.

    The same key with a different body is 409 `idempotency_key_reuse`.
    """
    receipt = state.receipts.get(scope)
    if receipt is None:
        return None
    if receipt.request != _canonical(body):
        raise ApiError(409, "idempotency_key_reuse", "that key was used with a different body")
    return receipt.response


def record(state: State, scope: Scope, body: dict, response: dict) -> None:
    state.receipts[scope] = Receipt(request=_canonical(body), response=response)

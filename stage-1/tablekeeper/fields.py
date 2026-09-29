"""Reading fields out of a parsed JSON body (§5).

A field of the wrong JSON type is 400 `malformed_request`; a missing field, or a value of
the right type that breaks a rule, is 422 `validation_failed`. A wrong type outranks every
other problem anywhere in the body, so a reader records problems while the body is walked
and `raise_first` reports the highest-ranked one once the walk is done. Unknown fields are
never read, so they are ignored.
"""
from __future__ import annotations

from typing import Any

from .errors import invalid, malformed

MAX_ID_LENGTH = 64

_JSON_TYPES = {"string": str, "number": (int, float), "array": list, "object": dict}


def at(path: str, name: str | int) -> str:
    """The display path of a member (`name`) or element (`int`) below `path`."""
    if isinstance(name, int):
        return f"{path}[{name}]"
    return f"{path}.{name}" if path else name


class FieldReader:
    def __init__(self) -> None:
        self._wrong_type: str | None = None
        self._invalid: str | None = None

    def reject(self, path: str, reason: str) -> None:
        """Record a missing or invalid value (422)."""
        if self._invalid is None:
            self._invalid = f"{path} {reason}"

    def _reject_type(self, path: str, kind: str) -> None:
        """Record a wrong JSON type (400)."""
        if self._wrong_type is None:
            self._wrong_type = f"{path} must be a JSON {kind}"

    def read(self, obj: dict, name: str, kind: str, path: str = "", *,
             required: bool = True) -> Any:
        """`obj[name]` when it has JSON type `kind`; otherwise None, with the problem recorded.

        Booleans are never numbers here, and `null` is a wrong type like any other.
        """
        where = at(path, name)
        if name not in obj:
            if required:
                self.reject(where, "is required")
            return None
        value = obj[name]
        if isinstance(value, bool) or not isinstance(value, _JSON_TYPES[kind]):
            self._reject_type(where, kind)
            return None
        return value

    def integer(self, obj: dict, name: str, path: str, *, minimum: int,
                maximum: int | None = None) -> int | None:
        """A whole JSON number within [minimum, maximum]; `4.0` is not whole (422)."""
        value = self.read(obj, name, "number", path)
        if value is None:
            return None
        if isinstance(value, float) or value < minimum or (maximum is not None and value > maximum):
            bound = f"from {minimum} to {maximum}" if maximum is not None else f"of at least {minimum}"
            self.reject(at(path, name), f"must be an integer {bound}")
            return None
        return value

    def identifier(self, obj: dict, name: str, path: str) -> str | None:
        """An opaque ID: a string of 1 to 64 characters (§3.4)."""
        value = self.read(obj, name, "string", path)
        if value is not None and not 1 <= len(value) <= MAX_ID_LENGTH:
            self.reject(at(path, name), f"must be 1 to {MAX_ID_LENGTH} characters")
            return None
        return value

    def objects(self, obj: dict, name: str, path: str = "", *,
                required: bool = True) -> list[tuple[str, dict]]:
        """The object elements of an array member, each with its display path."""
        items = self.read(obj, name, "array", path, required=required) or []
        found = []
        for index, item in enumerate(items):
            where = at(at(path, name), index)
            if isinstance(item, dict):
                found.append((where, item))
            else:
                self._reject_type(where, "object")
        return found

    def raise_first(self) -> None:
        if self._wrong_type is not None:
            raise malformed(self._wrong_type)
        if self._invalid is not None:
            raise invalid(self._invalid)

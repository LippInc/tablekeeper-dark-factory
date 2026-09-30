"""Reading fields out of a parsed JSON body or a query string (§5).

A field of the wrong JSON type is 400 `malformed_request`; a missing field, or a value of
the right type that breaks a rule, is 422 `validation_failed`. A wrong type outranks every
other problem anywhere in the body, so a reader records problems while the body is walked
and `raise_first` reports the highest-ranked one once the walk is done. Unknown fields are
never read, so they are ignored. Query parameters are always strings, so only 422 applies
to them.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, TypeVar

from . import timeutil
from .errors import invalid, malformed

MAX_ID_LENGTH = 64

_DIGITS = re.compile(r"[0-9]+")

T = TypeVar("T")


def is_identifier(value: str) -> bool:
    """An opaque ID is a string of 1 to 64 characters (§3.4)."""
    return 1 <= len(value) <= MAX_ID_LENGTH

_JSON_TYPES = {"string": str, "number": (int, float), "array": list, "object": dict}


def at(path: str, name: str | int) -> str:
    """The display path of a member (`name`) or element (`int`) below `path`."""
    if isinstance(name, int):
        return f"{path}[{name}]"
    return f"{path}.{name}" if path else name


class FieldReader:
    def __init__(self) -> None:
        self._foremost: str | None = None
        self._wrong_type: str | None = None
        self._invalid: str | None = None

    def reject_foremost(self, path: str, reason: str) -> None:
        """Record an invalid value (422) that a stated rule ranks before any wrong type."""
        if self._foremost is None:
            self._foremost = f"{path} {reason}"

    def reject(self, path: str, reason: str) -> None:
        """Record a missing or invalid value (422)."""
        if self._invalid is None:
            self._invalid = f"{path} {reason}"

    @staticmethod
    def _has_type(value: Any, kind: str) -> bool:
        """Whether `value` has JSON type `kind`: booleans are never numbers, and `null` has
        no type a field asks for."""
        return not isinstance(value, bool) and isinstance(value, _JSON_TYPES[kind])

    def _reject_type(self, path: str, kind: str) -> None:
        """Record a wrong JSON type (400)."""
        if self._wrong_type is None:
            self._wrong_type = f"{path} must be a JSON {kind}"

    def read(self, obj: dict, name: str, kind: str, path: str = "", *,
             required: bool = True) -> Any:
        """`obj[name]` when it has JSON type `kind`; otherwise None, with the problem recorded."""
        where = at(path, name)
        if name not in obj:
            if required:
                self.reject(where, "is required")
            return None
        value = obj[name]
        if not self._has_type(value, kind):
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
        return self._identifier(at(path, name), self.read(obj, name, "string", path))

    def _identifier(self, where: str, value: str | None) -> str | None:
        if value is not None and not is_identifier(value):
            self.reject(where, f"must be 1 to {MAX_ID_LENGTH} characters")
            return None
        return value

    def param(self, params: Mapping[str, str], name: str) -> str | None:
        """A required query parameter."""
        value = params.get(name)
        if value is None:
            self.reject(name, "is required")
        return value

    def identifier_param(self, params: Mapping[str, str], name: str) -> str | None:
        return self._identifier(name, self.param(params, name))

    def parsed(self, obj: Mapping[str, Any], name: str, path: str,
               parse: Callable[[str], T | None], reason: str) -> T | None:
        """A string field (or query parameter) turned into a value by `parse`, which
        returns None for a string that breaks the field's format (422 with `reason`)."""
        text = self.read(obj, name, "string", path)
        value = None if text is None else parse(text)
        if text is not None and value is None:
            self.reject(at(path, name), reason)
        return value

    def date_param(self, params: Mapping[str, str], name: str) -> date | None:
        return self.parsed(params, name, "", timeutil.parse_date,
                           "must be a calendar date YYYY-MM-DD")

    def integer_param(self, params: Mapping[str, str], name: str, *,
                      minimum: int) -> int | None:
        """An integer written as plain decimal digits: `1e9`, `4.0` and `+4` are not (§5)."""
        value = self.param(params, name)
        if value is None:
            return None
        try:
            number = int(value) if _DIGITS.fullmatch(value) else None
        except ValueError:  # more digits than Python converts
            number = None
        if number is None or number < minimum:
            self.reject(name, f"must be plain decimal digits, at least {minimum}")
            return None
        return number

    def elements(self, values: list, kind: str, path: str) -> list[tuple[str, Any]]:
        """The elements of the array at `path` that have JSON type `kind`, each with its
        display path; every other element is recorded as a wrong type."""
        found = []
        for index, value in enumerate(values):
            if self._has_type(value, kind):
                found.append((at(path, index), value))
            else:
                self._reject_type(at(path, index), kind)
        return found

    def objects(self, obj: dict, name: str, path: str = "", *,
                required: bool = True) -> list[tuple[str, dict]]:
        """The object elements of an array member, each with its display path."""
        items = self.read(obj, name, "array", path, required=required) or []
        return self.elements(items, "object", at(path, name))

    def strings(self, values: list, path: str) -> list[str] | None:
        """An array whose elements must all be strings; None when one is not."""
        found = self.elements(values, "string", path)
        return [value for _, value in found] if len(found) == len(values) else None

    def raise_first(self) -> None:
        if self._foremost is not None:
            raise invalid(self._foremost)
        if self._wrong_type is not None:
            raise malformed(self._wrong_type)
        if self._invalid is not None:
            raise invalid(self._invalid)

    def raise_as_invalid(self) -> None:
        """Raise the first problem as 422 whatever its kind, as an imported state's (§10)."""
        problem = self._foremost or self._wrong_type or self._invalid
        if problem is not None:
            raise invalid(problem)

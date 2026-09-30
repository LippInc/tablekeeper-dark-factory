"""Recurring agreements (stage 3): a reservation adopted as occurrence zero of a series, and
the occurrences generated after it.

A series changes only in the second phase of `booking.apply`, alongside its occurrences:
each operation that really changes or cancels occurrences of a series raises its revision
once, and an occurrence the diner really changed stays an exception for good; a seating
repair or an amendment of the series itself marks no exception.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .domain import CANCELLED, Reservation, User, show
from .errors import not_found

if TYPE_CHECKING:
    from .store import State


@dataclass(frozen=True)
class Occurrence:
    index: int
    reference: str
    exception: bool = False


@dataclass(frozen=True)
class Series:
    id: str
    user_id: str
    interval_weeks: int
    revision: int
    occurrences: tuple[Occurrence, ...]  # in index order; the anchor is occurrence 0


def add(state: State, series: Series) -> None:
    state.series[series.id] = series
    for occurrence in series.occurrences:
        state.series_by_reference[occurrence.reference] = series.id


def record(state: State, changes: list[tuple[Reservation | None, Reservation]], *,
           marks_exceptions: bool = True) -> None:
    """Phase two of an operation's `changes` (previous, current): each series with an
    occurrence changed or cancelled gains one revision; when the operation `marks_exceptions`
    (a diner's own change, not a seating repair nor an amendment of the whole series), each
    occurrence it really changed becomes an exception. New reservations belong to no series
    yet."""
    touched: dict[str, set[str]] = {}
    for previous, current in changes:
        series_id = state.series_by_reference.get(current.reference)
        if previous is not None and series_id is not None:
            exceptions = touched.setdefault(series_id, set())
            if current.status != CANCELLED and marks_exceptions:
                exceptions.add(current.reference)
    for series_id, exceptions in touched.items():
        series = state.series[series_id]
        state.series[series_id] = replace(series, revision=series.revision + 1, occurrences=tuple(
            replace(occurrence, exception=True) if occurrence.reference in exceptions else occurrence
            for occurrence in series.occurrences))


def own_series(state: State, user: User | None, series_id: str) -> Series:
    """The caller's series; anyone else's, or any series to a caller not signed in, is 404."""
    series = state.series.get(series_id)
    if series is None or user is None or series.user_id != user.id:
        raise not_found(f"no series {series_id!r}")
    return series


def view(state: State, series: Series) -> dict:
    """A series with its occurrences' current reservations."""
    return {"series_id": series.id, "revision": series.revision,
            "interval_weeks": series.interval_weeks,
            "occurrences": [{"index": occurrence.index, "reference": occurrence.reference,
                             "exception": occurrence.exception,
                             "reservation": show(state, state.reservations[occurrence.reference])}
                            for occurrence in series.occurrences]}

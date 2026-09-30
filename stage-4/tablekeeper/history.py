"""A reservation's own record of what happened to it (stage 3): created, changed, cancelled,
and (stage 4) reassigned to other tables by an applied seating plan.

History is written only in the second phase of `booking.apply`, once every check has
passed, so a refused request, a no-op or a replay never adds an entry. Each entry keeps the
revision and the terms the reservation had right after it, and never changes afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import timeutil
from .domain import CANCELLED, Policy, Reservation, accepted_terms

if TYPE_CHECKING:
    from .store import State

CREATED, CHANGED, REASSIGNED = "created", "changed", "reassigned"
EVENTS = (CREATED, CHANGED, CANCELLED, REASSIGNED)
FIELDS = ("table_ids", "starts_at", "party_size")  # the order changes are named in


@dataclass(frozen=True)
class Change:
    """One field before and after; `before` is None when the reservation was created."""
    field: str  # one of FIELDS
    before: Any
    after: Any


@dataclass(frozen=True)
class Entry:
    seq: int
    at: datetime  # UTC
    event: str
    changes: tuple[Change, ...]
    revision: int
    terms: Policy
    plan_id: str | None = None  # the plan that reassigned it


def _values(reservation: Reservation) -> dict[str, Any]:
    return {"table_ids": reservation.table_ids, "starts_at": reservation.starts_at,
            "party_size": reservation.party_size}


def record(state: State, previous: Reservation | None, current: Reservation, at: datetime,
           plan_id: str | None = None) -> None:
    """Append the entry for `current` replacing `previous` (None for a new reservation); a
    change made by applying plan `plan_id` is a reassignment, which names the plan."""
    entries = state.history.setdefault(current.reference, [])
    if previous is None:
        event, changes = CREATED, tuple(Change(name, None, value) for name, value in _values(current).items())
    elif current.status == CANCELLED:
        event, changes = CANCELLED, ()
    else:
        before, after = _values(previous), _values(current)
        event = CHANGED if plan_id is None else REASSIGNED
        changes = tuple(Change(name, before[name], after[name]) for name in FIELDS if before[name] != after[name])
    at = max(at, entries[-1].at) if entries else at  # entries in seq order are also in time order
    entries.append(Entry(seq=len(entries) + 1, at=at, event=event, changes=changes,
                         revision=current.revision, terms=current.terms, plan_id=plan_id))


def view(state: State, reservation: Reservation) -> dict:
    """The history as the API shows it, oldest first: times and starts at the restaurant."""
    zone = state.restaurants[reservation.restaurant_id].zone
    return {"reference": reservation.reference, "entries": [
        {"seq": entry.seq, "at": timeutil.rfc3339(entry.at, zone), "event": entry.event,
         "changes": [_shown(change, zone, as_set=entry.event == REASSIGNED) for change in entry.changes],
         **({} if entry.plan_id is None else {"plan_id": entry.plan_id}),
         "revision": entry.revision, "accepted_terms": accepted_terms(entry.terms)}
        for entry in state.history[reservation.reference]]}


def _shown(change: Change, zone, as_set: bool) -> dict:
    """A change in the API's field names: a table set is `table_id` while both sides are a
    single table and `table_ids` whenever either side is a pair, or always (`as_set`) in a
    reassignment; a start is local."""
    if change.field == "starts_at":
        return {"field": "starts_at_local",
                "from": None if change.before is None else timeutil.local_text(change.before, zone),
                "to": timeutil.local_text(change.after, zone)}
    if change.field == "table_ids":
        if not as_set and all(side is None or len(side) == 1 for side in (change.before, change.after)):
            return {"field": "table_id", "from": change.before and change.before[0],
                    "to": change.after[0]}
        return {"field": "table_ids", "from": None if change.before is None else list(change.before),
                "to": list(change.after)}
    return {"field": change.field, "from": change.before, "to": change.after}

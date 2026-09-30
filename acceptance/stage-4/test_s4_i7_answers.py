"""S4-I7 acceptance checks (verifier seat): the cheaper availability answers stay the answers the
rule text gives (stage-3 R302-R310, R329; stage-2 options), for every party size and both forms,
and the kept answers follow every write they depend on (Q27): a policy publication that changes
capacities and duration for one date only, and an applied closure (S4-I3). From the S4-I7
"Done means" in the room plan.

Resets the service: run it alone against other files that reset it.
"""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import assert_status, new_key

pytestmark = pytest.mark.stage(4)

BERLIN = ZoneInfo("Europe/Berlin")
DATE = fx.booking_date()
CAPS = {f"t_{n}": n for n in range(1, 7)}  # t_1 1 seat ... t_6 6 (within the planning limit of 6 tables)
PAIRS = [["t_1", "t_2"], ["t_6", "t_3"]]
OPENS, CLOSES = "12:00", "23:00"


def minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def later(days: int) -> str:
    return (dt.date.fromisoformat(DATE) + dt.timedelta(days=days)).isoformat()


# seeded bookings on DATE: (reference, tables, start); policy 0 lasts 90 minutes
SEEDS = [("SEED01", ["t_1"], "18:00"), ("SEED02", ["t_3"], "19:30"), ("SEED03", ["t_4", "t_5"], "12:30"),
         ("SEED04", ["t_2"], "21:00"), ("SEED05", ["t_6"], "20:15"), ("SEED06", ["t_6"], "13:45")]


@pytest.fixture
def world(reset, api):
    tables = [{"id": t, "label": t[2:], "capacity": c} for t, c in CAPS.items()]
    pairs = PAIRS + [["t_4", "t_5"]]
    reset(fx.fixture(restaurants=[{**fx.restaurant(tables=tables, slot_minutes=15, opening_hours=fx.all_week(OPENS, CLOSES)),
                                   "manager_user_ids": [fx.ADA["id"]], "combinable": pairs}],
                     reservations=[{"id": f"res_{r}", "reference": r, "user_id": "u_bob", "restaurant_id": "r_anker",
                                    **({"table_id": t[0]} if len(t) == 1 else {"table_ids": t}),
                                    "starts_at_local": fx.local(DATE, s), "party_size": 1} for r, t, s in SEEDS]))
    return SimpleNamespace(ada=api().authenticate(fx.ADA["email"], fx.ADA["password"]),
                           bob=api().authenticate(fx.BOB["email"], fx.BOB["password"]), pairs=pairs)


def held_on(date: str, closures=()) -> dict[str, list[tuple[int, int]]]:
    held: dict[str, list] = {}
    for _, tables, start in SEEDS if date == DATE else []:
        for table in tables:
            held.setdefault(table, []).append((minutes(start), minutes(start) + 90))
    for table, start, end in closures:
        held.setdefault(table, []).append((start, end))
    return held


def reference(date, party, explain, pairs, caps=CAPS, duration=90, slot=15, version=0, held=None) -> dict:
    """The answer by the rule text: slots every `slot` minutes from opening while a booking of
    `duration` ends by closing; a table available when it seats the party (R302 capacity) and
    nothing holds it over the slot (no_overlap); options = those singles, then declared pairs
    whose summed capacity seats the party and whose tables are both free."""
    held = held_on(date) if held is None else held
    offset = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(12), BERLIN).isoformat()[-6:]
    slots = []
    for start in range(minutes(OPENS), minutes(CLOSES) - duration + 1, slot):
        free = {t for t in caps if not any(s < start + duration and start < e for s, e in held.get(t, []))}
        singles = [t for t in caps if t in free and party <= caps[t]]
        options = [{"table_ids": [t], "capacity": caps[t]} for t in singles] + [
            {"table_ids": p, "capacity": caps[p[0]] + caps[p[1]]} for p in pairs
            if caps[p[0]] + caps[p[1]] >= party and p[0] in free and p[1] in free]
        text = f"{start // 60:02d}:{start % 60:02d}"
        entry = {"starts_at_local": f"{date}T{text}", "starts_at": f"{date}T{text}:00{offset}",
                 "available_table_ids": singles, "available_options": options}
        if explain:
            entry["explain"] = [{"table_id": t, "policy_version": version, "available": t in singles,
                                 "rules": [{"rule": "capacity", "holds": party <= caps[t]},
                                           {"rule": "no_overlap", "holds": t in free}]} for t in caps]
        slots.append(entry)
    return {"restaurant_id": "r_anker", "date": date, "timezone": "Europe/Berlin", "slots": slots}


def ask(world, date, party, explain):
    params = {"restaurant_id": "r_anker", "date": date, "party_size": party, **({"explain": "true"} if explain else {})}
    return assert_status(world.bob.get("/availability", params=params), 200).content


@pytest.mark.parametrize("explain", [False, True], ids=["plain", "explained"])
def test_every_party_size_is_answered_by_the_rule_text_and_asked_again_the_same(world, explain):
    """R302-R310/R329/stage-2 options: parties 1-10 on a day with singles and pairs held, each
    asked twice (the second from the kept answer), equal the rule-by-rule reference; answers of
    parties 1-7 and 10 all differ (8 and 9 read as 7: only the 9-seat pairs fit)."""
    answers = {}
    for party in range(1, 11):
        first, second = ask(world, DATE, party, explain), ask(world, DATE, party, explain)
        assert first == second, party
        assert json.loads(first) == reference(DATE, party, explain, world.pairs), party
        answers[party] = first
    assert len({answers[party] for party in (1, 2, 3, 4, 5, 6, 7, 10)}) == 8 and answers[7] == answers[8] == answers[9]


def test_a_policy_for_one_date_changes_that_dates_answers_only(world):
    """Q27/H1: with answers kept for three dates (both forms), policies published for the middle
    date (other capacities, 60 minutes, 30-minute slots) and from the day after (policy 0's
    values again) change the middle date's answers to the new rules; the day before reads
    byte-identical; the day after reads identical plain and, explained, names policy 2."""
    days = [later(7), later(8), later(9)]
    before = {(d, e): ask(world, d, 3, e) for d in days for e in (False, True)}
    caps = {t: (c % 4) + 3 for t, c in CAPS.items()}
    assert_status(world.ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=fx.policy(
        days[1], slot_minutes=30, reservation_duration_minutes=60, opening_hours=fx.all_week(OPENS, CLOSES),
        capacities=caps)), 201)
    assert_status(world.ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=fx.policy(
        days[2], slot_minutes=15, reservation_duration_minutes=90, opening_hours=fx.all_week(OPENS, CLOSES),
        capacities=CAPS)), 201)
    for explain in (False, True):
        assert ask(world, days[0], 3, explain) == before[(days[0], explain)]
        middle = ask(world, days[1], 3, explain)
        assert middle != before[(days[1], explain)]
        assert json.loads(middle) == reference(days[1], 3, explain, world.pairs, caps=caps, duration=60, slot=30, version=1)
        assert json.loads(ask(world, days[2], 3, explain)) == reference(days[2], 3, explain, world.pairs, version=2)
    assert ask(world, days[2], 3, False) == before[(days[2], False)]


def test_an_applied_closure_changes_the_next_answer(world):
    """Q27/Q26/R437/R438: with answers kept, applying a plan that closes t_4 from 16:30 to 17:30
    (nothing to move) makes the next answers exclude t_4 there, as the reference says."""
    kept = {e: ask(world, DATE, 2, e) for e in (False, True)}
    body = {"table_id": "t_4", "from": dt.datetime.combine(dt.date.fromisoformat(DATE), dt.time(16, 30), BERLIN).isoformat(),
            "to": dt.datetime.combine(dt.date.fromisoformat(DATE), dt.time(17, 30), BERLIN).isoformat()}
    plan = assert_status(world.ada.post("/restaurants/r_anker/replans", idempotency_key=new_key(), json=body), 201).json()
    assert plan["assignments"] == []
    assert_status(world.ada.post(f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", idempotency_key=new_key(), json={}), 201)
    held = held_on(DATE, closures=[("t_4", minutes("16:30"), minutes("17:30"))])
    for explain in (False, True):
        answer = ask(world, DATE, 2, explain)
        assert answer != kept[explain]
        assert json.loads(answer) == reference(DATE, 2, explain, world.pairs, held=held)

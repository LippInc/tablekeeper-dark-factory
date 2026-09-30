"""S4-I7 acceptance checks (verifier seat): dense availability within the task's 5 s per request
for every question mix (R468), the answers unchanged (stage-3 R302-R310, R329), from the item's
"Done means" in the room plan.

The dense state is built through the API on the stage-3 service of the same checkout
(TABLEKEEPER_STAGE3_URL): one restaurant, 40 tables of n % 8 + 1 seats, 1-minute slots from
00:00 to 23:30, policy 0 lasting 90 minutes and a published 45-minute policy from day D; on D
and every 5th day after it (10 dense dates) 200 seeded 90-minute and 200 created 45-minute
bookings. Its export is imported into the service under test and, when TABLEKEEPER_CONTROL_URL
names one (b9c3881, S4-I1), into the control, so both hold the same state.

Burst (a): 50 simultaneous different questions, parties 1-10 on D and the four days after it.
Burst (b): 50 simultaneous questions on 50 different dates (D .. D+49, party 2; the 10 dense
dates among them). Each burst is sent explained, then plain; with a control the two services
take turns (the order alternates by round). Every answer's slowest arrival must be under 5 s,
the explained burst's slowest at most half of the control's in the same round, every answer
byte-identical to the control's, and three answers per burst equal to the rule-by-rule
reference computed here from the bookings as created.

S4I7_ROUNDS sets the rounds per test (default 1). Resets the stage-3 service and the service
under test: run it alone, with nothing else loading the services; `-rP` prints the values.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
import time
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(4)

BERLIN = ZoneInfo("Europe/Berlin")
LIMIT_S = 5.0
TABLES = 40
ROUNDS = int(os.environ.get("S4I7_ROUNDS", "1"))
OPENS, CLOSES = 0, 23 * 60 + 30
SEED_MINUTES, MADE_MINUTES = 90, 45


def capacity(n: int) -> int:
    return n % 8 + 1


def first_dense_day() -> dt.date:
    """At least 30 days ahead, with no change of UTC offset from it to 50 days later."""
    day = dt.date.fromisoformat(fx.booking_date(lead=30))
    while len({dt.datetime.combine(day + dt.timedelta(days=k), dt.time(12), BERLIN).utcoffset()
               for k in range(52)}) > 1:
        day += dt.timedelta(days=1)
    return day


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def plan_bookings(day: dt.date):
    """Per dense date, per table: five 90-minute (seeded) and five 45-minute (made) bookings,
    alternating, 40 minutes apart, the first at a table-specific minute."""
    seeds, made = [], []
    for k in range(10):
        date = (day + dt.timedelta(days=5 * k)).isoformat()
        for n in range(1, TABLES + 1):
            cursor = (n * 7) % 60
            for j in range(10):
                minutes = SEED_MINUTES if j % 2 == 0 else MADE_MINUTES
                item = {"table": f"t_{n}", "date": date, "start": cursor, "minutes": minutes}
                (seeds if j % 2 == 0 else made).append(item | {"reference": f"K{k}T{n:02d}N{j}"})
                cursor += minutes + 40
    return seeds, made


def build(stage3: str, day: dt.date) -> SimpleNamespace:
    """The dense state on the stage-3 service, through its API; its export."""
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": capacity(n)} for n in range(1, TABLES + 1)]
    restaurant = {**fx.restaurant(tables=tables, slot_minutes=1, reservation_duration_minutes=SEED_MINUTES,
                                  opening_hours=fx.all_week("00:00", "23:30")), "manager_user_ids": [fx.ADA["id"]]}
    seeds, made = plan_bookings(day)
    fixture = fx.fixture(restaurants=[restaurant], reservations=[
        {"id": f"res_{s['reference']}", "reference": s["reference"], "user_id": "u_bob", "restaurant_id": "r_anker",
         "table_id": s["table"], "starts_at_local": fx.local(s["date"], hhmm(s["start"])), "party_size": 1}
        for s in seeds])
    with Api(stage3, timeout=60) as control:
        assert_status(control.post("/_test/reset", json=fixture), 204)
        ada = control.authenticate(fx.ADA["email"], fx.ADA["password"]).token
        bob = control.authenticate(fx.BOB["email"], fx.BOB["password"]).token
    with Api(stage3, token=ada, timeout=30) as client:
        assert_status(client.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=fx.policy(
            day.isoformat(), slot_minutes=1, reservation_duration_minutes=MADE_MINUTES,
            opening_hours=fx.all_week("00:00", "23:30"),
            capacities={f"t_{n}": capacity(n) for n in range(1, TABLES + 1)})), 201)

    def create(chunk):
        with Api(stage3, token=bob, timeout=30) as client:
            for m in chunk:
                assert_status(client.post("/reservations", idempotency_key=new_key(), json={
                    "restaurant_id": "r_anker", "table_id": m["table"], "party_size": 1,
                    "starts_at_local": fx.local(m["date"], hhmm(m["start"]))}), 201)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(create, [made[i::8] for i in range(8)]))
    with Api(stage3, timeout=60) as control:
        body = assert_status(control.get("/_test/export"), 200).json()
    return SimpleNamespace(day=day, body=body, bookings=seeds + made)


def load(base: str, body: dict) -> None:
    with Api(base, timeout=60) as control:
        assert_status(control.post("/_test/import", json=body), 204)


@pytest.fixture(scope="module")
def dense(base_url):
    world = build(os.environ["TABLEKEEPER_STAGE3_URL"].rstrip("/"), first_dense_day())
    world.control = os.environ.get("TABLEKEEPER_CONTROL_URL", "").rstrip("/") or None
    for base in filter(None, (base_url, world.control)):
        load(base, world.body)
    world.held = {}
    for b in world.bookings:
        world.held.setdefault((b["table"], b["date"]), []).append((b["start"], b["start"] + b["minutes"]))
    for intervals in world.held.values():
        intervals.sort()
    return world


def reference(world, date: str, party: int, explain: bool) -> dict:
    """The answer by the rule text (R302, R306-R309, R329): 1-minute slots from 00:00 while a
    45-minute booking ends by 23:30; a table is available when it seats the party and no
    booking on it overlaps the slot's interval; singles only (no pairs declared)."""
    zone_offset = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(12), BERLIN).isoformat()[-6:]
    slots = []
    for start in range(OPENS, CLOSES - MADE_MINUTES + 1):
        free, entries = [], []
        for n in range(1, TABLES + 1):
            table = f"t_{n}"
            held = world.held.get((table, date), [])
            i = bisect_left(held, (start + MADE_MINUTES,))
            no_overlap = not any(s < start + MADE_MINUTES and start < e for s, e in held[max(0, i - 3):i])
            seats = party <= capacity(n)
            if seats and no_overlap:
                free.append(table)
            entries.append({"table_id": table, "policy_version": 1, "available": seats and no_overlap,
                            "rules": [{"rule": "capacity", "holds": seats}, {"rule": "no_overlap", "holds": no_overlap}]})
        slot = {"starts_at_local": f"{date}T{hhmm(start)}", "starts_at": f"{date}T{hhmm(start)}:00{zone_offset}",
                "available_table_ids": free,
                "available_options": [{"table_ids": [t], "capacity": capacity(int(t[2:]))} for t in free]}
        slots.append(slot | ({"explain": entries} if explain else {}))
    return {"restaurant_id": "r_anker", "date": date, "timezone": "Europe/Berlin", "slots": slots}


def burst(base: str, questions: list[tuple[str, int]], explain: bool, keep: tuple[int, ...]):
    """All questions at once, one client each; (slowest seconds from the common start to the
    last byte, digests in question order, the bodies at the `keep` indexes)."""
    gate = threading.Barrier(len(questions))
    marks = [None] * len(questions)

    def ask(index):
        date, party = questions[index]
        params = {"restaurant_id": "r_anker", "date": date, "party_size": party, **({"explain": "true"} if explain else {})}
        with Api(base, timeout=60) as client:
            gate.wait()
            began = time.monotonic()
            response = client.get("/availability", params=params)
            ended = time.monotonic()
        assert response.status_code == 200, (date, party, response.status_code, response.text[:200])
        marks[index] = (began, ended, hashlib.sha256(response.content).hexdigest(),
                        response.content if index in keep else None)

    with ThreadPoolExecutor(len(questions)) as pool:
        list(pool.map(ask, range(len(questions))))
    slowest = max(end for _, end, _, _ in marks) - min(begin for begin, _, _, _ in marks)
    return slowest, [m[2] for m in marks], {i: marks[i][3] for i in keep}


def run_bursts(world, base_url, name, questions):
    keep = (0, len(questions) // 2, len(questions) - 1)
    failures = []
    for round_ in range(ROUNDS):
        for explain in (True, False):
            order = [("new", base_url), ("control", world.control)] if world.control else [("new", base_url)]
            order = order if round_ % 2 == 0 else order[::-1]
            measured = {who: burst(base, questions, explain, keep) for who, base in order}
            new_s, new_digests, bodies = measured["new"]
            line = f"burst {name} {'explained' if explain else 'plain'} round {round_}: new slowest {new_s:.2f} s"
            if new_s >= LIMIT_S:
                failures.append(f"{line}: not under {LIMIT_S} s")
            if world.control:
                control_s, control_digests, _ = measured["control"]
                line += f", control {control_s:.2f} s, ratio {new_s / control_s:.2f}"
                if new_digests != control_digests:
                    failures.append(f"{line}: {sum(a != b for a, b in zip(new_digests, control_digests))} answers differ from the control's")
                if explain and new_s > control_s / 2:
                    failures.append(f"{line}: more than half of the control's")
            for index, body in bodies.items():
                date, party = questions[index]
                if json.loads(body) != reference(world, date, party, explain):
                    failures.append(f"{line}: the answer for {date} party {party} differs from the reference")
            print(line)
    assert not failures, failures


def test_burst_a_50_different_questions_on_the_dense_day_and_the_four_after(dense, base_url):
    """R468/R302-R310: parties 1-10 on D .. D+4, 50 at once, explained then plain: slowest under
    5 s; explained at most half of the control's; answers equal to the control's and the
    reference."""
    questions = [((dense.day + dt.timedelta(days=d)).isoformat(), party) for d in range(5) for party in range(1, 11)]
    run_bursts(dense, base_url, "a", questions)


def test_burst_b_50_questions_on_50_different_dates(dense, base_url):
    """R468/R302-R310: party 2 on D .. D+49 (10 dense dates among them), 50 at once, explained then
    plain: slowest under 5 s; explained at most half of the control's; answers equal to the
    control's and the reference."""
    questions = [((dense.day + dt.timedelta(days=d)).isoformat(), 2) for d in range(50)]
    run_bursts(dense, base_url, "b", questions)

"""S4-I2 acceptance check (verifier seat): every preview's answer against my own brute-force
reference over generated restaurants within the limits, from the stage-4 specification
(R409-R421, R425) with the plan's Q1, Q2, Q6 and Q8-Q10.

Each case resets the service to a generated restaurant: 2-6 tables (sometimes 7) of 1-8 seats
(in 40 % of cases only 2 or 4 seats, so that plans tie on moves and unused seats),
0-4 declared pairs (sometimes 5) in either order, policy 0 lasting 60, 90 or 120 minutes; seeded
bookings (some cancelled) under policy 0; in 70 % of cases a policy for the date with another
duration (30-150 minutes) and other capacities, then bookings made through the API under it;
a closure of 15-660 minutes on a table, written with an offset, as Z or in another offset. In
35 % of cases the evening is dense: 3-6 seeded and 0-2 made bookings of 1-4 guests all starting
18:00-20:00 and a closure of 30-120 minutes in that window, so bookings compete for tables. The
reference enumerates every assignment of an option (singles in fixture order, then pairs in
declared order) to every considered booking, keeps the feasible ones (capacity under the
booking's own terms, no block over its own time, no table shared with an overlapping considered
booking) and takes the least (moved, unused, rank vector in reference order).

S4I2_CASES sets the number of cases (default 240); resets the service: run it alone.
"""
from __future__ import annotations

import datetime as dt
import itertools
import os
import random
import string
import time
from collections import Counter
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import error_code, new_key

pytestmark = pytest.mark.stage(4)

DATE = fx.booking_date()
BERLIN = ZoneInfo("Europe/Berlin")
CASES = int(os.environ.get("S4I2_CASES", "240"))
OPEN, CLOSE = 12 * 60, 23 * 60 + 30
MIDNIGHT = dt.datetime.combine(dt.date.fromisoformat(DATE), dt.time(), tzinfo=BERLIN).astimezone(dt.timezone.utc)
FORMS = {
    "offset": lambda at: at.astimezone(BERLIN).isoformat(),
    "Z": lambda at: at.isoformat().replace("+00:00", "Z"),
    "other_offset": lambda at: at.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(),
}


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def generate(rng: random.Random) -> dict:
    n_tables = 7 if rng.random() < 0.03 else rng.randint(2, 6)
    ids = [f"t_{i}" for i in range(1, n_tables + 1)]
    seats = (lambda: rng.choice([2, 2, 4])) if rng.random() < 0.4 else (lambda: rng.randint(1, 8))  # ties
    caps0 = {t: seats() for t in ids}
    candidates = list(itertools.combinations(ids, 2))
    n_pairs = min(len(candidates), 5 if rng.random() < 0.03 else rng.randint(0, 4))
    pairs = [p if rng.random() < 0.5 else p[::-1] for p in rng.sample(candidates, n_pairs)]
    options = [(t,) for t in ids] + [tuple(p) for p in pairs]
    duration0 = rng.choice([60, 90, 120])
    dense = rng.random() < 0.35  # one busy evening: bookings from 18:00 to 20:00 that compete for tables
    bookings: list[dict] = []
    references: set[str] = set()

    def reference() -> str:
        while (value := "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(6))) in references:
            pass
        references.add(value)
        return value

    def place(caps, duration, party):
        fitting = [o for o in options if sum(caps[t] for t in o) >= party]
        rng.shuffle(fitting)
        for option in fitting:
            start = rng.randrange(18 * 60, 20 * 60 + 1, 30) if dense else rng.randrange(OPEN, CLOSE - duration + 1, 30)
            if all(b["status"] == "cancelled" or not overlap(b["start"], b["end"], start, start + duration)
                   or set(b["tables"]).isdisjoint(option) for b in bookings):
                return option, start
        return None

    for _ in range(rng.randint(3, 6) if dense else rng.randint(0, 6)):
        party = rng.randint(1, 4) if dense else rng.randint(1, 7)
        if spot := place(caps0, duration0, party):
            bookings.append({"reference": reference(), "tables": spot[0], "start": spot[1],
                             "end": spot[1] + duration0, "party": party, "caps": caps0, "seeded": True,
                             "status": "cancelled" if rng.random() < 0.15 else "confirmed"})
    policy = None
    if rng.random() < 0.7:
        policy = {"duration": rng.choice([30, 60, 120, 150]), "caps": {t: seats() for t in ids}}
        for _ in range(rng.randint(0, 2) if dense else rng.randint(0, 4)):
            party = rng.randint(1, 4) if dense else rng.randint(1, 7)
            if spot := place(policy["caps"], policy["duration"], party):
                bookings.append({"reference": None, "tables": spot[0], "start": spot[1],
                                 "end": spot[1] + policy["duration"], "party": party, "caps": policy["caps"],
                                 "seeded": False, "status": "confirmed"})
    confirmed = [b for b in bookings if b["status"] == "confirmed"]
    if dense and confirmed:
        table, start = rng.choice(rng.choice(confirmed)["tables"]), rng.randrange(18 * 60, 20 * 60 + 1, 30)
        end = start + rng.choice([30, 60, 120])
    else:
        if confirmed and rng.random() < 0.85:
            anchor = rng.choice(confirmed)
            table, start = rng.choice(anchor["tables"]), anchor["start"] - rng.randrange(0, 121, 15)
        else:
            table, start = rng.choice(ids), rng.randrange(11 * 60, 23 * 60, 15)
        end = start + rng.randrange(15, 661, 15)
    form = rng.choice(list(FORMS))
    return {"ids": ids, "caps0": caps0, "pairs": pairs, "options": options, "duration0": duration0,
            "bookings": bookings, "policy": policy, "table": table, "start": start, "end": end,
            "body": {"table_id": table, "from": FORMS[form](MIDNIGHT + dt.timedelta(minutes=start)),
                     "to": FORMS[form](MIDNIGHT + dt.timedelta(minutes=end))}}


def fixture(case: dict) -> dict:
    tables = [{"id": t, "label": t[2:], "capacity": c} for t, c in case["caps0"].items()]
    restaurant = {**fx.restaurant(tables=tables, reservation_duration_minutes=case["duration0"],
                                  opening_hours=fx.all_week("12:00", "23:30")),
                  "manager_user_ids": [fx.ADA["id"]], "combinable": [list(p) for p in case["pairs"]]}
    seeds = [{"id": f"res_{b['reference']}", "reference": b["reference"], "user_id": "u_bob",
              "restaurant_id": "r_anker", "table_ids": list(b["tables"]),
              "starts_at_local": fx.local(DATE, hhmm(b["start"])), "party_size": b["party"], "status": b["status"]}
             for b in case["bookings"] if b["seeded"]]
    return fx.fixture(restaurants=[restaurant], reservations=seeds)


def reference_answer(case: dict):
    """(status, expected body part): 422 planning_limit, 409 no_feasible_plan or 201 with the
    least plan, by exhaustive enumeration of the feasible plans."""
    confirmed = [b for b in case["bookings"] if b["status"] == "confirmed"]
    considered = sorted((b for b in confirmed if overlap(b["start"], b["end"], case["start"], case["end"])),
                        key=lambda b: b["reference"])
    if len(case["ids"]) > 6 or len(case["pairs"]) > 4 or len(considered) > 6:
        return 422, None
    fixed = [b for b in confirmed if b not in considered]
    blocks = [(case["table"], case["start"], case["end"])] + [(t, b["start"], b["end"]) for b in fixed for t in b["tables"]]
    feasible = []
    for b in considered:
        feasible.append([(rank, option) for rank, option in enumerate(case["options"])
                         if sum(b["caps"][t] for t in option) >= b["party"]
                         and not any(t in option and overlap(s, e, b["start"], b["end"]) for t, s, e in blocks)])
    best = None
    chosen: list = []

    def search(i: int) -> None:
        nonlocal best
        if i == len(considered):
            moved = sum(set(o) != set(b["tables"]) for b, (_, o) in zip(considered, chosen))
            unused = sum(sum(b["caps"][t] for t in o) - b["party"] for b, (_, o) in zip(considered, chosen))
            key = (moved, unused, tuple(rank for rank, _ in chosen))
            if best is None or key < best[0]:
                best = (key, list(chosen))
            return
        for rank, option in feasible[i]:
            if all(not overlap(considered[i]["start"], considered[i]["end"], considered[j]["start"], considered[j]["end"])
                   or set(option).isdisjoint(chosen[j][1]) for j in range(i)):
                chosen.append((rank, option))
                search(i + 1)
                chosen.pop()

    search(0)
    if best is None:
        return 409, None
    (moved, unused, _), plan = best
    return 201, {"assignments": [{"reference": b["reference"], "table_ids": list(o), "changed": set(o) != set(b["tables"])}
                                 for b, (_, o) in zip(considered, plan)],
                 "moved_count": moved, "unused_seats": unused}


def test_every_preview_is_the_least_feasible_plan(reset, api):
    """R409-R421/R425/Q1/Q2/Q6/Q8-Q10: over CASES generated restaurants the preview answers
    exactly what the brute-force reference does: 422 planning_limit beyond a limit, 409
    no_feasible_plan when nothing fits, else 201 with every considered booking in reference
    order, its table set (declared order) and `changed`, `moved_count`, `unused_seats`, the
    closure as written and the restaurant revision (one publication plus each create)."""
    wrong, kinds, slowest = [], Counter(), 0.0
    for number in range(CASES):
        case = generate(random.Random(f"s4i2-{number}"))
        reset(fixture(case))
        ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
        writes = 0
        if case["policy"]:
            response = ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=fx.policy(
                DATE, reservation_duration_minutes=case["policy"]["duration"], capacities=case["policy"]["caps"],
                opening_hours=fx.all_week("12:00", "23:30")))
            assert response.status_code == 201, (number, response.text)
            writes += 1
        for b in case["bookings"]:
            if not b["seeded"]:
                response = ada.post("/reservations", idempotency_key=new_key(), json={
                    "restaurant_id": "r_anker", "table_ids": list(b["tables"]),
                    "starts_at_local": fx.local(DATE, hhmm(b["start"])), "party_size": b["party"]})
                assert response.status_code == 201, (number, b, response.text)
                b["reference"] = response.json()["reference"]
                writes += 1
        status, expected = reference_answer(case)
        began = time.monotonic()
        response = ada.post("/restaurants/r_anker/replans", idempotency_key=new_key(), json=case["body"])
        slowest = max(slowest, time.monotonic() - began)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if status == 201:
            kinds[f"moved {expected['moved_count']}"] += 1
            got = {k: body.get(k) for k in ("assignments", "moved_count", "unused_seats")}
            ok = (response.status_code == 201 and got == expected and body.get("closure") == case["body"]
                  and body.get("restaurant_revision") == writes)
        else:
            code = "planning_limit" if status == 422 else "no_feasible_plan"
            kinds[code] += 1
            got = body
            ok = response.status_code == status and error_code(response) == code
        if not ok:
            wrong.append(f"case {number}: expected {status} {expected} got {response.status_code} {got}")
    print(f"cases={CASES} wrong={len(wrong)} kinds={dict(sorted(kinds.items()))} slowest_preview_s={slowest:.3f}")
    assert not wrong, f"{len(wrong)} of {CASES} wrong; first: " + " | ".join(wrong[:3])

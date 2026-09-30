"""S3-I2 dense day under load (verifier seat), from the stage-3 specification ("Availability
explanations") with stage-1 §2 ("Concurrent requests: up to 50 in flight; per-request timeout
5 s") and the plan's S3-I2 item.

Run this file alone, with nothing else loading the service: its timings assume that.
`pytest -rP` prints the measured values.
"""
from __future__ import annotations

import datetime as dt
import time

import pytest

import fixtures as fx
from harness.concurrent import burst
from harness.http import REQUEST_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DENSE_DATE = "2026-12-03"
N_TABLES, BURST = 40, 50
CAPACITY = {f"t_{n}": n % 8 + 1 for n in range(N_TABLES)}
OLD, NEW, CLOSES = 90, 45, 23 * 60 + 30
EXPLAIN = {"explained": True, "plain": False}


def at(total: int) -> str:
    return fx.local(DENSE_DATE, f"{total // 60:02d}:{total % 60:02d}")


def dense_day(reset, api) -> dict:
    """200 bookings under policy 0 (90 minutes), a same-date policy of 45 minutes, then 200
    bookings under it; the bookings per table as (start minute, length)."""
    booked = {t: [] for t in CAPACITY}
    seeds = []
    for n, table in enumerate(CAPACITY):
        first = 30 * ((7 * n) % 15)
        for k in range(5):
            booked[table].append((first + OLD * k, OLD))
            seeds.append({"id": f"res_{n}_{k}", "reference": f"E{n:03d}{k:02d}", "user_id": fx.ADA["id"],
                          "restaurant_id": "r_anker", "table_id": table, "starts_at_local": at(first + OLD * k),
                          "party_size": 1})
    restaurant = fx.managed_restaurant(slot_minutes=1, opening_hours=fx.all_week("00:00", "23:30"),
                                       tables=[{"id": t, "label": t, "capacity": c} for t, c in CAPACITY.items()])
    reset(fx.fixture(restaurants=[restaurant], reservations=seeds))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_status(ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=fx.policy(
        DENSE_DATE, slot_minutes=1, reservation_duration_minutes=NEW, opening_hours=fx.all_week("00:00", "23:30"),
        capacities=CAPACITY)), 201)
    for n, table in enumerate(CAPACITY):
        first = 30 * ((7 * n) % 15) + OLD * 5
        for k in range(5):
            assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
                "restaurant_id": "r_anker", "table_id": table, "starts_at_local": at(first + NEW * k),
                "party_size": 1}), 201)
            booked[table].append((first + NEW * k, NEW))
    return booked


def reference(booked: dict, party: int, explained: bool) -> list:
    """Every slot of the day (1-minute grid, 45-minute bookings, 00:00-23:30) with the tables
    free for the party, and with explain every table's two rules under policy 1."""
    slots = []
    for start in range(0, CLOSES - NEW + 1):
        entries = []
        for table, capacity in CAPACITY.items():
            fits = party <= capacity
            free = all(start + NEW <= b or start >= b + d for b, d in booked.get(table, []))
            entries.append({"table_id": table, "policy_version": 1, "available": fits and free,
                            "rules": [{"rule": "capacity", "holds": fits}, {"rule": "no_overlap", "holds": free}]})
        slot = {"available_table_ids": [e["table_id"] for e in entries if e["available"]]}
        slots.append({**slot, "explain": entries} if explained else slot)
    return slots


def shown(slots: list, explained: bool) -> list:
    return [{"available_table_ids": s["available_table_ids"], **({"explain": s["explain"]} if explained else {})}
            for s in slots]


def timed_burst(base_url, questions: list[dict]):
    def timed(i):
        with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
            started = time.perf_counter()
            resp = client.get("/availability", params=questions[i])
            return resp, time.perf_counter() - started

    results = burst(timed, len(questions))
    failures = [r for r in results if isinstance(r, Exception)]
    slowest = max((elapsed for _, elapsed in (r for r in results if not isinstance(r, Exception))), default=float("inf"))
    return results, failures, slowest


@pytest.mark.parametrize("shape", list(EXPLAIN))
def test_the_dense_day_answers_fifty_identical_requests_within_5_s(reset, api, base_url, shape):
    """R306-R309/R329 and stage-1 §2: 50 simultaneous identical GET /availability for the
    dense day, with `explain=true` and without it, all answer 200 within 5 s, identically, and
    equal the reference built from each booking's own duration."""
    explained = EXPLAIN[shape]
    booked = dense_day(reset, api)
    question = {"restaurant_id": "r_anker", "date": DENSE_DATE, "party_size": 2, **({"explain": "true"} if explained else {})}
    results, failures, slowest = timed_burst(base_url, [question] * BURST)
    size = len(results[0][0].content) if not failures else 0
    print(f"dense {shape} identical burst50_max_s={slowest:.2f} bytes={size} failed={len(failures)}")
    assert not failures, f"{len(failures)} of {BURST} failed or took over 5 s: {failures[0]!r}"
    assert all(resp.status_code == 200 for resp, _ in results)
    assert slowest < REQUEST_TIMEOUT
    assert len({resp.content for resp, _ in results}) == 1
    slots = results[0][0].json()["slots"]
    assert shown(slots, explained) == reference(booked, 2, explained)


@pytest.mark.parametrize("shape", list(EXPLAIN))
def test_fifty_different_questions_about_the_dense_restaurant_answer_within_5_s(reset, api, base_url, shape):
    """Stage-1 §2 for every request: 50 simultaneous GET /availability about the dense
    restaurant, no two alike (parties 1-10 on the dense day and the four days after it), with
    `explain=true` and without it, all answer 200 within 5 s and equal their references."""
    explained = EXPLAIN[shape]
    booked = dense_day(reset, api)
    day = dt.date.fromisoformat(DENSE_DATE)
    questions = [{"restaurant_id": "r_anker", "date": (day + dt.timedelta(days=d)).isoformat(), "party_size": party,
                  **({"explain": "true"} if explained else {})} for d in range(5) for party in range(1, 11)]
    results, failures, slowest = timed_burst(base_url, questions)
    print(f"dense {shape} different burst50_max_s={slowest:.2f} failed={len(failures)}")
    assert not failures, f"{len(failures)} of {BURST} failed or took over 5 s: {failures[0]!r}"
    assert all(resp.status_code == 200 for resp, _ in results)
    assert slowest < REQUEST_TIMEOUT
    for question, (resp, _) in zip(questions, results, strict=True):
        on_dense_day = question["date"] == DENSE_DATE
        expected = reference(booked if on_dense_day else {}, question["party_size"], explained)
        assert shown(resp.json()["slots"], explained) == expected, question

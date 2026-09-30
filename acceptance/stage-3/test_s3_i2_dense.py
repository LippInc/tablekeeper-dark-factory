"""S3-I2 dense day with explanations (verifier seat), from the stage-3 specification
("Availability explanations") with §7's 5-second budget and the plan's S3-I2 item.

Run this file alone, with nothing else loading the service: its timings assume that.
`pytest -rP` prints the measured values.
"""
from __future__ import annotations

import time

import pytest

import fixtures as fx
from harness.concurrent import burst
from harness.http import REQUEST_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DENSE_DATE = "2026-12-03"
N_TABLES, BURST, PARTY = 40, 50, 2
CAPACITY = {f"t_{n}": n % 8 + 1 for n in range(N_TABLES)}
OLD, NEW, CLOSES = 90, 45, 23 * 60 + 30


def at(total: int) -> str:
    return fx.local(DENSE_DATE, f"{total // 60:02d}:{total % 60:02d}")


def test_the_dense_day_explained_answers_fifty_in_flight_within_5_s(reset, api, base_url):
    """R306-R309/R329 and §7: 200 bookings under policy 0 (90 minutes), a same-date policy of
    45 minutes, 200 bookings under it; 50 simultaneous GET /availability with `explain=true`
    all answer 200 within 5 s, identically, and every slot's explanation (40 tables, policy 1)
    equals the reference built from each booking's own duration."""
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
    params = {"restaurant_id": "r_anker", "date": DENSE_DATE, "party_size": PARTY, "explain": "true"}

    def timed(_):
        with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
            started = time.perf_counter()
            resp = client.get("/availability", params=params)
            return resp, time.perf_counter() - started

    results = burst(timed, BURST)
    failures = [r for r in results if isinstance(r, Exception)]
    slowest = max((elapsed for _, elapsed in (r for r in results if not isinstance(r, Exception))), default=float("inf"))
    size = len(results[0][0].content) if not failures else 0
    print(f"dense explained burst50_max_s={slowest:.2f} bytes={size} failed={len(failures)}")
    assert not failures, f"{len(failures)} of {BURST} failed or took over 5 s: {failures[0]!r}"
    assert all(resp.status_code == 200 for resp, _ in results)
    assert slowest < REQUEST_TIMEOUT
    assert len({resp.content for resp, _ in results}) == 1
    slots = results[0][0].json()["slots"]
    assert len(slots) == CLOSES - NEW + 1
    for slot in slots:
        start = int(slot["starts_at_local"][11:13]) * 60 + int(slot["starts_at_local"][14:16])
        expected = []
        for table, capacity in CAPACITY.items():
            fits = PARTY <= capacity
            free = all(start + NEW <= b or start >= b + d for b, d in booked[table])
            expected.append({"table_id": table, "policy_version": 1, "available": fits and free,
                             "rules": [{"rule": "capacity", "holds": fits}, {"rule": "no_overlap", "holds": free}]})
        assert slot["explain"] == expected, slot["starts_at_local"]
        assert slot["available_table_ids"] == [e["table_id"] for e in expected if e["available"]]

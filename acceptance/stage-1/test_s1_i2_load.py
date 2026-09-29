"""S1-I2 acceptance checks under load (verifier seat), from the stage-1 specification.

Run this file alone, with nothing else loading the service: its timings assume that.
A dense day -- a 5-minute grid around the clock, 40 tables, 400 seeded bookings -- must
answer within the 5 s per-request limit (§2), also with 50 requests in flight, with no
5xx (§5). `pytest -rP` prints the measured values.
"""
from __future__ import annotations

import time

import pytest

import fixtures as fx
from harness.concurrent import burst, no_5xx, tally
from harness.http import REQUEST_TIMEOUT, Api, assert_status

pytestmark = pytest.mark.stage(1)

BURST = 50
DATE = "2026-10-01"
TABLES = 40
BOOKINGS_PER_TABLE = 10


def dense_fixture() -> dict:
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": 4} for n in range(TABLES)]
    bookings = [{"id": f"res_{n}_{k}", "reference": f"S{n:03d}{k:03d}", "user_id": "u_ada",
                 "restaurant_id": "r_anker", "table_id": f"t_{n}",
                 "starts_at_local": f"{DATE}T{2 * k:02d}:{(5 * n) % 60:02d}", "party_size": 2}
                for n in range(TABLES) for k in range(BOOKINGS_PER_TABLE)]
    restaurant = fx.restaurant(slot_minutes=5, tables=tables,
                               opening_hours=fx.all_week("00:00", "23:55"))
    return fx.fixture(restaurants=[restaurant], reservations=bookings)


def timed_availability(base_url: str):
    with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
        started = time.perf_counter()
        resp = client.get("/availability", params={
            "restaurant_id": "r_anker", "date": DATE, "party_size": "2"})
        return resp, time.perf_counter() - started


def test_a_dense_day_answers_within_5_s(reset, base_url):
    """R17/R89/R90: 270 slots x 40 tables against 400 bookings within 5 s."""
    reset(dense_fixture())
    resp, elapsed = timed_availability(base_url)
    print(f"availability_dense_s={elapsed:.2f}")
    slots = assert_status(resp, 200).json()["slots"]
    assert len(slots) == (23 * 60 + 55 - 90) // 5 + 1
    assert elapsed < REQUEST_TIMEOUT


def test_fifty_simultaneous_availability_requests_agree_within_5_s(reset, base_url):
    """R16/R17/R60: 50 in flight at once: each answers 200 within 5 s, all alike."""
    reset(dense_fixture())
    results = burst(lambda i: timed_availability(base_url), BURST)
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"{len(failures)} requests failed or timed out, first: {failures[0]!r}"
    responses = [resp for resp, _ in results]
    no_5xx(responses)
    print(f"availability_burst_50 max_latency_s={max(e for _, e in results):.2f}")
    assert tally(responses) == {200: BURST}
    assert max(elapsed for _, elapsed in results) < REQUEST_TIMEOUT
    assert all(resp.json() == responses[0].json() for resp in responses)

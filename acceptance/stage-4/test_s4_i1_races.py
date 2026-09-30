"""S4-I1 race (verifier seat): the restaurant revision under simultaneous creates, from the
stage-4 specification ("increments once for each successful new booking") with stage-1 §2
(50 in flight) and the plan's J1 and Q5.

Run this file alone, with nothing else loading the service. `pytest -rP` prints the outcomes.
"""
from __future__ import annotations

import pytest

import fixtures as fx
from harness.concurrent import burst, tally
from harness.http import REQUEST_TIMEOUT, RESET_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(4)

DATE = fx.booking_date()
TABLES = [{"id": f"t_{n}", "label": str(n), "capacity": 4} for n in range(1, 11)]
ROUNDS = 3


def revision(base_url) -> int:
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        [restaurant] = assert_status(control.get("/_test/export"), 200).json()["state"]["restaurants"]
        return restaurant["revision"]


def test_twenty_simultaneous_creates_raise_it_by_the_number_that_succeed(reset, api, base_url):
    """R422/Q5: in each of three rounds, twenty clients create at once, two on each of ten
    tables at one time: exactly ten are 201, the others 409, and the revision rises by ten,
    once per successful create."""
    for round_number in range(ROUNDS):
        reset(fx.fixture(restaurants=[fx.managed_restaurant(tables=TABLES)]))
        token = api().authenticate(fx.BOB["email"], fx.BOB["password"]).token
        before = revision(base_url)

        def act(i):
            with Api(base_url, token=token, timeout=REQUEST_TIMEOUT) as client:
                return client.post("/reservations", idempotency_key=new_key(), json={
                    "restaurant_id": "r_anker", "table_id": f"t_{1 + i % 10}", "starts_at_local": fx.local(DATE),
                    "party_size": 2})

        results = burst(act, 20)
        failures = [r for r in results if isinstance(r, Exception)]
        assert not failures, f"{len(failures)} requests failed, first: {failures[0]!r}"
        created = sum(1 for r in results if r.status_code == 201)
        print(f"round {round_number} creates={tally(results)} revision {before} -> {revision(base_url)}")
        assert (created, sorted({r.status_code for r in results})) == (10, [201, 409]), tally(results)
        assert revision(base_url) == before + created

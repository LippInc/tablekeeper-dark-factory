"""S3-I4 races (verifier seat), from the stage-3 specification ("Recurring reservations")
with §7 and the plan's H2/H4.

Run this file alone, with nothing else loading the service. `pytest -rP` prints the outcomes.
"""
from __future__ import annotations

import datetime as dt

import pytest

import fixtures as fx
from harness.concurrent import burst, tally
from harness.http import REQUEST_TIMEOUT, Api, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()
ROUNDS = 3


def weeks(n: int) -> str:
    return (dt.date.fromisoformat(DATE) + dt.timedelta(weeks=n)).isoformat()


def setup(reset, api):
    reset(fx.fixture(restaurants=[fx.managed_restaurant()]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    anchor = assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE), "party_size": 2}), 201).json()
    return ada, bob, anchor


def settled(results):
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"{len(failures)} requests failed, first: {failures[0]!r}"
    assert all(r.status_code < 500 for r in results), tally(results)
    return results


def test_twenty_clients_sending_one_adoption_key_make_one_series(reset, api, base_url):
    """R360/§7: twenty clients send one adoption key and body at once: exactly one 201, the
    others 200 with the same body; one series and its occurrences exist."""
    ada, _, anchor = setup(reset, api)
    key, body = new_key(), {"anchor_reference": anchor["reference"], "count": 4, "interval_weeks": 1}

    def send(_):
        with Api(base_url, token=ada.token, timeout=REQUEST_TIMEOUT) as client:
            return client.post("/series", json=body, idempotency_key=key)

    results = settled(burst(send, 20))
    print(f"one adoption key statuses={tally(results)}")
    assert sorted(r.status_code for r in results) == [200] * 19 + [201]
    assert len({r.text for r in results}) == 1
    assert len(assert_status(ada.get("/reservations"), 200).json()["reservations"]) == 4


def test_an_adoption_racing_creates_never_overlaps_or_leaves_a_partial_series(reset, api, base_url):
    """R351/R354/H2: in each of three rounds an adoption (4 occurrences) races nine creates on
    its occurrences' table and times: no table is ever held twice, and either the whole series
    exists and every create was refused, or no occurrence exists and the adoption was refused
    with 409 table_unavailable."""
    for round_number in range(ROUNDS):
        ada, bob, anchor = setup(reset, api)

        def act(i):
            with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
                if i == 0:
                    client.token = ada.token
                    return client.post("/series", idempotency_key=new_key(), json={
                        "anchor_reference": anchor["reference"], "count": 4, "interval_weeks": 1})
                client.token = bob.token
                return client.post("/reservations", idempotency_key=new_key(), json={
                    "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(weeks(1 + (i - 1) % 3)),
                    "party_size": 2})

        results = settled(burst(act, 10))
        adoption, creates = results[0], results[1:]
        print(f"round {round_number} adoption={adoption.status_code} creates={tally(creates)}")
        held = [b for client in (ada, bob) for b in assert_status(client.get("/reservations"), 200).json()["reservations"]
                if b["status"] == "confirmed"]
        starts = [b["starts_at_local"] for b in held]
        assert len(starts) == len(set(starts)), sorted(starts)
        mine = assert_status(ada.get("/reservations"), 200).json()["reservations"]
        if adoption.status_code == 201:
            assert len(mine) == 4 and all(r.status_code == 409 for r in creates), tally(creates)
        else:
            assert (adoption.status_code, error_code(adoption)) == (409, "table_unavailable")
            assert [b["reference"] for b in mine] == [anchor["reference"]]
            assert any(r.status_code == 201 for r in creates)

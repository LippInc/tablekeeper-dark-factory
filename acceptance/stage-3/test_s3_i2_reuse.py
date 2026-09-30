"""S3-I2 availability answers after writes (verifier seat), from stage-2 "Concurrent bookings
and amendments" ("Concurrent requests must produce the same results as executing them one at
a time in some order") and the stage-1/3 rules each writer changes: after any write has been
answered, no availability answer, with or without explain, may be one from before it.

Identical reads race each writer; then the service's answers must equal a fresh rendering of
the same state: its export imported into a second stage-3 service (TABLEKEEPER_SECOND_URL,
which is reset). Run this file alone, with nothing else loading the service.
"""
from __future__ import annotations

import datetime as dt
import os

import pytest

import fixtures as fx
from harness.concurrent import burst, tally
from harness.http import REQUEST_TIMEOUT, RESET_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()
NEXT_WEEK = (dt.date.fromisoformat(DATE) + dt.timedelta(weeks=1)).isoformat()
ROUNDS, READS = 3, 20
RESTAURANT = {**fx.managed_restaurant(), "combinable": [["t_1", "t_2"]]}


def world(extra=()) -> dict:
    """Ada's booking OWN001 on t_2 at 19:00 on DATE, and any extra seeds."""
    return fx.fixture(restaurants=[RESTAURANT], reservations=[
        {"id": "res_own", "reference": "OWN001", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2",
         "starts_at_local": fx.local(DATE), "party_size": 2}, *extra])


EXTRA = {"id": "res_extra", "reference": "EXT001", "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": "t_1",
         "starts_at_local": fx.local(DATE, "20:00"), "party_size": 2}


def questions(date: str) -> list[dict]:
    base = {"restaurant_id": "r_anker", "date": date, "party_size": 2}
    return [base, {**base, "explain": "true"}]


def answers(client, date: str) -> list:
    return [assert_status(client.get("/availability", params=q), 200).json() for q in questions(date)]


def ada_token(base) -> str:
    with Api(base) as client:
        return client.authenticate(fx.ADA["email"], fx.ADA["password"]).token


def write(kind: str, base: str, token: str, other: dict | None):
    """One write that changes the answers about DATE (NEXT_WEEK for an adoption)."""
    with Api(base, token=token, timeout=RESET_TIMEOUT) as client:
        if kind == "create":
            return client.post("/reservations", idempotency_key=new_key(), json={
                "restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": fx.local(DATE), "party_size": 2})
        if kind == "patch":
            return client.patch("/reservations/OWN001", json={"starts_at_local": fx.local(DATE, "21:00")})
        if kind == "cancel":
            return client.post("/reservations/OWN001/cancel")
        if kind == "move":
            return client.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
                {"reference": "OWN001", "table_id": "t_1", "starts_at_local": fx.local(DATE, "20:30")}]})
        if kind == "adoption":
            return client.post("/series", idempotency_key=new_key(), json={
                "anchor_reference": "OWN001", "count": 2, "interval_weeks": 1})
        if kind == "policy":
            return client.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                               json=fx.policy(DATE, reservation_duration_minutes=45))
        if kind == "import":
            return client.post("/_test/import", json=other)
        return client.post("/_test/reset", json=world([EXTRA]))


WRITERS = ["create", "patch", "cancel", "move", "adoption", "policy", "import", "reset"]


def fresh(base_url: str, second: str, date: str) -> list:
    """The answers a service holding the same state renders afresh: `base_url`'s export
    imported into the second stage-3 service."""
    with Api(base_url, timeout=RESET_TIMEOUT) as control, Api(second, timeout=RESET_TIMEOUT) as other:
        assert_status(other.post("/_test/import", json=assert_status(control.get("/_test/export"), 200).json()), 204)
        return answers(other, date)


@pytest.mark.parametrize("kind", WRITERS)
def test_no_answer_from_before_a_write_is_served_after_it(reset, base_url, kind):
    """In each of three rounds: the plain question is read twice (its answer kept), the
    explained one not at all; then twenty identical reads of both race the write; once it is
    answered, the service's answers equal a fresh rendering of its state and differ from a
    fresh rendering before the write."""
    second = os.environ.get("TABLEKEEPER_SECOND_URL", "").rstrip("/")
    assert second, "set TABLEKEEPER_SECOND_URL to a second stage-3 service of the same checkout"
    date = NEXT_WEEK if kind == "adoption" else DATE
    for round_number in range(ROUNDS):
        reset(world())
        token = ada_token(base_url)
        with Api(base_url) as anon:
            plain = assert_status(anon.get("/availability", params=questions(date)[0]), 200).json()
            assert assert_status(anon.get("/availability", params=questions(date)[0]), 200).json() == plain
        before = fresh(base_url, second, date)
        other = None
        if kind == "import":
            with Api(second, timeout=RESET_TIMEOUT) as control:
                assert_status(control.post("/_test/reset", json=world([EXTRA])), 204)
                other = assert_status(control.get("/_test/export"), 200).json()

        def act(i):
            if i == 0:
                return write(kind, base_url, token, other)
            with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
                return client.get("/availability", params=questions(date)[i % 2])

        results = burst(act, READS + 1)
        failures = [r for r in results if isinstance(r, Exception)]
        assert not failures, f"{len(failures)} requests failed, first: {failures[0]!r}"
        assert results[0].status_code in (200, 201, 204), (kind, results[0].status_code, results[0].text[:200])
        assert all(r.status_code == 200 for r in results[1:]), tally(results[1:])
        with Api(base_url) as anon:
            after = answers(anon, date)
        reference = fresh(base_url, second, date)
        print(f"{kind} round {round_number}: reads {tally(results[1:])}, write {results[0].status_code}")
        assert after == reference, f"{kind} round {round_number}: an answer from before the write was served"
        assert reference[0] != before[0] and reference[1] != before[1], \
            f"precondition: the {kind} changes the answers about {date}"

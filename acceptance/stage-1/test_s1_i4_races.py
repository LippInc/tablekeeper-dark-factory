"""S1-I4 races (verifier seat), from the stage-1 specification.

Run this file alone, with nothing else loading the service. §7: concurrent identical
requests with an unused key take effect once; §1: two confirmed reservations never
occupy one table at overlapping times, including during concurrent requests, whichever
write path (create, PATCH, cancel, move) makes them; §5: no 5xx under concurrent load.
`pytest -rP` prints the measured values.
"""
from __future__ import annotations

import datetime as dt
import random
import time

import pytest

import fixtures as fx
from harness.concurrent import burst, no_5xx, tally
from harness.http import REQUEST_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(1)

BURST = 50
DATE = fx.booking_date()
DURATION = dt.timedelta(minutes=90)
SHARED = "t_S"
ROUNDS = 3


def accounts(n: int) -> list[dict]:
    return [{"id": f"u_{i:02d}", "email": f"diner{i:02d}@example.com",
             "password": "correct horse", "display_name": f"Diner {i}"} for i in range(n)]


def seed(reference: str, user: int, table_id: str, at: str) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": f"u_{user:02d}",
            "restaurant_id": "r_anker", "table_id": table_id,
            "starts_at_local": fx.local(DATE, at), "party_size": 2}


def timed(base_url: str, token: str, method: str, path: str, **kw):
    with Api(base_url, token=token, timeout=REQUEST_TIMEOUT) as client:
        started = time.perf_counter()
        resp = client.request(method, path, **kw)
        return resp, time.perf_counter() - started


def outcome(results, name: str):
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"{len(failures)} requests failed or timed out, first: {failures[0]!r}"
    responses = [resp for resp, _ in results]
    no_5xx(responses)
    slowest = max(elapsed for _, elapsed in results)
    print(f"{name} max_latency_s={slowest:.2f} statuses={tally(responses)}")
    assert slowest < REQUEST_TIMEOUT
    return responses


def test_one_move_key_replayed_by_twenty_clients_takes_effect_once(reset, api, base_url):
    """R81/R153: 20 identical move requests with an unused key at once: exactly one 201,
    19 x 200 with the same body; the swap happened once."""
    reset(fx.fixture(reservations=[seed("SWAPA1", 0, "t_1", "19:00"),
                                   seed("SWAPB1", 0, "t_2", "19:00")],
                     users=accounts(1)))
    token = api().authenticate("diner00@example.com", "correct horse").token
    key = new_key()
    payload = {"moves": [{"reference": "SWAPA1", "table_id": "t_2"},
                         {"reference": "SWAPB1", "table_id": "t_1"}]}
    responses = outcome(burst(lambda i: timed(
        base_url, token, "POST", "/reservation-moves", json=payload, idempotency_key=key), 20),
        "race_move_key_20_clients")
    assert tally(responses) == {200: 19, 201: 1}, tally(responses)
    assert all(r.json() == responses[0].json() for r in responses)
    listed = assert_status(api(token).get("/reservations"), 200).json()["reservations"]
    assert sorted((b["reference"], b["table_id"]) for b in listed) == \
        [("SWAPA1", "t_2"), ("SWAPB1", "t_1")]


def _starts(api, tokens: list[str], table_id: str) -> list[tuple[dt.datetime, str]]:
    """Every confirmed booking on `table_id`: (start instant, reference)."""
    found = []
    for token in tokens:
        for booking in assert_status(api(token).get("/reservations"), 200).json()["reservations"]:
            if booking["table_id"] == table_id and booking["status"] == "confirmed":
                found.append((dt.datetime.fromisoformat(booking["starts_at"]), booking["reference"]))
    return sorted(found)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def test_a_mixed_race_on_one_table_never_double_books(reset, api, base_url):
    """R7/R60/R16: 50 in flight on one table -- cancels of its bookings, creates on it,
    PATCHes and moves onto it at colliding times: afterwards no two confirmed bookings
    on the table overlap, and nothing answered 5xx. Three rounds, one shared table each,
    because the interleaving differs from run to run."""
    users = accounts(BURST)
    tables = ([{"id": f"{SHARED}{r}", "label": f"T{r}", "capacity": 4} for r in range(ROUNDS)]
              + [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(BURST)])
    # per round: users 0, 4, 8, ... hold the shared table every 90 minutes; the others
    # hold their own table, a different time per round
    shared = [seed(f"SHARE{r}{i:02d}", i, f"{SHARED}{r}", _hhmm((i // 4) * 90))
              for r in range(ROUNDS) for i in range(0, BURST, 4)]
    own = [seed(f"OWN{r}{i:02d}", i, f"t_{i}", _hhmm(12 * 60 + r * 90))
           for r in range(ROUNDS) for i in range(BURST) if i % 4]
    reset(fx.fixture(users=users, reservations=shared + own, restaurants=[
        fx.restaurant(tables=tables, opening_hours=fx.all_week("00:00", "23:30"))]))
    tokens = [api().authenticate(u["email"], u["password"]).token for u in users]
    rng = random.Random(20260929)
    for r in range(ROUNDS):
        table = f"{SHARED}{r}"
        targets = [fx.local(DATE, _hhmm(rng.randrange(0, 37) * 30)) for _ in range(BURST)]

        def act(i, r=r, table=table, targets=targets):
            at = targets[i]
            if i % 4 == 0:
                return timed(base_url, tokens[i], "POST", f"/reservations/SHARE{r}{i:02d}/cancel")
            if i % 4 == 1:
                return timed(base_url, tokens[i], "POST", "/reservations", idempotency_key=new_key(),
                             json={"restaurant_id": "r_anker", "table_id": table,
                                   "starts_at_local": at, "party_size": 2})
            if i % 4 == 2:
                return timed(base_url, tokens[i], "PATCH", f"/reservations/OWN{r}{i:02d}",
                             json={"table_id": table, "starts_at_local": at})
            return timed(base_url, tokens[i], "POST", "/reservation-moves", idempotency_key=new_key(),
                         json={"moves": [{"reference": f"OWN{r}{i:02d}", "table_id": table,
                                          "starts_at_local": at}]})

        responses = outcome(burst(act, BURST), f"race_mixed_round{r}")
        assert set(tally(responses)) <= {200, 201, 409}, (r, tally(responses))
        held = _starts(api, tokens, table)
        clashes = [(a[1], b[1]) for a, b in zip(held, held[1:]) if b[0] - a[0] < DURATION]
        print(f"race_mixed_round{r} confirmed_on_shared={len(held)} clashes={clashes}")
        assert not clashes, (r, clashes)

"""S1-I3 races at 50 in flight (verifier seat), from the stage-1 specification.

Run this file alone, with nothing else loading the service. §1: two confirmed
reservations never occupy one table at overlapping times, including during concurrent
requests; §7: concurrent identical requests with an unused key take effect once; §2: up
to 50 requests in flight, each within 5 s. `pytest -rP` prints the measured values.
"""
from __future__ import annotations

import time

import pytest

import fixtures as fx
from harness.concurrent import burst, no_5xx, tally
from harness.http import REQUEST_TIMEOUT, Api, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(1)

BURST = 50
DATE = fx.booking_date()
AT = fx.local(DATE, "19:00")


def accounts(n: int) -> list[dict]:
    return [{"id": f"u_{i:02d}", "email": f"diner{i:02d}@example.com",
             "password": "correct horse", "display_name": f"Diner {i}"} for i in range(n)]


def tokens(api, users: list[dict]) -> list[str]:
    return [api().authenticate(u["email"], u["password"]).token for u in users]


def seeded(i: int, table_id: str) -> dict:
    return {"id": f"res_{i:02d}", "reference": f"SEED{i:02d}", "user_id": f"u_{i:02d}",
            "restaurant_id": "r_anker", "table_id": table_id, "starts_at_local": AT,
            "party_size": 2}


def timed(base_url: str, token: str, method: str, path: str, **kw):
    with Api(base_url, token=token, timeout=REQUEST_TIMEOUT) as client:
        started = time.perf_counter()
        resp = client.request(method, path, **kw)
        return resp, time.perf_counter() - started


def outcome(results, name: str):
    """The responses of a burst; fails on a transport error, a 5xx or a request over 5 s."""
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"{len(failures)} requests failed or timed out, first: {failures[0]!r}"
    responses = [resp for resp, _ in results]
    no_5xx(responses)
    slowest = max(elapsed for _, elapsed in results)
    print(f"{name} max_latency_s={slowest:.2f}")
    assert slowest < REQUEST_TIMEOUT
    return responses


def confirmed_on(api, session_tokens: list[str], table_id: str) -> list[str]:
    """Every user's confirmed bookings on `table_id` at DATE 19:00."""
    found = []
    for token in session_tokens:
        for booking in assert_status(api(token).get("/reservations"), 200).json()["reservations"]:
            if (booking["table_id"], booking["status"], booking["starts_at_local"]) == \
                    (table_id, "confirmed", AT):
                found.append(booking["reference"])
    return found


def create_body(table_id: str = "t_2") -> dict:
    return {"restaurant_id": "r_anker", "table_id": table_id, "starts_at_local": AT,
            "party_size": 2}


def test_fifty_accounts_race_for_one_table_and_slot(reset, api, base_url):
    """R7/R98/R16: 50 accounts book one table and slot at once: exactly one 201 and 49 x
    409 table_unavailable, and exactly one confirmed booking holds the table."""
    users = accounts(BURST)
    reset(fx.fixture(users=users))
    session = tokens(api, users)
    responses = outcome(burst(lambda i: timed(
        base_url, session[i], "POST", "/reservations", json=create_body(),
        idempotency_key=new_key()), BURST), "race_50_accounts_one_slot")
    assert tally(responses) == {201: 1, 409: BURST - 1}, tally(responses)
    assert {error_code(r) for r in responses if r.status_code == 409} == {"table_unavailable"}
    assert len(confirmed_on(api, session, "t_2")) == 1


ROUNDS = 5


def test_cancel_and_rebook_leave_at_most_one_confirmed_booking(reset, api, base_url):
    """R7/R108: while the owner cancels, 49 others book the freed table at once: at
    most one of them wins, and at most one confirmed booking holds the interval. Five
    rounds, one table each, because the cancel may land before or after the bookings."""
    users = accounts(BURST)
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": 4} for n in range(ROUNDS)]
    reset(fx.fixture(users=users, restaurants=[fx.restaurant(tables=tables)],
                     reservations=[{**seeded(0, f"t_{n}"), "id": f"res_r{n}",
                                    "reference": f"ROUND{n}"} for n in range(ROUNDS)]))
    session = tokens(api, users)
    for n in range(ROUNDS):
        def act(i, table=f"t_{n}", reference=f"ROUND{n}"):
            if i == 0:
                return timed(base_url, session[0], "POST", f"/reservations/{reference}/cancel")
            return timed(base_url, session[i], "POST", "/reservations",
                         json=create_body(table), idempotency_key=new_key())

        responses = outcome(burst(act, BURST), f"race_cancel_and_rebook_round{n}")
        assert_status(responses[0], 200)
        creates = tally(responses[1:])
        assert set(creates) <= {201, 409} and creates.get(201, 0) <= 1, (n, creates)
        assert len(confirmed_on(api, session, f"t_{n}")) == creates.get(201, 0), n


def test_fifty_patches_onto_one_free_table(reset, api, base_url):
    """R7/R98/R116/R117: 50 users move their bookings onto one free table at once:
    exactly one 200, 49 x 409 table_unavailable, and every loser keeps its own table."""
    users = accounts(BURST)
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": 4} for n in range(BURST + 1)]
    reset(fx.fixture(users=users, restaurants=[fx.restaurant(tables=tables)],
                     reservations=[seeded(i, f"t_{i}") for i in range(BURST)]))
    session = tokens(api, users)
    free = f"t_{BURST}"
    responses = outcome(burst(lambda i: timed(
        base_url, session[i], "PATCH", f"/reservations/SEED{i:02d}", json={"table_id": free}),
        BURST), "race_50_patches_one_table")
    assert tally(responses) == {200: 1, 409: BURST - 1}, tally(responses)
    assert {error_code(r) for r in responses if r.status_code == 409} == {"table_unavailable"}
    assert len(confirmed_on(api, session, free)) == 1
    for i, resp in enumerate(responses):
        if resp.status_code == 409:
            assert confirmed_on(api, [session[i]], f"t_{i}") == [f"SEED{i:02d}"]


def test_one_key_replayed_by_twenty_clients_takes_effect_once(reset, api, base_url):
    """R81/R9: 20 identical requests with an unused key at once: exactly one 201, 19 x
    200 with the same body, and one booking."""
    reset(fx.fixture())
    token = api().authenticate(fx.ADA["email"], fx.ADA["password"]).token
    key = new_key()
    responses = outcome(burst(lambda i: timed(
        base_url, token, "POST", "/reservations", json=create_body(), idempotency_key=key), 20),
        "race_one_key_20_clients")
    assert tally(responses) == {200: 19, 201: 1}, tally(responses)
    assert all(r.json() == responses[0].json() for r in responses)
    assert len(assert_status(api(token).get("/reservations"), 200).json()["reservations"]) == 1

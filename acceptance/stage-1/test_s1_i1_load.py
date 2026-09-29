"""S1-I1 acceptance checks under load (verifier seat), from the stage-1 specification.

Run this file alone, with nothing else loading the service: its timings assume that.
Limits (§2): up to 50 requests in flight, 5 s per request, 10 s for POST /_test/reset,
no 5xx under concurrent load (§5). Measured values are printed for the evidence block
(`pytest -rP` shows them).
"""
from __future__ import annotations

import time

import pytest

import fixtures as fx
from harness.concurrent import burst, no_5xx, tally
from harness.http import REQUEST_TIMEOUT, RESET_TIMEOUT, Api, assert_status, error_code

pytestmark = pytest.mark.stage(1)

BURST = 50


def test_simultaneous_signups_for_one_email_create_one_account(world, api, base_url):
    """R63/R16: 50 signups for one email at once give exactly one 201 and 49 x 409
    email_taken, and the email logs in as the account that won."""
    email = "race@example.com"

    def sign_up(i):
        with Api(base_url) as client:
            return client.signup(email, "correct horse", f"Racer {i}")

    results = burst(sign_up, BURST)
    no_5xx(results)
    assert tally(results) == {201: 1, 409: BURST - 1}, tally(results)
    assert {error_code(r) for r in results if r.status_code == 409} == {"email_taken"}
    winner = next(r for r in results if r.status_code == 201).json()
    session = assert_status(api().login(email, "correct horse"), 200).json()
    assert session["user_id"] == winner["user_id"]


def test_simultaneous_signups_for_distinct_emails_all_succeed(world, api, base_url):
    """R61/R16: 50 different signups at once each create their own account."""
    def sign_up(i):
        with Api(base_url) as client:
            return client.signup(f"diner{i}@example.com", "correct horse", f"Diner {i}")

    results = burst(sign_up, BURST)
    no_5xx(results)
    assert tally(results) == {201: BURST}, tally(results)
    accounts = [r.json() for r in results]
    assert len({a["user_id"] for a in accounts}) == BURST, "user ids collide"
    for i, account in enumerate(accounts):
        assert_status(api(account["token"]).get("/reservations"), 200)
        session = assert_status(api().login(f"diner{i}@example.com", "correct horse"), 200)
        assert session.json()["user_id"] == account["user_id"]


def test_fifty_simultaneous_logins_each_answer_within_5_s(world, api, base_url):
    """R16/R17/R62: 50 logins in flight at once; each answers 200 within 5 s and
    every token it hands out works."""
    def log_in(i):
        with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
            started = time.perf_counter()
            resp = client.login(fx.ADA["email"], fx.ADA["password"])
            return resp, time.perf_counter() - started

    results = burst(log_in, BURST)
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"{len(failures)} logins failed or timed out, first: {failures[0]!r}"
    latencies = [elapsed for _, elapsed in results]
    print(f"login_burst_50 max_latency_s={max(latencies):.2f}")
    assert tally([resp for resp, _ in results]) == {200: BURST}
    assert max(latencies) < REQUEST_TIMEOUT
    for resp, _ in results:
        assert_status(api(resp.json()["token"]).get("/reservations"), 200)


def test_a_reset_with_100_users_answers_within_10_s(reset, api):
    """R17/R23/R42: a 100-user fixture resets within 10 s; its users log in at once."""
    users = [{"id": f"u_{i:03d}", "email": f"diner{i:03d}@example.com",
              "password": f"password {i:03d}", "display_name": f"Diner {i}"}
             for i in range(100)]
    started = time.perf_counter()
    resp = reset(fx.fixture(users=users), raw=True)
    elapsed = time.perf_counter() - started
    print(f"reset_100_users status={resp.status_code} reset_100_users_s={elapsed:.2f}")
    assert_status(resp, 204)
    assert elapsed < RESET_TIMEOUT
    for user in (users[0], users[49], users[99]):
        session = assert_status(api().login(user["email"], user["password"]), 200).json()
        assert session["user_id"] == user["id"]


def test_fifty_mixed_requests_in_flight_never_answer_5xx(world, base_url):
    """R60/R16: reads, logins and signups at once, 50 in flight: no 5xx."""
    rid, token = world.rid, world.ada.token

    def request(i):
        with Api(base_url, token=token) as client:
            return (lambda: client.get("/restaurants"),
                    lambda: client.get(f"/restaurants/{rid}"),
                    lambda: client.get("/reservations"),
                    lambda: client.login(fx.BOB["email"], fx.BOB["password"]),
                    lambda: client.signup(f"mixed{i}@example.com", "correct horse", "Mixed"),
                    )[i % 5]()

    results = burst(request, BURST)
    no_5xx(results)
    assert set(tally(results)) <= {200, 201}, tally(results)

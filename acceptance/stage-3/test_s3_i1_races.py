"""S3-I1 races and the dense day under two durations (verifier seat), from the stage-3
specification ("Policies and accepted terms") with §7 and the plan's H1-H3.

Run this file alone, with nothing else loading the service: its timings assume that.
`pytest -rP` prints the measured values. R.. and H.. name the room plan's lines.
"""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.concurrent import burst, tally
from harness.http import REQUEST_TIMEOUT, Api, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()
ROUNDS = 3


def clients_outcome(results):
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"{len(failures)} requests failed, first: {failures[0]!r}"
    assert all(r.status_code < 500 for r in results), tally(results)
    return results


def test_one_policy_key_from_twenty_clients_publishes_one_version(reset, api, base_url):
    """R321/R322/§7: twenty clients send one key and body at once: exactly one 201, the others
    200 with the same body, and one version exists."""
    reset(fx.fixture(restaurants=[fx.managed_restaurant()]))
    token = api().authenticate(fx.ADA["email"], fx.ADA["password"]).token
    key, body = new_key(), fx.policy(DATE, reservation_duration_minutes=45)

    def publish(_):
        with Api(base_url, token=token, timeout=REQUEST_TIMEOUT) as client:
            return client.post("/restaurants/r_anker/policies", json=body, idempotency_key=key)

    results = clients_outcome(burst(publish, 20))
    print(f"policy key race statuses={tally(results)}")
    assert sorted(r.status_code for r in results) == [200] * 19 + [201]
    assert len({r.text for r in results}) == 1
    with Api(base_url) as anon:
        assert [p["policy_version"] for p in anon.get("/restaurants/r_anker/policies").json()["policies"]] == [1]


def test_amendments_racing_with_one_revision_make_one_real_change(reset, api, base_url):
    """R339/H3: in each of three rounds, twenty PATCHes carrying `expected_revision` 1, each a
    real change, arrive at once: exactly one succeeds, the others are 409 stale_revision, and
    the booking ends at revision 2 with the winner's party."""
    for round_number in range(ROUNDS):
        reset(fx.fixture(restaurants=[fx.managed_restaurant()]))
        ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
        booking = assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": fx.local(DATE), "party_size": 6}), 201).json()

        def amend(i, ref=booking["reference"]):
            with Api(base_url, token=ada.token, timeout=REQUEST_TIMEOUT) as client:
                return client.patch(f"/reservations/{ref}", json={"party_size": 1 + i % 5, "expected_revision": 1})

        results = clients_outcome(burst(amend, 20))
        print(f"round {round_number} amendment race statuses={tally(results)}")
        winners = [r for r in results if r.status_code == 200]
        assert len(winners) == 1, tally(results)
        assert all(r.status_code == 409 and error_code(r) == "stale_revision" for r in results if r not in winners)
        final = assert_status(ada.get(f"/reservations/{booking['reference']}"), 200).json()
        assert (final["revision"], final["party_size"]) == (2, winners[0].json()["party_size"])


def test_publications_racing_creates_leave_every_booking_whole_terms(reset, api, base_url):
    """R330/R322/R324/H1: twenty same-date publications race twenty creates: the twenty
    publications are versions 1 to 20, once each; every booking's `accepted_terms` is exactly
    one policy's snapshot (policy 0 or a published one, never a mix), its end is its start
    plus that policy's duration, and its decision agrees."""
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": 6} for n in range(1, 11)]
    reset(fx.fixture(restaurants=[{**fx.managed_restaurant(tables=tables)}]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    policies = [fx.policy(DATE, reservation_duration_minutes=31 + i, cancellation_cutoff_minutes=100 + i,
                          slot_minutes=30, capacities={t["id"]: 10 + i for t in tables}) for i in range(20)]
    times = [(f"t_{1 + i % 10}", "18:00" if i < 10 else "20:30") for i in range(20)]

    def act(i):
        with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
            if i % 2 == 0:
                client.token = ada.token
                return client.post("/restaurants/r_anker/policies", json=policies[i // 2], idempotency_key=new_key())
            client.token = bob.token
            table, hhmm = times[i // 2]
            return client.post("/reservations", idempotency_key=new_key(), json={
                "restaurant_id": "r_anker", "table_id": table, "starts_at_local": fx.local(DATE, hhmm), "party_size": 2})

    results = clients_outcome(burst(act, 40))
    print(f"publications vs creates statuses={tally(results)}")
    assert all(r.status_code == 201 for r in results), tally(results)
    with Api(base_url) as anon:
        published = anon.get("/restaurants/r_anker/policies").json()["policies"]
    assert [p["policy_version"] for p in published] == list(range(1, 21))
    assert sorted(r.json()["policy_version"] for i, r in enumerate(results) if i % 2 == 0) == list(range(1, 21))
    snapshots ={p["policy_version"]: {k: v for k, v in p.items() if k != "effective_from"} for p in published}
    snapshots[0] = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
                    "cancellation_cutoff_minutes": 120, "opening_hours": fx.all_week(),
                    "capacities": {t["id"]: 6 for t in tables}}
    bookings = [r.json() for i, r in enumerate(results) if i % 2 == 1]
    for booking in bookings:
        terms = booking["accepted_terms"]
        assert terms == snapshots[terms["policy_version"]], terms
        length = dt.datetime.fromisoformat(booking["ends_at"]) - dt.datetime.fromisoformat(booking["starts_at"])
        assert length == dt.timedelta(minutes=terms["reservation_duration_minutes"]), booking["reference"]
        decision = assert_status(bob.get(f"/reservations/{booking['reference']}/decision"), 200).json()
        assert (decision["revision"], decision["accepted_terms"]) == (1, terms)


# ---- the S1-I7 dense day under two durations ------------------------------------------------------

DENSE_DATE = "2026-12-03"
ZONE = ZoneInfo("Europe/Berlin")
N_TABLES, BURST = 40, 50
CAPACITY = {f"t_{n}": n % 8 + 1 for n in range(N_TABLES)}
OPENS, CLOSES, OLD, NEW = 0, 23 * 60 + 30, 90, 45


def at(total: int) -> str:
    return fx.local(DENSE_DATE, f"{total // 60:02d}:{total % 60:02d}")


def test_the_dense_day_with_two_durations_answers_fifty_in_flight_within_5_s(reset, api, base_url):
    """R16/R17/R305/H1: 200 bookings under policy 0 (90 minutes), a same-date policy of 45
    minutes, then 200 bookings under it: 50 simultaneous GET /availability all answer 200
    within 5 s and equal the reference built from each booking's own duration."""
    booked = {t: [] for t in CAPACITY}
    seeds = []
    for n, table in enumerate(CAPACITY):
        first = 30 * ((7 * n) % 15)
        for k in range(5):
            start = first + OLD * k
            booked[table].append((start, OLD))
            seeds.append({"id": f"res_{n}_{k}", "reference": f"D{n:03d}{k:02d}", "user_id": fx.ADA["id"],
                          "restaurant_id": "r_anker", "table_id": table, "starts_at_local": at(start), "party_size": 1})
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
            start = first + NEW * k
            assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
                "restaurant_id": "r_anker", "table_id": table, "starts_at_local": at(start), "party_size": 1}), 201)
            booked[table].append((start, NEW))
    expected = []
    for start in range(OPENS, CLOSES - NEW + 1):
        free = [t for t, cap in CAPACITY.items() if cap >= 2 and all(start + NEW <= b or start >= b + d for b, d in booked[t])]
        expected.append((at(start), free))
    params = {"restaurant_id": "r_anker", "date": DENSE_DATE, "party_size": 2}

    def timed(_):
        with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
            started = time.perf_counter()
            resp = client.get("/availability", params=params)
            return resp, time.perf_counter() - started

    results = burst(timed, BURST)
    failures = [r for r in results if isinstance(r, Exception)]
    slowest = max((elapsed for _, elapsed in (r for r in results if not isinstance(r, Exception))), default=float("inf"))
    print(f"dense two durations slots={len(expected)} burst50_max_s={slowest:.2f} failed={len(failures)}")
    assert not failures, f"{len(failures)} of {BURST} failed or took over 5 s: {failures[0]!r}"
    assert all(resp.status_code == 200 for resp, _ in results)
    assert slowest < REQUEST_TIMEOUT
    for resp, _ in results:
        assert [(s["starts_at_local"], s["available_table_ids"]) for s in resp.json()["slots"]] == expected

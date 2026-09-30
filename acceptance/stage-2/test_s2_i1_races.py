"""S2-I1 races on table sets and the dense day with pairs (verifier seat), from the stage-2
specification.

Run this file alone, with nothing else loading the service: its timings assume that.
R274/R250/R263/R7: a pair and its member tables booked at once by 50 requests in flight
end with exactly one confirmed booking on each member, as a one-at-a-time order would;
a PATCH that grows a booking into a pair, racing creates on the added member, likewise.
R16/R17/R256/R257 (critic's point 7): the S1-I7 dense day with 20 declared pairs answers
50 simultaneous GET /availability, each 200 within 5 s and equal to a reference.
`pytest -rP` prints the measured values.
"""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.concurrent import burst, no_5xx, tally
from harness.http import REQUEST_TIMEOUT, Api, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(2)

BURST = 50
DATE = fx.booking_date()
TABLES = [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4},
          {"id": "t_3", "label": "3", "capacity": 6}]
PAIRS = [["t_1", "t_2"], ["t_3", "t_2"]]
KINDS = [{"table_ids": ["t_1", "t_2"]}, {"table_ids": ["t_2", "t_3"]},
         {"table_id": "t_1"}, {"table_id": "t_2"}, {"table_id": "t_3"}]
ROUNDS = ["12:00", "14:00", "16:00", "18:00", "20:00"]


def minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def at(total: int, date: str = DATE) -> str:
    return fx.local(date, f"{total // 60:02d}:{total % 60:02d}")


def accounts(n: int) -> list[dict]:
    return [{"id": f"u_{i:02d}", "email": f"diner{i:02d}@example.com",
             "password": "correct horse", "display_name": f"Diner {i}"} for i in range(n)]


def race_world(reset, api) -> list[str]:
    users = accounts(BURST)
    reset(fx.fixture(users=users, restaurants=[{
        **fx.restaurant(tables=[dict(t) for t in TABLES], opening_hours=fx.all_week("12:00", "23:00")),
        "combinable": [list(p) for p in PAIRS]}]))
    return [api().authenticate(u["email"], u["password"]).token for u in users]


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
    print(f"{name} max_latency_s={slowest:.2f} statuses={tally(responses)}")
    assert slowest < REQUEST_TIMEOUT
    return responses


def confirmed_between(api, session: list[str], first: int, last: int) -> list[dict]:
    """Every user's confirmed bookings starting from `first` to `last` minutes on DATE."""
    window = {at(m) for m in range(first, last + 1, 30)}
    return [b for token in session
            for b in assert_status(api(token).get("/reservations"), 200).json()["reservations"]
            if b["status"] == "confirmed" and b["starts_at_local"] in window]


def held(bookings: list[dict]) -> list[str]:
    return sorted(t for b in bookings for t in b["table_ids"])


def test_a_pair_and_its_members_race_at_fifty_in_flight(reset, api, base_url):
    """R274/R250/R263/R7/R16: in each of 5 rounds, 50 requests in flight book the two
    declared pairs and each of their three tables, at two overlapping starts: every loser
    is 409 table_unavailable and each table ends held by exactly one confirmed booking, the
    winners'."""
    session = race_world(reset, api)
    for number, start in enumerate(ROUNDS):
        def attempt(i: int, number=number, start=start):
            body = {"restaurant_id": "r_anker", "starts_at_local": at(minutes(start) + 30 * (i % 2)),
                    "party_size": 2, **KINDS[(i + number) % len(KINDS)]}
            return timed(base_url, session[i], "POST", "/reservations", json=body,
                         idempotency_key=new_key())

        responses = outcome(burst(attempt, BURST), f"round={number} start={start}")
        winners = [r.json() for r in responses if r.status_code == 201]
        losers = [r for r in responses if r.status_code != 201]
        assert all(r.status_code == 409 and error_code(r) == "table_unavailable" for r in losers), \
            tally(responses)
        assert held(winners) == ["t_1", "t_2", "t_3"], \
            f"round {number}: the winners hold {held(winners)}, not each table once"
        stored = confirmed_between(api, session, minutes(start), minutes(start) + 30)
        assert sorted(b["reference"] for b in stored) == sorted(w["reference"] for w in winners)
        assert held(stored) == ["t_1", "t_2", "t_3"]


def test_a_patch_into_a_pair_races_creates_on_the_added_table(reset, api, base_url):
    """R274/R266/R263/R7: in each of 3 rounds, one PATCH turns a single-table booking into
    a pair while 49 requests book the added table at overlapping starts: exactly one of
    them wins that table, and the stored bookings agree."""
    session = race_world(reset, api)
    for number, start in enumerate(ROUNDS[:3]):
        own = Api(base_url, token=session[0])
        reference = assert_status(own.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": at(minutes(start)),
            "party_size": 2}), 201).json()["reference"]
        own.close()

        def attempt(i: int, start=start, reference=reference):
            if i == 0:
                return timed(base_url, session[0], "PATCH", f"/reservations/{reference}",
                             json={"table_ids": ["t_2", "t_1"]})
            return timed(base_url, session[i], "POST", "/reservations", idempotency_key=new_key(),
                         json={"restaurant_id": "r_anker", "table_id": "t_2", "party_size": 2,
                               "starts_at_local": at(minutes(start) + 30 * (i % 2))})

        responses = outcome(burst(attempt, BURST), f"patch round={number} start={start}")
        won = [r for r in responses if r.status_code in (200, 201)]
        lost = [r for r in responses if r.status_code not in (200, 201)]
        assert len(won) == 1, f"round {number}: {len(won)} requests won table t_2: {tally(responses)}"
        assert all(r.status_code == 409 and error_code(r) == "table_unavailable" for r in lost)
        stored = confirmed_between(api, session, minutes(start), minutes(start) + 30)
        assert held(stored) == ["t_1", "t_2"], f"round {number}: stored bookings hold {held(stored)}"


# ---- the S1-I7 dense day with 20 declared pairs ------------------------------------------------

DENSE_DATE = "2026-12-03"           # a Thursday in standard time, as in S1-I7
ZONE = ZoneInfo("Europe/Berlin")
OPENS, CLOSES, DURATION = 0, 23 * 60 + 30, 90
N_TABLES, PER_TABLE = 40, 10
CAPACITY = {f"t_{n}": n % 8 + 1 for n in range(N_TABLES)}
# 20 pairs over neighbouring tables, sharing members, declared in descending order with
# every other pair named high table first: the answer must follow the declaration.
DENSE_PAIRS = [[f"t_{n + 1}", f"t_{n}"] if n % 2 else [f"t_{n}", f"t_{n + 1}"]
               for n in range(19, -1, -1)]


def dense_fixture() -> tuple[dict, dict[str, list[int]]]:
    """S1-I7's densest row (1-minute grid, 40 tables, 400 bookings) with 20 declared pairs."""
    booked = {f"t_{n}": [30 * ((7 * n) % 15) + DURATION * k for k in range(PER_TABLE)]
              for n in range(N_TABLES)}
    reservations = [{"id": f"res_{n}_{k}", "reference": f"D{n:03d}{k:02d}", "user_id": fx.ADA["id"],
                     "restaurant_id": "r_anker", "table_id": table,
                     "starts_at_local": at(start, DENSE_DATE), "party_size": 1}
                    for n, (table, starts) in enumerate(booked.items()) for k, start in enumerate(starts)]
    restaurant = {**fx.restaurant(slot_minutes=1, opening_hours=fx.all_week("00:00", "23:30"),
                                  tables=[{"id": t, "label": t, "capacity": c} for t, c in CAPACITY.items()]),
                  "combinable": DENSE_PAIRS}
    return fx.fixture(restaurants=[restaurant], reservations=reservations), booked


def dense_reference(booked: dict[str, list[int]], party: int) -> list[tuple]:
    """R89/R90/R257 per slot: the singles, then the options (singles in fixture order, then
    declared pairs in declared order with summed capacity, both members free)."""
    found = []
    for start in range(OPENS, CLOSES - DURATION + 1):
        free = {t for t in CAPACITY if all(abs(start - b) >= DURATION for b in booked[t])}
        singles = [t for t in CAPACITY if CAPACITY[t] >= party and t in free]
        pairs = [{"table_ids": p, "capacity": CAPACITY[p[0]] + CAPACITY[p[1]]} for p in DENSE_PAIRS
                 if CAPACITY[p[0]] + CAPACITY[p[1]] >= party and set(p) <= free]
        instant = dt.datetime.fromisoformat(at(start, DENSE_DATE)).replace(tzinfo=ZONE)
        found.append((at(start, DENSE_DATE), instant.astimezone(dt.timezone.utc), singles,
                      [{"table_ids": [t], "capacity": CAPACITY[t]} for t in singles] + pairs))
    return found


def dense_shown(body: dict) -> list[tuple]:
    return [(s["starts_at_local"], dt.datetime.fromisoformat(s["starts_at"]), s["available_table_ids"],
             s.get("available_options")) for s in body["slots"]]


@pytest.mark.parametrize("party", [2, 6])
def test_the_dense_day_with_pairs_answers_fifty_in_flight_within_5_s(reset, base_url, party):
    """R16/R17/R256/R257/R60: on the dense day with 20 declared pairs, 50 simultaneous
    GET /availability each answer 200 within 5 s, all equal to the reference."""
    fixture, booked = dense_fixture()
    reset(fixture)
    expected = dense_reference(booked, party)
    params = {"restaurant_id": "r_anker", "date": DENSE_DATE, "party_size": party}
    with Api(base_url) as client:
        started = time.perf_counter()
        single = assert_status(client.get("/availability", params=params), 200)
        single_s = time.perf_counter() - started
    assert dense_shown(single.json()) == expected

    def timed_read(_):
        with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
            started = time.perf_counter()
            resp = client.get("/availability", params=params)
            return resp, time.perf_counter() - started

    results = burst(timed_read, BURST)
    failures = [r for r in results if isinstance(r, Exception)]
    slowest = max((elapsed for _, elapsed in (r for r in results if not isinstance(r, Exception))),
                  default=float("inf"))
    options = sum(len(s[3]) for s in expected)
    print(f"dense-pairs party={party} slots={len(expected)} options={options} "
          f"bytes={len(single.content)} single_s={single_s:.3f} burst50_max_s={slowest:.2f} "
          f"headroom_s={REQUEST_TIMEOUT - slowest:.2f} failed={len(failures)}")
    assert not failures, f"{len(failures)} of {BURST} failed or took over 5 s: {failures[0]!r}"
    assert all(resp.status_code == 200 for resp, _ in results)
    assert slowest < REQUEST_TIMEOUT
    assert all(dense_shown(resp.json()) == expected for resp, _ in results)

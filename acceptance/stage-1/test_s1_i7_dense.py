"""S1-I7 acceptance checks (verifier seat): availability on a dense day, from §2, §8, §9.

Run this file alone, with nothing else loading the service: its timings assume that.
R16/R17: 50 GET /availability in flight each answer within 5 s, for four densities up
to a 1-minute grid, 40 tables and 400 bookings. R89/R90: every answer equals a reference
computed here from the fixture alone. R108/R116/R150: after every writer (create, PATCH of
time and table, cancel, a two-item table swap, an import of the state's export) one
answer still equals the reference computed from the confirmed bookings this check knows
of, a freed slot books 201 and a taken one 409. `pytest -rP` prints the measured values.
"""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.concurrent import burst
from harness.http import REQUEST_TIMEOUT, RESET_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(1)

DATE = "2026-12-03"            # a Thursday in standard time, well inside the cutoff
ZONE = ZoneInfo("Europe/Berlin")
OPENS, CLOSES, DURATION = 0, 23 * 60 + 30, 90
BURST = 50


def at(minutes: int) -> str:
    return fx.local(DATE, f"{minutes // 60:02d}:{minutes % 60:02d}")


def instant(minutes: int) -> dt.datetime:
    return dt.datetime.fromisoformat(at(minutes)).replace(tzinfo=ZONE).astimezone(dt.timezone.utc)


def dense_fixture(slot: int, tables: int, per_table: int) -> tuple[dict, dict[str, list[int]]]:
    """Tables t_0..t_{n-1} with capacities 1..8; each holds `per_table` back-to-back
    90-minute bookings from its own first start, so every table has other free hours."""
    booked = {f"t_{n}": [30 * ((7 * n) % 15) + DURATION * k for k in range(per_table)]
              for n in range(tables)}
    reservations = [{"id": f"res_{n}_{k}", "reference": f"D{n:03d}{k:02d}", "user_id": fx.ADA["id"],
                     "restaurant_id": "r_anker", "table_id": table, "starts_at_local": at(start),
                     "party_size": 1}
                    for n, (table, starts) in enumerate(booked.items()) for k, start in enumerate(starts)]
    restaurant = fx.restaurant(slot_minutes=slot, opening_hours=fx.all_week("00:00", "23:30"),
                               tables=[{"id": f"t_{n}", "label": str(n), "capacity": n % 8 + 1}
                                       for n in range(tables)])
    return fx.fixture(restaurants=[restaurant], reservations=reservations), booked


def reference(slot: int, capacities: dict[str, int], booked: dict[str, list[int]],
              party: int) -> list[tuple]:
    """The slot list §8 prescribes: every step from opens with start + duration <= closes,
    each with the tables (fixture order) that seat the party and clash with no booking."""
    found = []
    for start in range(OPENS, CLOSES - DURATION + 1, slot):
        free = [table for table, capacity in capacities.items()
                if capacity >= party and all(abs(start - b) >= DURATION for b in booked[table])]
        found.append((at(start), instant(start), free))
    return found


def shown(body: dict) -> list[tuple]:
    return [(s["starts_at_local"], dt.datetime.fromisoformat(s["starts_at"]), s["available_table_ids"])
            for s in body["slots"]]


def availability(client: Api, party: int):
    return client.get("/availability", params={"restaurant_id": "r_anker", "date": DATE,
                                               "party_size": party})


ROWS = [(30, 3, 1), (15, 10, 5), (5, 40, 10), (1, 40, 10)]


@pytest.mark.parametrize("slot,tables,per_table", ROWS, ids=[f"slot{r[0]}_{r[1]}tables_{r[1] * r[2]}bookings" for r in ROWS])
def test_fifty_in_flight_answer_within_5_s_and_equal_the_reference(reset, base_url, slot, tables,
                                                                  per_table):
    """R16/R17/R89/R90/R60: 50 simultaneous requests each 200 within 5 s, all equal to
    the reference slot list."""
    fixture, booked = dense_fixture(slot, tables, per_table)
    reset(fixture)
    expected = reference(slot, {f"t_{n}": n % 8 + 1 for n in range(tables)}, booked, 2)
    with Api(base_url) as client:
        started = time.perf_counter()
        single = assert_status(availability(client, 2), 200)
        single_s = time.perf_counter() - started
    assert shown(single.json()) == expected

    def timed(_):
        with Api(base_url, timeout=REQUEST_TIMEOUT) as client:
            started = time.perf_counter()
            resp = availability(client, 2)
            return resp, time.perf_counter() - started

    results = burst(timed, BURST)
    failures = [r for r in results if isinstance(r, Exception)]
    slowest = max((elapsed for _, elapsed in (r for r in results if not isinstance(r, Exception))),
                  default=float("inf"))
    print(f"dense slot={slot} tables={tables} bookings={tables * per_table} slots={len(expected)} "
          f"single_s={single_s:.3f} burst50_max_s={slowest:.2f} headroom_s={REQUEST_TIMEOUT - slowest:.2f} "
          f"failed={len(failures)}")
    assert not failures, f"{len(failures)} of {BURST} failed or took over 5 s: {failures[0]!r}"
    assert all(resp.status_code == 200 for resp, _ in results)
    assert slowest < REQUEST_TIMEOUT
    assert all(shown(resp.json()) == expected for resp, _ in results)


def test_availability_equals_the_reference_after_every_writer(reset, api, base_url):
    """R90/R108/R116/R150 (critic C29-B1): on the dense day, after a create, a PATCH of
    time and table, a cancel, a two-item table swap and an import of the export, the
    answer equals the reference built from the bookings this check knows of; a slot the
    write freed books 201 and a slot it took gives 409."""
    fixture, booked = dense_fixture(1, 40, 10)
    capacities = {f"t_{n}": n % 8 + 1 for n in range(40)}
    reset(fixture)
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    anon = api()

    def matches(step: str) -> None:
        body = assert_status(availability(anon, 1), 200).json()
        assert shown(body) == reference(1, capacities, booked, 1), f"availability differs after {step}"

    def create(client, table: str, start: int, expected: int) -> str | None:
        resp = client.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_anker", "table_id": table, "starts_at_local": at(start), "party_size": 1})
        assert resp.status_code == expected, (table, at(start), resp.status_code, resp.text[:200])
        if expected == 201:
            booked[table].append(start)
            return resp.json()["reference"]
        return None

    def moved(table: str, start: int, to_table: str, to_start: int) -> None:
        booked[table].remove(start)
        booked[to_table].append(to_start)

    matches("reset")
    first = create(ada, "t_0", 19 * 60, 201)                        # create
    matches("a create")
    create(bob, "t_0", 19 * 60 + 30, 409)                           # the slot it took
    assert_status(ada.patch(f"/reservations/{first}", json={        # PATCH time and table
        "table_id": "t_3", "starts_at_local": at(20 * 60)}), 200)
    moved("t_0", 19 * 60, "t_3", 20 * 60)
    matches("a PATCH of time and table")
    other = create(bob, "t_0", 19 * 60, 201)                        # the slot it freed
    create(bob, "t_3", 20 * 60 + 30, 409)                           # the slot it took
    matches("a create on the freed slot")
    assert_status(bob.post(f"/reservations/{other}/cancel"), 200)   # cancel
    booked["t_0"].remove(19 * 60)
    matches("a cancel")
    second = create(ada, "t_0", 19 * 60, 201)                       # the slot it freed
    move = {"moves": [{"reference": second, "table_id": "t_3"},     # two-item table swap
                      {"reference": first, "table_id": "t_0"}]}
    assert_status(ada.post("/reservation-moves", json=move, idempotency_key=new_key()), 201)
    moved("t_0", 19 * 60, "t_3", 19 * 60)
    moved("t_3", 20 * 60, "t_0", 20 * 60)
    matches("a two-item table swap")
    create(bob, "t_0", 18 * 60, 201)                                # freed by the swap
    create(bob, "t_0", 21 * 60, 409)                                # taken by the swap
    matches("a create after the swap")
    with Api(base_url, timeout=RESET_TIMEOUT) as control:           # import of the export
        exported = assert_status(control.get("/_test/export"), 200).json()
        reset(fx.fixture())
        assert_status(control.post("/_test/import", json=exported), 204)
    matches("an import of the export")
    create(bob, "t_0", 20 * 60 + 30, 409)
    create(bob, "t_3", 21 * 60, 201)
    matches("a create after the import")

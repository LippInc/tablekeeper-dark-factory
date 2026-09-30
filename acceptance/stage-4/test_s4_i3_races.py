"""S4-I3 acceptance checks (verifier seat): applications under simultaneous requests, from
the stage-4 specification ("A plan already applied under a different key gives 409
`plan_already_applied`", "Any intervening restaurant revision invalidates the plan", "Application
is atomic", "Concurrent applications must not leave partially moved bookings"; R429-R433,
R437, R439) with the plan's Q4, Q13 and Q15.

Resets the service; run it alone, with nothing else loading the service. `-rP` prints the
outcomes of every round.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

import fixtures as fx
from harness.http import Api, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(4)

_spec = importlib.util.spec_from_file_location("s4i3_apply", pathlib.Path(__file__).with_name("test_s4_i3_apply.py"))
a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(a)
make = a.make  # the reset-world fixture


def outcome(response) -> str:
    return str(response.status_code) if response.status_code < 400 else f"{response.status_code} {error_code(response)}"


def together(world, calls):
    """Send every (who, method, path, json, key) at once, each from its own client."""
    def send(call):
        who, method, path, body, key = call
        with Api(world.base, token=getattr(world, who).token, timeout=30) as client:
            return client.request(method, path, json=body, idempotency_key=key)
    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(send, calls))


def state(world) -> dict:
    return a.exported(world.base)["state"]


def overlapping(world) -> list[str]:
    """Pairs of holds on a common table that share time: the owner's confirmed bookings (each
    [starts_at, ends_at) as the service answers them) and the restaurants' closures."""
    instant = dt.datetime.fromisoformat
    listed = assert_status(world.bob.get("/reservations"), 200).json()["reservations"]
    holds = [(r["restaurant_id"], table, instant(r["starts_at"]), instant(r["ends_at"]), r["reference"])
             for r in listed if r["status"] == "confirmed" for table in r["table_ids"]]
    holds += [(restaurant["id"], c["table_id"], instant(c["from"]), instant(c["to"]), f"closure {c['plan_id']}")
              for restaurant in state(world)["restaurants"] for c in restaurant["closures"]]
    return [f"{x[4]} / {y[4]} on {x[1]}" for i, x in enumerate(holds) for y in holds[i + 1:]
            if x[:2] == y[:2] and x[2] < y[3] and y[2] < x[3]]


@pytest.mark.parametrize("round_", range(3))
def test_twenty_applications_of_one_plan_under_distinct_keys(make, round_):
    """R430/R432/R439: 20 simultaneous applications of one plan, each under its own key: one
    201, 19 × 409 plan_already_applied; one closure, the revision up by one, the moved booking
    one revision further with one `reassigned` entry."""
    world = a.world(make)
    plan_id = a.planned(world.ada, a.CLOSED)["plan_id"]
    before = a.read(world, "MOVE01")
    responses = together(world, [("ada", "POST", f"/restaurants/r_anker/replans/{plan_id}/apply", {}, new_key())
                                 for _ in range(20)])
    outcomes = Counter(outcome(r) for r in responses)
    print(f"round {round_}: {dict(outcomes)}")
    assert outcomes == {"201": 1, "409 plan_already_applied": 19}
    assert len(a.closures(world)) == 1 and a.revision(world) == 1
    assert a.read(world, "MOVE01")["revision"] == before["revision"] + 1
    assert [e["event"] for e in a.history(world, "MOVE01")].count("reassigned") == 1


@pytest.mark.parametrize("round_", range(5))
def test_two_plans_of_one_restaurant_applied_together(make, round_):
    """R429/R432: two plans made at the same revision (t_2 and t_4 closed) applied at once: one
    201 and one 409 stale_plan; one closure; no partial move."""
    world = a.world(make)
    first = a.planned(world.ada, a.CLOSED)["plan_id"]
    second = a.planned(world.ada, a.closure(table="t_3", start="19:00", end="21:00"))["plan_id"]
    responses = together(world, [("ada", "POST", f"/restaurants/r_anker/replans/{p}/apply", {}, new_key())
                                 for p in (first, second)])
    outcomes = Counter(outcome(r) for r in responses)
    print(f"round {round_}: {dict(outcomes)}")
    assert outcomes == {"201": 1, "409 stale_plan": 1}
    state_ = state(world)
    assert len(next(r for r in state_["restaurants"] if r["id"] == "r_anker")["closures"]) == 1
    assert overlapping(world) == []


def racing_writes(world, plan_id, mix):
    """The application, and at the same time writes onto the tables it touches. `every_write`:
    creates on the closed t_2 inside the closure after MOVE01's end, on MOVE01's destination t_1
    and on the pair t_1+t_2; PATCHes of KEEP01 and FIXD01 onto t_2 inside the closure; an
    adoption of FIXD01. `onto_the_closed_table`: only two creates and a PATCH onto t_2 at 20:30,
    inside the closure and after MOVE01's end, so nothing blocks MOVE01's move to t_1."""
    body = lambda table_ids, hhmm, party=2: {"restaurant_id": "r_anker", "table_ids": table_ids,
                                             "starts_at_local": fx.local(a.DATE, hhmm), "party_size": party}
    application = ("ada", "POST", f"/restaurants/r_anker/replans/{plan_id}/apply", {}, new_key())
    if mix == "onto_the_closed_table":
        return [application,
                ("bob", "POST", "/reservations", body(["t_2"], "20:30"), new_key()),
                ("bob", "POST", "/reservations", body(["t_2"], "20:30"), new_key()),
                ("bob", "PATCH", "/reservations/FIXD01", {"table_id": "t_2", "starts_at_local": fx.local(a.DATE, "20:30")}, None)]
    return [application,
            ("bob", "POST", "/reservations", body(["t_2"], "20:30"), new_key()),
            ("bob", "POST", "/reservations", body(["t_2"], "20:00"), new_key()),
            ("bob", "POST", "/reservations", body(["t_1"], "19:30"), new_key()),
            ("bob", "POST", "/reservations", body(["t_1"], "18:30"), new_key()),
            ("bob", "POST", "/reservations", body(["t_1", "t_2"], "21:00", 5), new_key()),
            ("bob", "POST", "/reservations", body(["t_2"], "19:00"), new_key()),
            ("bob", "PATCH", "/reservations/KEEP01", {"table_id": "t_2", "starts_at_local": fx.local(a.DATE, "20:30")}, None),
            ("bob", "PATCH", "/reservations/FIXD01", {"table_id": "t_2", "starts_at_local": fx.local(a.DATE, "20:30")}, None),
            ("bob", "POST", "/series", {"anchor_reference": "FIXD01", "count": 2, "interval_weeks": 1}, new_key())]


@pytest.mark.parametrize("round_", range(8))
@pytest.mark.parametrize("mix", ["every_write", "onto_the_closed_table"])
def test_an_application_racing_writes_is_never_partial_and_never_overlaps(make, mix, round_):
    """R432/R433/R437/R439/Q13/Q15: an application racing creates, PATCHes and an adoption on the
    tables it touches either applies whole (closure recorded, MOVE01 on t_1 with one
    `reassigned` entry) or not at all (no closure, MOVE01 on t_2, no `reassigned` entry), and
    afterwards no two holds - bookings or the closure - share a table at the same time."""
    world = a.world(make)
    plan_id = a.planned(world.ada, a.CLOSED)["plan_id"]
    responses = together(world, racing_writes(world, plan_id, mix))
    state_ = state(world)
    moved = a.read(world, "MOVE01")
    closed = next(r for r in state_["restaurants"] if r["id"] == "r_anker")["closures"]
    reassigned = [ref for ref in ("MOVE01", "KEEP01", "FIXD01")
                  if any(e["event"] == "reassigned" for e in a.history(world, ref))]
    tables = moved["table_ids"]
    print(f"{mix} round {round_}: apply {outcome(responses[0])}, writes {dict(Counter(outcome(r) for r in responses[1:]))}, "
          f"closures {len(closed)}, MOVE01 on {tables}, overlaps {len(overlapping(world))}")
    if responses[0].status_code == 201:
        assert len(closed) == 1 and tables == ["t_1"] and reassigned == ["MOVE01"]
    else:
        assert closed == [] and tables == ["t_2"] and reassigned == []
    assert overlapping(world) == [], overlapping(world)

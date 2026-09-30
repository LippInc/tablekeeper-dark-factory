"""S4-I2 acceptance check (verifier seat): the worst cases within the planning limits answer
within the task's 5 s per request (R411 with the task's runtime limits; plan v2.6 ruling on
BS4-4: timed against 5 s, the values reported).

Resets the service; run it alone, with nothing else loading the service. `-rP` prints the
measured values.
"""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(4)

DATE = fx.booking_date()
BERLIN = ZoneInfo("Europe/Berlin")
LIMIT_S = 5.0
PAIRS = [["t_2", "t_3"], ["t_4", "t_5"], ["t_3", "t_6"], ["t_5", "t_2"]]


def world(reset, api, seeds):
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(1, 7)]
    reset(fx.fixture(restaurants=[{**fx.restaurant(tables=tables, opening_hours=fx.all_week("12:00", "23:30")),
                                   "manager_user_ids": [fx.ADA["id"]], "combinable": PAIRS}],
                     reservations=seeds))
    return api().authenticate(fx.ADA["email"], fx.ADA["password"])


def seed(i, table, hhmm, party):
    return {"id": f"res_W{i:05d}", "reference": f"W{i:05d}", "user_id": "u_bob", "restaurant_id": "r_anker",
            "table_id": table, "starts_at_local": fx.local(DATE, hhmm), "party_size": party}


def timed(ada):
    body = {"table_id": "t_1",
            "from": dt.datetime.combine(dt.date.fromisoformat(DATE), dt.time(12), tzinfo=BERLIN).isoformat(),
            "to": dt.datetime.combine(dt.date.fromisoformat(DATE), dt.time(23, 30), tzinfo=BERLIN).isoformat()}
    began = time.monotonic()
    response = ada.post("/restaurants/r_anker/replans", idempotency_key=new_key(), json=body)
    return response, time.monotonic() - began


def test_six_bookings_with_every_option_open_are_planned_within_5_s(reset, api):
    """R411: 6 tables, 4 pairs, 6 considered bookings that follow each other on t_1 (all six
    must move, each can take any of the 5 other singles and 4 pairs): 201 within 5 s, three
    times."""
    seeds = [seed(i, "t_1", f"{12 + 2 * i:02d}:00", 1) for i in range(6)]
    for attempt in range(3):
        ada = world(reset, api, seeds)
        response, seconds = timed(ada)
        print(f"open 6/4/6 attempt {attempt}: status={response.status_code} seconds={seconds:.3f}")
        plan = assert_status(response, 201).json()
        assert plan["moved_count"] == 6 and seconds < LIMIT_S, seconds


def test_six_overlapping_bookings_with_no_plan_are_refused_within_5_s(reset, api):
    """R411/R425: 6 tables, 4 pairs, 6 bookings at 19:00 on every table and t_1 closed: five
    tables cannot seat six overlapping bookings: 409 no_feasible_plan within 5 s, three times."""
    seeds = [seed(i, f"t_{i + 1}", "19:00", 1) for i in range(6)]
    for attempt in range(3):
        ada = world(reset, api, seeds)
        response, seconds = timed(ada)
        print(f"infeasible 6/4/6 attempt {attempt}: status={response.status_code} seconds={seconds:.3f}")
        assert_error(response, 409, "no_feasible_plan")
        assert seconds < LIMIT_S, seconds

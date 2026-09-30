"""S3-I2 acceptance checks (verifier seat): availability explanations, from the stage-3
specification ("Availability explanations"; "With `explain=true`, each table explanation
additionally identifies its `policy_version`") with the plan's P9.

The restaurant lists its tables out of id order (t_3, t_1, t_2) so fixture order is visible.
Every explanation is compared with a reference built here from the rule text: `capacity`
holds when the party is at most the table's capacity under the selected policy; `no_overlap`
holds when no confirmed booking on the table, for its own accepted duration, overlaps the
slot's interval (the selected policy's duration from the slot). R.. and P.. name the room
plan's requirement lines and decisions.
"""
from __future__ import annotations

import datetime as dt
import os

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()
ORDER = ["t_3", "t_1", "t_2"]
CAPACITY = {"t_3": 6, "t_1": 2, "t_2": 4}
SLOT_KEYS = {"starts_at_local", "starts_at", "available_table_ids", "available_options"}
PARTIES = [1, 2, 4, 6, 7]


def shifted(days: int) -> str:
    return (dt.date.fromisoformat(DATE) + dt.timedelta(days=days)).isoformat()


def restaurant(**overrides) -> dict:
    tables = [{"id": t, "label": f"Table {t[-1]}", "capacity": CAPACITY[t]} for t in ORDER]
    return {**fx.restaurant(tables=tables, **overrides), "combinable": [["t_1", "t_2"]]}


def seed(reference, tables, hhmm, status="confirmed", user="u_ada") -> dict:
    record = {"id": f"res_{reference}", "reference": reference, "user_id": user, "restaurant_id": "r_anker",
              "starts_at_local": fx.local(DATE, hhmm), "party_size": 2, "status": status}
    return {**record, **({"table_id": tables[0]} if len(tables) == 1 else {"table_ids": tables})}


# t_3 19:00-20:30; the pair t_1+t_2 21:00-22:30; t_2 18:00 cancelled (holds nothing); t_1 18:00-19:30
SEEDS = [seed("EXA001", ["t_3"], "19:00"), seed("EXA002", ["t_1", "t_2"], "21:00"),
         seed("EXA003", ["t_2"], "18:00", status="cancelled"), seed("EXA004", ["t_1"], "18:00", user="u_bob")]
BOOKED = [("t_3", 19 * 60, 90), ("t_1", 21 * 60, 90), ("t_2", 21 * 60, 90), ("t_1", 18 * 60, 90)]


def minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def reference(slot_local: str, party: int, *, capacity=CAPACITY, booked=BOOKED, duration=90, version=0) -> list:
    start = minutes(slot_local[-5:])
    entries = []
    for table in ORDER:
        fits = party <= capacity[table]
        free = all(start + duration <= b or start >= b + length for t, b, length in booked if t == table)
        entries.append({"table_id": table, "policy_version": version, "available": fits and free,
                        "rules": [{"rule": "capacity", "holds": fits}, {"rule": "no_overlap", "holds": free}]})
    return entries


def availability(client, party: int, date: str = DATE, **extra):
    return client.get("/availability", params={"restaurant_id": "r_anker", "date": date, "party_size": party, **extra})


@pytest.fixture
def world(reset):
    reset(fx.fixture(restaurants=[restaurant()], reservations=SEEDS))


# ---- the parameter (R303, P9) ------------------------------------------------------------------

@pytest.mark.parametrize("value", ["false", "1", "", "TRUE", "True", " true", "true ", "yes"],
                         ids=["false", "one", "empty", "upper", "title", "leading_space", "trailing_space", "yes"])
def test_explain_accepts_only_true(world, anon, value):
    """R303/P9: `explain`'s only accepted value is `true`; `false`, `1`, the empty string and
    any other spelling are 422 validation_failed."""
    assert_error(availability(anon, 2, explain=value), 422, "validation_failed")


def test_explain_is_checked_with_the_other_parameters_before_the_restaurant(world, anon):
    """P9: an invalid `explain` is 422 before an unknown restaurant's 404, as the other query
    parameters are; a valid one leaves the 404; with a missing parameter it stays 422."""
    params = {"restaurant_id": "r_nope", "date": DATE, "party_size": 2}
    assert_error(anon.get("/availability", params={**params, "explain": "false"}), 422, "validation_failed")
    assert_error(anon.get("/availability", params={**params, "explain": "true"}), 404, "not_found")
    assert_error(anon.get("/availability", params={"restaurant_id": "r_anker", "date": DATE, "explain": "true"}),
                 422, "validation_failed")


# ---- without explain (R304) -----------------------------------------------------------------------

def test_without_explain_the_answer_is_the_stage_2_answer(world, anon):
    """R304: without `explain`, no explanation field appears anywhere: the answer has exactly
    the stage-2 keys and equals the stage-2 service's answer for the same fixture and
    bookings, for every party size (needs TABLEKEEPER_STAGE2_URL; resets that service)."""
    url = os.environ.get("TABLEKEEPER_STAGE2_URL")
    assert url, "set TABLEKEEPER_STAGE2_URL to the stage-2 service of the same checkout"
    with Api(url.rstrip("/"), timeout=RESET_TIMEOUT) as stage2:
        assert_status(stage2.post("/_test/reset", json=fx.fixture(restaurants=[restaurant()], reservations=SEEDS)), 204)
        for party in PARTIES:
            answer = assert_status(availability(anon, party), 200).json()
            assert set(answer) == {"restaurant_id", "date", "timezone", "slots"}
            assert all(set(slot) == SLOT_KEYS for slot in answer["slots"]), party
            assert answer == assert_status(availability(stage2, party), 200).json(), party


# ---- with explain (R302, R306-R309) ----------------------------------------------------------------

@pytest.mark.parametrize("party", PARTIES)
def test_every_slot_explains_every_table_by_both_rules(world, anon, party):
    """R302/R306-R309: with `explain=true` each slot carries one further field, `explain`:
    every table exactly once in fixture order, `table_id`, `policy_version`, `available` and
    both rules in order, each judged on its own (a table excluded by both reports both false),
    `available` exactly when both hold; the available ids are `available_table_ids` in order;
    everything else is the answer without `explain`."""
    plain = assert_status(availability(anon, party), 200).json()
    explained = assert_status(availability(anon, party, explain="true"), 200).json()
    assert [s["starts_at_local"][-5:] for s in explained["slots"]] == fx.expected_slots()
    for slot, before in zip(explained["slots"], plain["slots"], strict=True):
        assert set(slot) == SLOT_KEYS | {"explain"}
        assert {k: v for k, v in slot.items() if k != "explain"} == before
        assert slot["explain"] == reference(slot["starts_at_local"], party), slot["starts_at_local"]
        assert [e["table_id"] for e in slot["explain"] if e["available"]] == slot["available_table_ids"]
    assert {k: v for k, v in explained.items() if k != "slots"} == {k: v for k, v in plain.items() if k != "slots"}


def rules_at(answer: dict, hhmm: str) -> dict:
    slot = next(s for s in answer["slots"] if s["starts_at_local"].endswith(f"T{hhmm}"))
    return {e["table_id"]: [r["holds"] for r in e["rules"]] for e in slot["explain"]} | \
        {"available": slot["available_table_ids"]}


def test_the_rules_hold_at_their_boundaries(world, anon):
    """R302/R308: capacity holds at exactly the party size; a booking ending at the slot's start
    or starting at its end does not overlap it; a cancelled booking holds nothing; a pair
    booking holds both its tables."""
    four = assert_status(availability(anon, 4, explain="true"), 200).json()
    assert rules_at(four, "19:00") == {"t_3": [True, False], "t_1": [False, False], "t_2": [True, True],
                                       "available": ["t_2"]}
    assert rules_at(four, "20:30") == {"t_3": [True, True], "t_1": [False, False], "t_2": [True, False],
                                       "available": ["t_3"]}
    two = assert_status(availability(anon, 2, explain="true"), 200).json()
    assert rules_at(two, "19:30") == {"t_3": [True, False], "t_1": [True, True], "t_2": [True, True],
                                      "available": ["t_1", "t_2"]}


def test_a_closed_day_and_a_fully_booked_slot(reset, anon):
    """R310: a closed day still returns `"slots": []`; a slot with no available table still
    appears, with empty lists and a full `explain` for every table."""
    closed = [h for h in fx.all_week() if h["weekday"] != dt.date.fromisoformat(DATE).strftime("%a").lower()]
    full = [seed("FUL001", ["t_3"], "19:00"), seed("FUL002", ["t_1"], "19:00"), seed("FUL003", ["t_2"], "19:00")]
    reset(fx.fixture(restaurants=[restaurant(opening_hours=closed)], reservations=[]))
    answer = assert_status(availability(anon, 2, explain="true"), 200).json()
    assert (answer["slots"], set(answer)) == ([], {"restaurant_id", "date", "timezone", "slots"})
    reset(fx.fixture(restaurants=[restaurant()], reservations=full))
    answer = assert_status(availability(anon, 2, explain="true"), 200).json()
    assert [s["starts_at_local"][-5:] for s in answer["slots"]] == fx.expected_slots()
    slot = next(s for s in answer["slots"] if s["starts_at_local"].endswith("T19:00"))
    assert (slot["available_table_ids"], slot["available_options"]) == ([], [])
    booked = [(t, 19 * 60, 90) for t in ORDER]
    assert slot["explain"] == reference(slot["starts_at_local"], 2, booked=booked)


# ---- under published policies (R329, R305) ------------------------------------------------------------

def test_policy_version_and_both_rules_follow_the_selected_policy(reset, api, anon):
    """R329/R305/R323: under two same-date policies the explanation names the later one's
    version and judges capacity by its capacities and overlap by its duration against each
    booking's own; the day before names policy 0, a later-dated policy its own version."""
    reset(fx.fixture(restaurants=[{**restaurant(), "manager_user_ids": [fx.ADA["id"]]}], reservations=SEEDS))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    later = {"t_3": 2, "t_1": 5, "t_2": 3}
    for capacities, date in (({"t_3": 1, "t_1": 1, "t_2": 1}, DATE), (later, DATE), (CAPACITY, shifted(7))):
        assert_status(ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=fx.policy(
            date, reservation_duration_minutes=60, capacities=capacities)), 201)
    assert_status(bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE, "20:00"), "party_size": 1}), 201)
    booked = BOOKED + [("t_2", 20 * 60, 60)]
    answer = assert_status(availability(anon, 3, explain="true"), 200).json()
    assert [s["starts_at_local"][-5:] for s in answer["slots"]] == fx.expected_slots(duration=60)
    for slot in answer["slots"]:
        assert slot["explain"] == reference(slot["starts_at_local"], 3, capacity=later, booked=booked,
                                            duration=60, version=2), slot["starts_at_local"]
        assert [e["table_id"] for e in slot["explain"] if e["available"]] == slot["available_table_ids"]
    before = assert_status(availability(anon, 3, date=shifted(-1), explain="true"), 200).json()
    assert all(s["explain"] == reference(s["starts_at_local"], 3, booked=[]) for s in before["slots"])
    week = assert_status(availability(anon, 3, date=shifted(7), explain="true"), 200).json()
    assert {e["policy_version"] for s in week["slots"] for e in s["explain"]} == {3}

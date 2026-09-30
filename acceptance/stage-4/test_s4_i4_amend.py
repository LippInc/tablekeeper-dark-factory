"""S4-I4 acceptance checks (verifier seat): amending a series' clock time, from the stage-4
specification's "Amend recurring reservations" (R437, R441-R458, R422, R423, R429) with the
plan's Q18-Q23 and the stage-1/3 rules they reuse (D3, D6, D8, D11, H1-H4, P10).

The world helpers come from test_s4_i2_preview.py; races are in test_s4_i4_races.py. Resets the
service: run it alone against other files that reset it. One check waits up to a minute for an
occurrence to pass its cutoff; it needs the restaurant's local time to be before 23:40.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(4)

_spec = importlib.util.spec_from_file_location("s4i2_preview", pathlib.Path(__file__).with_name("test_s4_i2_preview.py"))
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)
make = w.make  # the reset-world fixture
DATE, seed, exported, closure, publish, planned = w.DATE, w.seed, w.exported, w.closure, w.publish, w.planned
BERLIN = ZoneInfo("Europe/Berlin")


def later(weeks: int, days: int = 0) -> str:
    return (dt.date.fromisoformat(DATE) + dt.timedelta(weeks=weeks, days=days)).isoformat()


def adopt(world, anchor="ANCH01", count=5) -> dict:
    return assert_status(world.bob.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": anchor, "count": count, "interval_weeks": 1}), 201).json()


def amend(client, sid, body, key=None):
    return client.post(f"/series/{sid}/amend", json=body, idempotency_key=key or new_key())


def get_series(world, sid) -> dict:
    return assert_status(world.bob.get(f"/series/{sid}"), 200).json()


def read(world, ref) -> dict:
    return assert_status(world.bob.get(f"/reservations/{ref}"), 200).json()


def history(world, ref) -> list:
    return assert_status(world.bob.get(f"/reservations/{ref}/history"), 200).json()["entries"]


def revision(world) -> int:
    return next(r["revision"] for r in exported(world.base)["state"]["restaurants"] if r["id"] == "r_anker")


def series_world(make, count=5, seeds=(), **kw):
    """ANCH01 (t_2, 19:00, party 2) on DATE adopted as a weekly series of `count`."""
    world = make(seeds=[seed("ANCH01", ["t_2"], "19:00", party=2), *seeds], **kw)
    world.series = adopt(world, count=count)
    world.sid = world.series["series_id"]
    world.refs = [o["reference"] for o in world.series["occurrences"]]
    return world


def local(ref_body) -> str:
    return ref_body["starts_at_local"]


# ---- the keyed write, who and in what order (R441-R445, Q18, D3, D11) ------------------------------------

def test_the_keyed_write_basics_and_a_replay_after_later_edits_and_cancellations(make):
    """R441/R458/D3: no token 401; a body that is not a JSON object 400; a missing key 400; a key
    over 255 characters 422; a success replays 200 with its original body after a later PATCH
    and a cancel; the key with another body is 409 idempotency_key_reuse; unknown fields are
    ignored."""
    world = series_world(make)
    path = f"/series/{world.sid}/amend"
    body = {"expected_revision": 1, "from_index": 0, "local_time": "20:00", "note": "ignored", "party_size": 9}
    assert_error(Api(world.base).post(path, json=body, idempotency_key=new_key()), 401, "unauthenticated")
    for raw in ("[]", "{", "null"):
        assert_error(world.bob.post(path, content=raw, idempotency_key=new_key()), 400, "malformed_request")
    assert_error(world.bob.post(path, json=body), 400, "missing_idempotency_key")
    assert_error(amend(world.bob, world.sid, body, key="k" * 256), 422, "validation_failed")
    key = new_key()
    original = assert_status(amend(world.bob, world.sid, body, key), 201).json()
    assert [o["reservation"]["party_size"] for o in original["occurrences"]] == [2] * 5
    assert_status(world.bob.patch(f"/reservations/{world.refs[1]}", json={"party_size": 3}), 200)
    assert_status(world.bob.post(f"/reservations/{world.refs[2]}/cancel"), 200)
    before = exported(world.base)
    assert assert_status(amend(world.bob, world.sid, body, key), 200).json() == original
    assert exported(world.base) == before
    assert_error(amend(world.bob, world.sid, {**body, "local_time": "21:00"}, key), 409, "idempotency_key_reuse")


def test_an_unknown_or_another_owners_series_is_404_before_the_fields(make):
    """R441/Q18: an unknown series, and another user's (ada's view of bob's), are 404, also
    with an empty or invalid body."""
    world = series_world(make)
    for client, sid in ((world.bob, "ser_nope"), (world.ada, world.sid)):
        for body in ({"expected_revision": 1, "from_index": 0, "local_time": "20:00"}, {}):
            assert_error(amend(client, sid, body), 404, "not_found")


INVALID = {
    "revision_missing": {"expected_revision": None}, "revision_null": {"expected_revision": "NULL"},
    "revision_0": {"expected_revision": 0}, "revision_negative": {"expected_revision": -1},
    "revision_true": {"expected_revision": True}, "revision_fraction": {"expected_revision": 1.5},
    "revision_float_whole": {"expected_revision": 1.0}, "revision_string": {"expected_revision": "1"},
    "index_missing": {"from_index": None}, "index_true": {"from_index": True}, "index_false": {"from_index": False},
    "index_negative": {"from_index": -1}, "index_count": {"from_index": 5}, "index_fraction": {"from_index": 0.5},
    "index_string": {"from_index": "0"},
    "time_missing": {"local_time": None}, "time_null": {"local_time": "NULL"}, "time_one_digit_hour": {"local_time": "8:00"},
    "time_24": {"local_time": "24:00"}, "time_60_minutes": {"local_time": "20:60"}, "time_seconds": {"local_time": "20:00:00"},
    "time_number": {"local_time": 2000}, "time_empty": {"local_time": ""}, "time_leading_space": {"local_time": " 20:00"},
    "time_dot": {"local_time": "20.00"},
    "invalid_time_with_a_stale_revision": {"expected_revision": 7, "local_time": "24:00"},
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_input_is_422_before_the_revision_and_changes_nothing(make, case):
    """R443/Q18: expected_revision a positive integer, from_index an integer 0..count-1 and
    local_time exactly HH:MM in 00:00..23:59, booleans not integers; each violation, and a
    missing field, is 422 validation_failed - also with a stale revision - and changes nothing."""
    world = series_world(make)
    body = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
    for name, value in INVALID[case].items():
        if value is None:
            del body[name]
        else:
            body[name] = None if value == "NULL" else value
    before = exported(world.base)
    assert_error(amend(world.bob, world.sid, body), 422, "validation_failed")
    assert exported(world.base) == before


def test_a_stale_revision_wins_over_an_occurrence_inside_its_cutoff(reset, api, base_url):
    """R444/R449/Q18/D8: with occurrence 0 inside its accepted cutoff (1 minute), a stale revision
    is 409 stale_revision, the right one with a real change of occurrence 0 is 409 cutoff_passed
    and changes nothing, the same time (a no-op) is 201, and from_index 1 changes the others."""
    tables = [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]
    reset(fx.fixture(restaurants=[{**fx.restaurant(tables=tables, slot_minutes=1, reservation_duration_minutes=15,
                                                   cancellation_cutoff_minutes=1,
                                                   opening_hours=fx.all_week("00:00", "23:59"))}]))
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    start = (dt.datetime.now(BERLIN) + dt.timedelta(minutes=2)).replace(second=0, microsecond=0)
    anchor = assert_status(bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "party_size": 2,
        "starts_at_local": start.strftime("%Y-%m-%dT%H:%M")}), 201).json()
    series = assert_status(bob.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}), 201).json()
    time.sleep(max(0.0, (start - dt.datetime.now(BERLIN)).total_seconds() - 60 + 2))
    assert_error(bob.post(f"/reservations/{anchor['reference']}/cancel"), 409, "cutoff_passed")
    sid, same, other = series["series_id"], start.strftime("%H:%M"), (start + dt.timedelta(minutes=5)).strftime("%H:%M")
    with Api(base_url) as control:
        before = assert_status(control.get("/_test/export"), 200).json()
        assert_error(amend(bob, sid, {"expected_revision": 2, "from_index": 0, "local_time": other}), 409, "stale_revision")
        assert_error(amend(bob, sid, {"expected_revision": 1, "from_index": 0, "local_time": other}), 409, "cutoff_passed")
        assert assert_status(control.get("/_test/export"), 200).json() == before
    assert_status(amend(bob, sid, {"expected_revision": 1, "from_index": 0, "local_time": same}), 201)
    done = assert_status(amend(bob, sid, {"expected_revision": 1, "from_index": 1, "local_time": other}), 201).json()
    assert [o["reservation"]["starts_at_local"][11:] for o in done["occurrences"]] == [same, other, other]


# ---- what an amendment changes (R446-R448, R453-R457, Q19, Q20, Q22) --------------------------------------------

def test_only_eligible_occurrences_change_each_once_on_its_own_date(make):
    """R446/R447/R453-R456: a series of five with occurrence 2 an exception (a diner's PATCH) and
    4 cancelled, amended from index 1 to 20:00: exactly 1 and 3 move to 20:00 on their dates,
    keeping reference, owner, table and party, each one revision further with one `changed`
    entry naming only `starts_at_local`; 0, 2 and 4 are untouched; the series and restaurant
    revisions rise once; the flags stay [F, F, T, F, F]; 201 is GET /series."""
    world = series_world(make)
    assert_status(world.bob.patch(f"/reservations/{world.refs[2]}", json={"party_size": 3}), 200)
    assert_status(world.bob.post(f"/reservations/{world.refs[4]}/cancel"), 200)
    before = {ref: (read(world, ref), history(world, ref)) for ref in world.refs}
    series_before, restaurant_before = get_series(world, world.sid), revision(world)
    response = assert_status(amend(world.bob, world.sid, {"expected_revision": series_before["revision"],
                                                          "from_index": 1, "local_time": "20:00"}), 201).json()
    assert response == get_series(world, world.sid)
    assert response["revision"] == series_before["revision"] + 1 and revision(world) == restaurant_before + 1
    assert [o["exception"] for o in response["occurrences"]] == [False, False, True, False, False]
    for index, ref in enumerate(world.refs):
        old, old_history = before[ref]
        now = read(world, ref)
        if index in (1, 3):
            assert local(now) == local(old)[:11] + "20:00"
            assert (now["table_ids"], now["party_size"], now["reference"]) == (old["table_ids"], old["party_size"], ref)
            assert now["revision"] == old["revision"] + 1
            entries = history(world, ref)
            assert entries[:-1] == old_history and entries[-1]["event"] == "changed"
            assert entries[-1]["changes"] == [{"field": "starts_at_local", "from": local(old), "to": local(now)}]
        else:
            assert (now, history(world, ref)) == (old, old_history)


def test_several_changes_raise_the_series_and_restaurant_revisions_once(make):
    """R455: an amendment moving all five occurrences raises the series revision by one and the
    restaurant revision by one."""
    world = series_world(make)
    restaurant_before = revision(world)
    response = assert_status(amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": "20:30"}), 201).json()
    assert response["revision"] == 2 and revision(world) == restaurant_before + 1
    assert all(o["reservation"]["starts_at_local"].endswith("T20:30") for o in response["occurrences"])


def test_all_no_op_and_empty_amendments_succeed_changing_nothing(make):
    """R448/R457/Q20/Q22: amending to the current 19:00 (all no-ops) and from an index whose only
    remaining occurrence is cancelled (empty) are 201 with the series as it is; no reservation,
    series or restaurant revision and no history changes; each key replays 200."""
    world = series_world(make, count=3)
    assert_status(world.bob.post(f"/reservations/{world.refs[2]}/cancel"), 200)
    for body in ({"expected_revision": 2, "from_index": 0, "local_time": "19:00"},
                 {"expected_revision": 2, "from_index": 2, "local_time": "21:00"}):
        state = exported(world.base)["state"]
        key = new_key()
        response = assert_status(amend(world.bob, world.sid, body, key), 201).json()
        assert response == get_series(world, world.sid) and response["revision"] == 2
        after = exported(world.base)["state"]
        assert {k: v for k, v in after.items() if k != "receipts"} == {k: v for k, v in state.items() if k != "receipts"}
        assert assert_status(amend(world.bob, world.sid, body, key), 200).json() == response


def test_real_changes_adopt_their_dates_policy_and_no_ops_keep_their_terms(make):
    """R448/R449/H1: with a 60-minute policy from occurrence 2's date, amending to 19:00 (no-ops)
    keeps every occurrence's 90-minute terms; amending to 20:00 gives occurrences 0-1 policy 0
    (90 minutes) and 2-4 the new policy (60 minutes, `ends_at` 21:00)."""
    world = series_world(make)
    publish(world, later(2), reservation_duration_minutes=60)
    assert_status(amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": "19:00"}), 201)
    assert [read(world, ref)["accepted_terms"]["reservation_duration_minutes"] for ref in world.refs] == [90] * 5
    assert_status(amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}), 201)
    reads = [read(world, ref) for ref in world.refs]
    assert [r["accepted_terms"]["reservation_duration_minutes"] for r in reads] == [90, 90, 60, 60, 60]
    assert [r["ends_at"][11:16] for r in reads] == ["21:30", "21:30", "21:00", "21:00", "21:00"]


RULES = {
    "capacity": ({"capacities": {"t_1": 2, "t_2": 1, "t_3": 6}}, "20:00"),
    "hours": ({"opening_hours": fx.all_week("12:00", "20:30")}, "20:00"),
    "grid": ({"slot_minutes": 60}, "20:30"),
}


@pytest.mark.parametrize("rule", list(RULES))
def test_a_real_change_is_refused_by_its_new_dates_policy_changing_nothing(make, rule):
    """R449/Q18: under a policy from occurrence 2's date that seats 1 at t_2, closes at 20:30 or
    uses a 60-minute grid, amending to that date's refused time is 422 and changes nothing."""
    world = series_world(make)
    overrides, time_ = RULES[rule]
    assert_status(world.ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=fx.policy(
        later(2), **({"opening_hours": fx.all_week("12:00", "23:30")} | overrides))), 201)
    before = exported(world.base)
    response = amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": time_})
    assert response.status_code == 422, response.text
    assert exported(world.base) == before


def test_the_earliest_non_occupancy_error_wins_over_an_earlier_occupancy_conflict(make):
    """R452/Q18: amending to 20:30 where occurrence 0 would clash with a booking at 21:00,
    occurrence 1's date seats only 1 at t_2 and occurrence 2's date has a 60-minute grid is 422
    party_exceeds_capacity (occurrence 1), not 409 and not the grid; nothing changes."""
    world = series_world(make, seeds=[seed("CLASH1", ["t_2"], "21:00", party=2)])
    publish(world, later(1), capacities={"t_1": 2, "t_2": 1, "t_3": 6})
    publish(world, later(2), slot_minutes=60)
    before = exported(world.base)
    assert_error(amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": "20:30"}),
                 422, "party_exceeds_capacity")
    assert exported(world.base) == before


def occupied_by_booking(world):
    w.create(world, ["t_2"], "21:00", 2, date=later(1))


def occupied_by_unchanged_occurrence(world):
    assert_status(world.bob.patch(f"/reservations/{world.refs[1]}", json={
        "starts_at_local": fx.local(later(2), "21:00")}), 200)  # an exception, now on occurrence 2's date


def occupied_by_closure(world):
    body = closure(start="20:45", end="23:00", date=later(1))
    plan = planned(world.ada, body)
    assert plan["assignments"] == []
    assert_status(world.ada.post(f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", idempotency_key=new_key(), json={}), 201)


OCCUPIED = {"another_booking": occupied_by_booking, "an_unchanged_occurrence": occupied_by_unchanged_occurrence,
            "an_applied_closure": occupied_by_closure}


@pytest.mark.parametrize("holder", list(OCCUPIED))
def test_an_occupancy_conflict_refuses_the_whole_amendment_and_records_nothing(make, holder):
    """R437/R450/R451/Q21/D11: a conflict at 20:30 with another booking, an unchanged occurrence
    (an exception moved onto occurrence 2's date) or an applied closure is 409 table_unavailable;
    the export - histories, revisions, receipts - is unchanged, and the key then serves a valid
    body (201)."""
    world = series_world(make)
    OCCUPIED[holder](world)
    revision_now = get_series(world, world.sid)["revision"]
    before = exported(world.base)
    key = new_key()
    assert_error(amend(world.bob, world.sid, {"expected_revision": revision_now, "from_index": 1, "local_time": "20:30"}, key),
                 409, "table_unavailable")
    assert exported(world.base) == before
    assert_status(amend(world.bob, world.sid, {"expected_revision": revision_now, "from_index": 3, "local_time": "20:30"}, key), 201)


def test_a_repaired_occurrence_keeps_its_repaired_tables(make):
    """R447/R459: occurrence 1, moved to t_1 by an applied plan, is amended to 20:00 on t_1."""
    world = series_world(make)
    plan = planned(world.ada, closure(start="18:00", end="20:00", date=later(1)))
    assert plan["assignments"] == [{"reference": world.refs[1], "table_ids": ["t_1"], "changed": True}]
    assert_status(world.ada.post(f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", idempotency_key=new_key(), json={}), 201)
    assert_status(amend(world.bob, world.sid, {"expected_revision": 2, "from_index": 0, "local_time": "20:00"}), 201)
    moved = read(world, world.refs[1])
    assert moved["table_ids"] == ["t_1"] and local(moved) == f"{later(1)}T20:00"
    assert [read(world, ref)["table_ids"] for ref in world.refs] == [["t_2"], ["t_1"], ["t_2"], ["t_2"], ["t_2"]]


def test_a_plan_made_before_a_real_amendment_is_stale_but_not_after_a_no_op(make):
    """R422/R429/R457/Q5: a plan previewed before a real amendment at that restaurant is 409
    stale_plan; one previewed before an all-no-op amendment still applies (201)."""
    for real, expected in (("20:00", 409), ("19:00", 201)):
        world = series_world(make)
        plan = planned(world.ada, closure(table="t_1", start="12:00", end="13:00"))
        assert_status(amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": real}), 201)
        response = world.ada.post(f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", idempotency_key=new_key(), json={})
        if expected == 409:
            assert_error(response, 409, "stale_plan")
        else:
            assert_status(response, 201)


# ---- daylight saving (R447, Q19) -------------------------------------------------------------------------------

def dst_world(reset, api, anchor_date):
    tables = [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]
    reset(fx.fixture(restaurants=[fx.restaurant(tables=tables, opening_hours=fx.all_week("00:00", "23:30"))],
                     reservations=[seed("ANCH01", ["t_2"], "19:00", date=anchor_date)]))
    world = SimpleNamespace(bob=api().authenticate(fx.BOB["email"], fx.BOB["password"]))
    world.sid = adopt(world, count=3)["series_id"]
    return world


def test_the_new_time_lands_on_each_scheduled_date_across_the_autumn_change(reset, api):
    """R447/Q19: a weekly series from Sunday 18 October 2026 amended to 00:30 reads 00:30 on 18
    and 25 October (+02:00, before the change that night) and 1 November (+01:00); amended to
    02:30, 25 October's repeated 02:30 is its first occurrence (+02:00)."""
    world = dst_world(reset, api, "2026-10-18")
    done = assert_status(amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": "00:30"}), 201).json()
    got = [(o["reservation"]["starts_at_local"], o["reservation"]["starts_at"][-6:]) for o in done["occurrences"]]
    assert got == [("2026-10-18T00:30", "+02:00"), ("2026-10-25T00:30", "+02:00"), ("2026-11-01T00:30", "+01:00")]
    done = assert_status(amend(world.bob, world.sid, {"expected_revision": 2, "from_index": 0, "local_time": "02:30"}), 201).json()
    got = [(o["reservation"]["starts_at_local"], o["reservation"]["starts_at"][-6:]) for o in done["occurrences"]]
    assert got == [("2026-10-18T02:30", "+02:00"), ("2026-10-25T02:30", "+02:00"), ("2026-11-01T02:30", "+01:00")]


def test_a_time_that_does_not_exist_on_one_date_refuses_the_amendment(reset, api, base_url):
    """R447/Q19: a weekly series from Sunday 21 March 2027 amended to 02:30 meets the spring gap
    on 28 March: 422 invalid_local_time, nothing changes."""
    world = dst_world(reset, api, "2027-03-21")
    with Api(base_url) as control:
        before = assert_status(control.get("/_test/export"), 200).json()
        assert_error(amend(world.bob, world.sid, {"expected_revision": 1, "from_index": 0, "local_time": "02:30"}),
                     422, "invalid_local_time")
        assert assert_status(control.get("/_test/export"), 200).json() == before
